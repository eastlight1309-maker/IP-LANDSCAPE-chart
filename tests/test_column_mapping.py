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


# 윈텔립스(WIPS ON) Excel 실제 다운로드 항목 전체 — 자동 매핑 회귀의 기준 목록
WINTELIPS_HEADERS = [
    "국가코드", "DB종류", "특허/실용 구분", "문헌종류 코드", "발명의 명칭",
    "발명의 명칭-번역문", "발명의 명칭-기타 원어", "요약", "요약-번역문", "요약-기타 원어",
    "대표청구항", "대표청구항-번역문", "대표청구항-기타 원어",
    "독립청구항[KR,JP,US,CN,EP,IN]", "독립청구항-번역문[JP,US,CN,EP]",
    "독립청구항-기타 원어[KR,JP,CN,EP]", "청구항 수", "독립항 수[KR,JP,US,CN,EP,IN]",
    "AI 요약[KR,US,JP,CN,EP,PCT,TW]", "기술분야 요약[KR,US,JP,CN,EP,PCT,TW]",
    "해결과제 요약[KR,US,JP,CN,EP,PCT,TW]", "해결수단 요약[KR,US,JP,CN,EP,PCT,TW]",
    "특징 요약[KR,US,JP,CN,EP,PCT,TW]", "효과 요약[KR,US,JP,CN,EP,PCT,TW]",
    "출원번호", "출원일", "번역문제출일(or §371 date)", "공개번호", "공개일",
    "공고번호", "공고일", "등록번호", "등록일", "발행일[JP,EP,PCT]",
    "출원인", "특허고객번호(출원인)[KR]", "법인등록번호(출원인)[KR]",
    "사업자등록번호(출원인)[KR]", "출원인(제2언어)", "출원인 국적", "출원인 주소[KR]",
    "출원인 수", "출원인 대표명화 코드", "출원인 대표명화 영문명",
    "출원인 대표명화 국문명[KR]", "원문상 출원인[KR]", "출원인 식별기호[JP]",
    "발명자", "발명자(제2언어)", "발명자 국적", "발명자 수",
    "대리인", "대리인 번호[KR]", "대리인 사무소[KR]",
    "우선권 번호", "우선권 국가", "우선권 주장일", "RA번호[US,PCT,AU]", "RA일[US,PCT,AU]",
    "원출원번호[KR,JP,EP,CN,IN,CA]", "원출원일[KR,JP,EP,CN,IN,CA]",
    "분할출원 여부[KR,US,JP,EP,CN,IN,CA,AU]", "최우선출원번호", "최우선출원국가", "최우선출원일",
    "국제 출원번호", "국제 출원일", "국제 공개번호", "국제 공개일", "지정국 코드",
    "Original CPC Main", "Original CPC All", "Original IPC Main", "Original IPC All",
    "Original US Class Main", "Original US Class All", "Original FI[JP]",
    "Original F-term[JP]", "Original Theme Code[JP]",
    "Current CPC Main", "Current CPC All", "Current IPC Main", "Current IPC All",
    "Current US Class Main", "Current US Class All", "Current FI[JP]", "Current F-term[JP]",
    "인용 문헌 수(B1)", "인용 문헌번호(B1)", "자기인용 문헌번호(B1)", "타인인용 문헌번호(B1)",
    "심사관인용 문헌번호(BE)[KR,US,JP,EP]", "비 특허 참고문헌(B1)", "비 특허 참고문헌 수(B1)",
    "피인용 문헌 수(F1)", "피인용 문헌번호(F1)", "자기 피인용 문헌번호(F1)",
    "타인 피인용 문헌번호(F1)", "심사관인용 문헌번호(FE)[KR,US,JP,EP]",
    "WIPS패밀리 ID", "WIPS패밀리 Basic Patent 문헌번호", "WIPS패밀리 문헌번호(출원기준)",
    "WIPS패밀리 문헌 수(출원기준)", "WIPS패밀리 개별국 문헌 수(출원기준)",
    "WIPS패밀리 국가 수(출원기준)", "EPO패밀리 ID", "EPO패밀리 문헌번호(출원기준)",
    "EPO패밀리 문헌 수(출원기준)", "EPO패밀리 개별국 문헌 수(출원기준)",
    "EPO패밀리 국가 수(출원기준)",
    "상태정보[KR,JP,US,EP,CN,CA,AU]", "심사청구 여부[KR,JP,EP,CA]",
    "존속기간(예상)만료일[KR,JP,US,EP,CN,CA,AU]", "현재권리자[KR,JP,US,CN,CA,AU]",
    "현재권리자(제2언어)[KR,JP,CN]", "현재권리자 대표명화 코드[KR,JP,US,CN,CA,AU]",
    "현재권리자 대표명화 영문명[KR,JP,US,CN,CA,AU]", "현재권리자 대표명화 국문명[KR]",
    "DOCDB 법적상태", "EPC지정국[EP]", "EPC소멸국[EP]", "EPC유효국[EP]", "통합특허법원[EP]",
    "원문(PDF)링크", "번역문(PDF)링크[JP]", "상세보기 링크(비로그인)", "상세보기 링크(로그인)",
    "개별도면 수", "관련도", "사용자태그", "문헌 메모", "관심특허", "내/외국인 출원여부",
    "정정공보 존재 유무[KR,JP]",
    "표준화기구", "표준번호", "선언일", "선언(등재)자", "선언(등재)자 국적", "대표도면",
    "Entity Status[US]", "AIA 적용여부[US]", "PTA 연장일[US]",
    "거절서류발행 횟수[KR]", "거절결정 여부[KR,JP]", "재심사청구 여부[KR]", "거절 사유[KR]",
    "우선심사청구 여부[KR]", "신규성상실예외주장유무[JP]", "심사관[KR,JP,US,CN]",
    "실시권 설정 유무[KR]", "실시권자 수[KR]", "최근 양수인[KR,US,CN]", "최근 양도인[KR,US,CN]",
    "최근 양도일[KR,US,CN]", "최근 양도유형[KR,US,CN]", "최근 연차료일[KR,US,EP]",
    "권리변동 유무[KR,US,CN]",
    "심판 전체 횟수[KR,JP,US,EP]", "심판 종류[KR,JP,US,EP]", "소송 전체 횟수[US]",
    "관할법원 종류[US]",
    "국가연구 과제번호[KR]", "국가연구 과제명[KR]", "국가연구 사업명[KR]", "국가연구 부처명[KR]",
    "국가연구 주관기관[KR]", "식의약품 특허등재여부[US]",
]


def test_wintelips_full_header_mapping():
    """윈텔립스 실제 항목 168종에서 핵심 개념이 정확한 컬럼으로 자동 매핑된다."""
    m = suggest_mapping(WINTELIPS_HEADERS)
    got = {k: v["column"] for k, v in m.items()}
    expect = {
        "pub_number": "공개번호", "app_number": "출원번호", "reg_number": "등록번호",
        "title": "발명의 명칭", "abstract": "요약",
        "indep_claim": "독립청구항[KR,JP,US,CN,EP,IN]",
        "claims_count": "청구항 수", "indep_claims_count": "독립항 수[KR,JP,US,CN,EP,IN]",
        "applicant": "출원인", "applicant_std": "출원인 대표명화 국문명[KR]",
        "assignee": "현재권리자 대표명화 국문명[KR]", "inventors": "발명자",
        "app_date": "출원일", "pub_date": "공개일", "reg_date": "등록일",
        "priority_date": "우선권 주장일",
        "expiry_date": "존속기간(예상)만료일[KR,JP,US,EP,CN,CA,AU]",
        "country": "국가코드", "legal_status": "상태정보[KR,JP,US,EP,CN,CA,AU]",
        "cites_backward": "인용 문헌 수(B1)", "cites_forward": "피인용 문헌 수(F1)",
        "family_id": "WIPS패밀리 ID",
        "family_rep": "WIPS패밀리 Basic Patent 문헌번호",
        "family_size": "WIPS패밀리 문헌 수(출원기준)",
        "family_countries": "WIPS패밀리 개별국 문헌 수(출원기준)",
        "family_country_count": "WIPS패밀리 국가 수(출원기준)",
        "problem": "해결과제 요약[KR,US,JP,CN,EP,PCT,TW]",
        "solution": "해결수단 요약[KR,US,JP,CN,EP,PCT,TW]",
        "ipc": "Current IPC All",
        "agent": "대리인", "expedited_exam": "우선심사청구 여부[KR]",
        "license_flag": "실시권 설정 유무[KR]", "licensee_count": "실시권자 수[KR]",
        "sep_org": "표준화기구", "sep_number": "표준번호", "sep_date": "선언일",
        "rejection_reason": "거절 사유[KR]", "rejection_flag": "거절결정 여부[KR,JP]",
        "reexam_flag": "재심사청구 여부[KR]", "npl_count": "비 특허 참고문헌 수(B1)",
        "recent_assignee": "최근 양수인[KR,US,CN]", "recent_assignor": "최근 양도인[KR,US,CN]",
        "assign_date": "최근 양도일[KR,US,CN]", "assign_type": "최근 양도유형[KR,US,CN]",
        "examiner": "심사관[KR,JP,US,CN]", "oa_count": "거절서류발행 횟수[KR]",
        "examiner_citations": "심사관인용 문헌번호(BE)[KR,US,JP,EP]",
        "applicant_citations": "자기인용 문헌번호(B1)",
        "parent_app_number": "원출원번호[KR,JP,EP,CN,IN,CA]",
        "drawings_count": "개별도면 수",
        "trial_info": "심판 종류[KR,JP,US,EP]", "trial_count": "심판 전체 횟수[KR,JP,US,EP]",
        "lawsuit_count": "소송 전체 횟수[US]", "court_type": "관할법원 종류[US]",
        "gov_program": "국가연구 과제명[KR]",
    }
    for concept, col in expect.items():
        assert got.get(concept) == col, \
            "%s: 기대 %r, 실제 %r" % (concept, col, got.get(concept))
    # 오매핑 금지: 인원수·주소·링크류가 개념에 배정되면 안 됨
    banned = {"출원인 수", "발명자 수", "출원인 주소[KR]", "원문(PDF)링크",
              "상세보기 링크(비로그인)", "최근 연차료일[KR,US,EP]"}
    assert not banned & set(got.values()), banned & set(got.values())
