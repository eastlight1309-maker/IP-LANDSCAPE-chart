# -*- coding: utf-8 -*-
"""엑셀 업로드 작업 저장소: 필수 입력·영속화·재적재·목록·삭제."""
import io

import pandas as pd
import pytest
from flask import Flask

from generate_sample_data import generate_sample
from src import storage
from src.api import register_routes
from src.cache import clear_all_caches
from src.data_access import _INJECTED_DATASETS


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("IP_LANDSCAPE_UPLOAD_DIR", str(tmp_path / "uploads"))
    storage.save_uploads({"items": []})
    clear_all_caches()
    app = Flask(__name__)
    register_routes(app)
    app.testing = True
    with app.test_client() as c:
        yield c


def _xlsx_bytes(n=40):
    buf = io.BytesIO()
    generate_sample(n=n, seed=61).to_excel(buf, index=False, engine="openpyxl")
    buf.seek(0)
    return buf


def test_upload_requires_worker_and_job(client):
    r = client.post("/api/uploads", data={"file": (_xlsx_bytes(), "t.xlsx"),
                                          "worker": "", "job": "작업"},
                    content_type="multipart/form-data")
    assert r.status_code == 400
    assert "작업자" in r.get_json()["message"]
    r2 = client.post("/api/uploads", data={"file": (_xlsx_bytes(), "t.xlsx"),
                                           "worker": "홍길동", "job": " "},
                     content_type="multipart/form-data")
    assert r2.status_code == 400


def test_upload_rejects_bad_extension(client):
    r = client.post("/api/uploads",
                    data={"file": (io.BytesIO(b"abc"), "malware.exe"),
                          "worker": "홍길동", "job": "테스트"},
                    content_type="multipart/form-data")
    assert r.status_code == 400
    assert "형식" in r.get_json()["message"]


def test_upload_save_list_reload_delete(client):
    # ① 업로드 → 저장 + 즉시 dataset 등록
    r = client.post("/api/uploads",
                    data={"file": (_xlsx_bytes(40), "wips_2026.xlsx"),
                          "worker": "홍길동", "job": "상반기 IP 조사"},
                    content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    entry = r.get_json()["entry"]
    assert entry["worker"] == "홍길동" and entry["job"] == "상반기 IP 조사"
    assert entry["n_rows"] == 40 and entry["dataset"].startswith("upload__")
    ds = entry["dataset"]
    assert ds in _INJECTED_DATASETS

    # ② 목록 조회 (최신순, 상태 플래그)
    lst = client.get("/api/uploads").get_json()["items"]
    assert lst[0]["id"] == entry["id"]
    assert lst[0]["loaded"] is True and lst[0]["file_exists"] is True

    # ③ Backend 재시작 시뮬레이션 → dataset 참조 시 파일에서 자동 재적재
    _INJECTED_DATASETS.pop(ds, None)
    clear_all_caches()
    resp = client.post("/api/filter-options", json={"dataset": ds})
    assert resp.status_code == 200
    assert resp.get_json()["n_rows"] > 0
    assert ds in _INJECTED_DATASETS  # 자동 재적재됨

    # ④ 명시적 불러오기 endpoint
    _INJECTED_DATASETS.pop(ds, None)
    r3 = client.post("/api/uploads/load", json={"id": entry["id"]})
    assert r3.status_code == 200 and r3.get_json()["entry"]["dataset"] == ds
    assert ds in _INJECTED_DATASETS

    # ⑤ 설정 저장에서도 업로드 dataset 허용 (재적재 경유)
    _INJECTED_DATASETS.pop(ds, None)
    r4 = client.post("/api/settings", json={"dataset": ds})
    assert r4.status_code == 200

    # ⑥ 삭제 → 목록·파일 제거
    r5 = client.post("/api/uploads/delete", json={"id": entry["id"]})
    assert r5.status_code == 200
    lst2 = client.get("/api/uploads").get_json()["items"]
    assert all(it["id"] != entry["id"] for it in lst2)
    r6 = client.post("/api/uploads/load", json={"id": entry["id"]})
    assert r6.status_code == 404


def test_upload_csv_supported(client):
    csv_bytes = io.BytesIO(
        generate_sample(n=15, seed=62).to_csv(index=False).encode("utf-8"))
    r = client.post("/api/uploads",
                    data={"file": (csv_bytes, "data.csv"),
                          "worker": "김담당", "job": "CSV 케이스"},
                    content_type="multipart/form-data")
    assert r.status_code == 200
    assert r.get_json()["entry"]["n_rows"] == 15
