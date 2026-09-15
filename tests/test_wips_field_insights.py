# -*- coding: utf-8 -*-
"""윈텔립스 확장 필드 인사이트 7종 회귀 테스트.

① 자기 vs 타인 피인용 분리 (citation-diffusion self_other)
② 세트 내 인용 네트워크 (citation-diffusion inset_network)
③ 원천국→출원국 흐름 (basic-stats country_flow)
④ 심사청구율 (wips-deep exam_request)
⑤ 분할출원 여부·비율 (wips-deep divisional fig_ratio)
⑥ EPC 검증국·연차료 (deep-plus epc)
⑦ AI 요약 시맨틱 텍스트 소스 (semantic _corpus_texts)

원칙: 화면 수치와 drill-down 목록이 정확히 일치해야 한다 (값 지어내기 금지).
"""
import numpy as np
import pandas as pd
import pytest

from conftest import make_prepared
from generate_sample_data import generate_sample
from src.analyses.common import select_patents
from src.analyses.basic_stats import compute_basic_stats
from src.analyses.citation_influence import compute_citation_influence
from src.analyses.wips_deep import compute_wips_deep, _count_like
from src.analyses.deep_plus import compute_deep_plus
from src.analyses.semantic_insights import _corpus_texts


@pytest.fixture(scope="module")
def prepared(settings_mod):
    return make_prepared(generate_sample(n=600, seed=42))


@pytest.fixture(scope="module")
def settings_mod():
    from src.config import merged_settings
    return merged_settings({})


# ---------------- ① 자기 vs 타인 피인용 ----------------
def test_self_other_citation_split(prepared, settings_mod):
    r = compute_citation_influence(prepared, settings_mod)
    assert r["status"] == "ok"
    so = r["self_other"]
    assert so is not None, r.get("extras_skipped")
    assert so["overall"]["n_self"] + so["overall"]["n_other"] > 0
    assert 0.0 <= so["overall"]["self_rate"] <= 1.0
    # 합성 데이터 계약: 자기+타인 피인용 목록 길이 합 == 피인용 수
    self_c = _count_like(prepared["cites_forward_self"]).fillna(0)
    other_c = _count_like(prepared["cites_forward_other"]).fillna(0)
    assert float((self_c + other_c - prepared["cites_forward"]).abs().sum()) == 0.0
    # 차트 데이터: 기업 행에 자기/타인 건수와 self_rate 일관성
    for row in so["rows"]:
        assert row["n_self"] + row["n_other"] > 0
        assert row["self_rate"] == round(
            row["n_self"] / float(row["n_self"] + row["n_other"]), 4)
    # 타인 피인용 상위 특허 drill 은 해당 문헌 1건과 일치
    if so["top_patents"]:
        top = so["top_patents"][0]
        sub = select_patents(prepared, top["drill"])
        assert len(sub) == 1
        assert int(other_c.loc[sub.index[0]]) == top["n_other"]


# ---------------- ② 세트 내 인용 네트워크 ----------------
def test_inset_citation_network(prepared, settings_mod):
    r = compute_citation_influence(prepared, settings_mod)
    net = r["inset_network"]
    assert net is not None, r.get("extras_skipped")
    assert net["n_pairs"] > 0 and net["n_refs"] >= net["n_pairs"]
    assert 0.0 < net["matched_ratio"] <= 1.0
    assert net["network"] and net["network"]["nodes"]
    # 엣지 drill(ids)은 실제로 그 인용쌍의 citing 문헌들과 일치
    if net["top_pairs"]:
        p0 = net["top_pairs"][0]
        sub = select_patents(prepared, p0["drill"])
        assert len(sub) == len(set(p0["drill"]["ids"]))
        # citing 문헌들의 인용 목록에 cited 기업 문헌번호가 실제 포함되는지 표본 검증
        from src.preprocessing import parse_multiclass_cell
        pubs_norm = {}
        import re as _re
        def _n(v):
            return _re.sub(r"[^A-Z0-9]", "", str(v).upper())
        for _i, _r in prepared.iterrows():
            if str(_r.get("applicant_display", "")) == p0["cited"]:
                pubs_norm[_n(_r.get("pub_number", ""))] = True
        hit = False
        for _i, _r in sub.iterrows():
            for num in parse_multiclass_cell(_r.get("cites_backward_nums")):
                if _n(num) in pubs_norm:
                    hit = True
                    break
        assert hit, "citing 문헌의 인용 목록에 cited 기업 문헌이 없음"
    # 세트 내 최다 피인용 특허 drill = 그 특허를 인용한 문헌 목록
    if net["top_cited"]:
        c0 = net["top_cited"][0]
        sub = select_patents(prepared, c0["drill"])
        assert len(sub) == c0["n_inset"]


# ---------------- ③ 원천국→출원국 흐름 ----------------
def test_country_flow(prepared, settings_mod):
    r = compute_basic_stats(prepared, settings_mod)
    assert r["status"] == "ok"
    fig = r["country_flow"]
    assert fig is not None
    data = fig["data"][0]
    z = data["z"]
    custom = data["customdata"]
    # 값>0 인 셀의 drill 이 정확히 그 건수를 반환
    checked = 0
    for ri, row in enumerate(z):
        for ci, v in enumerate(row):
            if v and checked < 3:
                drill = custom[ri][ci]["drill"]
                sub = select_patents(prepared, drill)
                assert len(sub) == v, (drill, len(sub), v)
                checked += 1
    assert checked > 0
    assert "country_flow" in (r.get("chart_insights") or {})


def test_country_flow_absent_without_column(settings_mod):
    df = generate_sample(n=80, seed=7).drop(columns=["최우선출원국가"])
    r = compute_basic_stats(make_prepared(df), settings_mod)
    assert r["status"] == "ok"
    assert r["country_flow"] is None  # 컬럼 없으면 조용히 생략 (값 지어내기 금지)


# ---------------- ④ 심사청구율 ----------------
def test_exam_request_section(prepared, settings_mod):
    r = compute_wips_deep(prepared, settings_mod, only_sections=["exam_request"])
    assert r["status"] == "ok"
    sec = r["sections"]["exam_request"]
    assert 0.0 <= sec["overall_rate"] <= 1.0
    assert sec["n_valued"] > 0
    # KR/JP/EP 만 값 보유 (합성 데이터 계약) → 판정 가능 건수 < 전체
    assert sec["n_valued"] < len(prepared)
    # 기업 막대 drill = 그 회사의 심사청구 특허 수 (분자와 일치)
    comp = [c for c in sec["companies"] if c["n_req"] > 0][0]
    sub = select_patents(prepared, {"applicant": comp["company"],
                                    "applicant_scope": "any",
                                    "exam_requested": True})
    assert len(sub) >= comp["n_req"] > 0
    # coapplicant all 모드에서 분자는 전개 집계라 문헌 수 이상일 수 없음을 확인
    assert comp["n_req"] <= comp["n"]


# ---------------- ⑤ 분할출원 여부·비율 ----------------
def test_divisional_flag_and_ratio(prepared, settings_mod):
    r = compute_wips_deep(prepared, settings_mod, only_sections=["divisional"])
    assert r["status"] == "ok"
    sec = r["sections"]["divisional"]
    assert sec.get("fig_ratio") is not None
    # 비율 차트 drill: 분할출원 True 조건이 플래그∪원출원번호 기준과 일치
    labels = sec["fig_ratio"]["data"][0]["y"]
    customs = sec["fig_ratio"]["data"][0]["customdata"]
    d0 = customs[0]["drill"]
    sub = select_patents(prepared, d0)
    assert len(sub) > 0
    from src.preprocessing import parse_bool
    for _i, row in sub.iterrows():
        flag = parse_bool(row.get("divisional_flag"))
        parent = str(row.get("parent_app_number", "")).strip()
        assert flag is True or parent not in ("", "nan", "None")


def test_divisional_flag_only_dataset(settings_mod):
    # 원출원번호 없이 분할출원 여부 플래그만 있어도 섹션이 동작
    df = generate_sample(n=200, seed=11).drop(columns=["원출원번호"])
    prep = make_prepared(df)
    r = compute_wips_deep(prep, settings_mod, only_sections=["divisional"])
    assert r["status"] == "ok"
    assert "divisional" in r["sections"], r.get("message")


# ---------------- ⑥ EPC 검증국·연차료 ----------------
def test_epc_maintenance_section(prepared, settings_mod):
    r = compute_deep_plus(prepared, settings_mod, only_sections=["epc"])
    assert r["status"] == "ok"
    sec = r["sections"]["epc"]
    assert sec.get("n_epc", 0) > 0
    assert sec["avg_valid_all"] >= 1.0  # EPC유효국은 1개국 이상으로 생성
    for row in sec.get("epc_rows", []):
        assert row["n_valid"] >= 1
        sub = select_patents(prepared, row["drill"])
        assert len(sub) == 1
    assert sec.get("n_annuity", 0) > 0
    assert "note" in sec


# ---------------- 표준화 규칙: 표시명 키·권리자 적용 ----------------
def test_rule_on_display_name_merges_variants():
    """규칙 키가 '화면에 보이는 표준명'이어도 적용된다 (연쇄 규칙 포함).

    회귀: '삼성전자→SEC' 규칙을 만들었는데 다른 규칙/경로로 '삼성전자'로
    귀결되는 행이 병합되지 않고 남던 문제."""
    import pandas as pd
    from src.preprocessing import build_standard_frame
    from src.column_mapping import suggest_mapping
    df = pd.DataFrame({
        "공개번호": ["KR1", "KR2", "KR3"],
        "출원인": ["에스이씨", "삼성전자 주식회사", "SK하이닉스"],
        "현재권리자": ["에스이씨", "삼성전자(주)", "SK HYNIX INC."],
        "출원일": ["2020-01-01", "2021-02-02", "2022-03-03"],
        "발명의 명칭": ["a", "b", "c"],
    })
    m = {k: v["column"] for k, v in suggest_mapping(list(df.columns)).items()}
    rules = {"mapping": {"에스이씨": "삼성전자",      # 변형 → 표준명
                         "삼성전자": "SEC",            # 표준명 → 새 표준명 (연쇄)
                         "SK HYNIX INC.": "SK하이닉스"}}  # 권리자 전용 표기
    out = build_standard_frame(df, m, applicant_rules=rules)
    # 출원인: 연쇄 규칙까지 적용되어 전부 SEC 로 병합
    assert list(out["applicant_display"][:2]) == ["SEC", "SEC"]
    # 권리자도 동일 규칙 체인 적용 → 가짜 양도(표기 변형) 소멸
    assert list(out["owner_display"]) == ["SEC", "SEC", "SK하이닉스"]
    assert (out["applicant_display"] == out["owner_display"]).all()


# ---------------- 상세보기 링크(비로그인) ----------------
def test_patent_records_detail_link(prepared):
    """근거특허 목록: 상세보기 링크(비로그인)가 _detail_link 메타로 포함되고
    http(s) 외 스킴(javascript: 등)은 차단된다."""
    from src.analyses.common import patent_records
    out = patent_records(prepared.head(5))
    for rec in out["records"]:
        assert rec["_detail_link"].startswith("https://")
        assert "상세보기" not in rec  # 표의 열로는 노출하지 않음 (메타 필드)
    # 위험 스킴·비 URL 값은 링크 미포함
    df2 = prepared.head(3).copy()
    df2["detail_link"] = ["javascript:alert(1)", "메모텍스트", ""]
    out2 = patent_records(df2)
    assert all("_detail_link" not in rec for rec in out2["records"])


def test_export_includes_detail_link(prepared):
    from src.analyses.common import export_dataframe
    out = export_dataframe(prepared.head(10))
    assert "상세보기 링크" in out.columns
    assert str(out["상세보기 링크"].iloc[0]).startswith("https://")


# ---------------- 권리범위 엔트로피: 분석 대상 출원인 선택 ----------------
def test_scope_entropy_companies_selection(prepared, settings_mod):
    """회사를 선택하면 그 출원인들만 레이더·표에 표시된다 (사용자 요청)."""
    from src.analyses.scope_entropy import compute_scope_entropy
    full = compute_scope_entropy(prepared, settings_mod)
    assert full["status"] == "ok"
    all_names = [r["company"] for r in full["companies"]]
    assert len(all_names) >= 3
    pick = all_names[:2]
    sel = compute_scope_entropy(prepared, settings_mod, companies=pick)
    assert sel["status"] == "ok"
    sel_names = [r["company"] for r in sel["companies"]]
    assert set(sel_names) == set(pick), sel_names


# ---------------- ⑦ AI 요약 시맨틱 텍스트 소스 ----------------
def test_corpus_texts_prefers_ai_summary(prepared):
    texts, source = _corpus_texts(prepared)
    assert source == "AI 요약+특징 요약"
    assert texts.str.len().ge(30).mean() > 0.9


def test_corpus_texts_fallback_without_ai_summary(prepared):
    df = prepared.drop(columns=["ai_summary", "feature_summary"])
    texts, source = _corpus_texts(df)
    assert source == "명칭+요약"  # 기존 폴백 유지
