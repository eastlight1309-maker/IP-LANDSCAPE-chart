# -*- coding: utf-8 -*-
"""임베딩 Adapter: KR-SBERT 로컬 모델·폴백 체인·캐시."""
import sys
import types

import numpy as np
import pandas as pd
import pytest

from src.config import merged_settings, DEFAULT_SBERT_MODEL
from src.embedding_adapter import get_adapter, SbertEmbeddingAdapter
from tests.conftest import make_prepared
from generate_sample_data import generate_sample, without_embeddings


def test_default_settings_use_sbert():
    s = merged_settings({})
    assert s["embedding_adapter"]["type"] == "sbert"
    # 빈 값 = 자동 (사내 로컬 경로 → 2024-hn → 2023 순서로 시도)
    assert s["embedding_adapter"]["model_name"] == ""


def test_sbert_unavailable_falls_back_gracefully():
    """sentence-transformers 미설치 환경: adapter None → TF-IDF 폴백 (오류 없음)."""
    s = merged_settings({})
    df = make_prepared(without_embeddings(generate_sample(n=40, seed=31)))
    ids = list(df["pub_number"].astype(str))
    adapter = get_adapter(s, df=df, id_series=ids)
    assert adapter is None  # 이 테스트 환경에는 sentence-transformers 가 없음
    from src.analyses.claim_density import compute_claim_density
    r = compute_claim_density(df, s)
    assert r["status"] == "ok"
    assert r["methods"]["embedding"] == "tfidf_fallback"


def test_precomputed_column_takes_priority_over_sbert():
    """사전 계산 임베딩 컬럼이 있으면 sbert 보다 우선."""
    s = merged_settings({})
    df = make_prepared(generate_sample(n=40, seed=32))
    ids = list(df["pub_number"].astype(str))
    adapter = get_adapter(s, df=df, id_series=ids)
    assert adapter is not None and adapter.name == "column"


@pytest.fixture()
def fake_sentence_transformers(monkeypatch):
    """가짜 sentence_transformers 모듈: 결정적 벡터 + encode 호출 기록."""
    calls = {"encode": 0, "texts": []}

    class FakeModel:
        def __init__(self, name, device=None):
            self.name = name

        def encode(self, texts, batch_size=32, show_progress_bar=False,
                   convert_to_numpy=True):
            calls["encode"] += 1
            calls["texts"].extend(texts)
            return np.stack([
                np.array([len(t) % 7, len(t) % 5, len(t) % 3], dtype=np.float32)
                for t in texts])

    mod = types.ModuleType("sentence_transformers")
    mod.SentenceTransformer = FakeModel
    monkeypatch.setitem(sys.modules, "sentence_transformers", mod)
    SbertEmbeddingAdapter._models.clear()
    SbertEmbeddingAdapter._cache.clear()
    yield calls
    SbertEmbeddingAdapter._models.clear()
    SbertEmbeddingAdapter._cache.clear()


def test_sbert_adapter_embeds_and_caches(fake_sentence_transformers):
    calls = fake_sentence_transformers
    adapter = SbertEmbeddingAdapter()
    assert adapter.model_name == DEFAULT_SBERT_MODEL
    out = adapter.get_embeddings(["a", "b"], ["청구항 하나", "청구항 둘입니다"])
    assert out["a"] is not None and len(out["a"]) == 3
    assert calls["encode"] == 1 and len(calls["texts"]) == 2
    # 동일 텍스트 재요청 → 캐시 사용 (encode 재호출 없음)
    out2 = adapter.get_embeddings(["c"], ["청구항 하나"])
    assert calls["encode"] == 1
    assert np.allclose(out2["c"], out["a"])
    # 새 텍스트만 인코딩
    adapter.get_embeddings(["d", "e"], ["청구항 하나", "새로운 청구항"])
    assert calls["encode"] == 2 and calls["texts"][-1] == "새로운 청구항"


def test_get_adapter_returns_sbert_without_column(fake_sentence_transformers):
    s = merged_settings({})
    df = make_prepared(without_embeddings(generate_sample(n=30, seed=33)))
    ids = list(df["pub_number"].astype(str))
    adapter = get_adapter(s, df=df, id_series=ids)
    assert adapter is not None and adapter.name == "sbert"


def test_claim_density_uses_sbert(fake_sentence_transformers):
    """임베딩 컬럼이 없어도 KR-SBERT(가짜)로 지형도가 계산되고 방식이 표시됨."""
    from src.analyses.claim_density import compute_claim_density
    s = merged_settings({})
    df = make_prepared(without_embeddings(generate_sample(n=60, seed=34)))
    r = compute_claim_density(df, s)
    assert r["status"] == "ok"
    assert r["methods"]["embedding"] == "adapter:sbert"


def test_sbert_model_name_validation(fake_sentence_transformers):
    with pytest.raises(ValueError):
        SbertEmbeddingAdapter("bad name; rm -rf")
