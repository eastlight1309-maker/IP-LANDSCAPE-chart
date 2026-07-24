# -*- coding: utf-8 -*-
"""API 엔드포인트 통합 테스트 (Flask test client + 주입 dataset)."""
import io
import json
import subprocess
import sys
import os

import pytest
from flask import Flask

from generate_sample_data import generate_sample
from src import storage
from src.data_access import inject_dataset
from src.cache import clear_all_caches
from src.api import register_routes

DATASET = "test_patents"


@pytest.fixture(scope="module")
def client(raw_df):
    inject_dataset(DATASET, raw_df)
    storage.save_settings({"dataset": DATASET})
    clear_all_caches()
    app = Flask(__name__)
    register_routes(app)
    app.testing = True
    with app.test_client() as c:
        yield c


def _post(client, path, body=None):
    resp = client.post(path, data=json.dumps(body or {}),
                       content_type="application/json")
    return resp


def test_config(client):
    r = client.get("/api/config")
    assert r.status_code == 200
    data = r.get_json()
    assert data["app"] and data["version"].startswith("3.")
    assert len(data["llm_options"]) == 4
    # LLM ID(azureopenai:...)는 노출 금지 — 라벨만
    assert all(":" not in opt or "azureopenai" not in opt.split("|")[0]
               for opt in data["llm_options"])
    assert "llm_id" not in data["settings"]
    assert data["availability"]["overview"]["available"]
    assert data["disclaimer"]


def test_datasets_and_columns(client):
    data = client.get("/api/datasets").get_json()
    assert DATASET in data["datasets"]
    cols = client.get("/api/columns?dataset=%s" % DATASET).get_json()
    assert "공개번호" in cols["columns"]
    bad = client.get("/api/columns?dataset=../etc/passwd")
    assert bad.status_code == 404
    assert bad.get_json()["status"] == "error"


def test_column_mapping_roundtrip(client):
    got = client.get("/api/column-mapping?dataset=%s" % DATASET).get_json()
    assert got["effective"]["pub_number"] == "공개번호"
    save = _post(client, "/api/column-mapping",
                 {"dataset": DATASET, "mapping": got["effective"]})
    assert save.status_code == 200
    assert save.get_json()["availability"]["overview"]["available"]
    bad = _post(client, "/api/column-mapping",
                {"dataset": DATASET, "mapping": {"pub_number": "없는컬럼"}})
    assert bad.status_code == 400


def test_filter_options(client):
    data = _post(client, "/api/filter-options").get_json()
    assert data["options"]["year_min"] is not None
    assert data["options"]["applicants"]


ANALYSIS_PATHS = [
    "/api/overview", "/api/technology-network", "/api/emerging-combinations",
    "/api/lifecycle", "/api/opportunity", "/api/problem-solution",
    "/api/technology-transition", "/api/trajectory", "/api/company-dna",
    "/api/lead-lag", "/api/claim-density", "/api/citation-diffusion",
    "/api/inventor-mobility", "/api/classification-quality",
]


@pytest.mark.parametrize("path", ANALYSIS_PATHS)
def test_analysis_endpoints(client, path):
    resp = _post(client, path, {"filters": {}})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] in ("ok", "empty", "disabled")
    assert "insight" in data


def test_analysis_with_filters_and_cache(client):
    body = {"filters": {"year_from": 2016, "countries": ["KR", "US"]}}
    d1 = _post(client, "/api/overview", body).get_json()
    d2 = _post(client, "/api/overview", body).get_json()
    assert d1["status"] == "ok"
    assert d2["meta"]["cache_hit"] is True


def test_patents_drilldown_pagination(client):
    data = _post(client, "/api/patents",
                 {"drill": {"type": "tech", "tech": "FOWLP"},
                  "page": 1, "page_size": 5}).get_json()
    assert data["status"] == "ok"
    assert data["total"] > 0 and len(data["records"]) <= 5
    data2 = _post(client, "/api/patents", {"page": 1, "page_size": 99999}).get_json()
    assert data2["page_size"] <= 200  # 대용량 JSON 방지 상한


def test_export_excel(client):
    resp = _post(client, "/api/export", {"drill": {"type": "tech", "tech": "FOWLP"},
                                         "filename": "test_export"})
    assert resp.status_code == 200
    assert resp.data[:2] == b"PK"  # xlsx(zip) 시그니처
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(resp.data))
    assert wb.sheetnames == ["patents"]


def test_insight_endpoint_fallback(client):
    data = _post(client, "/api/insight",
                 {"analysis": "overview", "metrics": {"total": 100},
                  "sentences": ["규칙 기반 문장"]}).get_json()
    assert data["status"] == "ok"
    assert data["sentences"]  # LLM 미가용 환경 → 규칙 기반 그대로


def test_settings_roundtrip(client):
    data = _post(client, "/api/settings",
                 {"multiclass_mode": "fractional",
                  "llm_label": "gpt-5.4 | dw-aoai-chat-eastus2-cognitiv"}).get_json()
    assert data["settings"]["multiclass_mode"] == "fractional"
    assert "llm_id" not in data["settings"]
    saved = storage.load_settings()
    assert saved["llm_id"].endswith("gpt-5.4")
    bad = _post(client, "/api/settings", {"multiclass_mode": "잘못된값"})
    assert bad.status_code == 400
    _post(client, "/api/settings", {"multiclass_mode": "duplicate"})


def test_llm_id_direct_set_blocked(client):
    _post(client, "/api/settings", {"llm_id": "azureopenai:evil:model"})
    saved = storage.load_settings()
    assert saved.get("llm_id") != "azureopenai:evil:model"


def test_applicant_rules(client):
    got = client.get("/api/applicant-rules?dataset=%s" % DATASET).get_json()
    assert "검토" in got["note"]
    save = _post(client, "/api/applicant-rules",
                 {"mapping": {"SAMSUNG ELECTRONICS": "삼성전자"},
                  "groups": {"삼성전자": "삼성그룹"},
                  "history_entry": "합병: 테스트"}).get_json()
    assert save["rules"]["mapping"]["SAMSUNG ELECTRONICS"] == "삼성전자"
    reset = _post(client, "/api/applicant-rules",
                  {"reset": ["SAMSUNG ELECTRONICS"], "reset_groups": ["삼성전자"]}).get_json()
    assert "SAMSUNG ELECTRONICS" not in reset["rules"]["mapping"]


def test_project_save_load(client):
    _post(client, "/api/project/save",
          {"name": "테스트 프로젝트", "filters": {"year_from": 2018}})
    lst = _post(client, "/api/project/load", {}).get_json()
    assert any(p["name"] == "테스트 프로젝트" for p in lst["projects"])
    got = _post(client, "/api/project/load", {"name": "테스트 프로젝트"}).get_json()
    assert got["project"]["filters"]["year_from"] == 2018
    _post(client, "/api/project/load", {"name": "테스트 프로젝트", "delete": True})


def test_filter_state(client):
    r = _post(client, "/api/filter-state", {"filters": {"year_from": 2019}})
    assert r.get_json()["status"] == "ok"
    cfg = client.get("/api/config").get_json()
    assert cfg["filter_state"].get("year_from") == 2019


def test_merged_backend_builds_and_serves(raw_df, tmp_path):
    """tools/build_backend.py 산출물이 문법적으로 유효하고 라우트가 동작하는지."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    subprocess.check_call([sys.executable, os.path.join(root, "tools", "build_backend.py")])
    backend_path = os.path.join(root, "webapp", "backend.py")
    assert os.path.exists(backend_path)
    import importlib.util
    spec = importlib.util.spec_from_file_location("merged_backend", backend_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # app 생성 + register_routes 실행
    mod.inject_dataset(DATASET, raw_df)
    mod.app.testing = True
    with mod.app.test_client() as c:
        cfg = c.get("/api/config").get_json()
        assert cfg["app"]
        for path in ("/api/overview", "/api/technology-network",
                     "/api/emerging-combinations", "/api/lead-lag",
                     "/api/citation-diffusion", "/api/claim-density"):
            r = c.post(path, data=json.dumps({}),
                       content_type="application/json").get_json()
            assert r["status"] in ("ok", "empty", "disabled"), \
                "%s → %s" % (path, r)
