# -*- coding: utf-8 -*-
"""검증·신뢰성 리포트(quality_report) 테스트 — 과장·조작 없는 표기 검증."""
import pandas as pd
import pytest

from src.config import merged_settings
from src.quality_report import (compute_quality_report, get_build_info,
                                run_self_check, VERIFICATION_REGISTRY)
from tests.conftest import make_prepared
from generate_sample_data import generate_sample


@pytest.fixture()
def settings():
    return merged_settings({})


def test_quality_report_ok(settings):
    df = make_prepared(generate_sample(n=300, seed=7))
    r = compute_quality_report(df, settings)
    assert r["status"] == "ok"
    assert r["checks"] and r["principles"] and r["registry"]
    statuses = {c["status"] for c in r["checks"]}
    assert statuses <= {"통과", "주의", "확인 불가"}
    s = r["summary"]
    assert s["pass"] + s["warn"] + s["na"] == len(r["checks"])
    # 인사이트 문장은 셀프 체크 실측 수치와 일치
    assert ("통과 %d" % s["pass"]) in r["insight"]["sentences"][0]


def test_build_info_counts_are_real():
    """빌드 정보의 테스트 수는 실측 집계 — 지어낸 수치 금지."""
    info = get_build_info()
    # 개발 모드: 저장소 tests/ 실측. 이 파일 자체도 집계에 포함되므로 > 0.
    assert info["test_functions"] and info["test_functions"] > 100
    assert info["test_files"] and info["test_files"] >= 10


def test_registry_references_exist():
    """검증 레지스트리가 가리키는 테스트 함수는 실제로 존재해야 한다."""
    import io
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for entry in VERIFICATION_REGISTRY:
        ref = entry["test"]
        if "::" not in ref:
            continue  # 파일 단위·파이프라인 항목은 아래에서 파일 존재만 확인
        fname, func = ref.split("::")
        path = os.path.join(root, "tests", fname)
        assert os.path.exists(path), ref
        with io.open(path, encoding="utf-8") as fh:
            assert ("def %s(" % func) in fh.read(), ref
    # 파일 단위 참조 확인
    for entry in VERIFICATION_REGISTRY:
        ref = entry["test"]
        if "::" in ref or ".py" not in ref:
            continue
        fname = ref.split(" ")[0]
        assert os.path.exists(os.path.join(root, "tests", fname)), ref


def test_self_check_flags_bad_data(settings):
    """이상 데이터 주입 시 '주의'로 잡아내는지 — 통과로 위장하지 않음."""
    raw = generate_sample(n=120, seed=3)
    df = make_prepared(raw)
    # 미래 연도 + 날짜 논리 위반 주입
    df = df.copy()
    df.loc[df.index[:5], "_base_year"] = 2100
    if "reg_date" in df.columns and "app_date" in df.columns:
        i = df.index[df["reg_date"].notna() & df["app_date"].notna()][:3]
        df.loc[i, "reg_date"] = pd.Timestamp("1990-01-01")
    checks = {c["name"]: c for c in run_self_check(df)}
    assert checks["미래 연도 이상치"]["status"] == "주의"
    assert "5건" in checks["미래 연도 이상치"]["detail"]
    if "reg_date" in df.columns and "app_date" in df.columns:
        assert checks["날짜 논리 (등록일 ≥ 출원일)"]["status"] == "주의"


def test_self_check_honest_when_unmapped(settings):
    """컬럼이 없으면 '확인 불가' — 통과로 표시하면 안 된다."""
    df = make_prepared(generate_sample(n=80, seed=5))
    df = df.drop(columns=[c for c in ("cites_forward",) if c in df.columns])
    checks = {c["name"]: c for c in run_self_check(df)}
    assert checks["피인용 수치 해석률"]["status"] == "확인 불가"
