# -*- coding: utf-8 -*-
"""실데이터 오매핑 회귀 테스트: WIPS 유사 헤더에서의 형식 가드·값 검증·필터 정화."""
import pandas as pd

from src.column_mapping import (suggest_mapping, validate_mapping_values,
                                _header_kind, concept_kind)
from src.preprocessing import parse_dates, filter_options
from tests.conftest import make_prepared


def test_header_kind_guard():
    # 건수류 헤더는 number, 번호류는 text, 일자류는 date
    assert _header_kind("출원인수") == "number"
    assert _header_kind("인용문헌수") == "number"
    assert _header_kind("출원번호출원일") == "text"   # 번호 우선
    assert _header_kind("출원일") == "date"
    assert _header_kind("우선권주장일자") == "date"
    assert _header_kind("해결수단") == "text"          # '수'로 끝나지 않음
    assert concept_kind("applicant") == "text"
    assert concept_kind("app_date") == "date"


def test_applicant_not_mapped_to_count_column():
    """출원인(텍스트)이 '출원인 수'(숫자) 컬럼에 부분일치로 매핑되면 안 됨."""
    cols = ["출원번호", "출원인 수", "출원인명[KR]", "출원일자", "기술 대분류"]
    auto = suggest_mapping(cols)
    assert auto["applicant"]["column"] == "출원인명[KR]"
    assert auto.get("app_date", {}).get("column") == "출원일자"


def test_date_concept_not_mapped_to_text_header():
    """국가(텍스트)가 일자류 헤더에, 날짜 개념이 번호류 헤더에 매핑되면 안 됨."""
    cols = ["우선권주장 국가/일자", "국가코드", "출원번호(출원일)", "등록일자"]
    auto = suggest_mapping(cols)
    assert auto["country"]["column"] == "국가코드"
    # 출원번호(출원일)은 exact 변형이므로 app_number 로 매핑
    assert auto["app_number"]["column"] == "출원번호(출원일)"
    assert auto["reg_date"]["column"] == "등록일자"


def test_value_validation_drops_mismatches():
    sample = pd.DataFrame({
        "이상한출원인": [0.0, 4.0, 2.0, 1.0],           # applicant 로 잘못 추천된 숫자 컬럼
        "날짜국가": ["2020-01-01", "2021-03-02", "2019-05-06", "2022-07-08"],
        "정상출원인": ["삼성전자", "SK하이닉스", "TSMC", "Intel"],
        "정상국가": ["KR", "US", "JP", "CN"],
        "정상출원일": ["2020.01.01", "2021.03.02", "2019-05-06", "20220708"],
        "숫자아닌인용수": ["a", "b", "c", "d"],
    })
    mapping = {"applicant": "이상한출원인", "country": "날짜국가",
               "applicant_std": "정상출원인", "app_date": "정상출원일",
               "cites_forward": "숫자아닌인용수"}
    ok, dropped = validate_mapping_values(sample, mapping)
    dropped_concepts = {d["concept"] for d in dropped}
    assert "applicant" in dropped_concepts        # 숫자값 → 제외
    assert "country" in dropped_concepts          # 날짜값 → 제외
    assert "cites_forward" in dropped_concepts    # 비숫자 → 제외
    assert ok.get("applicant_std") == "정상출원인"
    assert ok.get("app_date") == "정상출원일"


def test_parse_dates_extracts_from_combined_column():
    """'출원번호(출원일)' 혼합 컬럼에서 날짜 추출, 번호 일련부는 오인하지 않음."""
    s = pd.Series(["10-2020-0123456 (2020.03.02)", "KR10-2019-0000001", "20211231",
                   "2018-05-06", None])
    out = parse_dates(s)
    assert out.iloc[0] == pd.Timestamp("2020-03-02")
    assert pd.isna(out.iloc[1])  # 순수 출원번호에서 가짜 날짜를 만들지 않음
    assert out.iloc[2] == pd.Timestamp("2021-12-31")
    assert out.iloc[3] == pd.Timestamp("2018-05-06")


def test_filter_options_hygiene():
    """필터 옵션에 숫자·날짜 오염값과 비정상 국가값이 노출되지 않아야 함."""
    df = pd.DataFrame({
        "공개번호": ["P%03d" % i for i in range(8)],
        "출원인": ["삼성전자", "0.0", "4.0", "SK하이닉스", "2020-01-01", "TSMC", "1", "네패스"],
        "국가": ["KR", "2020-01-01", "US", "20210101", "JP", "3.0", "KR", "US"],
        "기술 대분류": ["패키징", "kr", "본딩", "2020.01.02", "패키징", "5.0", "본딩", "테스트"],
        "출원일": ["2020-01-01"] * 8,
    })
    prep = make_prepared(df)
    opts = filter_options(prep)
    assert "0.0" not in opts["applicants"] and "4.0" not in opts["applicants"]
    assert "2020-01-01" not in opts["applicants"]
    assert set(opts["countries"]) <= {"KR", "US", "JP"}
    assert "2020.01.02" not in opts["tech_l1"] and "5.0" not in opts["tech_l1"]
    assert "패키징" in opts["tech_l1"]


def test_diagnose_message_when_dates_unparseable():
    """출원일이 매핑됐지만 값이 날짜가 아니면 원인을 알려주는 진단 메시지."""
    from src.analyses.lifecycle import compute_lifecycle
    from src.config import merged_settings
    df = pd.DataFrame({
        "공개번호": ["A1", "A2", "A3", "A4"],
        "출원인": ["갑", "을", "병", "정"],
        "기술 대분류": ["패키징", "본딩", "패키징", "본딩"],
        "출원일": ["-", "-", "-", "-"],   # 날짜 해석 불가
    })
    prep = make_prepared(df)
    r = compute_lifecycle(prep, merged_settings({}))
    assert r["status"] == "empty"
    assert "연도" in r["message"] and "매핑" in r["message"]


def test_parse_dates_year_only_and_excel_serial():
    """연도만 있는 값(2020, 2020.0)과 Excel 일련번호에서 연도 자동 추출."""
    s = pd.Series(["2020", "2021.0", "44562", "2019-03-01", "10-2020-0012345"])
    out = parse_dates(s)
    assert out.iloc[0].year == 2020
    assert out.iloc[1].year == 2021
    assert out.iloc[2] == pd.Timestamp("2022-01-01")  # Excel serial 44562
    assert out.iloc[3].year == 2019
    assert pd.isna(out.iloc[4])  # 순수 출원번호는 날짜로 오인하지 않음


def test_base_year_fallback_from_raw_year():
    """날짜 해석이 전부 실패해도 출원일 원본에서 4자리 연도를 추출해 반영."""
    df = pd.DataFrame({
        "공개번호": ["A1", "A2", "A3"],
        "출원인": ["갑", "을", "병"],
        "기술 대분류": ["패키징", "본딩", "패키징"],
        "출원일": ["2020년 출원", "출원연도: 2021", "2019 (심사중)"],  # 날짜 형식 아님
    })
    prep = make_prepared(df)
    assert prep["_base_year"].notna().all()
    assert sorted(prep["_base_year"].astype(int)) == [2019, 2020, 2021]


def test_applicant_display_prefers_std_column():
    """표준화 출원인 컬럼이 있으면 '기업' 값으로 그 값을 그대로 사용."""
    df = pd.DataFrame({
        "공개번호": ["A1", "A2"],
        "출원인": ["삼성전자 주식회사", "에스케이하이닉스 주식회사"],
        "표준화 출원인": ["삼성전자", "SK하이닉스"],
        "기술 대분류": ["패키징", "본딩"],
        "출원일": ["2020-01-01", "2021-01-01"],
    })
    prep = make_prepared(df)
    assert list(prep["applicant_display"]) == ["삼성전자", "SK하이닉스"]


def test_applicant_numeric_column_ignored():
    """출원인 개념이 숫자 컬럼에 매핑돼 있어도 표준화 출원인이 있으면 그쪽 사용."""
    from src.preprocessing import build_standard_frame
    df = pd.DataFrame({
        "번호": ["A1", "A2", "A3"],
        "숫자컬럼": [0.0, 4.0, 2.0],
        "표준명": ["삼성전자", "TSMC", "네패스"],
        "출원일": ["2020-01-01", "2021-01-01", "2022-01-01"],
        "대분류": ["패키징", "본딩", "패키징"],
    })
    mapping = {"pub_number": "번호", "applicant": "숫자컬럼", "applicant_std": "표준명",
               "app_date": "출원일", "tech_l1": "대분류"}
    prep = build_standard_frame(df, mapping)
    assert list(prep["applicant_display"]) == ["삼성전자", "TSMC", "네패스"]
    # 두 컬럼 모두 숫자면 빈 값 (0.0 이 기업으로 노출되지 않음)
    mapping2 = {"pub_number": "번호", "applicant": "숫자컬럼",
                "app_date": "출원일", "tech_l1": "대분류"}
    prep2 = build_standard_frame(df, mapping2)
    assert (prep2["applicant_display"] == "").all()


def test_country_derived_from_doc_number():
    """국가 컬럼이 없으면 공개번호 선두 국가코드에서 파생."""
    df = pd.DataFrame({
        "공개번호": ["KR10-2020-0000001A", "US2021123456A1", "JP2019-123456A", "KR10-2022-0000002A"],
        "출원인": ["갑", "을", "병", "정"],
        "기술 대분류": ["패키징", "본딩", "패키징", "본딩"],
        "출원일": ["2020-01-01", "2021-01-01", "2019-01-01", "2022-01-01"],
    })
    prep = make_prepared(df)
    assert list(prep["country"]) == ["KR", "US", "JP", "KR"]
    opts = filter_options(prep)
    assert set(opts["countries"]) == {"KR", "US", "JP"}


def test_filter_options_junk_tokens_removed():
    df = pd.DataFrame({
        "공개번호": ["P%d" % i for i in range(6)],
        "출원인": ["삼성전자", "or", "SK하이닉스", "a", "-", "네패스"],
        "기술 대분류": ["패키징; or", "본딩", "a; 패키징", "테스트", "본딩", "패키징"],
        "출원일": ["2020-01-01"] * 6,
    })
    prep = make_prepared(df)
    opts = filter_options(prep)
    assert "or" not in opts["applicants"] and "a" not in opts["applicants"]
    assert "or" not in opts["tech_l1"] and "a" not in opts["tech_l1"]
    assert "패키징" in opts["tech_l1"]


def test_parse_numeric_variants():
    from src.preprocessing import parse_numeric
    s = pd.Series(["1,234", "3건", "5 회", "12회 인용", "7", None, "값없음"])
    out = parse_numeric(s)
    assert list(out.dropna().astype(int)) == [1234, 3, 5, 12, 7]


def test_number_validation_accepts_units():
    sample = pd.DataFrame({"인용": ["1,234", "3건", "5 회", "0"]})
    ok, dropped = validate_mapping_values(sample, {"cites_forward": "인용"})
    assert ok.get("cites_forward") == "인용" and not dropped


def test_resolve_mapped_columns_normalized():
    """스키마 컬럼명과 로딩 컬럼명이 다를 때(특수문자·공백) 정규화 매칭으로 복원."""
    from src.preprocessing import resolve_mapped_columns
    mapping = {"cites_forward": "피인용 수", "legal_status": "상태정보[KR]",
               "title": "발명의 명칭", "missing": "없는컬럼"}
    loaded_cols = ["피인용수", "상태정보 KR", "발명의 명칭", "기타"]
    out = resolve_mapped_columns(mapping, loaded_cols)
    assert out["cites_forward"] == "피인용수"
    assert out["legal_status"] == "상태정보 KR"
    assert out["title"] == "발명의 명칭"
    assert "missing" not in out
    # 동일 정규화명이 2개면(모호) 임의 선택하지 않음
    out2 = resolve_mapped_columns({"cites_forward": "피인용 수"},
                                  ["피인용수", "피인용_수"])
    assert "cites_forward" not in out2


def test_build_frame_survives_column_name_drift():
    """매핑은 '피인용 수'인데 로딩된 컬럼명이 '피인용수'여도 분석 컬럼이 생성됨."""
    from src.preprocessing import build_standard_frame
    df = pd.DataFrame({
        "공개번호": ["A1", "A2", "A3"],
        "출원인": ["갑", "을", "병"],
        "피인용수": ["3", "1,234", "5건"],
        "출원일": ["2020-01-01", "2021-01-01", "2022-01-01"],
        "대분류": ["패키징", "본딩", "패키징"],
    })
    mapping = {"pub_number": "공개번호", "applicant": "출원인",
               "cites_forward": "피인용 수",  # 로딩명과 다름 (공백)
               "app_date": "출원일", "tech_l1": "대분류"}
    prep = build_standard_frame(df, mapping)
    assert "cites_forward" in prep.columns
    assert list(prep["cites_forward"].astype(int)) == [3, 1234, 5]
    from src.analyses.portfolio_index import compute_portfolio_index
    from src.config import merged_settings
    s = merged_settings({"thresholds": {"min_class_patents": 1}})
    r = compute_portfolio_index(prep, s)
    assert r["status"] == "ok", r.get("message")
