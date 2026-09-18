# -*- coding: utf-8 -*-
"""사용자 정의 차트 빌더 회귀 테스트.

차트 종류·축 항목을 사용자가 직접 고르는 기능 — 축 의미(분류/값)가 종류별로
다르므로, 각 종류가 실제 데이터에서 계산되고 drill-down 이 화면 수치와
일치하는지 검증한다 (값 지어내기 금지 원칙).
"""
import json

import pytest
from flask import Flask

from conftest import make_prepared
from generate_sample_data import generate_sample
from src import storage
from src.api import register_routes
from src.cache import clear_all_caches
from src.config import merged_settings
from src.data_access import inject_dataset
from src.analyses.common import select_patents
from src.analyses.custom_chart import (compute_custom_chart, chart_fields,
                                       CHART_TYPES, DIM_BY_KEY, MEASURE_BY_KEY)

DS = "custom_chart_ds"


@pytest.fixture(scope="module")
def prepared():
    return make_prepared(generate_sample(n=300, seed=42))


@pytest.fixture(scope="module")
def settings():
    return merged_settings({})


@pytest.fixture(scope="module")
def client(prepared):
    inject_dataset(DS, generate_sample(n=300, seed=42))
    storage.save_settings({"dataset": DS, "demo_mode": False})
    clear_all_caches()
    app = Flask(__name__)
    register_routes(app)
    app.testing = True
    with app.test_client() as c:
        yield c


def _post(client, path, body):
    return client.post(path, data=json.dumps(body),
                       content_type="application/json").get_json()


def test_fields_catalog_only_available_items(prepared):
    """카탈로그는 현재 데이터에 값이 있는 항목만 — 빈 축 선택을 막는다."""
    f = chart_fields(prepared)
    dims = {d["key"] for d in f["dimensions"]}
    meas = {m["key"] for m in f["measures"]}
    assert {"year", "applicant", "tech", "country"} <= dims
    assert {"count", "cites_forward_avg", "grant_rate"} <= meas
    assert len(f["chart_types"]) == len(CHART_TYPES)
    # 매핑되지 않은 컬럼 기반 항목은 빠진다
    thin = prepared.drop(columns=[c for c in ("cites_forward", "family_size")
                                  if c in prepared.columns])
    meas2 = {m["key"] for m in chart_fields(thin)["measures"]}
    assert "cites_forward_avg" not in meas2 and "family_size_avg" not in meas2
    assert "count" in meas2      # 문헌 수는 항상 가능


@pytest.mark.parametrize("spec", [
    {"chart_type": "bar", "x": "applicant", "y": "count"},
    {"chart_type": "line", "x": "year", "y": "count"},
    {"chart_type": "pie", "x": "country", "y": "count"},
    {"chart_type": "bubble_matrix", "x": "year", "y": "tech", "size": "count"},
    {"chart_type": "heatmap", "x": "year", "y": "tech_l1", "size": "cites_forward_avg"},
    {"chart_type": "bubble", "group": "applicant", "x": "count",
     "y": "cites_forward_avg", "size": "family_size_avg"},
    {"chart_type": "scatter", "group": "applicant", "x": "grant_rate",
     "y": "cites_forward_avg"},
])
def test_each_chart_type_renders(prepared, settings, spec):
    r = compute_custom_chart(prepared, settings, spec=spec)
    assert r["status"] == "ok", r.get("message")
    assert r["figure"]["data"], spec
    assert r["insight"]["sentences"]


def test_bar_values_match_drilldown(prepared, settings):
    """막대 값(문헌 수)과 drill-down 결과 건수가 정확히 일치한다."""
    r = compute_custom_chart(prepared, settings,
                             spec={"chart_type": "bar", "x": "applicant",
                                   "y": "count", "top_n": 5})
    assert r["status"] == "ok"
    rows = r["rows"]
    assert len(rows) <= 5 and rows
    for row in rows[:3]:
        sub = select_patents(prepared, row["drill"])
        assert len(sub) == int(row["value"]), row


def test_bubble_size_measure_is_used(prepared, settings):
    """버블 크기 항목을 바꾸면 마커 크기 구성이 실제로 달라진다."""
    base = {"chart_type": "bubble", "group": "applicant", "x": "count",
            "y": "cites_forward_avg", "top_n": 8}
    a = compute_custom_chart(prepared, settings,
                             spec=dict(base, size="count"))
    b = compute_custom_chart(prepared, settings,
                             spec=dict(base, size="claims_avg"))
    assert a["status"] == "ok" and b["status"] == "ok"
    sa = a["figure"]["data"][0]["marker"]["size"]
    sb = b["figure"]["data"][0]["marker"]["size"]
    assert len(sa) == len(sb) and sa != sb
    assert a["axis_info"]["size"] == MEASURE_BY_KEY["count"]["label"]
    assert b["axis_info"]["size"] == MEASURE_BY_KEY["claims_avg"]["label"]


def test_matrix_cell_drill_matches(prepared, settings):
    """버블 매트릭스 셀의 drill 은 그 교차 문헌만 연다."""
    r = compute_custom_chart(prepared, settings,
                             spec={"chart_type": "bubble_matrix", "x": "year",
                                   "y": "tech", "size": "count", "top_n": 6})
    assert r["status"] == "ok"
    tr = r["figure"]["data"][0]
    cd = tr["customdata"][0]
    sub = select_patents(prepared, cd["drill"])
    assert len(sub) > 0
    year = str(int(sub["_base_year"].iloc[0]))
    assert year == str(tr["x"][0])


def test_invalid_spec_returns_guidance(prepared, settings):
    """잘못된 선택은 오류가 아니라 '무엇을 고르라'는 안내로 돌려준다."""
    r = compute_custom_chart(prepared, settings, spec={"chart_type": "bar"})
    assert r["status"] == "empty" and "선택" in r["message"]
    r2 = compute_custom_chart(prepared, settings,
                              spec={"chart_type": "heatmap", "x": "year",
                                    "y": "year", "size": "count"})
    assert r2["status"] == "empty" and "서로 다른" in r2["message"]
    r3 = compute_custom_chart(prepared, settings, spec={"chart_type": "없는차트"})
    assert r3["status"] == "empty"


def test_api_routes(client):
    f = client.get("/api/custom-chart/fields").get_json()
    assert f["status"] == "ok" and f["dimensions"] and f["measures"]
    r = _post(client, "/api/custom-chart",
              {"filters": {}, "spec": {"chart_type": "bar", "x": "applicant",
                                       "y": "count"}})
    assert r["status"] == "ok" and r["figure"]["data"]
    # 필터가 반영된다 (연도 제한 시 문헌 수 감소)
    r2 = _post(client, "/api/custom-chart",
               {"filters": {"year_from": 2022},
                "spec": {"chart_type": "bar", "x": "applicant", "y": "count"}})
    assert r2["status"] == "ok"
    assert sum(x["n"] for x in r2["rows"]) < sum(x["n"] for x in r["rows"])
