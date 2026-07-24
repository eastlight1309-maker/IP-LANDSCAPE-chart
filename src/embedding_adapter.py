# -*- coding: utf-8 -*-
"""
embedding_adapter.py — 사내 임베딩 모델 연결 Adapter (3단계).

설계:
- EmbeddingAdapter (추상): get_embeddings(ids, texts) -> {id: np.ndarray | None}
- DatasetEmbeddingAdapter : 사전 계산 벡터 Dataset 방식.
    설정: {"type":"dataset","dataset":이름,"id_column":문헌키 컬럼,"vector_column":벡터 컬럼}
    벡터 컬럼은 JSON 배열/공백·쉼표 구분 문자열 지원 (preprocessing.parse_embedding).
- RestEmbeddingAdapter    : REST API 방식.
    설정: {"type":"rest","url":엔드포인트,"api_key_env":환경변수명,"batch_size":n,
           "timeout":sec}
    요청: POST {"texts":[...]} → 응답: {"embeddings":[[...],...]} 규약.
    API Key 는 환경변수에서만 읽으며 프론트엔드에 노출하지 않는다.
- ColumnEmbeddingAdapter  : 분석 대상 Dataset 자체의 임베딩 벡터 컬럼 사용 (기본).

get_adapter(settings): 설정에 따라 구현체 반환. 실패·미설정 시 None (분석은
임베딩 없이 가능한 범위로 degrade, 임의 벡터 생성 금지).
"""
import json
import logging
import os
import urllib.request

import numpy as np

from src.preprocessing import parse_embedding
from src.data_access import load_raw_dataframe, validate_dataset_name

logger = logging.getLogger("ip_landscape")


class EmbeddingAdapter(object):
    """사내 임베딩 모델 연결 추상 클래스."""

    name = "abstract"

    def get_embeddings(self, ids, texts):
        """문헌 id 목록·텍스트 목록 → {id: np.ndarray 또는 None}.

        구현체는 벡터를 구할 수 없는 문헌에 대해 None 을 반환해야 하며,
        임의의 벡터를 생성해서는 안 된다.
        """
        raise NotImplementedError


class ColumnEmbeddingAdapter(EmbeddingAdapter):
    """분석 Dataset 의 임베딩 컬럼(_embedding 파생)을 그대로 사용."""

    name = "column"

    def __init__(self, df, id_series):
        self._by_id = {}
        if "_embedding" in df.columns:
            for pid, vec in zip(id_series, df["_embedding"]):
                if vec is not None:
                    self._by_id[str(pid)] = np.asarray(vec, dtype=np.float64)

    def get_embeddings(self, ids, texts):
        return {str(i): self._by_id.get(str(i)) for i in ids}


class DatasetEmbeddingAdapter(EmbeddingAdapter):
    """사전 계산 벡터 Dataset 방식 구현체."""

    name = "dataset"

    def __init__(self, dataset, id_column, vector_column):
        self.dataset = validate_dataset_name(dataset)
        self.id_column = str(id_column)
        self.vector_column = str(vector_column)
        self._loaded = None

    def _load(self):
        if self._loaded is not None:
            return self._loaded
        self._loaded = {}
        if not self.dataset:
            logger.warning("DatasetEmbeddingAdapter: dataset not in whitelist")
            return self._loaded
        try:
            df = load_raw_dataframe(self.dataset, columns=[self.id_column, self.vector_column])
            for pid, raw in zip(df[self.id_column], df[self.vector_column]):
                vec = parse_embedding(raw)
                if vec is not None:
                    self._loaded[str(pid).strip()] = vec
        except Exception as e:
            logger.warning("DatasetEmbeddingAdapter load failed: %s", e)
        return self._loaded

    def get_embeddings(self, ids, texts):
        table = self._load()
        return {str(i): table.get(str(i).strip()) for i in ids}


class RestEmbeddingAdapter(EmbeddingAdapter):
    """REST API 방식 구현체 (POST {"texts": [...]} → {"embeddings": [...]})."""

    name = "rest"

    def __init__(self, url, api_key_env=None, batch_size=64, timeout=60):
        self.url = str(url)
        self.api_key = os.environ.get(api_key_env) if api_key_env else None
        self.batch_size = max(1, int(batch_size))
        self.timeout = float(timeout)

    def _call(self, texts):
        payload = json.dumps({"texts": texts}).encode("utf-8")
        req = urllib.request.Request(self.url, data=payload,
                                     headers={"Content-Type": "application/json"})
        if self.api_key:
            req.add_header("Authorization", "Bearer %s" % self.api_key)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        embs = body.get("embeddings")
        if not isinstance(embs, list) or len(embs) != len(texts):
            raise ValueError("embedding API 응답 형식 오류")
        return [np.asarray(e, dtype=np.float64) if e else None for e in embs]

    def get_embeddings(self, ids, texts):
        out = {}
        ids = [str(i) for i in ids]
        for start in range(0, len(ids), self.batch_size):
            batch_ids = ids[start:start + self.batch_size]
            batch_texts = [t if t else "" for t in texts[start:start + self.batch_size]]
            try:
                vecs = self._call(batch_texts)
            except Exception as e:
                logger.warning("REST embedding call failed: %s", e)
                vecs = [None] * len(batch_ids)
            for pid, vec in zip(batch_ids, vecs):
                out[pid] = vec
        return out


def get_adapter(settings, df=None, id_series=None):
    """설정 기반 Adapter 팩토리.

    우선순위: 설정된 adapter(dataset/rest) → Dataset 자체 임베딩 컬럼 → None.
    """
    conf = (settings or {}).get("embedding_adapter") or {}
    atype = conf.get("type", "none")
    try:
        if atype == "dataset" and conf.get("dataset") and conf.get("id_column") \
                and conf.get("vector_column"):
            return DatasetEmbeddingAdapter(conf["dataset"], conf["id_column"],
                                           conf["vector_column"])
        if atype == "rest" and conf.get("url"):
            return RestEmbeddingAdapter(conf["url"], conf.get("api_key_env"),
                                        conf.get("batch_size", 64), conf.get("timeout", 60))
    except Exception as e:
        logger.warning("embedding adapter init failed: %s", e)
    if df is not None and id_series is not None and "_embedding" in df.columns \
            and df["_embedding"].map(lambda v: v is not None).any():
        return ColumnEmbeddingAdapter(df, id_series)
    return None
