# -*- coding: utf-8 -*-
"""⑪ 50,000건 대용량 성능 테스트 (합성 데이터)."""
import time

from generate_sample_data import generate_sample
from tests.conftest import make_prepared
from src.preprocessing import dedupe_families, apply_filters
from src.analyses.overview import compute_overview
from src.analyses.tech_network import compute_tech_network
from src.analyses.emerging import compute_emerging


def test_50k_pipeline(settings):
    t0 = time.time()
    raw = generate_sample(n=50000, seed=99)
    t_gen = time.time() - t0

    t0 = time.time()
    prep = make_prepared(raw)
    fam = dedupe_families(prep)
    t_prep = time.time() - t0
    assert len(prep) == 50000
    assert len(fam) < len(prep)  # 패밀리 dedup 동작

    t0 = time.time()
    filtered = apply_filters(fam, {"year_from": 2015})
    r1 = compute_overview(filtered, settings)
    r2 = compute_tech_network(filtered, settings)
    r3 = compute_emerging(filtered, settings)
    t_analysis = time.time() - t0
    assert r1["status"] == "ok" and r2["status"] == "ok" and r3["status"] == "ok"
    # 상한 적용 확인 (대용량에서도 응답 크기 제한)
    assert r2["n_nodes"] <= 80 and r2["n_edges"] <= 250

    total = t_gen + t_prep + t_analysis
    print("\n50k 성능: 생성 %.1fs / 전처리 %.1fs / 분석 %.1fs (합계 %.1fs)"
          % (t_gen, t_prep, t_analysis, total))
    assert t_prep < 120, "전처리가 너무 느립니다 (%.1fs)" % t_prep
    assert t_analysis < 180, "분석이 너무 느립니다 (%.1fs)" % t_analysis
