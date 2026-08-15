# -*- coding: utf-8 -*-
"""목적 맞춤 분석: 목적 키 서버 검증 + 프론트 차트 연결(딥링크) 정합 검사.

PURPOSES 의 각 추천 차트는 (메뉴 view, 탭 라벨) 로 딥링크된다 — 라벨 오타나
탭 개편 시 조용히 끊기지 않도록 app.js 원문과 대조해 실존을 검증한다.
"""
import io
import os
import re

from src.config import ANALYSIS_PURPOSES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with io.open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def test_purpose_keys_match_frontend():
    js = _read("webapp/app.js")
    block = js.split("var PURPOSES = [", 1)[1].split("\n  ];", 1)[0]
    keys = re.findall(r"key: '(\w+)'", block)
    assert keys == ANALYSIS_PURPOSES  # 서버 검증 목록과 순서까지 일치
    assert len(keys) == 10


def test_purpose_chart_links_exist():
    """추천 차트의 view·탭 라벨이 실제 메뉴·탭에 실존해야 딥링크가 동작한다."""
    js = _read("webapp/app.js")
    html = _read("webapp/index.html")
    views = set(re.findall(r'data-view="(\w+)"', html))
    labels = set(re.findall(r"label: '([^']+)'", js))
    # execPlusTab/deepTab/deepPlusTab 은 label 을 첫 인자로 받는다
    labels |= set(re.findall(r"(?:execPlusTab|deepTab|deepPlusTab)\('([^']+)'", js))
    block = js.split("var PURPOSES = [", 1)[1].split("\n  ];", 1)[0]
    entries = re.findall(r"\{ v: '(\w+)', t: '([^']+)'", block)
    assert len(entries) >= 40  # 10개 목적 × 핵심+보조
    for view, tab in entries:
        assert view in views, "존재하지 않는 메뉴 view: %s" % view
        assert tab in labels, "존재하지 않는 탭 라벨: %r (view=%s)" % (tab, view)


def test_purpose_entries_have_reasons():
    js = _read("webapp/app.js")
    block = js.split("var PURPOSES = [", 1)[1].split("\n  ];", 1)[0]
    entries = re.findall(r"\{ v: '\w+', t: '[^']+', why: '([^']+)'", block)
    assert entries and all(len(w) >= 10 for w in entries)  # 이유 없는 추천 금지


def test_fto_design_around_have_legal_disclaimer():
    """특허 회피·FTO 목적에는 법률 자문 아님 고지가 반드시 붙는다 (앱 원칙)."""
    js = _read("webapp/app.js")
    block = js.split("var PURPOSES = [", 1)[1].split("\n  ];", 1)[0]
    for key in ("design_around", "fto"):
        seg = block.split("key: '%s'" % key, 1)[1].split("key: '", 1)[0]
        assert "note:" in seg and ("법률" in seg or "대리인" in seg), key
