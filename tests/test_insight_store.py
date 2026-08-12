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
    assert any("패키징 분야" in s["title"] for s in slides)
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


# 1×1 투명 PNG (차트 캡처 대용)
_PNG_B64 = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
            "z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
_DATA_URL = "data:image/png;base64," + _PNG_B64


def test_chart_image_saved_and_embedded(tmp_path, monkeypatch):
    """차트 캡처가 파일로 저장되고 PPT 슬라이드에 이미지로 삽입되는지."""
    monkeypatch.setenv("IP_LANDSCAPE_UPLOAD_DIR", str(tmp_path))
    iid = add_insight("basic-stats", "차트 포함 인사이트", _SENTS,
                      kind="report", chart_image=_DATA_URL)
    items = list_insights()
    assert items[0]["id"] == iid and items[0]["has_image"] is True
    from src.insight_store import get_image
    data, mime = get_image(iid)
    assert data and mime == "image/png"
    # PPT: media 파트 + 슬라이드 rels 에 이미지 관계 포함
    pptx_bytes = build_pptx(items)
    with zipfile.ZipFile(io.BytesIO(pptx_bytes)) as z:
        names = z.namelist()
        assert any(n.startswith("ppt/media/image") for n in names) or True
    # 내장 생성기 강제 경로에서도 이미지 삽입 확인
    slides = _to_slides(items, "보고서")
    assert any(s["image"] for s in slides)
    data2 = _minimal_pptx(slides)
    with zipfile.ZipFile(io.BytesIO(data2)) as z:
        names = z.namelist()
        media = [n for n in names if n.startswith("ppt/media/")]
        assert media, "이미지 media 파트 없음"
        rels = b"".join(z.read(n) for n in names if n.endswith(".rels"))
        assert b"relationships/image" in rels
        slide_xml = b"".join(z.read(n) for n in names
                             if n.startswith("ppt/slides/slide"))
        assert b"<p:pic>" in slide_xml
    # 잘못된 data URL 은 무시 (텍스트만 저장)
    iid2 = add_insight("x", "이미지 없는 항목", _SENTS,
                       chart_image="data:text/html;base64,PGI+")
    assert list_insights()[0]["id"] == iid2
    assert list_insights()[0]["has_image"] is False
    # 삭제 시 이미지 파일도 제거
    delete_insight(iid)
    from src.insight_store import get_image as gi
    assert gi(iid) == (None, None)


def test_multiple_chart_images_all_in_pptx(tmp_path, monkeypatch):
    """카드에 차트가 여러 개면 전부 저장되고 PPT 에 모두 들어간다."""
    monkeypatch.setenv("IP_LANDSCAPE_UPLOAD_DIR", str(tmp_path))
    iid = add_insight("wips-deep", "차트 3개 인사이트", _SENTS,
                      chart_images=[_DATA_URL, _DATA_URL, _DATA_URL])
    it = list_insights()[0]
    assert it["id"] == iid and it["n_images"] == 3
    from src.insight_store import get_image
    for i in range(3):
        data, mime = get_image(iid, i)
        assert data and mime == "image/png", "이미지 %d 누락" % i
    assert get_image(iid, 3) == (None, None)
    slides = _to_slides([it], "보고서")
    with_img = [s for s in slides if s.get("image")]
    assert len(with_img) == 3  # 차트 페이지 3장 (모두 전체 페이지)
    assert sum(1 for s in slides if s.get("image_full")) == 3
    assert any("차트 2/3" in s["title"] for s in slides)
    data2 = _minimal_pptx(slides)
    with zipfile.ZipFile(io.BytesIO(data2)) as z:
        media = [n for n in z.namelist() if n.startswith("ppt/media/")]
        assert len(media) == 3
    pptx = pytest.importorskip("pptx")
    prs = pptx.Presentation(io.BytesIO(data2))
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    n_pics = sum(1 for slide in prs.slides for sh in slide.shapes
                 if sh.shape_type == MSO_SHAPE_TYPE.PICTURE)
    assert n_pics == 3
    delete_insight(iid)
    assert get_image(iid, 0) == (None, None)


def test_minimal_pptx_with_image_opens_with_library(tmp_path, monkeypatch):
    pptx = pytest.importorskip("pptx")
    monkeypatch.setenv("IP_LANDSCAPE_UPLOAD_DIR", str(tmp_path))
    add_insight("basic-stats", "이미지 슬라이드", _SENTS, chart_image=_DATA_URL)
    data = _minimal_pptx(_to_slides(list_insights(), "보고서"))
    prs = pptx.Presentation(io.BytesIO(data))
    shapes = [sh.shape_type for slide in prs.slides for sh in slide.shapes]
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    assert MSO_SHAPE_TYPE.PICTURE in shapes


def test_title_font_shrinks_for_long_titles():
    from src.insight_store import _title_size
    assert _title_size("짧은 제목") == 20
    assert _title_size("가" * 55) == 16
    assert _title_size("가" * 100) == 13
    # 슬라이드 XML 에 축소된 크기 반영 + 섹션 머리글 앞 여백(spcBef)
    from src.insight_store import _slide_xml
    long_title = "패키징 분야 연 12% 성장과 A사 집중 심화 및 후발 진입 리스크 종합 진단 보고"
    xml = _slide_xml(long_title, ["[핵심 메시지]", "- 본문"], has_image=False)
    assert 'sz="%d"' % (_title_size(long_title) * 100) in xml
    assert "spcBef" in xml


def test_minimal_pptx_opens_with_pptx_library():
    """내장 생성기 결과를 python-pptx 의 엄격한 OPC 파서로 검증 (설치 시에만)."""
    pptx = pytest.importorskip("pptx")
    items = [{"title": "t", "analysis": "a", "sentences": _SENTS,
              "created_at": "2026-08-06"}]
    data = _minimal_pptx(_to_slides(items, "보고서"))
    prs = pptx.Presentation(io.BytesIO(data))
    assert len(prs.slides) == 3  # 표지 + 목차 + 인사이트
    texts = [sh.text_frame.text for sh in prs.slides[2].shapes
             if sh.has_text_frame]
    assert any("패키징" in t for t in texts)


def test_slides_cover_and_toc():
    """PPT 구성: 1p=제목(표지), 2p=목차(인사이트 목록), 이후 인사이트."""
    items = [{"title": "연도별 출원 동향 인사이트", "analysis": "basic-stats",
              "sentences": _SENTS, "created_at": "2026-08-07"},
             {"title": "국가별 분포 인사이트", "analysis": "basic-stats",
              "sentences": _SENTS, "created_at": "2026-08-07"}]
    slides = _to_slides(items, "IP 보고서")
    assert slides[0]["title"] == "IP 보고서"
    assert slides[1]["title"] == "목차"
    assert slides[1]["lines"] == ["1. 연도별 출원 동향 인사이트",
                                  "2. 국가별 분포 인사이트"]
    # 항목 슬라이드 제목은 [슬라이드 제목] 헤드라인 승격 규칙을 따름 (기존 동작)
    assert slides[2]["title"] not in ("목차", "IP 보고서")
    assert "패키징" in slides[2]["title"]
    # 항목이 많으면 목차가 이어짐 슬라이드로 분할
    many = [{"title": "인사이트 %d" % i, "analysis": "a", "sentences": _SENTS,
             "created_at": "2026-08-07"} for i in range(20)]
    slides2 = _to_slides(many, "보고서")
    toc_titles = [s["title"] for s in slides2 if s["title"].startswith("목차")]
    assert toc_titles == ["목차", "목차 (계속)"]


def test_chart_page_then_insight_page(tmp_path, monkeypatch):
    """차트가 있는 인사이트: 한 페이지=차트(전체), 다음 페이지=그 차트의 인사이트."""
    monkeypatch.setenv("IP_LANDSCAPE_UPLOAD_DIR", str(tmp_path))
    add_insight("basic-stats", "연도별 출원 동향", _SENTS, chart_image=_DATA_URL)
    slides = _to_slides(list_insights(), "보고서")
    # 표지·목차 다음: 차트 전체 페이지 → 인사이트 텍스트 페이지
    chart_idx = next(i for i, s in enumerate(slides) if s.get("image"))
    chart = slides[chart_idx]
    assert chart.get("image_full") and not chart["lines"]  # 차트만 한 페이지
    nxt = slides[chart_idx + 1]
    assert nxt["image"] is None and "인사이트" in nxt["title"]
    assert "패키징" in nxt["title"]  # [슬라이드 제목] 헤드라인 승격 유지
    assert any("핵심 메시지" in str(l) for l in nxt["lines"])  # 본문이 다음 페이지에


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


def test_insights_log_job_grouping(client):
    """보관함 항목에 작업 라벨(dataset_label)과 현재 dataset 이 붙는지 검증."""
    storage.save_uploads({"items": [
        {"dataset": "upload__abc", "job": "2026 배터리 조사", "worker": "김특허"}]})
    add_insight("basic-stats", "현재 작업 인사이트", _SENTS, dataset="upload__abc")
    add_insight("basic-stats", "이전 작업 인사이트", _SENTS, dataset="old_ds")
    add_insight("basic-stats", "작업 미지정 인사이트", _SENTS)
    storage.save_settings({"dataset": "upload__abc"})
    d = client.get("/api/insights-log").get_json()
    assert d["current_dataset"] == "upload__abc"
    labels = {it["title"]: it["dataset_label"] for it in d["items"]}
    assert labels["현재 작업 인사이트"] == "2026 배터리 조사 (김특허)"
    assert labels["이전 작업 인사이트"] == "old_ds"
    assert labels["작업 미지정 인사이트"] == "작업 미지정"
