# -*- coding: utf-8 -*-
"""분석 모듈: envelope 규약·graceful degradation·시나리오 케이스."""
import pandas as pd
import pytest

from generate_sample_data import (generate_sample, drop_optional_columns,
                                  with_singleton_class, with_zero_recent_year,
                                  without_citations, without_embeddings)
from tests.conftest import make_prepared
from src.preprocessing import dedupe_families
from src.analyses.overview import compute_overview
from src.analyses.tech_network import compute_tech_network
from src.analyses.emerging import compute_emerging
from src.analyses.lifecycle import compute_lifecycle, detect_reemerging
from src.analyses.whitespace import compute_opportunity
from src.analyses.problem_solution import compute_problem_solution, cell_detail
from src.analyses.transition import compute_transition
from src.analyses.trajectory import compute_trajectory
from src.analyses.company_dna import compute_company_dna
from src.analyses.lead_lag import compute_lead_lag
from src.analyses.claim_density import compute_claim_density
from src.analyses.citation_influence import compute_citation_influence
from src.analyses.inventor_mobility import compute_inventor_mobility
from src.analyses.classification_quality import compute_classification_quality
from src.analyses.common import select_patents, patent_records, export_dataframe

ENVELOPE_STATUSES = {"ok", "empty", "disabled"}


def _check_envelope(result):
    assert result["status"] in ENVELOPE_STATUSES
    assert "insight" in result
    assert isinstance(result["insight"]["sentences"], list)
    return result


@pytest.fixture(scope="module")
def family_df(prepared):
    return dedupe_families(prepared).reset_index(drop=True)


# ---------------- 1단계 ----------------
def test_overview_full(family_df, settings):
    r = _check_envelope(compute_overview(family_df, settings))
    assert r["status"] == "ok"
    assert r["kpi"]["total"] == len(family_df)
    assert r["growing"] or r["declining"]
    assert r["meta"]["disclaimer"]


def test_tech_network(family_df, settings):
    r = _check_envelope(compute_tech_network(family_df, settings))
    assert r["status"] == "ok"
    assert r["network"]["nodes"] and r["network"]["edges"]
    assert r["n_nodes"] <= 80 and r["n_edges"] <= 250
    e0 = r["network"]["edges"][0]["data"]
    for key in ("jaccard", "lift", "weight", "drill"):
        assert key in e0
    # scope=company
    company = family_df["applicant_display"].value_counts().index[0]
    r2 = compute_tech_network(family_df, settings, scope="company", company=company)
    assert r2["status"] in ("ok", "empty")


def test_emerging(family_df, settings):
    r = _check_envelope(compute_emerging(family_df, settings))
    assert r["status"] == "ok"
    assert r["figure"]["data"]
    top = r["combos"][0]
    assert 0 <= (top["score"] or 0) <= 1
    assert "growth_method" in top


def test_lifecycle(family_df, settings):
    r = _check_envelope(compute_lifecycle(family_df, settings))
    assert r["status"] == "ok"
    assert r["phases"]
    assert all(p["phase"] in ("Emerging", "Growing", "Competitive", "Mature",
                              "Declining", "Re-emerging") for p in r["phases"])


def test_reemerging_rule():
    s = pd.Series([10, 8, 6, 5, 7, 9, 12], index=range(2016, 2023))
    assert detect_reemerging(s, new_entrants_recent=2, combo_growth=0.5)
    assert not detect_reemerging(s, new_entrants_recent=0, combo_growth=0.5)
    assert not detect_reemerging(pd.Series([1, 2, 3]), 2, 0.5)  # 표본 부족


def test_opportunity(family_df, settings):
    r = _check_envelope(compute_opportunity(family_df, settings))
    assert r["status"] == "ok"
    area = r["areas"][0]
    assert set(area["components"].keys()) == set(r["opportunity_keys"])
    assert 0 <= area["barrier"] <= 1
    assert "opportunity_score" in area
    # 자사(네패스) 특허 여부 반영
    assert any(a["own_capability"] is not None for a in r["areas"])


def test_problem_solution(family_df, settings):
    r = _check_envelope(compute_problem_solution(family_df, settings))
    assert r["status"] == "ok"
    assert r["problems"] and r["solutions"]
    p, s = r["problems"][0], r["solutions"][0]
    detail = cell_detail(family_df, settings, p, s)
    assert detail["status"] in ("ok", "empty")
    if detail["status"] == "ok":
        assert "trend" in detail and "opportunity_score" in detail


def test_problem_solution_disabled_without_columns(settings):
    # ② 선택 컬럼 없는 데이터 → 해당 분석만 disabled, 안내 포함
    df = make_prepared(drop_optional_columns(generate_sample(n=80, seed=11)))
    r = compute_problem_solution(df, settings)
    assert r["status"] == "disabled"
    assert "해결과제" in r["missing_columns"] or "해결수단" in r["missing_columns"]


def test_optional_columns_missing_overview_still_ok(settings):
    df = make_prepared(drop_optional_columns(generate_sample(n=120, seed=12)))
    r = _check_envelope(compute_overview(df, settings))
    assert r["status"] == "ok"


def test_singleton_class_excluded(settings):
    # ④ 특허 1건뿐인 기술분류 → 최소 표본 미달로 제외되어도 전체는 정상
    df = make_prepared(with_singleton_class(generate_sample(n=100, seed=13)))
    r = compute_lifecycle(df, settings)
    assert r["status"] == "ok"
    assert all(p["tech"] != "양자 패키징" for p in r["phases"])


def test_zero_recent_year(settings):
    # ⑤ 최근 연도 0건 시계열에서도 성장률 폴백으로 정상 계산
    df = make_prepared(with_zero_recent_year(generate_sample(n=150, seed=14)))
    r = compute_overview(df, settings)
    assert r["status"] == "ok"


def test_empty_dataframe(prepared, settings):
    empty = prepared.iloc[0:0]
    for fn in (compute_overview, compute_emerging, compute_lifecycle,
               compute_opportunity):
        r = fn(empty, settings)
        assert r["status"] == "empty"


# ---------------- 2단계 ----------------
def test_transition_modes(family_df, settings):
    for mode in ("cooccurrence", "applicant", "family", "continuation"):
        r = _check_envelope(compute_transition(family_df, settings, mode=mode))
        assert r["status"] in ("ok", "empty")
        if r["status"] == "ok":
            assert r["figure"]["data"][0]["type"] == "sankey"
            assert len(r["figure"]["data"][0]["link"]["source"]) <= 120


def test_trajectory(family_df, settings):
    r = _check_envelope(compute_trajectory(family_df, settings))
    assert r["status"] == "ok"
    assert r["companies"]
    assert r["method"]
    r2 = compute_trajectory(family_df, settings, method="umap")
    assert r2["status"] == "ok"  # umap 미설치 시 PCA 폴백


def test_company_dna(family_df, settings):
    r = _check_envelope(compute_company_dna(family_df, settings))
    assert r["status"] == "ok"
    comp = r["companies"][0]
    assert len(comp["std"]) == 12 and len(comp["raw"]) == 12
    assert comp["type"]
    assert r["similarity"] is not None and r["overlap"] is not None


def test_lead_lag(family_df, settings):
    r = _check_envelope(compute_lead_lag(family_df, settings))
    assert r["status"] in ("ok", "empty")
    if r["status"] == "ok":
        assert "인과관계" in r["meta"]["note"]


# ---------------- 3단계 ----------------
def test_claim_density(family_df, settings):
    r = _check_envelope(compute_claim_density(family_df, settings))
    assert r["status"] == "ok"
    assert r["figure"]["data"][0]["type"] == "contour"
    assert "FTO" in r["meta"]["purpose"]


def test_claim_density_without_embeddings(settings):
    # ⑩ 임베딩 없음 → TF-IDF 폴백으로 동작
    df = make_prepared(without_embeddings(generate_sample(n=120, seed=15)))
    r = compute_claim_density(df, settings)
    assert r["status"] == "ok"
    assert r["methods"]["embedding"] == "tfidf_fallback"


def test_citation_influence(family_df, settings):
    r = _check_envelope(compute_citation_influence(family_df, settings))
    assert r["status"] == "ok"
    assert r["top_patents"]
    assert set(r["top_patents"][0]["parts"].keys()) == {
        "direct_citations", "indirect_citations", "cross_class", "cross_company",
        "family_expansion", "legal_strength"}


def test_citation_disabled_without_citations(settings):
    # ⑨ 인용 데이터 없음 → 기능 비활성화 + 필요 컬럼 안내
    df = make_prepared(without_citations(generate_sample(n=80, seed=16)))
    r = compute_citation_influence(df, settings)
    assert r["status"] == "disabled"
    assert "피인용 수" in r["missing_columns"]


def test_inventor_mobility(family_df, settings):
    r = _check_envelope(compute_inventor_mobility(family_df, settings,
                                                  include_uncertain=True))
    assert r["status"] in ("ok", "empty")
    if r["status"] == "ok":
        assert r["network"]["nodes"]


def test_classification_quality(family_df, settings):
    r = _check_envelope(compute_classification_quality(family_df, settings))
    assert r["status"] == "ok"
    assert r["has_embedding"] is True
    assert r["confusion"]
    assert isinstance(r["suggestions"], list)


def test_classification_quality_no_embedding(settings):
    df = make_prepared(without_embeddings(generate_sample(n=100, seed=17)))
    r = compute_classification_quality(df, settings)
    assert r["status"] == "ok"
    assert r["has_embedding"] is False  # 중복 비율 기반 degrade


# ---------------- drill-down ----------------
def test_select_patents_and_records(family_df):
    tech = [t for lst in family_df["_tech_list"] for t in lst][0]
    sub = select_patents(family_df, {"type": "tech", "tech": tech})
    assert len(sub) > 0
    assert sub["_tech_list"].map(lambda lst: tech in lst).all()
    page = patent_records(sub, page=1, page_size=10)
    assert page["total"] == len(sub) and len(page["records"]) <= 10
    rec = page["records"][0]
    assert "공개번호" in rec and "기술분류" in rec
    combo_sub = select_patents(family_df, {"type": "combo", "a": tech, "b": tech})
    assert len(combo_sub) == len(sub)
    out = export_dataframe(sub)
    assert len(out) == len(sub)
