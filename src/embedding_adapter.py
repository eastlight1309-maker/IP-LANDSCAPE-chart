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


class SbertEmbeddingAdapter(EmbeddingAdapter):
    """로컬 sentence-transformers 모델 구현체.

    기본 동작(모델명 미지정): 사내 로컬 경로(LOCAL_SBERT_MODEL_DIR, 네트워크·비용
    없음) → snunlp/KR-SBERT-Medium-extended-patent2024-hn → patent2023 순으로 시도.
    Dataiku 인스턴스(코드 환경)에 준비된 HuggingFace 모델을 직접 로드하며,
    GPU(cuda) 가용 시 자동 사용한다. 임베딩 결과는 (모델, 텍스트 SHA1) 키의
    프로세스 내 캐시에 저장되어 필터 변경·재조회 시 재계산하지 않는다.

    sentence-transformers 미설치·모델 미존재 시 __init__ 에서 예외를 던지고,
    get_adapter 가 이를 잡아 다음 폴백으로 넘어간다 (임의 벡터 생성 없음).
    """

    name = "sbert"
    _models = {}          # model_name -> SentenceTransformer (프로세스 공유)
    _cache = {}           # (model_name, sha1(text)) -> np.ndarray
    _CACHE_MAX = 120000   # 약 5만 건 × 여유 (768차원 float32 ≈ 3KB/건)

    def __init__(self, model_name=None, batch_size=64):
        import re as _re
        from src.config import SBERT_MODEL_CANDIDATES
        candidates = []
        user_name = str(model_name or "").strip()
        if user_name:
            if not _re.fullmatch(r"[\w\-./]+", user_name):
                raise ValueError("허용되지 않는 임베딩 모델명 형식: %r" % user_name)
            candidates.append(user_name)
        candidates += [c for c in SBERT_MODEL_CANDIDATES if c not in candidates]
        self.batch_size = max(1, int(batch_size))
        self._model, self.model_name = self._load_first(candidates)

    @classmethod
    def _load_first(cls, candidates):
        """후보를 순서대로 시도: 사내 로컬 경로(디렉터리 존재 시) → HF 캐시 모델명.

        로컬 경로는 네트워크 없이 디스크에서 직접 로드된다 (비용 없음).
        전부 실패하면 마지막 오류를 던져 get_adapter 폴백으로 넘어간다.
        """
        last_err = None
        for cand in candidates:
            # 경로 형태 후보는 디렉터리가 실제 존재할 때만 시도
            if "/" in cand and cand.startswith(("/", ".")) and not os.path.isdir(cand):
                continue
            try:
                return cls._load_model(cand), cand
            except Exception as e:
                logger.warning("SBERT 모델 로드 실패 (%s): %s", cand, e)
                last_err = e
        raise last_err if last_err else RuntimeError("사용 가능한 SBERT 모델 없음")

    @classmethod
    def _load_model(cls, name):
        if name in cls._models:
            return cls._models[name]
        from sentence_transformers import SentenceTransformer  # 미설치 시 ImportError
        device = None
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            pass
        logger.info("SBERT 모델 로드: %s (device=%s)", name, device or "auto")
        model = SentenceTransformer(name, device=device)
        cls._models[name] = model
        return model

    @staticmethod
    def _text_key(text):
        import hashlib
        return hashlib.sha1(str(text).encode("utf-8")).hexdigest()

    def get_embeddings(self, ids, texts):
        ids = [str(i) for i in ids]
        keys = [(self.model_name, self._text_key(t or "")) for t in texts]
        missing_idx = [i for i, k in enumerate(keys) if k not in self._cache]
        if missing_idx:
            batch_texts = [str(texts[i] or "")[:2000] for i in missing_idx]
            vectors = self._model.encode(batch_texts, batch_size=self.batch_size,
                                         show_progress_bar=False,
                                         convert_to_numpy=True)
            for i, vec in zip(missing_idx, vectors):
                if len(self._cache) >= self._CACHE_MAX:
                    self._cache.clear()  # 상한 도달 시 단순 초기화 (메모리 보호)
                self._cache[keys[i]] = np.asarray(vec, dtype=np.float32)
        return {pid: self._cache.get(k) for pid, k in zip(ids, keys)}


class LLMMeshEmbeddingAdapter(EmbeddingAdapter):
    """Dataiku LLM Mesh 임베딩 모델 구현체.

    설정: {"type":"llm_mesh","llm_id":"<Mesh 에 등록된 임베딩 모델 ID>"}
    (예: KR-SBERT 를 Local HuggingFace 연결로 Mesh 에 등록한 경우.)
    호출은 Backend 전용이며 llm_id 는 프론트에 노출되지 않는다.
    """

    name = "llm_mesh"

    def __init__(self, llm_id, batch_size=64):
        import re as _re
        from src.config import LEGACY_LLM_ID_MAP
        if _dataiku_mod_available() is None:
            raise RuntimeError("dataiku 모듈 미가용 — LLM Mesh 임베딩 사용 불가")
        llm_id = str(llm_id or "").strip()
        llm_id = LEGACY_LLM_ID_MAP.get(llm_id, llm_id)  # 구 Connection 자동 승계
        if not _re.fullmatch(r"[\w\-.:/]+", llm_id):
            raise ValueError("허용되지 않는 임베딩 LLM ID 형식")
        self.llm_id = llm_id
        self.batch_size = max(1, int(batch_size))
        client = _dataiku_mod_available().api_client()
        self._llm = client.get_default_project().get_llm(self.llm_id)

    def get_embeddings(self, ids, texts):
        out = {}
        ids = [str(i) for i in ids]
        for start in range(0, len(ids), self.batch_size):
            batch_ids = ids[start:start + self.batch_size]
            batch_texts = [str(t or "")[:2000] for t in texts[start:start + self.batch_size]]
            try:
                emb = self._llm.new_embeddings()
                for t in batch_texts:
                    emb.add_text(t)
                resp = emb.execute()
                vectors = resp.get_embeddings()
                if len(vectors) != len(batch_ids):
                    raise ValueError("임베딩 응답 개수 불일치")
                for pid, vec in zip(batch_ids, vectors):
                    out[pid] = np.asarray(vec, dtype=np.float32) if vec is not None else None
            except Exception as e:
                logger.warning("LLM Mesh 임베딩 호출 실패: %s", e)
                for pid in batch_ids:
                    out[pid] = None
        return out


def _dataiku_mod_available():
    try:
        import dataiku as _d
        return _d
    except ImportError:
        return None


def get_adapter(settings, df=None, id_series=None):
    """설정 기반 Adapter 팩토리.

    우선순위:
      ① 명시 설정 dataset/rest Adapter
      ② Dataset 자체 임베딩 벡터 컬럼 (사전 계산 벡터가 있으면 재계산보다 우선)
      ③ 설정 type=sbert → 로컬 KR-SBERT (기본값) / type=llm_mesh → Mesh 임베딩
      ④ 전부 불가 시 None (호출부가 TF-IDF 폴백 또는 기능 degrade — 임의 생성 없음)
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
    try:
        if atype == "sbert":
            return SbertEmbeddingAdapter(conf.get("model_name"),
                                         conf.get("batch_size", 64))
        if atype == "llm_mesh" and conf.get("llm_id"):
            return LLMMeshEmbeddingAdapter(conf["llm_id"], conf.get("batch_size", 64))
    except Exception as e:
        logger.warning("모델 기반 임베딩 adapter 초기화 실패 (%s) — 폴백 사용: %s", atype, e)
    return None
