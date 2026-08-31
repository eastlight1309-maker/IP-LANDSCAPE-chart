# -*- coding: utf-8 -*-
"""
analyses/common.py — 분석 모듈 공통 유틸.

- combo_counts(): 행별 기술분류 리스트 → 조합(pair) 동시출현 집계 (전체/최근/신규출원인)
- tech_year_matrix(): 기술분류 × 연도 건수 매트릭스 (가중치 지원)
- select_patents(): drill-down 조건 → 근거 특허 행 선택 (모든 그래프 클릭의 근거)
- patent_records(): 특허 목록 직렬화 (페이지네이션)
- company_tech_shares(): 기업×기술분류 구성비 벡터
"""
from itertools import combinations

import numpy as np
import pandas as pd

from src.preprocessing import explode_tech


def _pair_key(a, b):
    return (a, b) if a <= b else (b, a)


def diagnose_year_tech(df):
    """연도·기술분류 부족 시 사용자 조치가 가능한 진단 메시지 생성."""
    n = len(df)
    n_year = int(df["_base_year"].notna().sum()) if "_base_year" in df.columns else 0
    n_tech = int(df["_tech_list"].map(lambda lst: bool(lst)).sum()) \
        if "_tech_list" in df.columns else 0
    problems = []
    if n_year == 0:
        problems.append("연도를 해석할 수 있는 문헌이 없습니다 — 출원일/우선일/공개일 매핑과 "
                        "날짜 형식(YYYY-MM-DD, YYYY.MM.DD, YYYYMMDD)을 확인하세요")
    if n_tech == 0:
        problems.append("기술분류가 있는 문헌이 없습니다 — 기술 대/중/소분류 또는 다중 기술분류 "
                        "매핑을 확인하세요")
    detail = " / ".join(problems) if problems else "표본이 부족합니다"
    return ("계산 불가: %s. (전체 %d건 중 연도 해석 %d건, 기술분류 보유 %d건) "
            "Settings → 컬럼 매핑에서 매핑된 실제 컬럼과 예시 값을 확인하세요."
            % (detail, n, n_year, n_tech))


def combo_counts(df, recent_year_from=None, settings=None):
    """기술분류 pair 동시출현 집계.

    반환 DataFrame: [a, b, n_ab(전체), n_recent(최근), applicants(set), new_applicants(set),
                     years(list)] — new_applicants 는 최근 구간에 처음 등장한 출원인.
    개별 기술 건수는 dict 로 함께 반환: (pairs_df, tech_counts, n_docs)
    출원인 집합은 coapplicant_mode 를 따른다 (기본 'all'=공동출원인 각각 포함).
    """
    rows = []
    tech_counts = {}
    first_year_by_pair_applicant = {}
    pair_rows = {}
    n_docs = 0
    use_co = (_coapp_mode(settings) == "all"
              and "_co_applicants_display" in df.columns)
    app_lists = (df["_co_applicants_display"] if use_co
                 else df["applicant_display"].map(lambda a: [a] if str(a).strip() else []))
    for techs, year, row_apps in zip(df["_tech_list"], df["_base_year"], app_lists):
        row_apps = [str(a).strip() for a in (row_apps or []) if str(a).strip()]
        techs = sorted(set(techs or []))
        if not techs:
            continue
        n_docs += 1
        for t in techs:
            tech_counts[t] = tech_counts.get(t, 0) + 1
        if len(techs) < 2:
            continue
        y = int(year) if not (year is None or (isinstance(year, float) and np.isnan(year))) else None
        for a, b in combinations(techs, 2):
            key = _pair_key(a, b)
            rec = pair_rows.setdefault(key, {"a": key[0], "b": key[1], "n_ab": 0,
                                             "n_recent": 0, "applicants": set(),
                                             "recent_applicants": set(), "years": []})
            rec["n_ab"] += 1
            if y is not None:
                rec["years"].append(y)
            for applicant in row_apps:
                rec["applicants"].add(applicant)
            if recent_year_from is not None and y is not None and y >= recent_year_from:
                rec["n_recent"] += 1
                for applicant in row_apps:
                    rec["recent_applicants"].add(applicant)
            if y is not None:
                for applicant in row_apps:
                    fk = (key, applicant)
                    prev = first_year_by_pair_applicant.get(fk)
                    if prev is None or y < prev:
                        first_year_by_pair_applicant[fk] = y
        rows.append(techs)
    # 신규 출원인: 해당 조합에 최근 구간에 처음 등장
    for (key, applicant), first_y in first_year_by_pair_applicant.items():
        if recent_year_from is not None and first_y >= recent_year_from:
            pair_rows[key].setdefault("new_applicants", set()).add(applicant)
    records = []
    for key, rec in pair_rows.items():
        rec.setdefault("new_applicants", set())
        records.append(rec)
    pairs_df = pd.DataFrame(records) if records else pd.DataFrame(
        columns=["a", "b", "n_ab", "n_recent", "applicants", "recent_applicants",
                 "new_applicants", "years"])
    return pairs_df, tech_counts, n_docs


def tech_year_matrix(df, multiclass_mode="duplicate", level=None):
    """기술분류 × 연도 건수 매트릭스 (pivot). 반환: DataFrame(index=tech, columns=year)."""
    ex = explode_tech(df, mode=multiclass_mode, level=level)
    ex = ex[ex["_base_year"].notna()]
    if not len(ex):
        return pd.DataFrame()
    ex["_year_int"] = ex["_base_year"].astype(int)
    mat = ex.pivot_table(index="tech", columns="_year_int", values="weight",
                         aggfunc="sum", fill_value=0.0)
    if len(mat.columns):
        full_years = range(int(mat.columns.min()), int(mat.columns.max()) + 1)
        mat = mat.reindex(columns=full_years, fill_value=0.0)
    return mat


def company_tech_shares(df, multiclass_mode="duplicate", by_year=False):
    """기업(×연도)별 기술분류 구성비 벡터.

    반환: DataFrame(index=(company[,year]), columns=tech, values=구성비 0~1).
    """
    ex = explode_tech(df, mode=multiclass_mode)
    ex = ex[ex["applicant_display"].astype(str) != ""]
    if by_year:
        ex = ex[ex["_base_year"].notna()]
        if not len(ex):
            return pd.DataFrame()
        ex["_year_int"] = ex["_base_year"].astype(int)
        counts = ex.pivot_table(index=["applicant_display", "_year_int"], columns="tech",
                                values="weight", aggfunc="sum", fill_value=0.0)
    else:
        if not len(ex):
            return pd.DataFrame()
        counts = ex.pivot_table(index="applicant_display", columns="tech",
                                values="weight", aggfunc="sum", fill_value=0.0)
    sums = counts.sum(axis=1)
    sums[sums == 0] = 1.0
    return counts.div(sums, axis=0)


# ---------------------------------------------------------------------------
# Drill-down
# ---------------------------------------------------------------------------
def applicant_mask(df, name, scope="display"):
    """출원인 매칭 마스크.

    scope="any"  : 공동출원인 중 하나로라도 포함되면 매칭 (공동출원 귀속)
    scope 기타   : 대표 출원인(applicant_display) 일치만 (기존 동작)
    """
    nm = str(name)
    eq = df["applicant_display"].astype(str) == nm
    if scope != "any" or "_co_applicants_display" not in df.columns:
        return eq
    return eq | df["_co_applicants_display"].map(lambda lst: nm in (lst or []))


def select_patents(df, drill):
    """drill-down 조건 → 근거 특허 행 선택.

    drill 예:
      {"type":"tech","tech":"본딩"}                — 해당 기술분류 포함
      {"type":"combo","a":"본딩","b":"몰딩"}       — 두 분류 동시 포함
      {"type":"applicant","applicant":"삼성전자"}  — 해당 출원인
      {"type":"cell","problem":"...","solution":"..."} — 문제-해결수단 셀
      {"type":"tech_applicant","tech":…,"applicant":…}
      {"type":"transition","source":…,"target":…} — 두 분류 중 하나 이상 포함
      {"type":"year","year":2021}                  — 해당 연도
      {"type":"inventor","inventor":"홍길동"}      — 발명자 이력
      {"type":"ids","ids":[공개번호...]}           — 명시적 문헌 목록
      조합 필드는 and 로 결합 (예: tech + year).
    알 수 없는 type 이면 전체 반환.
    """
    if not drill:
        return df
    mask = pd.Series(True, index=df.index)
    dtype = drill.get("type", "")

    def has_tech(t):
        return df["_tech_list"].map(lambda lst: t in (lst or []))

    if dtype == "tech" or "tech" in drill:
        t = drill.get("tech")
        if t:
            if drill.get("tech_primary"):
                # 대표(첫) 분류 기준으로 집계한 차트의 drill — 포함 매칭을 쓰면
                # 차트 건수보다 많은 상위집합이 열리므로 대표 분류 일치로 제한
                mask &= df["_tech_list"].map(
                    lambda lst, tv=str(t): bool(lst) and str(lst[0]) == tv)
            else:
                mask &= has_tech(str(t))
    if dtype == "combo":
        a, b = drill.get("a"), drill.get("b")
        if a:
            mask &= has_tech(str(a))
        if b:
            mask &= has_tech(str(b))
    if dtype == "transition":
        a, b = drill.get("source"), drill.get("target")
        m = pd.Series(False, index=df.index)
        if a:
            m |= has_tech(str(a))
        if b:
            m |= has_tech(str(b))
        mask &= m
    if drill.get("applicant"):
        # applicant_scope="any": 공동출원인으로 포함된 건까지 매칭 (공동출원인
        # 각각 집계 모드의 차트에서 온 drill). 기본은 대표 출원인 일치 — 기존
        # 차트·공동출원 분석의 drill 의미를 바꾸지 않는다.
        mask &= applicant_mask(df, drill["applicant"],
                               scope=drill.get("applicant_scope", "display"))
    if drill.get("co_applicant"):
        # 출원인 화면을 특정 회사로 좁혀 본 상태의 drill: 그 회사가 (공동)출원인으로
        # 포함된 건으로 추가 제한
        mask &= applicant_mask(df, drill["co_applicant"], scope="any")
    if drill.get("joint_only") and "_co_applicants_display" in df.columns:
        # 공동출원 건만: 표준화 후 서로 다른 출원인 2인 이상 (협력 네트워크 노드 drill)
        mask &= df["_co_applicants_display"].map(lambda lst: len(lst or []) >= 2)
    if drill.get("ipc_main") and "ipc" in df.columns:
        # IPC/CPC 서브클래스(4자리) drill: 해당 코드로 시작하는 분류 보유 문헌
        from src.preprocessing import parse_multiclass_cell as _pmc
        _code = str(drill["ipc_main"]).upper().replace(" ", "")
        mask &= df["ipc"].map(lambda v: any(
            str(x).strip().upper().replace(" ", "").startswith(_code)
            for x in _pmc(v)))
    if drill.get("owner") and "owner_display" in df.columns:
        mask &= df["owner_display"].astype(str) == str(drill["owner"])
    if drill.get("transferred") is not None and "owner_display" in df.columns:
        both = (df["applicant_display"].astype(str) != "") & \
               (df["owner_display"].astype(str) != "")
        diff = df["applicant_display"].astype(str) != df["owner_display"].astype(str)
        mask &= (both & diff) if drill["transferred"] else (both & ~diff)
    if drill.get("year") not in (None, ""):
        mask &= df["_base_year"] == float(drill["year"])
    if dtype == "cell":
        # PS 매트릭스는 C축(해결과제)×B축(해결수단) 기반 — 축 리스트 포함 매칭 우선,
        # 축이 없으면 구버전 텍스트 컬럼 매칭으로 폴백
        p, s = drill.get("problem"), drill.get("solution")
        use_axes = "_tech_c_list" in df.columns and "_tech_b_list" in df.columns
        if p:
            if use_axes:
                mask &= df["_tech_c_list"].map(lambda lst: str(p) in (lst or []))
            elif "problem" in df.columns:
                mask &= df["problem"].astype(str).str.strip() == str(p)
        if s:
            if use_axes:
                mask &= df["_tech_b_list"].map(lambda lst: str(s) in (lst or []))
            elif "solution" in df.columns:
                mask &= df["solution"].astype(str).str.strip() == str(s)
    if dtype == "axis_cell":  # A/B/C 분류축 교차 셀: 각 축의 값 동시 포함
        axis_cols = {"A": "_tech_list", "B": "_tech_b_list", "C": "_tech_c_list"}
        for cond in (drill.get("conds") or []):
            col = axis_cols.get(str(cond.get("axis", "")).upper())
            val = cond.get("value")
            if col and col in df.columns and val:
                mask &= df[col].map(lambda lst: str(val) in (lst or []))
    if dtype == "cell_group":  # 의미 그룹 셀: 그룹에 속한 문구 목록으로 매칭
        if drill.get("problems") and "problem" in df.columns:
            wanted_p = set(map(str, drill["problems"]))
            mask &= df["problem"].astype(str).str.strip().isin(wanted_p)
        if drill.get("solutions") and "solution" in df.columns:
            wanted_s = set(map(str, drill["solutions"]))
            mask &= df["solution"].astype(str).str.strip().isin(wanted_s)
    for _lk, _lc in (("tech_l1", "_tech_l1_list"), ("tech_l2", "_tech_l2_list"),
                     ("tech_l3", "_tech_l3_list")):
        if drill.get(_lk) and _lc in df.columns:
            _lv = str(drill[_lk])
            if drill.get("tech_levels_primary"):
                # 트리맵·계층 버블은 문헌당 각 레벨의 첫(대표) 분류로 1회 집계 —
                # drill 도 대표 분류 일치로 제한해야 차트 건수와 목록이 일치
                mask &= df[_lc].map(
                    lambda lst, v=_lv: bool(lst) and str(lst[0]) == v)
            else:
                mask &= df[_lc].map(lambda lst, v=_lv: v in (lst or []))
    if drill.get("tech_path_next_empty"):
        # 계층 경로가 중간에 끊긴 행의 drill: 다음 레벨 대표 분류가 비어 있는
        # 문헌만 — 하위 경로 행과 목록이 겹치지 않게 한다
        _nc = "_%s_list" % str(drill["tech_path_next_empty"])
        if _nc in df.columns:
            def _first_empty(lst):
                v = (lst or [None])[0]
                s = "" if v is None else str(v).strip()
                return (not s) or s.lower() in ("nan", "none", "-")
            mask &= df[_nc].map(_first_empty)
    if drill.get("npl_cited") is not None and "npl_count" in df.columns:
        from src.preprocessing import parse_numeric as _pnum
        npl = _pnum(df["npl_count"]).fillna(0)
        mask &= (npl > 0) if drill["npl_cited"] else (npl <= 0)
    if drill.get("licensed") is not None and "license_flag" in df.columns:
        from src.preprocessing import parse_bool as _pb
        lic = df["license_flag"].map(_pb)
        mask &= (lic == True) if drill["licensed"] else (lic == False)  # noqa: E712
    if drill.get("sep") is not None and "sep_org" in df.columns:
        has_sep = ~df["sep_org"].astype(str).str.strip().str.lower() \
            .isin(["", "nan", "none", "-"])
        mask &= has_sep if drill["sep"] else ~has_sep
    if drill.get("gov_program") and "gov_program" in df.columns:
        mask &= df["gov_program"].astype(str).str.strip() == \
            str(drill["gov_program"]).strip()
    if drill.get("gov_linked") is not None and "gov_program" in df.columns:
        prog = df["gov_program"].astype(str).str.strip()
        linked = ~prog.str.lower().isin(["", "nan", "none", "-"])
        mask &= linked if drill["gov_linked"] else ~linked
    if drill.get("inventor") and "_inventor_list" in df.columns:
        inv = str(drill["inventor"])
        mask &= df["_inventor_list"].map(lambda lst: inv in (lst or []))
    if dtype == "ids" and drill.get("ids"):
        wanted = set(map(str, drill["ids"]))
        id_col = "pub_number" if "pub_number" in df.columns else \
            ("app_number" if "app_number" in df.columns else None)
        if id_col:
            mask &= df[id_col].astype(str).isin(wanted)
        else:
            mask &= df.index.astype(str).isin(wanted)
    if drill.get("legal_status"):
        mask &= df["legal_status_norm"] == str(drill["legal_status"])
    if drill.get("country") and "country" in df.columns:
        mask &= df["country"].astype(str).str.upper() == str(drill["country"]).upper()
    return df[mask]


_RECORD_FIELDS = [
    ("pub_number", "공개번호"), ("app_number", "출원번호"), ("reg_number", "등록번호"),
    ("title", "발명의 명칭"), ("applicant_display", "출원인"), ("country", "국가"),
    ("legal_status_norm", "법적상태"), ("family_id", "패밀리 ID"),
    ("cites_forward", "피인용 수"), ("family_size", "패밀리 수"),
    ("gov_program", "국가과제"),   # 매핑된 경우에만 표시 — 연계특허 식별용
]


def patent_records(df, page=1, page_size=25, max_page_size=200, extra_fields=None):
    """특허 목록 직렬화 + 페이지네이션.

    반환: {"total", "page", "page_size", "records": [...]} — 대용량 JSON 응답 방지.
    """
    page = max(1, int(page or 1))
    page_size = min(max(1, int(page_size or 25)), int(max_page_size))
    total = len(df)
    start = (page - 1) * page_size
    sub = df.iloc[start:start + page_size]
    fields = list(_RECORD_FIELDS) + list(extra_fields or [])
    records = []
    for _, row in sub.iterrows():
        rec = {}
        for col, label in fields:
            if col in sub.columns:
                v = row.get(col)
                if isinstance(v, float) and np.isnan(v):
                    v = None
                rec[label] = v if v is None or isinstance(v, (int, float, bool)) else str(v)
        y = row.get("_base_year")
        rec["연도"] = int(y) if y is not None and not (isinstance(y, float) and np.isnan(y)) else None
        # 공동출원 건은 출원인 전원(표준명) 표시 — 대표 출원인만 보이면
        # 협력 네트워크 등에서 연 목록에서 상대 회사가 확인되지 않는다
        co_all = row.get("_co_applicants_display") or []
        if len(co_all) >= 2 and "출원인" in rec:
            rec["출원인"] = "; ".join(map(str, co_all))
        techs = row.get("_tech_list") or []
        rec["기술분류"] = "; ".join(map(str, techs[:6]))
        # 대표청구항: 윈텔립스 '대표청구항'(claims) 우선, 없으면 독립청구항 앞부분.
        # 컬럼이 매핑돼 있으면 모든 행에 키를 넣어 목록 표의 열이 항상 표시되게 한다.
        if "claims" in sub.columns or "indep_claim" in sub.columns:
            claim = ""
            for ccol in ("claims", "indep_claim"):
                if ccol in sub.columns:
                    v = row.get(ccol)
                    s = "" if v is None else str(v).strip()
                    if s and s.lower() not in ("nan", "none"):
                        claim = s
                        break
            rec["대표청구항"] = claim[:180] + ("…" if len(claim) > 180 else "")
        active = row.get("_active_flag")
        rec["유효특허"] = ("Y" if active is True else ("N" if active is False else "?"))
        records.append(rec)
    return {"total": int(total), "page": page, "page_size": page_size, "records": records}


def export_dataframe(df, extra_fields=None, max_rows=20000):
    """Excel export 용 DataFrame (행 상한 적용)."""
    fields = list(_RECORD_FIELDS) + list(extra_fields or [])
    cols, labels = [], []
    for col, label in fields:
        if col in df.columns:
            cols.append(col)
            labels.append(label)
    out = df[cols].head(int(max_rows)).copy()
    out.columns = labels
    techs = df["_tech_list"].head(int(max_rows)).map(lambda lst: "; ".join(map(str, lst or [])))
    out["기술분류"] = techs
    years = df["_base_year"].head(int(max_rows))
    out["연도"] = years
    return out


# ---------------------------------------------------------------------------
# 공동출원 집계 공용 헬퍼 — coapplicant_mode 설정을 모든 출원인 집계에 일관 적용
# ---------------------------------------------------------------------------
def _coapp_mode(settings):
    return str((settings or {}).get("coapplicant_mode") or "all")


def applicant_series(df, settings):
    """coapplicant_mode 를 따르는 출원인 Series (index=문헌, 값=출원인명).

    mode 'all'(기본, WIPS 방식): 공동출원 1건이 각 공동출원인 행으로 전개되어
    출원인별 카운팅 시 각각 1건씩 계산된다 (합계가 문헌 수를 초과할 수 있음).
    mode 'first': 대표(첫) 출원인만. 빈 이름은 제외.
    """
    import pandas as _pd
    if _coapp_mode(settings) == "all" and "_co_applicants_display" in df.columns:
        idx, vals = [], []
        for i, lst in df["_co_applicants_display"].items():
            for a in (lst or []):
                s = str(a).strip()
                if s:
                    idx.append(i)
                    vals.append(s)
        if vals:
            return _pd.Series(vals, index=idx)
    s = df["applicant_display"].astype(str)
    s = s[s.str.strip() != ""]
    return s


def applicant_counts(df, settings):
    """coapplicant_mode 를 따르는 출원인별 문헌 수 value_counts."""
    return applicant_series(df, settings).value_counts()


def applicant_set(df, settings):
    """coapplicant_mode 를 따르는 출원인 집합 (신규 진입 판정 등)."""
    return set(applicant_series(df, settings))


def company_groups(df, settings, min_n=0, head=None):
    """(회사, 소속 문헌 subframe) 반복자 — 문헌 수 내림차순.

    mode 'all': 회사별 subframe = 그 회사가 (공동)출원인으로 포함된 문헌 전체
    (공동출원 1건이 양쪽 회사 subframe 에 모두 나타남 — 각각 집계).
    mode 'first': 대표 출원인 일치 문헌만.
    """
    ser = applicant_series(df, settings)
    counts = ser.value_counts()
    if head:
        counts = counts.head(int(head))
    for comp, n in counts.items():
        if n < min_n:
            continue
        yield str(comp), df.loc[ser.index[ser == comp]]


def explode_applicants(df, settings):
    """출원인별 groupby 용 전개 프레임 — applicant_display 를 coapplicant_mode
    기준으로 치환한 복사본. mode 'all'이면 공동출원 1건이 공동출원인 수만큼
    행으로 복제된다 (출원인별 집계 전용 — 문헌 단위 집계에 쓰면 중복됨).

    입력 인덱스가 중복(예: 기술분류 전개 프레임)이어도 안전하도록 내부에서
    위치 기반 인덱스로 재설정한 뒤 전개한다."""
    work = df.reset_index(drop=True)
    ser = applicant_series(work, settings)
    out = work.loc[ser.index].copy()
    out["applicant_display"] = ser.values
    return out
