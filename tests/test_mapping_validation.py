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
