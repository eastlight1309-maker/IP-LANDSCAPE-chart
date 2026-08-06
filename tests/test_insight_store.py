# -*- coding: utf-8 -*-
"""LLM 인사이트 보관함 + PPT 보고서 생성."""
import io
import zipfile
import xml.etree.ElementTree as ET

import pytest
from flask import Flask

from src import storage
from src.api import register_routes
from src.insight_store import add_insight, list_insights, delete_insight, \
    build_pptx, _minimal_pptx, _to_slides


@pytest.fixture(autouse=True)
def clean_store():
    storage.save_store("insights", {"items": []})
    yield
    storage.save_store("insights", {"items": []})


@pytest.fixture()
def client():
    app = Flask(__name__)
    register_routes(app)
    app.testing = True
    with app.test_client() as c:
        yield c


_SENTS = ["[슬라이드 제목] 패키징 분야 연 12% 성장 — A사 집중 심화",
          "[차트 개요] 연도별 출원 동향",
          "[핵심 메시지]", "- A사 2023년 34건으로 1위",
          "[근거 데이터]", "- 전체 2015–2024년 1,200건",
          "[시사점·제언]", "- 후속 분석: 회사별 비교",
          "[유의사항] 최근 연도는 미공개분 존재"]


def test_add_list_delete_roundtrip():
    iid = add_insight("basic-stats", "연도별 출원 동향", _SENTS,
                      dataset="ds1", kind="report")
    assert iid
    items = list_insights()
    assert len(items) == 1 and items[0]["id"] == iid
    assert items[0]["sentences"][0].startswith("[슬라이드 제목]")
    assert add_insight("x", "빈 문장", []) is None  # 내용 없으면 저장 안 함
    delete_insight(iid)
    assert list_insights() == []


def test_minimal_pptx_structure():
    items = [{"title": "인사이트1", "analysis": "basic-stats",
              "sentences": _SENTS, "created_at": "2026-08-06 10:00:00"},
             {"title": "인사이트2 <특수&문자>", "analysis": "lifecycle",
              "sentences": ["줄%d" % i for i in range(30)],  # 분할 케이스
              "created_at": "2026-08-06 11:00:00"}]
    slides = _to_slides(items, "테스트 보고서")
    assert len(slides) >= 4  # 표지 + 1장 + 분할 2장 이상
    # 헤드라인이 슬라이드 제목으로 승격
    assert any("패키징 분야" in t for t, _l in slides)
    data = _minimal_pptx(slides)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = set(z.namelist())
        assert "[Content_Types].xml" in names
        assert "ppt/presentation.xml" in names
        assert "ppt/slideMasters/slideMaster1.xml" in names
        assert "ppt/theme/theme1.xml" in names
        slide_files = [n for n in names if n.startswith("ppt/slides/slide")
                       and n.endswith(".xml")]
        assert len(slide_files) == len(slides)
        for n in names:
            if n.endswith(".xml") or n.endswith(".rels"):
                ET.fromstring(z.read(n))  # 모든 파트가 유효한 XML
        # 특수문자 이스케이프 확인
        joined = b"".join(z.read(n) for n in slide_files)
        assert b"&lt;" in joined and b"&amp;" in joined
    assert build_pptx(items)  # 라이브러리 부재 환경에서 폴백 동작


def test_minimal_pptx_opens_with_pptx_library():
    """내장 생성기 결과를 python-pptx 의 엄격한 OPC 파서로 검증 (설치 시에만)."""
    pptx = pytest.importorskip("pptx")
    items = [{"title": "t", "analysis": "a", "sentences": _SENTS,
              "created_at": "2026-08-06"}]
    data = _minimal_pptx(_to_slides(items, "보고서"))
    prs = pptx.Presentation(io.BytesIO(data))
    assert len(prs.slides) == 2
    texts = [sh.text_frame.text for sh in prs.slides[1].shapes
             if sh.has_text_frame]
    assert any("패키징" in t for t in texts)


def test_insights_endpoints(client, monkeypatch):
    # LLM 생성 시 자동 저장 (버튼 경로)
    from src import insights as ins_mod
    monkeypatch.setattr(ins_mod, "call_llm",
                        lambda *a, **k: "\n".join(_SENTS))
    monkeypatch.setattr(ins_mod, "llm_available", lambda: True)
    storage.save_settings({"llm_insights_enabled": True})
    d = client.post("/api/insight", json={
        "analysis": "basic-stats", "metrics": {"total": 10},
        "sentences": ["규칙 문장"]}).get_json()
    assert d["source"] == "llm" and d.get("saved_id")
    items = client.get("/api/insights-log").get_json()["items"]
    assert items and items[0]["id"] == d["saved_id"]
    assert items[0]["kind"] == "report"
    # PPT 다운로드 (전체)
    r = client.post("/api/insights-report", json={})
    assert r.status_code == 200
    assert r.mimetype.endswith("presentation")
    with zipfile.ZipFile(io.BytesIO(r.data)) as z:
        assert "ppt/presentation.xml" in z.namelist()
    # 선택 다운로드 + 삭제
    r2 = client.post("/api/insights-report", json={"ids": [d["saved_id"]]})
    assert r2.status_code == 200
    client.post("/api/insights-log/delete", json={"id": d["saved_id"]})
    assert client.get("/api/insights-log").get_json()["items"] == []
    r3 = client.post("/api/insights-report", json={})
    assert r3.status_code == 404
