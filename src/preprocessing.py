# -*- coding: utf-8 -*-
"""
preprocessing.py — 데이터 전처리 모듈.

담당 기능:
1. 개념 컬럼명으로 rename 된 표준 DataFrame 생성 (build_standard_frame)
2. 날짜 파싱(다양한 형식) → *_year 파생, 불리언 파싱(Y/N/True/1 등)
3. 다중 기술분류 파싱: 쉼표/세미콜론/파이프/JSON 배열/복수 컬럼 지원 (parse_multiclass)
4. 법적상태 정규화: 원본값 보존(legal_status_raw) + 정규화값(legal_status_norm)
5. 출원인 표준화: 대소문자·법인 접미사·괄호·특수문자 정리 + 사용자 매핑/그룹 규칙 적용
   (자동 표준화 결과는 확정값이 아니라 사용자 검토 대상 — applicant_auto_std 로 분리)
6. 패밀리 dedup: 대표문헌 선정 우선순위
   ① 유효 등록특허 → ② 가장 이른 우선일 → ③ 서지·청구항 완전성 → ④ 지정국 우선순위
   → ⑤ 공개번호 정렬
7. 공통 필터 적용 (apply_filters): 기간/출원인/기술분류/국가/법적상태/유효특허
8. 다중분류 집계용 explode (explode_tech): duplicate / fractional / primary / level_separate

예외처리: 결측 컬럼은 건너뛰고 존재하는 컬럼만 처리. 파싱 실패 값은 NaN/원본 유지.
분석값을 임의로 생성하지 않는다.
"""
import json
import re

import numpy as np
import pandas as pd

from src.config import (LEGAL_STATUS_PATTERNS, ACTIVE_LEGAL_STATUSES,
                        DEFAULT_MULTICLASS_MODE)
from src.column_mapping import _norm as _norm_header

# ---------------------------------------------------------------------------
# 기본 파서
# ---------------------------------------------------------------------------
_TRUE_TOKENS = frozenset(["y", "yes", "true", "1", "o", "유", "예", "등록", "유효", "존속", "active", "t"])
_FALSE_TOKENS = frozenset(["n", "no", "false", "0", "x", "무", "아니오", "미등록", "무효", "소멸", "inactive", "f"])


def parse_bool(value):
    """Y/N·True/False·1/0·유/무 등 다양한 불리언 표기 파싱. 불명확하면 None."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer, float, np.floating)):
        return bool(int(value))
    s = str(value).strip().lower()
    if s in _TRUE_TOKENS:
        return True
    if s in _FALSE_TOKENS:
        return False
    return None


def parse_numeric(series):
    """숫자 파싱: 천 단위 쉼표·단위 문자 제거 후 첫 숫자 추출.

    "1,234" / "3건" / "5 회" / "12회 인용" 형태를 모두 숫자로 해석한다. 실패값 NaN.
    """
    if series is None:
        return None
    s = series.astype(str).str.strip().str.replace(",", "", regex=False)
    ext = s.str.extract(r"([+-]?\d+(?:\.\d+)?)")[0]
    return pd.to_numeric(ext, errors="coerce")


def parse_dates(series):
    """날짜 시리즈 파싱: pandas 추론 + YYYYMMDD 보정 + 문자열 내 날짜 추출.

    '출원번호(출원일)' 처럼 번호와 날짜가 한 컬럼에 섞인 WIPS 헤더도 지원:
    해석 실패 값에서 (19|20)YY[.-/년]MM[.-/월]DD 패턴 또는 8자리 날짜를 추출한다.
    (앞뒤가 숫자인 경우는 제외해 출원번호 일련부를 날짜로 오인하지 않음)
    실패값은 NaT.
    """
    if series is None:
        return None
    s = series.astype(str).str.strip().replace({"": None, "nan": None, "None": None, "NaT": None})
    s = s.str.replace(r"[./]", "-", regex=True)
    out = pd.to_datetime(s, errors="coerce", format="mixed")
    # 8자리 숫자(YYYYMMDD) 재시도
    mask = out.isna() & s.notna() & s.str.fullmatch(r"\d{8}", na=False)
    if mask.any():
        out.loc[mask] = pd.to_datetime(s[mask], format="%Y%m%d", errors="coerce")
    # 문자열 내 날짜 추출 (예: "10-2020-0123456 (2020-01-02)")
    mask = out.isna() & s.notna()
    if mask.any():
        ext = s[mask].str.extract(
            r"(?<!\d)((?:19|20)\d{2})[\-년]\s?(\d{1,2})[\-월]\s?(\d{1,2})(?!\d)")
        good = ext.notna().all(axis=1)
        if good.any():
            combined = (ext.loc[good, 0] + "-" + ext.loc[good, 1].str.zfill(2)
                        + "-" + ext.loc[good, 2].str.zfill(2))
            out.loc[combined.index] = pd.to_datetime(combined, errors="coerce")
        ext8 = s[mask & out.isna()].str.extract(r"(?<!\d)((?:19|20)\d{6})(?!\d)")
        good8 = ext8[0].notna()
        if good8.any():
            out.loc[ext8.index[good8]] = pd.to_datetime(
                ext8.loc[good8, 0], format="%Y%m%d", errors="coerce")
    # 연도만 있는 값 ("2020", "2020.0" — 숫자형 컬럼 캐스팅 포함) → 해당 연도 1월 1일
    mask = out.isna() & s.notna()
    if mask.any():
        yr = s[mask].str.extract(r"^((?:19|20)\d{2})(?:-0+)?$")[0]
        good_yr = yr.notna()
        if good_yr.any():
            out.loc[yr.index[good_yr]] = pd.to_datetime(
                yr[good_yr] + "-01-01", errors="coerce")
    # Excel 날짜 일련번호 (5자리, 1954~2064년 범위) → 1899-12-30 기준 일수
    mask = out.isna() & s.notna() & s.str.fullmatch(r"\d{5}(-0+)?", na=False)
    if mask.any():
        serial = pd.to_numeric(s[mask].str.split("-").str[0], errors="coerce")
        in_range = serial.between(20000, 60000)
        if in_range.any():
            out.loc[serial.index[in_range]] = pd.to_datetime(
                serial[in_range], unit="D", origin="1899-12-30", errors="coerce")
    return out


_EMB_SPLIT_RE = re.compile(r"[,\s]+")


def parse_embedding(value):
    """임베딩 셀 파싱: JSON 배열 / 공백·쉼표 구분 숫자 문자열 / list → np.array. 실패 시 None."""
    if value is None:
        return None
    if isinstance(value, (list, tuple, np.ndarray)):
        arr = np.asarray(value, dtype=np.float64)
        return arr if arr.size else None
    if isinstance(value, float) and np.isnan(value):
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        if s.startswith("["):
            return np.asarray(json.loads(s), dtype=np.float64)
        parts = [p for p in _EMB_SPLIT_RE.split(s) if p]
        return np.asarray([float(p) for p in parts], dtype=np.float64)
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# 다중 기술분류 파싱
# ---------------------------------------------------------------------------
def parse_multiclass_cell(value):
    """단일 셀의 다중 기술분류 파싱.

    지원 형식: JSON 배열('["A","B"]') / 쉼표 / 세미콜론 / 파이프(|).
    반환: 중복 제거·순서 유지 리스트 (없으면 []).
    """
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return []
    if isinstance(value, (list, tuple)):
        items = [str(v).strip() for v in value]
    else:
        s = str(value).strip()
        if not s or s.lower() in ("nan", "none"):
            return []
        items = None
        if s.startswith("["):
            try:
                loaded = json.loads(s)
                if isinstance(loaded, list):
                    items = [str(v).strip() for v in loaded]
            except (ValueError, json.JSONDecodeError):
                items = None
        if items is None:
            for sep in ("|", ";", ","):
                if sep in s:
                    items = [p.strip() for p in s.split(sep)]
                    break
            else:
                items = [s]
    seen, out = set(), []
    for it in items:
        if it and it.lower() not in ("nan", "none") and it not in seen:
            seen.add(it)
            out.append(it)
    return out


def build_tech_lists(df):
    """행별 기술분류 리스트 컬럼(_tech_list) 생성.

    우선순위: tech_multi(다중 기술분류) → tech_l3 → tech_l2 → tech_l1.
    복수의 기술분류 컬럼(tech_l1/l2/l3 각각 다중값 포함 가능)도 지원:
    각 레벨의 파싱 결과를 _tech_l1_list/_tech_l2_list/_tech_l3_list 로도 보관한다.
    """
    for level in ("tech_l1", "tech_l2", "tech_l3"):
        if level in df.columns:
            df["_%s_list" % level] = df[level].map(parse_multiclass_cell)
    if "tech_multi" in df.columns:
        df["_tech_list"] = df["tech_multi"].map(parse_multiclass_cell)
        # tech_multi 가 전부 비어있으면 레벨 컬럼으로 폴백
        if not df["_tech_list"].map(len).any():
            df = _tech_list_from_levels(df)
    else:
        df = _tech_list_from_levels(df)
    if "_tech_list" not in df.columns:
        df["_tech_list"] = [[] for _ in range(len(df))]
    return df


def _tech_list_from_levels(df):
    """레벨 컬럼(소→중→대 우선)으로 _tech_list 구성."""
    for level in ("_tech_l3_list", "_tech_l2_list", "_tech_l1_list"):
        if level in df.columns and df[level].map(len).any():
            df["_tech_list"] = df[level]
            return df
    df["_tech_list"] = [[] for _ in range(len(df))]
    return df


def build_l1_lookup(df):
    """소/중분류 → 대분류 매핑 dict (색상 그룹용). 다중값은 첫 대응 대분류 사용."""
    lookup = {}
    if "_tech_l1_list" not in df.columns:
        return lookup
    for child_col in ("_tech_l3_list", "_tech_l2_list"):
        if child_col not in df.columns:
            continue
        for childs, l1s in zip(df[child_col], df["_tech_l1_list"]):
            if not childs or not l1s:
                continue
            for c in childs:
                if c not in lookup:
                    lookup[c] = l1s[0]
    for l1s in df["_tech_l1_list"]:
        for v in (l1s or []):
            lookup.setdefault(v, v)
    return lookup


# ---------------------------------------------------------------------------
# 법적상태 정규화
# ---------------------------------------------------------------------------
def normalize_legal_status(value):
    """법적상태 원본값 → 표준 카테고리. 매칭 실패·결측 시 'Unknown'."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "Unknown"
    s = str(value).strip().lower()
    if not s or s in ("nan", "none"):
        return "Unknown"
    for pattern, category in LEGAL_STATUS_PATTERNS:
        if pattern in s:
            return category
    return "Unknown"


def derive_active_flag(row):
    """유효특허 여부 파생: is_active 컬럼 → 법적상태 → 등록여부+만료일 순으로 판단.

    판단 불가 시 None (임의 생성 금지 — 분석에서는 'Unknown' 취급).
    """
    v = row.get("_is_active_bool")
    if v is not None:
        return v
    status = row.get("legal_status_norm")
    if status and status != "Unknown":
        return status in ACTIVE_LEGAL_STATUSES
    return None


# ---------------------------------------------------------------------------
# 출원인 표준화
# ---------------------------------------------------------------------------
_CORP_SUFFIXES = [
    "co., ltd.", "co.,ltd.", "co., ltd", "co.,ltd", "co. ltd", "co ltd", "company limited",
    "corporation", "incorporated", "corp.", "corp", "inc.", "inc", "ltd.", "ltd", "llc",
    "l.l.c.", "gmbh & co. kg", "gmbh", "ag", "s.a.", "sa", "s.p.a.", "spa", "b.v.", "bv",
    "n.v.", "nv", "k.k.", "kk", "kabushiki kaisha", "co", "limited", "plc",
    "주식회사", "(주)", "㈜", "유한회사", "유한책임회사", "합자회사", "재단법인", "사단법인", "학교법인",
    "국립대학법인", "주)",
]
_PAREN_RE = re.compile(r"[\(\)\[\]\{\}（）]")
_MULTISPACE_RE = re.compile(r"\s+")
_SPECIAL_RE = re.compile(r"[\"'`!@#$%^*+=~?<>]")


def auto_standardize_name(name):
    """출원인/권리자명 자동 표준화(검토 대상 후보값).

    규칙: 트림 → 괄호류 제거 → 특수문자 제거 → 법인 접미사 제거(반복) → 공백 정리 →
    영문은 대문자 통일. 결과가 비면 원본 트림값 유지.
    """
    if name is None or (isinstance(name, float) and np.isnan(name)):
        return ""
    s = str(name).strip()
    if not s or s.lower() in ("nan", "none"):
        return ""
    original = s
    for marker in ("(주)", "㈜", "（주）", "주식회사", "(유)", "(재)", "(사)", "(학)"):
        s = s.replace(marker, " ")
    s = _PAREN_RE.sub(" ", s)
    s = _SPECIAL_RE.sub(" ", s)
    s = _MULTISPACE_RE.sub(" ", s).strip()
    changed = True
    while changed and s:
        changed = False
        low = s.lower()
        for suf in _CORP_SUFFIXES:
            if low.endswith(" " + suf) or low == suf or low.endswith(suf):
                cut = len(s) - len(suf)
                trimmed = s[:cut].strip(" ,.-·")
                if trimmed:
                    s = trimmed
                    changed = True
                    break
        low2 = s.lower()
        for pre in ("주식회사 ", "(주)", "㈜", "유한회사 "):
            if low2.startswith(pre.lower()):
                trimmed = s[len(pre):].strip(" ,.-·")
                if trimmed:
                    s = trimmed
                    changed = True
                break
    s = _MULTISPACE_RE.sub(" ", s).strip()
    if not s:
        return original
    if re.fullmatch(r"[\x00-\x7F]+", s):
        s = s.upper()
    return s


def split_names(value):
    """출원인/발명자 셀에서 복수 이름 분리 (세미콜론/파이프/쉼표+공백)."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return []
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none"):
        return []
    for sep in ("|", ";", "\n"):
        if sep in s:
            return [p.strip() for p in s.split(sep) if p.strip()]
    # 쉼표는 "성, 이름" 오분리 위험이 있어 ', ' + 대문자/한글 시작 패턴만 분리
    if ", " in s and len(s.split(", ")) > 1 and all(len(p.strip()) > 1 for p in s.split(", ")):
        return [p.strip() for p in s.split(", ") if p.strip()]
    return [s]


_NUMERIC_ONLY_RE = re.compile(r"^[+-]?\d+(\.\d+)?$")


def _mostly_numeric(series, threshold=0.7):
    """시리즈 값이 대부분 순수 숫자인지 (오매핑된 건수 컬럼 등 판별)."""
    s = series.dropna().astype(str).str.strip()
    s = s[(s != "") & (~s.str.lower().isin(["nan", "none"]))]
    if not len(s):
        return False
    return float(s.str.fullmatch(_NUMERIC_ONLY_RE).mean()) >= threshold


def standardize_applicants(df, applicant_rules=None):
    """출원인 표준화 컬럼 생성.

    applicant_rules: storage 에 저장된 사용자 규칙
      {"mapping": {원본명: 표준명}, "groups": {구성사 표준명: 그룹 대표명}}
    생성 컬럼:
      applicant_display : 분석·필터('기업')에 사용하는 최종 표준명
        (우선순위: 사용자 mapping > 데이터의 표준화 출원인 컬럼(값 그대로) > 자동 표준화)
      applicant_auto_std: 자동 표준화 후보값 (사용자 검토·승인 대상)
      applicant_raw     : 원본 첫 출원인 (복원용)

    방어: 출원인/표준화 출원인 컬럼의 값이 대부분 숫자(오매핑된 건수 컬럼 등)이면
    해당 컬럼을 무시하고 다른 소스를 사용한다.
    """
    rules = applicant_rules or {}
    user_map = {str(k).strip(): v for k, v in (rules.get("mapping") or {}).items()}
    groups = {str(k).strip(): v for k, v in (rules.get("groups") or {}).items()}

    app_col = "applicant" if ("applicant" in df.columns
                              and not _mostly_numeric(df["applicant"])) else None
    std_col = "applicant_std" if ("applicant_std" in df.columns
                                  and not _mostly_numeric(df["applicant_std"])) else None
    raw_source = app_col or std_col
    if raw_source is None:
        df["applicant_raw"] = ""
        df["applicant_auto_std"] = ""
        df["applicant_display"] = ""
        df["_co_applicants"] = [[] for _ in range(len(df))]
        return df

    raw_first = df[raw_source].map(lambda v: (split_names(v) or [""])[0])
    df["applicant_raw"] = raw_first
    df["applicant_auto_std"] = raw_first.map(auto_standardize_name)

    # 표준화 출원인 컬럼이 있으면 그 값을 그대로 사용 (재표준화하지 않음)
    if std_col:
        provided = df[std_col].map(lambda v: (split_names(v) or [""])[0].strip())
        provided = provided.map(lambda s: "" if s.lower() in ("nan", "none") else s)
    else:
        provided = pd.Series([""] * len(df), index=df.index)

    def _final(raw, prov, auto):
        name = user_map.get(raw) or user_map.get(prov) or user_map.get(auto)
        if not name:
            name = prov or auto or raw
        return groups.get(name, name)

    df["applicant_display"] = [
        _final(r, p, a) for r, p, a in zip(df["applicant_raw"], provided, df["applicant_auto_std"])]
    df["_co_applicants"] = (df[app_col].map(split_names)
                            if app_col else [[] for _ in range(len(df))])
    return df


def resolve_mapped_columns(mapping, available_columns):
    """매핑 컬럼명 ↔ 실제 로딩 컬럼명 해결.

    Dataiku 는 특수문자([ ] 등)·공백이 포함된 헤더를 스키마와 다르게 로딩하는 경우가
    있어, 정확히 일치하지 않으면 정규화(_norm) 기준으로 유일하게 대응되는 컬럼을
    찾는다. 유일 대응이 없으면 해당 개념은 제외 (임의 추측 금지).
    반환: {concept: 실제 컬럼명}
    """
    available = list(available_columns or [])
    avail_set = set(available)
    by_norm = {}
    for c in available:
        by_norm.setdefault(_norm_header(c), []).append(c)
    out = {}
    for concept, col in (mapping or {}).items():
        if not col:
            continue
        if col in avail_set:
            out[concept] = col
            continue
        candidates = by_norm.get(_norm_header(col), [])
        if len(candidates) == 1:
            out[concept] = candidates[0]
    return out


# 해결과제·해결수단 상투구 제거: "본 발명은 휨 저감…" → "휨 저감…"
_PS_BOILER_RE = re.compile(
    r"^\s*(?:본\s*(?:발명|고안|출원|기술|실시예?)|상기|이\s*발명)"
    r"(?:에\s*(?:따른|의한|있어서)|에서는|에서|의|은|는|이|가|을|를)?\s*[,:·]?\s*")
_PS_TAIL_RE = re.compile(r"\s*(?:을|를)?\s*(?:제공|해결|목적으로)\s*(?:하는|한다|함)?\s*"
                         r"(?:것이다|것|이다)?\s*[.。]?\s*$")


def clean_ps_text(value):
    """해결과제/해결수단 텍스트 정리.

    - 선두 상투구("본 발명은/본 고안의/상기 …") 반복 제거
    - 말미 상투구("…를 제공하는 것이다") 제거 (2회까지)
    - 공백 정리. 전부 제거되어 비면 원문 유지 (정보 손실 방지).
    """
    s = str(value or "").strip()
    if not s or s.lower() in ("nan", "none"):
        return value
    out = s
    for _ in range(3):
        new = _PS_BOILER_RE.sub("", out)
        if new == out:
            break
        out = new
    for _ in range(2):
        new = _PS_TAIL_RE.sub("", out)
        if new == out:
            break
        out = new
    out = re.sub(r"\s+", " ", out).strip(" ,·:;")
    return out if len(out) >= 2 else s


def _derive_country(df):
    """국가 컬럼 검증·파생.

    국가 컬럼이 없거나 값이 국가 형태(2~3자 코드 또는 짧은 비숫자 텍스트)가 아니면,
    공개번호/출원번호/등록번호의 선두 2자리 알파벳(KR10-…, US2020…)에서 파생한다.
    기존 값은 country_raw 로 보존. 파생 성공률 30% 미만이면 변경하지 않는다.
    """
    def _country_like_frac(series):
        s = series.dropna().astype(str).str.strip()
        s = s[(s != "") & (~s.str.lower().isin(["nan", "none"]))]
        if not len(s):
            return 0.0
        code = float(s.str.fullmatch(r"[A-Za-z]{2,3}").mean())
        short_text = float(((s.str.len() <= 8)
                            & (~s.str.fullmatch(_NUMERIC_ONLY_RE).fillna(False))
                            & (~s.str.contains(r"\d{4}", regex=True))).mean())
        return max(code, short_text)

    has_valid = "country" in df.columns and _country_like_frac(df["country"]) >= 0.3
    if has_valid:
        return df
    for id_col in ("pub_number", "app_number", "reg_number"):
        if id_col not in df.columns:
            continue
        prefix = df[id_col].astype(str).str.extract(r"^\s*([A-Za-z]{2})")[0].str.upper()
        if float(prefix.notna().mean()) >= 0.3:
            if "country" in df.columns:
                df["country_raw"] = df["country"]
            df["country"] = prefix
            break
    return df


# ---------------------------------------------------------------------------
# 표준 프레임 생성
# ---------------------------------------------------------------------------
def build_standard_frame(raw_df, mapping, applicant_rules=None):
    """원본 DataFrame + 매핑 → 표준 개념 컬럼 DataFrame.

    - 매핑된 컬럼만 유지·rename (필요 컬럼 최소화)
    - 날짜/불리언/다중분류/법적상태/출원인 표준화 파생 컬럼 생성
    - _base_year: 출원일 → 우선일 → 공개일 순의 대표 연도
    - 매핑 컬럼명이 로딩된 컬럼명과 정확히 일치하지 않으면(특수문자·공백 변형)
      정규화 매칭으로 복원한다 (resolve_mapped_columns)
    """
    cols = resolve_mapped_columns(mapping, list(raw_df.columns))
    df = raw_df[list(dict.fromkeys(cols.values()))].copy()
    df.columns = [c for c in df.columns]  # 유지
    rename = {}
    for concept, col in cols.items():
        if col not in rename.values():
            rename[col] = concept
    df = df.rename(columns=rename)
    # 동일 실제 컬럼이 두 개념에 매핑될 수는 없음(automap 이 보장) — 방어적으로 중복 제거
    df = df.loc[:, ~df.columns.duplicated()]

    raw_date_strs = {}
    for date_col in ("app_date", "pub_date", "reg_date", "priority_date", "expiry_date",
                     "lapse_date", "exam_request_date"):
        if date_col in df.columns:
            raw_date_strs[date_col] = df[date_col].astype(str)
            df[date_col] = parse_dates(df[date_col])
            df[date_col + "_year"] = df[date_col].dt.year

    base_year = pd.Series([np.nan] * len(df), index=df.index, dtype="float64")
    for date_col in ("app_date_year", "priority_date_year", "pub_date_year"):
        if date_col in df.columns:
            base_year = base_year.fillna(df[date_col])
    # 폴백: 날짜 해석이 전부 실패하면 원본 문자열에서 4자리 연도만 추출 (출원일 우선)
    if not base_year.notna().any():
        for date_col in ("app_date", "priority_date", "pub_date"):
            raw = raw_date_strs.get(date_col)
            if raw is None:
                continue
            ext = raw.str.extract(r"(?<!\d)((?:19|20)\d{2})(?!\d)")[0]
            years = pd.to_numeric(ext, errors="coerce")
            base_year = base_year.fillna(years)
            if date_col + "_year" in df.columns:
                df[date_col + "_year"] = df[date_col + "_year"].fillna(years)
    df["_base_year"] = base_year

    # 국가 폴백: 국가 컬럼이 없거나 값이 오염(숫자·날짜·빈값)됐으면 문헌번호 앞
    # 2자리 국가코드(KR10-…, US…)에서 파생. 원본은 country_raw 로 보존.
    df = _derive_country(df)

    # 해결과제·해결수단 상투구 제거 ("본 발명은 …" 등) — 원문은 *_raw 로 보존.
    # 매트릭스·필터·drill-down 이 모두 동일한 정제 값을 쓰도록 전처리에서 일괄 적용.
    for ps_col in ("problem", "solution"):
        if ps_col in df.columns:
            df[ps_col + "_raw"] = df[ps_col]
            df[ps_col] = df[ps_col].map(clean_ps_text)

    if "legal_status" in df.columns:
        df["legal_status_raw"] = df["legal_status"]
        df["legal_status_norm"] = df["legal_status"].map(normalize_legal_status)
    else:
        df["legal_status_raw"] = None
        df["legal_status_norm"] = "Unknown"

    def _obj_bool(values):
        """numpy bool → python bool 로 통일한 object 시리즈 (`v is True` 판정 안정화)."""
        return pd.Series([(bool(v) if isinstance(v, (bool, np.bool_)) else None)
                          for v in values], index=df.index, dtype=object)

    for bool_col, target in (("is_granted", "_is_granted_bool"), ("is_active", "_is_active_bool"),
                             ("is_own", "_is_own_bool")):
        df[target] = _obj_bool(df[bool_col].map(parse_bool)) if bool_col in df.columns \
            else pd.Series([None] * len(df), index=df.index, dtype=object)

    # 등록여부 폴백: 등록번호 존재 → 법적상태 순
    if all(v is None for v in df["_is_granted_bool"]):
        granted = pd.Series([None] * len(df), index=df.index, dtype=object)
        if "reg_number" in df.columns:
            granted = df["reg_number"].map(
                lambda v: True if (v is not None and str(v).strip() not in ("", "nan", "None")) else None)
        from_status = df["legal_status_norm"].map(
            lambda s: True if s in ("Granted-Active", "Granted-Expired")
            else (False if s in ("Pending", "Rejected", "Withdrawn") else None))
        df["_is_granted_bool"] = _obj_bool(
            [g if g is not None else f for g, f in zip(granted, from_status)])

    # 유효특허 플래그: is_active 컬럼 → 법적상태 순 (판단 불가 시 None)
    df["_active_flag"] = _obj_bool([
        (a if a is not None else
         ((s in ACTIVE_LEGAL_STATUSES) if (s and s != "Unknown") else None))
        for a, s in zip(df["_is_active_bool"], df["legal_status_norm"])])

    # 현재 권리자(소유자) 표준화 — 출원인과 동일한 규칙(사용자 mapping > 자동)을
    # 적용해 사명 표기 차이가 '가짜 양도'로 잡히지 않게 한다.
    if "assignee" in df.columns and not _mostly_numeric(df["assignee"]):
        _rules = applicant_rules or {}
        _omap = {str(k).strip(): v for k, v in (_rules.get("mapping") or {}).items()}
        owner_first = df["assignee"].map(lambda v: (split_names(v) or [""])[0])
        df["owner_display"] = owner_first.map(
            lambda v: _omap.get(str(v).strip(),
                                auto_standardize_name(v)) if str(v).strip() else "")
    else:
        df["owner_display"] = ""

    df = build_tech_lists(df)
    # B·C축 기술분류 리스트 (매핑된 경우에만 — 소→중→대 우선, 다중값 지원)
    for axis in ("b", "c"):
        target = "_tech_%s_list" % axis
        for level in ("l3", "l2", "l1"):
            col = "tech_%s_%s" % (axis, level)
            if col in df.columns:
                lists = df[col].map(parse_multiclass_cell)
                if lists.map(len).any():
                    df[target] = lists
                    break
    df = standardize_applicants(df, applicant_rules)

    for num_col in ("cites_backward", "cites_forward", "family_size",
                    "family_country_count", "class_confidence",
                    "claims_count", "indep_claims_count"):
        if num_col in df.columns:
            df[num_col] = parse_numeric(df[num_col])

    if "inventors" in df.columns:
        df["_inventor_list"] = df["inventors"].map(split_names)

    if "embedding" in df.columns:
        df["_embedding"] = df["embedding"].map(parse_embedding)

    return df


# ---------------------------------------------------------------------------
# 패밀리 dedup
# ---------------------------------------------------------------------------
def _completeness_score(row, text_cols):
    """서지·청구항 완전성 점수: 존재하는 텍스트 컬럼 값 길이 합 (③ 기준)."""
    score = 0
    for c in text_cols:
        v = row.get(c)
        if v is not None and not (isinstance(v, float) and np.isnan(v)):
            score += min(len(str(v)), 2000)
    return score


COUNTRY_PRIORITY = {"US": 0, "EP": 1, "KR": 2, "JP": 3, "CN": 4, "WO": 5}


def dedupe_families(df):
    """패밀리 단위 dedup: 패밀리별 대표문헌 1건 선택.

    우선순위: ① 유효 등록특허(_active_flag & _is_granted_bool)
             → ② 가장 이른 우선일(없으면 출원일)
             → ③ 서지·청구항 완전성(제목+요약+독립청구항+청구항 길이)
             → ④ 지정국 우선순위(US>EP>KR>JP>CN>WO>기타)
             → ⑤ 공개번호 오름차순.
    family_id 가 없으면 dedup 하지 않고 원본 반환 (분석단위 안내는 API 계층 담당).
    패밀리 대표문헌 컬럼(family_rep)이 있으면 대표문헌 == 공개번호 행을 최우선 선택.
    """
    if "family_id" not in df.columns or df["family_id"].isna().all():
        return df
    text_cols = [c for c in ("title", "abstract", "indep_claim", "claims") if c in df.columns]

    work = df.copy()
    fam = work["family_id"].astype(str).str.strip()
    no_fam = fam.isin(["", "nan", "None"]) | work["family_id"].isna()
    work["_fam_key"] = fam.where(~no_fam, other=["__solo_%d" % i for i in range(len(work))])

    # 정렬 점수 계산 (낮을수록 우선)
    active = work["_active_flag"].map(lambda v: 0 if v else 1)
    granted = work["_is_granted_bool"].map(lambda v: 0 if v else 1)
    rep_match = pd.Series([1] * len(work), index=work.index)
    if "family_rep" in work.columns and "pub_number" in work.columns:
        rep_match = (work["family_rep"].astype(str).str.strip()
                     == work["pub_number"].astype(str).str.strip()).map(lambda b: 0 if b else 1)
    prio_date = work["priority_date"] if "priority_date" in work.columns else None
    if prio_date is None or prio_date.isna().all():
        prio_date = work["app_date"] if "app_date" in work.columns else pd.Series(
            [pd.NaT] * len(work), index=work.index)
    completeness = work.apply(lambda r: -_completeness_score(r, text_cols), axis=1) if text_cols \
        else pd.Series([0] * len(work), index=work.index)
    country_rank = (work["country"].astype(str).str.strip().str.upper().map(
        lambda c: COUNTRY_PRIORITY.get(c, 9)) if "country" in work.columns
        else pd.Series([9] * len(work), index=work.index))
    pub_no = (work["pub_number"].astype(str) if "pub_number" in work.columns
              else pd.Series([""] * len(work), index=work.index))

    work["_sort_rep"] = rep_match
    work["_sort_active_granted"] = active + granted
    work["_sort_prio"] = prio_date.fillna(pd.Timestamp("2262-01-01"))
    work["_sort_completeness"] = completeness
    work["_sort_country"] = country_rank
    work["_sort_pub"] = pub_no
    work = work.sort_values(
        ["_fam_key", "_sort_rep", "_sort_active_granted", "_sort_prio",
         "_sort_completeness", "_sort_country", "_sort_pub"])
    deduped = work.drop_duplicates(subset="_fam_key", keep="first")
    deduped = deduped.drop(columns=[c for c in deduped.columns if c.startswith("_sort_")])
    return deduped.drop(columns=["_fam_key"])


def apply_analysis_unit(df, unit):
    """분석 단위 적용: family=패밀리 dedup / registration=등록건만 / 그 외 원본."""
    if unit == "family":
        return dedupe_families(df)
    if unit == "registration":
        mask = df["_is_granted_bool"].map(lambda v: v is True)
        sub = df[mask]
        return sub if len(sub) else df.iloc[0:0]
    return df  # publication / application: 문헌 단위 그대로


# ---------------------------------------------------------------------------
# 공통 필터
# ---------------------------------------------------------------------------
def apply_filters(df, filters):
    """공통 필터 적용.

    filters 예:
      {"year_from": 2015, "year_to": 2024, "applicants": [...], "countries": [...],
       "legal_statuses": [...(정규화값)...], "tech_l1": [...], "tech_l2": [...],
       "tech_l3": [...], "tech": [...(=_tech_list 항목)...], "active_only": true}
    존재하지 않는 컬럼 관련 필터는 무시 (graceful degradation).
    """
    f = filters or {}
    mask = pd.Series(True, index=df.index)

    yf, yt = f.get("year_from"), f.get("year_to")
    if yf not in (None, "") or yt not in (None, ""):
        years = df["_base_year"]
        if yf not in (None, ""):
            mask &= years.notna() & (years >= float(yf))
        if yt not in (None, ""):
            mask &= years.notna() & (years <= float(yt))

    if f.get("applicants"):
        wanted = set(map(str, f["applicants"]))
        mask &= df["applicant_display"].astype(str).isin(wanted)

    if f.get("countries") and "country" in df.columns:
        wanted = set(str(c).strip().upper() for c in f["countries"])
        mask &= df["country"].astype(str).str.strip().str.upper().isin(wanted)

    if f.get("legal_statuses"):
        wanted = set(map(str, f["legal_statuses"]))
        mask &= df["legal_status_norm"].isin(wanted)

    for level, col in (("tech_l1", "_tech_l1_list"), ("tech_l2", "_tech_l2_list"),
                       ("tech_l3", "_tech_l3_list")):
        if f.get(level) and col in df.columns:
            wanted = set(map(str, f[level]))
            mask &= df[col].map(lambda lst: bool(set(lst or []) & wanted))

    if f.get("tech"):
        wanted = set(map(str, f["tech"]))
        mask &= df["_tech_list"].map(lambda lst: bool(set(lst or []) & wanted))

    if f.get("active_only"):
        mask &= df["_active_flag"].map(lambda v: v is True)

    return df[mask]


# ---------------------------------------------------------------------------
# 다중분류 explode
# ---------------------------------------------------------------------------
def explode_tech(df, mode=None, level=None):
    """행×기술분류 long-format 변환.

    mode:
      duplicate     — 각 기술분류에 1건씩 중복 계산 (weight=1)
      fractional    — 1/N 가중치 배분 (weight=1/분류수)
      primary       — 대표(첫) 기술분류만 사용 (weight=1)
      level_separate— level 인자('l1'|'l2'|'l3')의 분류 리스트 사용
    반환: 원본 컬럼 + [tech, weight]. 기술분류 없는 행은 제외.
    """
    mode = mode or DEFAULT_MULTICLASS_MODE
    col = "_tech_list"
    if mode == "level_separate" and level:
        cand = "_tech_%s_list" % level
        col = cand if cand in df.columns else "_tech_list"

    lists = df[col].map(lambda lst: list(lst or []))
    if mode == "primary":
        lists = lists.map(lambda lst: lst[:1])
    n = lists.map(len)
    keep = n > 0
    sub = df[keep].copy()
    sub["_x_tech"] = lists[keep]
    sub["_x_n"] = n[keep]
    exploded = sub.explode("_x_tech")
    exploded = exploded.rename(columns={"_x_tech": "tech"})
    if mode == "fractional":
        exploded["weight"] = 1.0 / exploded["_x_n"].astype(float)
    else:
        exploded["weight"] = 1.0
    return exploded.drop(columns=["_x_n"])


_PURE_NUMBER_RE = re.compile(r"^[+-]?\d+(\.\d+)?$")
_DATEISH_RE = re.compile(r"^(19|20)\d{2}([.\-/]\d{1,2}){0,2}\.?$|^(19|20)\d{6}$")
_COUNTRY_CODE_RE = re.compile(r"^[A-Z]{2,3}$")


_JUNK_TOKENS = frozenset(["nan", "none", "null", "n/a", "na", "-", "or", "and", "of",
                          "the", "etc", "true", "false", "y", "n", "yes", "no"])


def _clean_option_values(values):
    """필터 옵션 오염값 제거.

    순수 숫자·날짜형 값, 접속사류 잔여 토큰(or/and 등), 1글자 값(문헌 종류코드 a 등)은
    범주가 아니므로 제외한다.
    """
    out = []
    for v in values:
        sv = str(v).strip()
        if not sv or len(sv) <= 1:
            continue
        if sv.lower() in _JUNK_TOKENS:
            continue
        if _PURE_NUMBER_RE.match(sv) or _DATEISH_RE.match(sv):
            continue
        out.append(v)
    return out


def filter_options(df):
    """필터바 옵션 생성: 연도범위/출원인/국가/법적상태/기술분류 목록 (Top 값 순).

    매핑 오류로 섞여 들어온 숫자·날짜형 값은 옵션에서 제외한다 (오염 방지).
    국가는 2~3자 알파벳 코드만 노출한다.
    """
    years = df["_base_year"].dropna()
    countries = []
    if "country" in df.columns:
        raw = df["country"].astype(str).str.strip().str.upper().replace("", np.nan) \
            .replace("NAN", np.nan).dropna().value_counts().index.tolist()
        countries = [c for c in raw if _COUNTRY_CODE_RE.match(str(c))]
        if not countries:  # 코드가 아닌 국가명(한글 등)만 있는 경우: 날짜·숫자만 제거
            countries = _clean_option_values(raw)[:50]
    opts = {
        "year_min": int(years.min()) if len(years) else None,
        "year_max": int(years.max()) if len(years) else None,
        "applicants": _clean_option_values(
            df["applicant_display"].astype(str).replace("", np.nan).dropna()
              .value_counts().head(400).index.tolist())[:300],
        "countries": countries,
        "legal_statuses": df["legal_status_norm"].value_counts().index.tolist(),
        "tech_l1": _level_values(df, "_tech_l1_list"),
        "tech_l2": _level_values(df, "_tech_l2_list"),
        "tech_l3": _level_values(df, "_tech_l3_list"),
        "tech": _clean_option_values(
            pd.Series([t for lst in df["_tech_list"] for t in lst])
              .value_counts().head(400).index.tolist())[:300] if len(df) else [],
    }
    return opts


def _level_values(df, col):
    if col not in df.columns or not len(df):
        return []
    return _clean_option_values(
        pd.Series([t for lst in df[col] for t in (lst or [])])
        .value_counts().head(300).index.tolist())[:200]
