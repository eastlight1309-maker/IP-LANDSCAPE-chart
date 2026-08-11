# -*- coding: utf-8 -*-
"""전처리: 다중분류 파싱·법적상태·출원인 표준화·패밀리 dedup·필터."""
import json

import pandas as pd

from generate_sample_data import (generate_sample, with_duplicate_families,
                                  with_applicant_variants, with_missing_legal_status)
from tests.conftest import make_prepared
from src.preprocessing import (parse_multiclass_cell, normalize_legal_status,
                               auto_standardize_name, parse_bool, parse_embedding,
                               dedupe_families, apply_filters, explode_tech,
                               filter_options)


# --- 케이스 ③: 다중 기술분류 (쉼표/세미콜론/파이프/JSON) ---
def test_multiclass_separators():
    assert parse_multiclass_cell("A, B, C") == ["A", "B", "C"]
    assert parse_multiclass_cell("A; B;C") == ["A", "B", "C"]
    assert parse_multiclass_cell("A|B | C") == ["A", "B", "C"]
    assert parse_multiclass_cell('["A","B"]') == ["A", "B"]
    assert parse_multiclass_cell(["A", "B"]) == ["A", "B"]
    assert parse_multiclass_cell("단일분류") == ["단일분류"]
    assert parse_multiclass_cell(None) == []
    assert parse_multiclass_cell("A; A; B") == ["A", "B"]  # 중복 제거


def test_multiclass_end_to_end_json_and_pipe():
    for fmt, sep in (("json", None), ("sep", "|"), ("sep", ",")):
        df = generate_sample(n=60, seed=3, multiclass_format=fmt, sep=sep or "; ")
        prep = make_prepared(df)
        assert prep["_tech_list"].map(len).max() >= 2


def test_explode_modes(prepared):
    dup = explode_tech(prepared, mode="duplicate")
    frac = explode_tech(prepared, mode="fractional")
    prim = explode_tech(prepared, mode="primary")
    assert len(dup) >= len(prim)
    assert abs(frac["weight"].sum() - prim["weight"].sum()) < len(prepared)  # 1/N 합 = 문헌 수
    assert (prim.groupby(prim.index).size() == 1).all()
    lvl = explode_tech(prepared, mode="level_separate", level="l1")
    assert set(lvl["tech"]) <= {"패키징", "본딩", "테스트", "소재"}


# --- 법적상태 정규화 (케이스 ⑧ 포함) ---
def test_legal_status_normalization():
    assert normalize_legal_status("등록") == "Granted-Active"
    assert normalize_legal_status("존속기간만료") == "Granted-Expired"
    assert normalize_legal_status("거절결정") == "Rejected"
    assert normalize_legal_status("취하") == "Withdrawn"
    assert normalize_legal_status("공개") == "Pending"
    assert normalize_legal_status("Lapsed (non-payment)") == "Lapsed"
    assert normalize_legal_status(None) == "Unknown"
    assert normalize_legal_status("이상한값") == "Unknown"


def test_missing_legal_status_graceful():
    df = with_missing_legal_status(generate_sample(n=100, seed=5))
    prep = make_prepared(df)
    assert "Unknown" in set(prep["legal_status_norm"])
    assert prep["legal_status_raw"].isna().any()  # 원본값 보존


# --- 출원인 표준화 (케이스 ⑦) ---
def test_auto_standardize_name():
    assert auto_standardize_name("삼성전자 주식회사") == "삼성전자"
    assert auto_standardize_name("(주)삼성전자") == "삼성전자"
    assert auto_standardize_name("SAMSUNG ELECTRONICS CO., LTD.") == "SAMSUNG ELECTRONICS"
    assert auto_standardize_name("Samsung Electronics Co Ltd") == "SAMSUNG ELECTRONICS"
    assert auto_standardize_name("  Intel Corporation ") == "INTEL"


def test_applicant_variants_merge():
    df = with_applicant_variants(generate_sample(n=200, seed=7))
    prep = make_prepared(df)
    names = set(prep.loc[prep["applicant_raw"].str.contains("amsung|삼성", regex=True),
                         "applicant_display"])
    # 자동 표준화만으로 국문/영문은 서로 다른 표준명 → 사용자 매핑 규칙으로 통합
    from src.preprocessing import standardize_applicants
    rules = {"mapping": {"SAMSUNG ELECTRONICS": "삼성전자"}}
    prep2 = standardize_applicants(prep.copy(), rules)
    names2 = set(prep2.loc[prep2["applicant_raw"].str.contains("amsung|삼성", regex=True),
                           "applicant_display"])
    assert "삼성전자" in names2
    assert len(names2) <= len(names)


# --- 불리언·임베딩 파싱 ---
def test_parse_bool_and_embedding():
    assert parse_bool("Y") is True and parse_bool("n") is False
    assert parse_bool(1) is True and parse_bool("아니오") is False
    assert parse_bool("모름") is None
    emb = parse_embedding(json.dumps([0.1, 0.2, 0.3]))
    assert emb is not None and len(emb) == 3
    assert parse_embedding("0.1 0.2 0.3") is not None
    assert parse_embedding("not-a-vector") is None


# --- 패밀리 dedup (케이스 ⑥) ---
def test_family_dedup():
    df = with_duplicate_families(generate_sample(n=100, seed=9))
    prep = make_prepared(df)
    deduped = dedupe_families(prep)
    fams = prep["family_id"].astype(str)
    assert deduped["family_id"].astype(str).nunique() == fams.nunique()
    assert len(deduped) == fams.nunique()
    # 대표문헌 우선순위: 유효 등록특허가 있으면 대표로 선정
    for fid, grp in prep.groupby(prep["family_id"].astype(str)):
        rep = deduped[deduped["family_id"].astype(str) == fid].iloc[0]
        has_active_granted = ((grp["_active_flag"].map(lambda v: v is True))
                              & (grp["_is_granted_bool"].map(lambda v: v is True))).any()
        if has_active_granted:
            assert rep["_active_flag"] is True and rep["_is_granted_bool"] is True
            break


# --- 공통 필터 ---
def test_apply_filters(prepared):
    f1 = apply_filters(prepared, {"year_from": 2018, "year_to": 2020})
    assert f1["_base_year"].between(2018, 2020).all()
    apps = filter_options(prepared)["applicants"][:2]
    f2 = apply_filters(prepared, {"applicants": apps})
    # 공동출원 포함: 선택 출원인이 공동출원인 중 하나로라도 포함되면 매칭
    wanted = set(apps)
    assert f2.apply(lambda r: (str(r["applicant_display"]) in wanted)
                    or bool(wanted & set(r["_co_applicants_display"] or [])),
                    axis=1).all()
    # 대표 출원인 기준 건은 모두 포함 (기존 결과의 상위집합)
    assert prepared["applicant_display"].astype(str).isin(wanted).sum() <= len(f2)
    f3 = apply_filters(prepared, {"countries": ["KR"]})
    assert (f3["country"].str.upper() == "KR").all()
    f4 = apply_filters(prepared, {"legal_statuses": ["Granted-Active"]})
    assert (f4["legal_status_norm"] == "Granted-Active").all()
    f5 = apply_filters(prepared, {"active_only": True})
    assert f5["_active_flag"].map(lambda v: v is True).all()
    f6 = apply_filters(prepared, {"tech_l1": ["패키징"]})
    assert f6["_tech_l1_list"].map(lambda lst: "패키징" in lst).all()
    # 존재하지 않는 컬럼 필터는 무시 (graceful)
    df_min = prepared.drop(columns=["country"])
    assert len(apply_filters(df_min, {"countries": ["KR"]})) == len(df_min)
