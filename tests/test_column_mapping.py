# -*- coding: utf-8 -*-
"""컬럼 매핑: 자동 추천·검증·가용성 매트릭스."""
from src.column_mapping import (suggest_mapping, clean_mapping, analysis_availability,
                                concept_catalog, CONCEPTS)


def test_suggest_mapping_korean_headers(raw_df):
    auto = suggest_mapping(list(raw_df.columns))
    assert auto["pub_number"]["column"] == "공개번호"
    assert auto["applicant"]["column"] == "출원인"
    assert auto["tech_l1"]["column"] == "기술 대분류"
    assert auto["tech_multi"]["column"] == "다중 기술분류"
    assert auto["app_date"]["column"] == "출원일"
    assert auto["problem"]["column"] == "해결과제"
    assert auto["embedding"]["column"] == "임베딩 벡터"


def test_suggest_mapping_english_variants():
    cols = ["Publication Number", "Application Date", "Applicant Name",
            "Forward Citation Count", "Legal Status", "IPC", "Level 1"]
    auto = suggest_mapping(cols)
    assert auto["pub_number"]["column"] == "Publication Number"
    assert auto["app_date"]["column"] == "Application Date"
    assert auto["cites_forward"]["column"] == "Forward Citation Count"
    assert auto["legal_status"]["column"] == "Legal Status"
    assert auto["tech_l1"]["column"] == "Level 1"


def test_one_column_one_concept(raw_df):
    auto = suggest_mapping(list(raw_df.columns))
    used = [v["column"] for v in auto.values()]
    assert len(used) == len(set(used))


def test_clean_mapping_removes_missing():
    clean, warnings = clean_mapping({"pub_number": "없는컬럼", "title": "발명의 명칭"},
                                    ["발명의 명칭"])
    assert clean == {"title": "발명의 명칭"}
    assert warnings


def test_availability_matrix(mapping):
    avail = analysis_availability(mapping)
    assert avail["overview"]["available"]
    assert avail["problem-solution"]["available"]
    # 필수 개념(B·C축 분류) 제거 시 비활성 + missing 라벨 안내
    no_ps = {k: v for k, v in mapping.items()
             if not k.startswith("tech_b_") and not k.startswith("tech_c_")}
    avail2 = analysis_availability(no_ps)
    assert not avail2["problem-solution"]["available"]
    assert any("B축" in m or "C축" in m
               for m in avail2["problem-solution"]["missing"])


def test_concept_catalog_complete():
    cat = concept_catalog()
    assert len(cat) == len(CONCEPTS) == 80
