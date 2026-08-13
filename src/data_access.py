# -*- coding: utf-8 -*-
"""
data_access.py — Dataiku Dataset 로딩 + 전처리 파이프라인 진입점.

- list_datasets(): 프로젝트 내 Dataset 이름 목록 (화이트리스트의 원천)
- validate_dataset_name(): 사용자 입력 Dataset 명을 목록과 대조 (임의 문자열 차단)
- get_dataset_columns(): 스키마에서 컬럼명 목록
- load_raw_dataframe(): 필요한 컬럼만 로딩 (dataiku.Dataset.get_dataframe(columns=...))
- get_prepared(): 표준 프레임(전처리 완료) 캐시 조회/생성 — 모든 분석의 공통 진입점.
  캐시 키 = (dataset, mapping, applicant_rules, analysis_unit).
  분석 단위(family dedup 등) 적용 결과를 캐시한다.

로컬 개발·테스트 폴백: dataiku 미설치 시 CSV 디렉터리(IP_LANDSCAPE_DATA_DIR)의
<dataset>.csv 를 로딩하고, 데모 모드에서는 등록된 in-memory DataFrame 을 사용한다.
Demo mode 는 사용자가 Settings 에서 명시적으로 켠 경우에만 동작한다.
"""
import logging
import os

import pandas as pd

from src.cache import DF_CACHE, make_cache_key
from src.column_mapping import CONCEPTS
from src.preprocessing import build_standard_frame, apply_analysis_unit, \
    resolve_mapped_columns

logger = logging.getLogger("ip_landscape")

try:
    import dataiku as _dataiku_mod
except ImportError:
    _dataiku_mod = None

_LOCAL_DATA_DIR = os.environ.get("IP_LANDSCAPE_DATA_DIR", os.path.abspath("."))

# 테스트/데모용 in-memory 데이터 주입 지점 {name: DataFrame}
_INJECTED_DATASETS = {}


def inject_dataset(name, df):
    """테스트·데모용 DataFrame 등록 (Dataiku 미가용 환경 전용)."""
    _INJECTED_DATASETS[str(name)] = df
    DF_CACHE.clear()


def list_datasets():
    """사용 가능한 Dataset 이름 목록 (화이트리스트)."""
    names = list(_INJECTED_DATASETS.keys())
    if _dataiku_mod is not None:
        try:
            client = _dataiku_mod.api_client()
            project = client.get_default_project()
            names += [d["name"] for d in project.list_datasets()]
        except Exception as e:
            logger.warning("list_datasets via dataiku failed: %s", e)
    else:
        try:
            for fn in sorted(os.listdir(_LOCAL_DATA_DIR)):
                if fn.lower().endswith(".csv"):
                    names.append(os.path.splitext(fn)[0])
        except OSError:
            pass
    # 순서 유지 중복 제거
    return list(dict.fromkeys(names))


def validate_dataset_name(name):
    """Dataset 명 화이트리스트 검증. 유효하면 원래 이름, 아니면 None."""
    if not name:
        return None
    name = str(name)
    return name if name in set(list_datasets()) else None


def get_dataset_columns(dataset_name):
    """Dataset 의 컬럼명 목록. 실패 시 []."""
    name = validate_dataset_name(dataset_name)
    if name is None:
        return []
    if name in _INJECTED_DATASETS:
        return list(_INJECTED_DATASETS[name].columns)
    if _dataiku_mod is not None:
        try:
            ds = _dataiku_mod.Dataset(name)
            schema = ds.read_schema()
            return [c["name"] for c in schema]
        except Exception as e:
            logger.warning("read_schema failed for %s: %s", name, e)
            return []
    path = os.path.join(_LOCAL_DATA_DIR, name + ".csv")
    try:
        return list(pd.read_csv(path, nrows=0).columns)
    except (OSError, ValueError):
        return []


def load_raw_dataframe(dataset_name, columns=None):
    """원본 DataFrame 로딩. columns 지정 시 해당 컬럼만 (50,000건 대비 메모리 절약)."""
    name = validate_dataset_name(dataset_name)
    if name is None:
        raise ValueError("허용되지 않은 Dataset: %r" % dataset_name)
    if name in _INJECTED_DATASETS:
        df = _INJECTED_DATASETS[name]
        if columns:
            cols = [c for c in columns if c in df.columns]
            return df[cols].copy()
        return df.copy()
    if _dataiku_mod is not None:
        ds = _dataiku_mod.Dataset(name)
        wanted = [c for c in (columns or []) if c]
        if wanted:
            # 스키마에 실존하는 컬럼만 요청 (매핑이 오래된 경우 방어)
            try:
                schema_cols = set(get_dataset_columns(name))
                requested = [c for c in wanted if c in schema_cols] or wanted
            except Exception:
                requested = wanted
            try:
                return ds.get_dataframe(columns=requested, infer_with_pandas=True)
            except Exception as e:
                # 특수문자([·] 등) 포함 컬럼명은 Dataiku 컬럼 지정 스트림 로딩이
                # 실패할 수 있음 → 전체 로딩 후 부분 선택으로 폴백
                logger.warning("컬럼 지정 로딩 실패(%s) — 전체 로딩 폴백", e)
        df = ds.get_dataframe(infer_with_pandas=True)
        if wanted:
            # 정규화 매칭 포함: 스키마 컬럼명과 로딩 컬럼명이 다른 경우(특수문자) 대응
            resolved = resolve_mapped_columns(dict(enumerate(wanted)), list(df.columns))
            keep = list(dict.fromkeys(resolved.values()))
            if keep:
                df = df[keep]
        return df
    path = os.path.join(_LOCAL_DATA_DIR, name + ".csv")
    df = pd.read_csv(path)
    if columns:
        cols = [c for c in columns if c in df.columns]
        df = df[cols]
    return df


def load_sample_dataframe(dataset_name, columns=None, limit=300):
    """검증·미리보기용 샘플 로딩 (head limit). 실패 시 빈 DataFrame."""
    name = validate_dataset_name(dataset_name)
    if name is None:
        return pd.DataFrame()
    wanted = [c for c in (columns or []) if c]
    try:
        if name in _INJECTED_DATASETS:
            df = _INJECTED_DATASETS[name].head(int(limit))
        elif _dataiku_mod is not None:
            ds = _dataiku_mod.Dataset(name)
            try:
                df = ds.get_dataframe(limit=int(limit), infer_with_pandas=True)
            except TypeError:  # 구버전 API: limit 미지원
                df = ds.get_dataframe(infer_with_pandas=True).head(int(limit))
        else:
            df = pd.read_csv(os.path.join(_LOCAL_DATA_DIR, name + ".csv"), nrows=int(limit))
    except Exception as e:
        logger.warning("sample load failed for %s: %s", name, e)
        return pd.DataFrame()
    if wanted:
        keep = [c for c in wanted if c in df.columns]
        if keep:
            df = df[keep]
    return df.copy()


def needed_raw_columns(mapping):
    """매핑에서 실제 로딩할 원본 컬럼 목록."""
    return sorted(set(c for c in (mapping or {}).values() if c))


def get_prepared(dataset_name, mapping, applicant_rules=None, analysis_unit="family",
                 embedding_file=None):
    """전처리 완료 표준 프레임 (캐시). 모든 분석 API 의 공통 진입점.

    embedding_file: 업로드된 임베딩 파일(.npy/.npz) entry id — 지정 시
    _embedding 컬럼을 출원번호/공개번호 매칭으로 채운다 (raw 컬럼 매핑 불필요).
    반환: (df, from_cache). 매핑이 비어 있으면 ValueError.
    """
    mapping = {k: v for k, v in (mapping or {}).items() if v and k in CONCEPTS}
    if not mapping:
        raise ValueError("컬럼 매핑이 비어 있습니다. 컬럼 매핑 화면에서 매핑을 설정하세요.")
    key = make_cache_key("prepared", dataset_name, mapping, applicant_rules or {},
                         analysis_unit, embedding_file or "")
    cached = DF_CACHE.get(key)
    if cached is not None:
        return cached, True
    raw = load_raw_dataframe(dataset_name, columns=needed_raw_columns(mapping))
    df = build_standard_frame(raw, mapping, applicant_rules)
    df = apply_analysis_unit(df, analysis_unit)
    df = df.reset_index(drop=True)
    if embedding_file:
        from src.embedding_files import apply_to_frame
        result = apply_to_frame(df, embedding_file)
        if not result.get("applied"):
            logger.warning("업로드 임베딩 적용 실패 (%s): %s",
                           embedding_file, result.get("reason"))
    DF_CACHE.set(key, df)
    return df, False
