# -*- coding: utf-8 -*-
"""pytest 공용 fixture. src 모듈 import 전에 로컬 저장소 경로를 격리한다."""
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="ipls_test_")
os.environ["IP_LANDSCAPE_STORE"] = os.path.join(_TMP, "store.json")
os.environ.setdefault("IP_LANDSCAPE_DATA_DIR", _TMP)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pytest  # noqa: E402

from generate_sample_data import generate_sample  # noqa: E402
from src.column_mapping import suggest_mapping  # noqa: E402
from src.preprocessing import build_standard_frame  # noqa: E402


@pytest.fixture(scope="session")
def raw_df():
    """① 필수 컬럼이 모두 있는 합성 데이터 (한글·영문·일문 혼재 = 케이스 ⑫)."""
    return generate_sample(n=600, seed=42)


@pytest.fixture(scope="session")
def mapping(raw_df):
    auto = suggest_mapping(list(raw_df.columns))
    return {k: v["column"] for k, v in auto.items()}


@pytest.fixture(scope="session")
def prepared(raw_df, mapping):
    """표준 프레임 (dedup 전 — 문헌 단위)."""
    return build_standard_frame(raw_df, mapping)


@pytest.fixture()
def settings():
    from src.config import merged_settings
    return merged_settings({})


def make_prepared(df):
    """임의 raw DataFrame → 표준 프레임 헬퍼."""
    auto = suggest_mapping(list(df.columns))
    m = {k: v["column"] for k, v in auto.items()}
    return build_standard_frame(df, m)
