# -*- coding: utf-8 -*-
"""공동출원 카운팅(coapplicant_mode) 회귀 테스트.

원칙: 출원건수·기술분석 등 '출원인별' 집계에서 공동출원 1건은
설정 'all'(기본, WIPS 방식)일 때 각 공동출원인에게 1건씩 계상된다.
'first' 모드에서는 대표(첫) 출원인에게만 계상된다.
"""
import numpy as np
import pandas as pd

from src.analyses.common import applicant_series, applicant_counts, \
    applicant_set, explode_applicants


def _joint_df():
    """A사 단독 2건 + A·B 공동 1건 + B사 단독 1건."""
    return pd.DataFrame({
        "applicant_display": ["A사", "A사", "A사", "B사"],
        "_co_applicants_display": [["A사"], ["A사"], ["A사", "B사"], ["B사"]],
        "title": ["t1", "t2", "t3", "t4"],
    })


def test_applicant_counts_all_mode_counts_each_coapplicant():
    df = _joint_df()
    counts = applicant_counts(df, {"coapplicant_mode": "all"})
    # 공동출원 1건이 A·B 각각에 1건씩: A=3, B=2 (합계 5 > 문헌 4 허용)
    assert int(counts["A사"]) == 3
    assert int(counts["B사"]) == 2


def test_applicant_counts_first_mode_counts_representative_only():
    df = _joint_df()
    counts = applicant_counts(df, {"coapplicant_mode": "first"})
    assert int(counts["A사"]) == 3
    assert int(counts["B사"]) == 1


def test_default_mode_is_all():
    df = _joint_df()
    counts = applicant_counts(df, {})
    assert int(counts["B사"]) == 2


def test_explode_applicants_duplicates_joint_rows():
    df = _joint_df()
    out = explode_applicants(df, {"coapplicant_mode": "all"})
    # 4개 문헌, 공동 1건 → 5행. 문헌 속성(title)은 그대로 복제된다.
    assert len(out) == 5
    assert list(out[out["applicant_display"] == "B사"]["title"]) == ["t3", "t4"]
    # 원본은 변경되지 않는다
    assert len(df) == 4
    assert df["applicant_display"].tolist()[2] == "A사"


def test_applicant_set_includes_coapplicants():
    df = _joint_df().iloc[[2]]  # 공동출원 1건만
    assert applicant_set(df, {"coapplicant_mode": "all"}) == {"A사", "B사"}
    assert applicant_set(df, {"coapplicant_mode": "first"}) == {"A사"}


def test_overview_applicant_kpi_uses_membership(prepared, settings):
    """전체 KPI 출원인 수는 공동출원인 포함 고유 출원인 수와 일치."""
    from src.analyses.overview import compute_overview
    res = compute_overview(prepared, settings)
    kpi = res["kpi"]
    expected = int(applicant_counts(prepared, settings).index.nunique())
    assert kpi["applicants"] == expected


def test_barrier_cr3_is_doc_coverage_ratio(prepared, settings):
    """CR3 는 상위 3사가 (공동)출원인인 문헌 비율 — 각각 집계에서도 0~1."""
    from src.analyses.overview import compute_overview
    res = compute_overview(prepared, settings)
    rows = res.get("barriers") or []
    assert rows, "장벽 행이 계산되어야 합니다"
    for r in rows:
        assert 0.0 <= float(r["cr3"]) <= 1.0


def test_dna_ratio_to_max_scaling():
    """A:B = 6:4 → 1.0 : 0.667 (min-max 로 0 이 되지 않음). 음수만 0."""
    from src.analyses.company_dna import _ratio_to_max
    out = _ratio_to_max([6.0, 4.0])
    assert abs(out[0] - 1.0) < 1e-9
    assert abs(out[1] - 4.0 / 6.0) < 1e-9
    out2 = _ratio_to_max([5.0, -2.0, None])
    assert abs(out2[0] - 1.0) < 1e-9
    assert out2[1] == 0.0 and out2[2] == 0.0
    assert list(_ratio_to_max([0.0, 0.0])) == [0.0, 0.0]


def test_coapplicant_network_uses_user_standardization(settings):
    """협력 네트워크 노드가 사용자 출원인 표준화 규칙(mapping·groups)을 따른다.

    회귀: 원본 공동출원인 리스트에 자동 표준화만 적용해 사용자가 지정한
    표준명이 네트워크에 반영되지 않던 버그.
    """
    from src.analyses.advanced_stats import _coapplicant_section
    from src.preprocessing import standardize_applicants

    df = pd.DataFrame({
        "applicant": ["가나전자 주식회사; ABC Semiconductor Inc.",
                      "가나전자(주); ABC Semiconductor Inc.",
                      "다라소재; 가나전자 주식회사"],
        "app_number": ["A1", "A2", "A3"],
    })
    rules = {"mapping": {"가나전자": "가나전자그룹",
                         "ABC SEMICONDUCTOR": "ABC반도체"},
             "groups": {}}
    df = standardize_applicants(df, rules)
    result, reason = _coapplicant_section(df, settings)
    assert reason is None, reason
    node_names = {n["data"]["label"] for n in result["network"]["nodes"]}
    # 사용자 표준명이 노드로, 원본 표기 변형·자동 표준화명은 남지 않아야 함
    assert "가나전자그룹" in node_names
    assert "ABC반도체" in node_names
    assert not any("주식회사" in n or "(주)" in n for n in node_names)
    assert "가나전자" not in node_names and "ABC SEMICONDUCTOR" not in node_names
    # 표기 변형 2건이 같은 쌍으로 합산: (가나전자그룹, ABC반도체) = 2건
    pair = result["top_pair"]
    assert {pair["a"], pair["b"]} == {"ABC반도체", "가나전자그룹"}
    assert pair["n"] == 2


def test_coapplicant_network_merged_names_not_paired(settings):
    """표준화로 같은 회사가 된 공동출원('A' + 'A(주)')은 관계로 잡히지 않는다."""
    from src.analyses.advanced_stats import _coapplicant_section
    from src.preprocessing import standardize_applicants
    df = pd.DataFrame({
        "applicant": ["가나전자 주식회사; 가나전자(주)"],
        "app_number": ["B1"],
    })
    df = standardize_applicants(df, None)
    result, reason = _coapplicant_section(df, {})
    assert result is None and "공동출원" in reason
