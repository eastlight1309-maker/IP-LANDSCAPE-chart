# -*- coding: utf-8 -*-
"""
IP Landscape Advanced Insight Webapp — Dataiku Standard Webapp Python Backend.

⚠ 이 파일은 tools/build_backend.py 가 src/ 모듈을 병합하여 자동 생성한다.
   수정은 src/ 에서 하고 다시 빌드할 것.

Dataiku Standard Webapp 의 "Python" 탭에 이 파일 전체를 붙여넣으면
Dataiku 가 제공하는 전역 `app`(Flask) 객체에 라우트가 등록된다.
"""



# ===========================================================================
# src/config.py
# ===========================================================================
# -*- coding: utf-8 -*-
"""
config.py — 전역 상수, 허용 LLM 목록, 임계값·가중치 기본값, 상한(LIMITS).

모든 설정값은 상수로 정의하며, 런타임에는 storage.load_settings()가 반환하는
사용자 설정(dict)이 이 기본값 위에 overlay 된다. UI 문자열(안내문·면책문구 등)은
MESSAGES 에 모아 계산 로직과 분리한다.
"""

APP_NAME = "IP Landscape Advanced Insight"
APP_VERSION = "3.0.0"  # 1단계=1.x, 2단계=2.x, 3단계=3.x

# =========================
# 사용 허용할 LLM 목록 (고정)
# =========================
ALLOWED_LLM_CANDIDATES = [
    ("gpt-5.3-chat | dw-aoai-chat-eastus2-cognitiv", "azureopenai:dw-aoai-chat-eastus2-cognitiv:gpt-5.3-chat"),
    ("gpt-5.4-nano | dw-aoai-chat-eastus2-cognitiv", "azureopenai:dw-aoai-chat-eastus2-cognitiv:gpt-5.4-nano"),
    ("gpt-5.4-mini | dw-aoai-chat-eastus2-cognitiv", "azureopenai:dw-aoai-chat-eastus2-cognitiv:gpt-5.4-mini"),
    ("gpt-5.4 | dw-aoai-chat-eastus2-cognitiv", "azureopenai:dw-aoai-chat-eastus2-cognitiv:gpt-5.4"),
]
DEFAULT_LLM_ID = "azureopenai:dw-aoai-chat-eastus2-cognitiv:gpt-5.4-nano"
ALLOWED_LLM_IDS = frozenset(llm_id for _, llm_id in ALLOWED_LLM_CANDIDATES)

# =========================
# 규모 상한 (Settings 에서 변경 가능 — settings["limits"] 로 overlay)
# =========================
LIMITS = {
    "network_max_nodes": 80,          # 조합 네트워크 노드 상한 (Top-N by weight)
    "network_max_edges": 250,         # 조합 네트워크 엣지 상한
    "sankey_max_links": 120,          # Sankey 링크 상한
    "bubble_max_points": 200,         # 버블차트 포인트 상한
    "heatmap_max_cells": 2500,        # Plotly 히트맵 셀 상한 (초과 시 ECharts 전환)
    "echarts_threshold_cells": 100000,  # ECharts 필요 기준 (10만 셀)
    "matrix_max_rows": 40,            # 문제-해결수단 매트릭스 행 상한
    "matrix_max_cols": 40,
    "patents_page_size": 25,          # drill-down 페이지 크기
    "patents_max_page_size": 200,
    "export_max_rows": 20000,         # Excel export 행 상한
    "top_n_default": 10,
    "max_companies_compare": 12,      # DNA 레이더 최대 기업 수 (초과 시 히트맵)
    "trajectory_max_companies": 10,
    "leadlag_max_companies": 20,
    "claim_density_max_points": 5000, # 지형도 산점 상한 (초과 시 샘플링)
    "inventor_network_max_edges": 200,
    "insight_llm_max_chars": 4000,    # LLM 에 전달하는 요약통계 문자열 상한
}

# =========================
# 분석 임계값 기본값 (Settings 에서 변경 가능 — settings["thresholds"])
# =========================
THRESHOLDS = {
    "min_combo_patents": 3,        # 조합 최소 표본 (미만 조합 제외)
    "min_class_patents": 3,        # 기술분류 최소 표본
    "recent_years": 3,             # "최근" 정의 (년)
    "fuzzy_match_cutoff": 0.75,    # 컬럼 자동매핑 유사도 임계값
    "winsor_pct": 0.02,            # Winsorization 양측 백분위
    "min_years_leadlag": 5,        # 선도-추종 최소 관측연도
    "min_patents_leadlag": 10,     # 선도-추종 최소 특허 수
    "max_lag_years": 3,            # 선도-추종 최대 시차
    "leadlag_min_corr": 0.5,       # 선도-추종 최소 상관
    "inventor_match_confidence": 0.6,  # 발명자 동일인 판정 신뢰도 임계값
    "low_confidence_class": 0.5,   # 저신뢰 분류 임계값 (분류 신뢰도 컬럼)
    "emerging_min_growth": 0.3,    # Emerging 단계 최소 성장률
    "reemerging_decline_years": 3, # Re-emerging: 과거 감소·정체 기간
    "insight_small_sample": 10,    # 표본 부족 경고 기준 (건)
    "sim_topk_per_doc": 20,        # 청구항 유사도 상위 K 이웃만 유지
}

# =========================
# 점수 가중치 기본값 (Settings 슬라이더 — settings["weights"])
# =========================
WEIGHTS = {
    # Emerging Combination Score = 가중 기하평균(성장률, Lift, 신규출원인, 다양성)
    "emerging": {"growth": 1.0, "lift": 1.0, "new_entrants": 1.0, "diversity": 0.5},
    # Opportunity Score = 매력도(기회) x 진입가능성(1/장벽)
    "opportunity": {
        "growth": 1.0, "new_entrants": 1.0, "combo_growth": 0.7,
        "keyword_growth": 0.5, "problem_recurrence": 0.5, "adjacency": 0.7,
        "barrier": 1.0,  # 분모(권리장벽)
    },
    # Influence Score
    "influence": {
        "direct_citations": 1.0, "indirect_citations": 0.7, "cross_class": 0.8,
        "cross_company": 0.8, "family_expansion": 0.6, "legal_strength": 0.6,
    },
    # 기업 유형 분류 기준값 (표준화 점수 기준, 사용자가 조정 가능)
    "dna_type_cutoff": 0.6,
}

# =========================
# 법적상태 정규화 카테고리 (원본값 보존, normalized 컬럼 병행)
# =========================
LEGAL_STATUS_CATEGORIES = [
    "Pending", "Granted-Active", "Granted-Expired", "Abandoned",
    "Withdrawn", "Rejected", "Lapsed", "Unknown",
]
ACTIVE_LEGAL_STATUSES = frozenset(["Granted-Active", "Pending"])
GRANTED_LEGAL_STATUSES = frozenset(["Granted-Active", "Granted-Expired"])

# 법적상태 원본 → 정규화 매핑 (소문자 부분일치, 순서 = 우선순위)
LEGAL_STATUS_PATTERNS = [
    ("존속기간만료", "Granted-Expired"), ("granted-expired", "Granted-Expired"),
    ("expired", "Granted-Expired"), ("만료", "Granted-Expired"),
    ("granted-active", "Granted-Active"), ("등록유지", "Granted-Active"),
    ("in force", "Granted-Active"), ("active", "Granted-Active"),
    ("유효", "Granted-Active"), ("존속", "Granted-Active"),
    ("소멸", "Lapsed"), ("lapsed", "Lapsed"), ("연차료불납", "Lapsed"),
    ("non-payment", "Lapsed"), ("포기", "Abandoned"), ("abandon", "Abandoned"),
    ("취하", "Withdrawn"), ("withdraw", "Withdrawn"),
    ("거절", "Rejected"), ("reject", "Rejected"), ("refus", "Rejected"),
    ("무효", "Rejected"),
    ("등록", "Granted-Active"), ("grant", "Granted-Active"), ("registered", "Granted-Active"),
    ("출원계속", "Pending"), ("심사중", "Pending"), ("pending", "Pending"),
    ("공개", "Pending"), ("published", "Pending"), ("examination", "Pending"),
    ("출원", "Pending"), ("filed", "Pending"),
]

# 분석 단위
ANALYSIS_UNITS = ["family", "publication", "application", "registration"]
DEFAULT_ANALYSIS_UNIT = "family"

# 다중 기술분류 집계 방식
MULTICLASS_MODES = ["duplicate", "fractional", "primary", "level_separate"]
DEFAULT_MULTICLASS_MODE = "duplicate"

# 생애주기 단계
LIFECYCLE_PHASES = ["Emerging", "Growing", "Competitive", "Mature", "Declining", "Re-emerging"]

# 기업 유형 (4.5 규칙 기반 분류)
COMPANY_TYPES = ["선도 개척형", "권리 장벽형", "집중 방어형", "융합 확장형", "추격 확장형", "양적 출원형"]

# =========================
# UI 문자열 (계산 로직과 분리)
# =========================
MESSAGES = {
    "disclaimer": ("본 분석은 특허 데이터에 기반한 탐색적 스크리닝 결과이며, "
                   "법률적 FTO 판단, 특허 유효성 판단 또는 인과관계를 의미하지 않습니다."),
    "small_sample": "현재 표본 수가 적어 추세를 확정하기 어렵습니다.",
    "missing_columns": "필수 컬럼이 없습니다. 컬럼 매핑 화면에서 다음 컬럼을 매핑하세요: {cols}",
    "no_data": "필터 조건에 해당하는 데이터가 없어 계산할 수 없습니다.",
    "not_implemented": "이 분석은 아직 구현되지 않았습니다 (다음 단계 예정).",
    "no_dataset": "Dataset 이 선택되지 않았습니다. Settings 에서 Dataset 을 선택하세요.",
    "llm_fallback": "LLM 응답에 실패하여 규칙 기반 인사이트로 대체되었습니다.",
    "estimated_move": "추정 이동",
}

# 오류 코드
ERR_BAD_REQUEST = 400
ERR_NOT_FOUND = 404
ERR_NOT_IMPLEMENTED = 501
ERR_INTERNAL = 500

# 데모 모드 기본값 (사용자가 Settings 에서 명시적으로 켠 경우에만 샘플 데이터 사용)
DEFAULT_SETTINGS = {
    "dataset": None,
    "demo_mode": False,
    "analysis_unit": DEFAULT_ANALYSIS_UNIT,
    "multiclass_mode": DEFAULT_MULTICLASS_MODE,
    "llm_id": DEFAULT_LLM_ID,
    "llm_insights_enabled": False,
    "embedding_adapter": {"type": "none"},  # none | dataset | rest
    "limits": {}, "thresholds": {}, "weights": {},
    "transition_mode": "cooccurrence",  # 4.1 전이 정의 기본값
    "trajectory_weighting": "share",    # share | tfidf
    "dna_type_cutoffs": {},
    "own_company_names": [],            # 자사 표준 출원인명 목록
    "own_capability_keywords": [],      # 사용자가 입력한 보유 기술목록
}


def merged_settings(user_settings):
    """DEFAULT_SETTINGS 위에 사용자 설정을 overlay 한 dict 반환 (dict 값은 개별 병합)."""
    out = {}
    for k, v in DEFAULT_SETTINGS.items():
        out[k] = dict(v) if isinstance(v, dict) else (list(v) if isinstance(v, list) else v)
    for k, v in (user_settings or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def get_limit(settings, key):
    """상한값 조회: 사용자 설정 → 기본 LIMITS."""
    try:
        v = (settings or {}).get("limits", {}).get(key)
        if v is not None:
            return int(v)
    except Exception:
        pass
    return LIMITS[key]


def get_threshold(settings, key):
    """임계값 조회: 사용자 설정 → 기본 THRESHOLDS."""
    try:
        v = (settings or {}).get("thresholds", {}).get(key)
        if v is not None:
            return float(v)
    except Exception:
        pass
    return THRESHOLDS[key]


def get_weights(settings, group):
    """가중치 그룹 조회: 기본 WEIGHTS[group] 위에 사용자 설정 overlay."""
    base = dict(WEIGHTS.get(group, {}))
    user = (settings or {}).get("weights", {}).get(group, {})
    if isinstance(user, dict):
        for k, v in user.items():
            if k in base:
                try:
                    base[k] = float(v)
                except (TypeError, ValueError):
                    pass
    return base


# ===========================================================================
# src/gpu_utils.py
# ===========================================================================
# -*- coding: utf-8 -*-
"""
gpu_utils.py — GPU 감지 및 cuML/cupy ↔ scikit-learn/numpy 자동 폴백.

계산 논리:
- import 시점에 cupy/cuML/torch(cuda) 가용성을 1회 탐지하여 캐시한다.
- get_backend() 는 {"pca","umap","hdbscan","dbscan","kmeans","cosine_sim"} 팩토리를
  반환하며, GPU 구현이 없거나 로드 실패 시 CPU(scikit-learn/numpy) 구현으로 폴백한다.
- UMAP 은 GPU(cuml.UMAP) → CPU(umap-learn) → PCA 순으로 폴백한다 (4.4/4.9 요구사항).
- HDBSCAN 은 GPU(cuml.HDBSCAN) → CPU(hdbscan 또는 sklearn.cluster.HDBSCAN) → DBSCAN 폴백.
모든 반환 결과는 numpy 배열로 통일한다 (cupy 배열은 .get() 으로 변환).
"""
import logging
import numpy as np

logger = logging.getLogger("ip_landscape")

_GPU_STATE = {"checked": False, "cupy": None, "cuml": None}


def _detect_gpu():
    """cupy/cuML 가용성 1회 탐지 (임포트 실패·GPU 미탑재 시 CPU 모드)."""
    if _GPU_STATE["checked"]:
        return _GPU_STATE
    _GPU_STATE["checked"] = True
    try:
        import cupy  # noqa
        cupy.cuda.runtime.getDeviceCount()
        _GPU_STATE["cupy"] = cupy
    except Exception:
        _GPU_STATE["cupy"] = None
    try:
        if _GPU_STATE["cupy"] is not None:
            import cuml  # noqa
            _GPU_STATE["cuml"] = cuml
    except Exception:
        _GPU_STATE["cuml"] = None
    logger.info("GPU detection: cupy=%s cuml=%s",
                bool(_GPU_STATE["cupy"]), bool(_GPU_STATE["cuml"]))
    return _GPU_STATE


def gpu_available():
    """GPU(cuML) 사용 가능 여부."""
    return _detect_gpu()["cuml"] is not None


def _to_numpy(arr):
    """cupy → numpy 변환 (이미 numpy 면 그대로)."""
    if hasattr(arr, "get"):
        try:
            return np.asarray(arr.get())
        except Exception:
            pass
    return np.asarray(arr)


def run_pca(X, n_components=2, random_state=42):
    """PCA 차원축소. GPU(cuml) 우선, CPU(sklearn) 폴백. 반환: (embedding, method명)."""
    X = np.asarray(X, dtype=np.float64)
    n_components = int(min(n_components, max(1, min(X.shape) - 1))) if min(X.shape) > 1 else 1
    st = _detect_gpu()
    if st["cuml"] is not None:
        try:
            from cuml.decomposition import PCA as cuPCA
            model = cuPCA(n_components=n_components)
            emb = model.fit_transform(st["cupy"].asarray(X))
            return _to_numpy(emb), "cuml.PCA"
        except Exception as e:
            logger.warning("cuml PCA failed, falling back to sklearn: %s", e)
    from sklearn.decomposition import PCA
    model = PCA(n_components=n_components, random_state=random_state)
    return model.fit_transform(X), "sklearn.PCA"


def run_umap(X, n_components=2, n_neighbors=15, random_state=42):
    """UMAP 차원축소. cuml.UMAP → umap-learn → PCA 자동 폴백. 반환: (embedding, method명)."""
    X = np.asarray(X, dtype=np.float64)
    st = _detect_gpu()
    if X.shape[0] > n_neighbors + 1:
        if st["cuml"] is not None:
            try:
                from cuml.manifold import UMAP as cuUMAP
                model = cuUMAP(n_components=n_components, n_neighbors=n_neighbors,
                               random_state=random_state)
                emb = model.fit_transform(st["cupy"].asarray(X))
                return _to_numpy(emb), "cuml.UMAP"
            except Exception as e:
                logger.warning("cuml UMAP failed: %s", e)
        try:
            import umap
            model = umap.UMAP(n_components=n_components, n_neighbors=n_neighbors,
                              random_state=random_state)
            return np.asarray(model.fit_transform(X)), "umap-learn"
        except Exception as e:
            logger.warning("umap-learn unavailable (%s); falling back to PCA", e)
    emb, method = run_pca(X, n_components=n_components, random_state=random_state)
    return emb, method + "(umap-fallback)"


def run_hdbscan(X, min_cluster_size=5):
    """HDBSCAN 클러스터링. cuml → hdbscan/sklearn → DBSCAN 폴백. 반환: (labels, method명)."""
    X = np.asarray(X, dtype=np.float64)
    st = _detect_gpu()
    if st["cuml"] is not None:
        try:
            from cuml.cluster import HDBSCAN as cuHDBSCAN
            model = cuHDBSCAN(min_cluster_size=min_cluster_size)
            labels = model.fit_predict(st["cupy"].asarray(X))
            return _to_numpy(labels).astype(int), "cuml.HDBSCAN"
        except Exception as e:
            logger.warning("cuml HDBSCAN failed: %s", e)
    try:
        try:
            from sklearn.cluster import HDBSCAN as skHDBSCAN  # sklearn >= 1.3
            model = skHDBSCAN(min_cluster_size=min_cluster_size)
        except ImportError:
            import hdbscan
            model = hdbscan.HDBSCAN(min_cluster_size=min_cluster_size)
        return np.asarray(model.fit_predict(X)).astype(int), "cpu.HDBSCAN"
    except Exception as e:
        logger.warning("HDBSCAN unavailable (%s); falling back to DBSCAN", e)
    from sklearn.cluster import DBSCAN
    # eps 휴리스틱: 좌표 스케일의 5%
    span = float(np.ptp(X)) if X.size else 1.0
    model = DBSCAN(eps=max(span * 0.05, 1e-6), min_samples=max(min_cluster_size // 2, 2))
    return model.fit_predict(X).astype(int), "sklearn.DBSCAN(fallback)"


def cosine_similarity_matrix(X, Y=None):
    """코사인 유사도 행렬. GPU(cupy) 우선, CPU(sklearn) 폴백. 반환: numpy 2D array."""
    X = np.asarray(X, dtype=np.float64)
    st = _detect_gpu()
    if st["cupy"] is not None:
        try:
            cp = st["cupy"]
            Xc = cp.asarray(X)
            Yc = Xc if Y is None else cp.asarray(np.asarray(Y, dtype=np.float64))
            Xn = Xc / (cp.linalg.norm(Xc, axis=1, keepdims=True) + 1e-12)
            Yn = Yc / (cp.linalg.norm(Yc, axis=1, keepdims=True) + 1e-12)
            return _to_numpy(Xn @ Yn.T)
        except Exception as e:
            logger.warning("cupy cosine similarity failed: %s", e)
    from sklearn.metrics.pairwise import cosine_similarity
    return cosine_similarity(X, Y if Y is not None else X)


# ===========================================================================
# src/cache.py
# ===========================================================================
# -*- coding: utf-8 -*-
"""
cache.py — 결과 캐싱 (필터 조합 기준 캐시 키) + 분석 실행 로그.

계산 논리:
- 캐시 키 = SHA1( dataset명 | 분석명 | 정렬된 필터 JSON | 정렬된 설정 JSON ).
- in-memory LRU(OrderedDict) + TTL. 전처리 DataFrame 캐시와 분석 결과(JSON) 캐시를
  분리하여, 필터가 같으면 전처리를 재사용하고 집계 결과도 재사용한다.
- Webapp backend 프로세스는 단일 프로세스이므로 thread lock 으로 보호한다.
- run_log: 최근 분석 실행 기록(분석명, 캐시 hit 여부, 소요시간, 행 수)을 보관하여
  /api/config 의 "분석 실행 로그" 기능에 제공한다.
"""
import hashlib
import json
import threading
import time
from collections import OrderedDict


def make_cache_key(*parts):
    """임의 객체들을 안정적인 문자열 키(SHA1)로 변환. dict 는 key 정렬 후 직렬화."""
    ser = []
    for p in parts:
        try:
            ser.append(json.dumps(p, sort_keys=True, ensure_ascii=False, default=str))
        except (TypeError, ValueError):
            ser.append(repr(p))
    return hashlib.sha1("|".join(ser).encode("utf-8")).hexdigest()


class LRUCache(object):
    """TTL 지원 in-memory LRU 캐시."""

    def __init__(self, max_items=64, ttl_seconds=1800):
        self.max_items = int(max_items)
        self.ttl = float(ttl_seconds)
        self._data = OrderedDict()  # key -> (expire_ts, value)
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            expire_ts, value = item
            if time.time() > expire_ts:
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return value

    def set(self, key, value):
        with self._lock:
            self._data[key] = (time.time() + self.ttl, value)
            self._data.move_to_end(key)
            while len(self._data) > self.max_items:
                self._data.popitem(last=False)

    def clear(self):
        with self._lock:
            self._data.clear()


# 전처리 DataFrame 캐시 (무겁고 수가 적음) / 분석 결과 캐시 (가볍고 수가 많음)
DF_CACHE = LRUCache(max_items=8, ttl_seconds=3600)
RESULT_CACHE = LRUCache(max_items=256, ttl_seconds=1800)

_RUN_LOG = []
_RUN_LOG_LOCK = threading.Lock()
_RUN_LOG_MAX = 200


def log_run(analysis, cache_hit, elapsed_ms, n_rows, status="ok"):
    """분석 실행 로그 기록 (최근 _RUN_LOG_MAX 건 유지)."""
    with _RUN_LOG_LOCK:
        _RUN_LOG.append({
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "analysis": analysis, "cache_hit": bool(cache_hit),
            "elapsed_ms": round(float(elapsed_ms), 1),
            "n_rows": int(n_rows) if n_rows is not None else None,
            "status": status,
        })
        del _RUN_LOG[:-_RUN_LOG_MAX]


def get_run_log(limit=50):
    with _RUN_LOG_LOCK:
        return list(_RUN_LOG[-int(limit):])[::-1]


def clear_all_caches():
    DF_CACHE.clear()
    RESULT_CACHE.clear()


def cached_analysis(analysis_name, key_parts, compute_fn):
    """분석 결과 캐시 래퍼.

    key_parts: 캐시 키 구성 요소 리스트 (dataset, 필터, 설정 등).
    compute_fn: () -> (result_dict, n_rows). 캐시 미스 시 호출.
    반환: result_dict (meta.cache_hit / meta.generated_at 을 주입).
    """
    key = make_cache_key(analysis_name, *key_parts)
    t0 = time.time()
    cached = RESULT_CACHE.get(key)
    if cached is not None:
        log_run(analysis_name, True, (time.time() - t0) * 1000.0,
                cached.get("meta", {}).get("n_rows"))
        out = dict(cached)
        meta = dict(out.get("meta", {}))
        meta["cache_hit"] = True
        out["meta"] = meta
        return out
    result, n_rows = compute_fn()
    meta = dict(result.get("meta", {}))
    meta.setdefault("generated_at", time.strftime("%Y-%m-%d %H:%M:%S"))
    meta["cache_hit"] = False
    meta["n_rows"] = int(n_rows) if n_rows is not None else None
    result["meta"] = meta
    if result.get("status") in ("ok", "empty", "disabled"):
        RESULT_CACHE.set(key, result)
    log_run(analysis_name, False, (time.time() - t0) * 1000.0, n_rows,
            status=result.get("status", "ok"))
    return result


# ===========================================================================
# src/column_mapping.py
# ===========================================================================
# -*- coding: utf-8 -*-
"""
column_mapping.py — 개념 컬럼 매핑 사전 + 자동 매핑 로직.

계산 논리:
1. CONCEPTS: 개념 컬럼별 정의(한글 라벨, 데이터 형식 설명, 헤더 변형 목록).
   변형 목록은 한글명·영문명·약어·WIPS 실제 헤더 변형을 포함한다.
2. 자동 추천 매핑 파이프라인 (suggest_mapping):
   a) 헤더 정규화: 소문자화, 공백/괄호/특수문자/개행 제거 → _norm()
   b) 사전 완전일치 (정규화된 변형 == 정규화된 실제 헤더)
   c) 사전 부분일치 (변형이 헤더에 포함 또는 그 반대, 길이>=2)
   d) difflib.SequenceMatcher 유사도 매칭 (임계값: THRESHOLDS.fuzzy_match_cutoff)
   각 실제 컬럼은 최대 1개 개념에만 배정한다 (신뢰도 높은 순서로 greedy).
3. 검증(validate_mapping): 분석별 필수 개념(ANALYSIS_REQUIREMENTS)과 매핑 상태를
   비교하여 활성/비활성 매트릭스를 생성한다.

예외처리: 실제 헤더가 비어있거나 중복이면 무시. 매핑 결과에 존재하지 않는 실제
컬럼이 있으면(데이터셋 교체 등) 해당 항목을 제거하고 warnings 에 기록.
"""
import difflib
import re


# ---------------------------------------------------------------------------
# 개념 컬럼 정의: key -> {label(한글), dtype(형식 안내), variants([헤더 변형...])}
# ---------------------------------------------------------------------------
CONCEPTS = {
    "pub_number": {
        "label": "공개번호", "dtype": "문자열 (예: KR10-2020-0001234A)",
        "variants": ["공개번호", "공개 번호", "공개(공고)번호", "공개공고번호", "publication number",
                     "pub number", "pub no", "pub_no", "pubno", "공보번호", "publication no",
                     "publn no", "공개번호(공개일)", "publication"],
    },
    "app_number": {
        "label": "출원번호", "dtype": "문자열 (예: KR10-2019-0123456)",
        "variants": ["출원번호", "출원 번호", "application number", "app number", "app no",
                     "appl no", "application no", "출원번호(출원일)", "filing number"],
    },
    "reg_number": {
        "label": "등록번호", "dtype": "문자열 (예: KR10-2345678)",
        "variants": ["등록번호", "등록 번호", "registration number", "reg number", "reg no",
                     "grant number", "patent number", "등록번호(등록일)", "특허번호"],
    },
    "family_id": {
        "label": "패밀리 ID", "dtype": "문자열 또는 숫자 (INPADOC/DOCDB 패밀리 식별자)",
        "variants": ["패밀리 id", "패밀리id", "패밀리 번호", "family id", "family_id", "famid",
                     "inpadoc family id", "docdb family id", "패밀리번호", "family no", "패밀리"],
    },
    "family_rep": {
        "label": "패밀리 대표문헌", "dtype": "문자열 (대표 공개/등록번호)",
        "variants": ["패밀리 대표문헌", "대표문헌", "대표 문헌", "family representative",
                     "representative document", "대표특허", "rep document", "대표문헌번호"],
    },
    "title": {
        "label": "발명의 명칭", "dtype": "문자열",
        "variants": ["발명의 명칭", "발명의명칭", "발명명칭", "명칭", "title", "invention title",
                     "발명의 명칭(국문)", "제목", "title of invention"],
    },
    "abstract": {
        "label": "요약", "dtype": "문자열 (요약문)",
        "variants": ["요약", "초록", "abstract", "요약문", "abstract text", "요약(국문)"],
    },
    "indep_claim": {
        "label": "독립청구항", "dtype": "문자열 (독립항 전문)",
        "variants": ["독립청구항", "독립 청구항", "대표청구항", "대표 청구항", "청구항 1",
                     "independent claim", "indep claim", "first claim", "claim 1", "청구항1",
                     "main claim", "representative claim"],
    },
    "claims": {
        "label": "전체 청구항", "dtype": "문자열 (청구항 전문)",
        "variants": ["전체 청구항", "청구항", "청구범위", "claims", "all claims", "claim text",
                     "청구항 전문", "claims text", "특허청구범위"],
    },
    "applicant": {
        "label": "출원인", "dtype": "문자열 (복수 시 구분자 포함)",
        "variants": ["출원인", "출원인명", "applicant", "applicants", "applicant name",
                     "출원인(국문)", "assignee applicant", "출원인 명칭"],
    },
    "applicant_std": {
        "label": "표준화 출원인", "dtype": "문자열 (정비된 대표 출원인명)",
        "variants": ["표준화 출원인", "표준 출원인", "대표 출원인", "출원인 대표명",
                     "standardized applicant", "normalized applicant", "std applicant",
                     "대표출원인", "출원인(정비)", "current assignee normalized", "출원인 그룹"],
    },
    "assignee": {
        "label": "현재 권리자", "dtype": "문자열",
        "variants": ["현재 권리자", "권리자", "현재권리자", "양수인", "assignee",
                     "current assignee", "owner", "patent owner", "right holder", "권리자명"],
    },
    "inventors": {
        "label": "발명자", "dtype": "문자열 (복수 시 구분자 포함)",
        "variants": ["발명자", "발명자명", "inventor", "inventors", "inventor name",
                     "발명자(국문)", "발명인"],
    },
    "app_date": {
        "label": "출원일", "dtype": "날짜 (YYYY-MM-DD 또는 YYYY.MM.DD)",
        "variants": ["출원일", "출원일자", "application date", "app date", "filing date",
                     "출원년월일", "filed date", "출원 일자"],
    },
    "pub_date": {
        "label": "공개일", "dtype": "날짜",
        "variants": ["공개일", "공개일자", "publication date", "pub date", "공개(공고)일",
                     "공개년월일", "공고일"],
    },
    "reg_date": {
        "label": "등록일", "dtype": "날짜",
        "variants": ["등록일", "등록일자", "registration date", "reg date", "grant date",
                     "등록년월일", "issue date"],
    },
    "priority_date": {
        "label": "우선일", "dtype": "날짜 (최우선일)",
        "variants": ["우선일", "우선권주장일", "최우선일", "priority date", "earliest priority",
                     "earliest priority date", "우선권 주장일", "최우선일자"],
    },
    "expiry_date": {
        "label": "만료예정일", "dtype": "날짜 (존속기간 만료 예정일)",
        "variants": ["만료예정일", "만료일", "존속기간 만료일", "존속기간만료일", "expiry date",
                     "expiration date", "expected expiry", "predicted expiry date", "만료 예정일"],
    },
    "country": {
        "label": "국가", "dtype": "문자열 (국가코드: KR/US/JP/CN/EP 등)",
        "variants": ["국가", "국가코드", "출원국", "출원국가", "country", "country code",
                     "jurisdiction", "office", "국가(코드)", "발행국"],
    },
    "legal_status": {
        "label": "법적상태", "dtype": "문자열 (등록/공개/거절/소멸 등)",
        "variants": ["법적상태", "법적 상태", "행정상태", "행정처분", "legal status", "status",
                     "current status", "법률상태", "법적상태정보"],
    },
    "is_granted": {
        "label": "등록 여부", "dtype": "불리언/문자열 (Y/N, True/False)",
        "variants": ["등록 여부", "등록여부", "granted", "is granted", "grant status",
                     "등록유무", "registered yn"],
    },
    "is_active": {
        "label": "존속 여부", "dtype": "불리언/문자열 (Y/N — 권리 유효 여부)",
        "variants": ["존속 여부", "존속여부", "유효 여부", "유효여부", "권리존속여부", "alive",
                     "is active", "active yn", "in force", "유효특허여부", "권리 존속 여부"],
    },
    "cites_backward": {
        "label": "인용 수", "dtype": "정수 (선행문헌 인용 수)",
        "variants": ["인용 수", "인용수", "인용문헌수", "인용 문헌 수", "backward citations",
                     "citing count", "cited references", "references cited", "인용특허수",
                     "backward citation count", "인용횟수"],
    },
    "cites_forward": {
        "label": "피인용 수", "dtype": "정수 (후행문헌에 의한 피인용 수)",
        "variants": ["피인용 수", "피인용수", "피인용횟수", "피인용 문헌 수", "forward citations",
                     "cited by count", "citation count", "forward citation count", "피인용특허수",
                     "cited by"],
    },
    "family_size": {
        "label": "패밀리 수", "dtype": "정수 (패밀리 문헌 수)",
        "variants": ["패밀리 수", "패밀리수", "패밀리 문헌 수", "family size", "family count",
                     "패밀리문헌수", "simple family size", "extended family size"],
    },
    "family_country_count": {
        "label": "패밀리 국가 수", "dtype": "정수",
        "variants": ["패밀리 국가 수", "패밀리 국가수", "패밀리국가수", "family country count",
                     "family countries", "지정국 수", "출원국 수", "국가 수"],
    },
    "tech_l1": {
        "label": "기술 대분류", "dtype": "문자열",
        "variants": ["기술 대분류", "대분류", "기술대분류", "tech l1", "level1", "level 1",
                     "category l1", "main category", "대분류명", "기술분류(대)", "1차분류"],
    },
    "tech_l2": {
        "label": "기술 중분류", "dtype": "문자열",
        "variants": ["기술 중분류", "중분류", "기술중분류", "tech l2", "level2", "level 2",
                     "category l2", "sub category", "중분류명", "기술분류(중)", "2차분류"],
    },
    "tech_l3": {
        "label": "기술 소분류", "dtype": "문자열",
        "variants": ["기술 소분류", "소분류", "기술소분류", "tech l3", "level3", "level 3",
                     "category l3", "detail category", "소분류명", "기술분류(소)", "3차분류"],
    },
    "tech_multi": {
        "label": "다중 기술분류", "dtype": "문자열 (쉼표/세미콜론/파이프/JSON 배열)",
        "variants": ["다중 기술분류", "다중분류", "복수 기술분류", "기술분류(전체)", "multi class",
                     "multi classification", "all classifications", "기술분류 목록", "복수분류",
                     "multiple categories", "다중기술분류"],
    },
    "class_confidence": {
        "label": "분류 신뢰도", "dtype": "실수 0~1",
        "variants": ["분류 신뢰도", "분류신뢰도", "신뢰도", "classification confidence",
                     "confidence", "confidence score", "class confidence", "분류 확신도"],
    },
    "problem": {
        "label": "해결과제", "dtype": "문자열",
        "variants": ["해결과제", "해결 과제", "과제", "기술적 과제", "problem", "technical problem",
                     "problem to solve", "해결하려는 과제", "발명의 과제"],
    },
    "solution": {
        "label": "해결수단", "dtype": "문자열",
        "variants": ["해결수단", "해결 수단", "수단", "과제 해결 수단", "solution",
                     "solution means", "technical solution", "과제해결수단"],
    },
    "product": {
        "label": "제품", "dtype": "문자열 (적용 제품)",
        "variants": ["제품", "적용제품", "적용 제품", "product", "products", "target product",
                     "응용제품"],
    },
    "process": {
        "label": "공정", "dtype": "문자열",
        "variants": ["공정", "제조공정", "제조 공정", "process", "manufacturing process", "공법"],
    },
    "material": {
        "label": "소재", "dtype": "문자열",
        "variants": ["소재", "재료", "material", "materials", "원재료", "소재/재료"],
    },
    "structure": {
        "label": "구조", "dtype": "문자열",
        "variants": ["구조", "structure", "구조/형상", "형상", "구성"],
    },
    "effect": {
        "label": "효과", "dtype": "문자열",
        "variants": ["효과", "발명의 효과", "effect", "effects", "기대효과", "기술적 효과"],
    },
    "embedding": {
        "label": "임베딩 벡터", "dtype": "문자열(JSON 배열) 또는 숫자 배열",
        "variants": ["임베딩 벡터", "임베딩", "embedding", "embedding vector", "vector",
                     "text embedding", "임베딩벡터", "doc vector", "문서벡터"],
    },
    "is_own": {
        "label": "자사 특허 여부", "dtype": "불리언/문자열 (Y/N)",
        "variants": ["자사 특허 여부", "자사특허여부", "자사 여부", "자사여부", "own patent",
                     "is own", "our patent", "당사 특허", "자사구분", "in-house"],
    },
}

CONCEPT_KEYS = list(CONCEPTS.keys())

# ---------------------------------------------------------------------------
# 분석별 필수/선택 개념 컬럼 (활성/비활성 매트릭스의 근거)
# 기술분류는 tech_l1/l2/l3/tech_multi 중 하나라도 있으면 되는 경우
# "any:" 그룹으로 표기한다.
# ---------------------------------------------------------------------------
ANY_TECH = ["tech_l1", "tech_l2", "tech_l3", "tech_multi"]
ANY_APPLICANT = ["applicant_std", "applicant"]
ANY_DATE = ["app_date", "priority_date", "pub_date"]

ANALYSIS_REQUIREMENTS = {
    "overview":              {"required": [{"any": ANY_TECH}, {"any": ANY_DATE}], "optional": ANY_APPLICANT + ["legal_status", "country"]},
    "technology-network":    {"required": [{"any": ANY_TECH}], "optional": ["family_id", "app_date"] + ANY_APPLICANT},
    "emerging-combinations": {"required": [{"any": ANY_TECH}, {"any": ANY_DATE}], "optional": ANY_APPLICANT + ["is_active", "legal_status"]},
    "lifecycle":             {"required": [{"any": ANY_TECH}, {"any": ANY_DATE}], "optional": ANY_APPLICANT + ["is_active", "legal_status", "cites_forward"]},
    "opportunity":           {"required": [{"any": ANY_TECH}, {"any": ANY_DATE}], "optional": ANY_APPLICANT + ["legal_status", "is_active", "problem", "product", "process", "family_country_count", "expiry_date", "is_own"]},
    "problem-solution":      {"required": ["problem", "solution"], "optional": [{"any": ANY_DATE}] + ANY_APPLICANT + ["indep_claim", "is_active", "legal_status"]},
    "technology-transition": {"required": [{"any": ANY_TECH}, {"any": ANY_DATE}], "optional": ["family_id"] + ANY_APPLICANT},
    "trajectory":            {"required": [{"any": ANY_TECH}, {"any": ANY_DATE}, {"any": ANY_APPLICANT}], "optional": ["family_id", "is_active"]},
    "company-dna":           {"required": [{"any": ANY_TECH}, {"any": ANY_DATE}, {"any": ANY_APPLICANT}], "optional": ["family_size", "family_country_count", "cites_forward", "legal_status", "inventors", "family_id"]},
    "lead-lag":              {"required": [{"any": ANY_TECH}, {"any": ANY_DATE}, {"any": ANY_APPLICANT}], "optional": []},
    "claim-density":         {"required": ["indep_claim", {"any": ANY_TECH}], "optional": ["embedding", "legal_status", "expiry_date", "family_id", "cites_forward"] + ANY_APPLICANT},
    "citation-diffusion":    {"required": ["cites_forward", {"any": ANY_TECH}], "optional": ["cites_backward", "family_size", "family_country_count", "legal_status", "expiry_date"] + ANY_APPLICANT},
    "inventor-mobility":     {"required": ["inventors", {"any": ANY_APPLICANT}, {"any": ANY_DATE}], "optional": [{"any": ANY_TECH}, "country"]},
    "classification-quality": {"required": [{"any": ANY_TECH}], "optional": ["embedding", "class_confidence", "title", "abstract", {"any": ANY_DATE}]},
}

_NORM_RE = re.compile(r"[\s\(\)\[\]\{\}\-_/\\.,:;'\"·|]+")


def _norm(s):
    """헤더 정규화: 소문자화 + 공백/특수문자 제거."""
    if s is None:
        return ""
    return _NORM_RE.sub("", str(s).strip().lower())


def suggest_mapping(actual_columns, cutoff=None):
    """실제 컬럼 목록 → {concept: {column, method, score}} 자동 추천 매핑.

    매칭 순서: 완전일치(1.0) → 부분일치(0.85) → difflib 유사도(cutoff 이상).
    하나의 실제 컬럼은 하나의 개념에만 배정 (점수 높은 순 greedy).
    """
    if cutoff is None:
        cutoff = THRESHOLDS["fuzzy_match_cutoff"]
    cols = [c for c in actual_columns if c is not None and str(c).strip() != ""]
    norm_cols = {c: _norm(c) for c in cols}

    candidates = []  # (score, concept, column, method)
    for concept, spec in CONCEPTS.items():
        norm_variants = [_norm(v) for v in spec["variants"]]
        for col, ncol in norm_cols.items():
            if not ncol:
                continue
            best = None
            if ncol in norm_variants:
                best = (1.0, "exact")
            else:
                for nv in norm_variants:
                    if len(nv) >= 2 and (nv in ncol or ncol in nv):
                        best = (0.85, "partial")
                        break
                if best is None:
                    ratio = max(
                        (difflib.SequenceMatcher(None, ncol, nv).ratio() for nv in norm_variants),
                        default=0.0)
                    if ratio >= cutoff:
                        best = (round(ratio, 3), "fuzzy")
            if best:
                candidates.append((best[0], concept, col, best[1]))

    candidates.sort(key=lambda t: (-t[0], t[1], t[2]))
    mapping, used_cols, used_concepts = {}, set(), set()
    for score, concept, col, method in candidates:
        if concept in used_concepts or col in used_cols:
            continue
        mapping[concept] = {"column": col, "method": method, "score": score}
        used_concepts.add(concept)
        used_cols.add(col)
    return mapping


def clean_mapping(mapping, actual_columns):
    """저장된 매핑에서 실제 존재하지 않는 컬럼 항목 제거. 반환: (clean, warnings)."""
    actual = set(actual_columns or [])
    clean, warnings = {}, []
    for concept, col in (mapping or {}).items():
        if concept not in CONCEPTS:
            warnings.append("알 수 없는 개념 컬럼 매핑 무시: %s" % concept)
            continue
        if col and col in actual:
            clean[concept] = col
        elif col:
            warnings.append("매핑된 컬럼이 데이터셋에 없어 제외: %s → %s" % (CONCEPTS[concept]["label"], col))
    return clean, warnings


def _requirement_met(req, mapped_concepts):
    """단일 필수 항목 충족 여부. req 는 개념 key 문자열 또는 {"any": [keys]}."""
    if isinstance(req, dict) and "any" in req:
        return any(k in mapped_concepts for k in req["any"])
    return req in mapped_concepts


def _requirement_label(req):
    if isinstance(req, dict) and "any" in req:
        return " 또는 ".join(CONCEPTS[k]["label"] for k in req["any"])
    return CONCEPTS[req]["label"]


def analysis_availability(mapping):
    """분석별 사용 가능 여부 매트릭스.

    mapping: {concept: actual_column} (단순 dict).
    반환: {analysis: {available, missing: [필수 라벨...], optional_missing: [...]}}
    """
    mapped = set(k for k, v in (mapping or {}).items() if v)
    out = {}
    for analysis, spec in ANALYSIS_REQUIREMENTS.items():
        missing = [_requirement_label(r) for r in spec["required"]
                   if not _requirement_met(r, mapped)]
        opt_missing = [_requirement_label(r) for r in spec.get("optional", [])
                       if not _requirement_met(r, mapped)]
        out[analysis] = {
            "available": len(missing) == 0,
            "missing": missing,
            "optional_missing": opt_missing,
            "required": [_requirement_label(r) for r in spec["required"]],
        }
    return out


def concept_catalog():
    """컬럼 매핑 화면용 개념 컬럼 카탈로그 (key, 라벨, 형식)."""
    return [{"key": k, "label": v["label"], "dtype": v["dtype"]} for k, v in CONCEPTS.items()]


# ===========================================================================
# src/preprocessing.py
# ===========================================================================
# -*- coding: utf-8 -*-
"""
preprocessing.py — 데이터 전처리 모듈.

담당 기능:
1. 개념 컬럼명으로 rename 된 표준 DataFrame 생성 (build_standard_frame)
2. 날짜 파싱(다양한 형식) → *_year 파생, 불리언 파싱(Y/N/True/1 등)
3. 다중 기술분류 파싱: 쉼표/세미콜론/파이프/JSON 배열/복수 컬럼 지원 (parse_multiclass)
4. 법적상태 정규화: 원본값 보존(legal_status_raw) + 정규화값(legal_status_norm)
5. 출원인 표준화: 대소문자·법인 접미사·괄호·특수문자 정리 + 사용자 매핑/그룹 규칙 적용
   (자동 표준화 결과는 확정값이 아니라 사용자 검토 대상 — applicant_auto_std 로 분리)
6. 패밀리 dedup: 대표문헌 선정 우선순위
   ① 유효 등록특허 → ② 가장 이른 우선일 → ③ 서지·청구항 완전성 → ④ 지정국 우선순위
   → ⑤ 공개번호 정렬
7. 공통 필터 적용 (apply_filters): 기간/출원인/기술분류/국가/법적상태/유효특허
8. 다중분류 집계용 explode (explode_tech): duplicate / fractional / primary / level_separate

예외처리: 결측 컬럼은 건너뛰고 존재하는 컬럼만 처리. 파싱 실패 값은 NaN/원본 유지.
분석값을 임의로 생성하지 않는다.
"""
import json
import re

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# 기본 파서
# ---------------------------------------------------------------------------
_TRUE_TOKENS = frozenset(["y", "yes", "true", "1", "o", "유", "예", "등록", "유효", "존속", "active", "t"])
_FALSE_TOKENS = frozenset(["n", "no", "false", "0", "x", "무", "아니오", "미등록", "무효", "소멸", "inactive", "f"])


def parse_bool(value):
    """Y/N·True/False·1/0·유/무 등 다양한 불리언 표기 파싱. 불명확하면 None."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer, float, np.floating)):
        return bool(int(value))
    s = str(value).strip().lower()
    if s in _TRUE_TOKENS:
        return True
    if s in _FALSE_TOKENS:
        return False
    return None


def parse_dates(series):
    """날짜 시리즈 파싱: pandas 추론 + YYYYMMDD/YYYY.MM.DD 보정. 실패값은 NaT."""
    if series is None:
        return None
    s = series.astype(str).str.strip().replace({"": None, "nan": None, "None": None, "NaT": None})
    s = s.str.replace(r"[./]", "-", regex=True)
    out = pd.to_datetime(s, errors="coerce", format="mixed")
    # 8자리 숫자(YYYYMMDD) 재시도
    mask = out.isna() & s.notna() & s.str.fullmatch(r"\d{8}", na=False)
    if mask.any():
        out.loc[mask] = pd.to_datetime(s[mask], format="%Y%m%d", errors="coerce")
    return out


_EMB_SPLIT_RE = re.compile(r"[,\s]+")


def parse_embedding(value):
    """임베딩 셀 파싱: JSON 배열 / 공백·쉼표 구분 숫자 문자열 / list → np.array. 실패 시 None."""
    if value is None:
        return None
    if isinstance(value, (list, tuple, np.ndarray)):
        arr = np.asarray(value, dtype=np.float64)
        return arr if arr.size else None
    if isinstance(value, float) and np.isnan(value):
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        if s.startswith("["):
            return np.asarray(json.loads(s), dtype=np.float64)
        parts = [p for p in _EMB_SPLIT_RE.split(s) if p]
        return np.asarray([float(p) for p in parts], dtype=np.float64)
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


# ---------------------------------------------------------------------------
# 다중 기술분류 파싱
# ---------------------------------------------------------------------------
def parse_multiclass_cell(value):
    """단일 셀의 다중 기술분류 파싱.

    지원 형식: JSON 배열('["A","B"]') / 쉼표 / 세미콜론 / 파이프(|).
    반환: 중복 제거·순서 유지 리스트 (없으면 []).
    """
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return []
    if isinstance(value, (list, tuple)):
        items = [str(v).strip() for v in value]
    else:
        s = str(value).strip()
        if not s or s.lower() in ("nan", "none"):
            return []
        items = None
        if s.startswith("["):
            try:
                loaded = json.loads(s)
                if isinstance(loaded, list):
                    items = [str(v).strip() for v in loaded]
            except (ValueError, json.JSONDecodeError):
                items = None
        if items is None:
            for sep in ("|", ";", ","):
                if sep in s:
                    items = [p.strip() for p in s.split(sep)]
                    break
            else:
                items = [s]
    seen, out = set(), []
    for it in items:
        if it and it.lower() not in ("nan", "none") and it not in seen:
            seen.add(it)
            out.append(it)
    return out


def build_tech_lists(df):
    """행별 기술분류 리스트 컬럼(_tech_list) 생성.

    우선순위: tech_multi(다중 기술분류) → tech_l3 → tech_l2 → tech_l1.
    복수의 기술분류 컬럼(tech_l1/l2/l3 각각 다중값 포함 가능)도 지원:
    각 레벨의 파싱 결과를 _tech_l1_list/_tech_l2_list/_tech_l3_list 로도 보관한다.
    """
    for level in ("tech_l1", "tech_l2", "tech_l3"):
        if level in df.columns:
            df["_%s_list" % level] = df[level].map(parse_multiclass_cell)
    if "tech_multi" in df.columns:
        df["_tech_list"] = df["tech_multi"].map(parse_multiclass_cell)
        # tech_multi 가 전부 비어있으면 레벨 컬럼으로 폴백
        if not df["_tech_list"].map(len).any():
            df = _tech_list_from_levels(df)
    else:
        df = _tech_list_from_levels(df)
    if "_tech_list" not in df.columns:
        df["_tech_list"] = [[] for _ in range(len(df))]
    return df


def _tech_list_from_levels(df):
    """레벨 컬럼(소→중→대 우선)으로 _tech_list 구성."""
    for level in ("_tech_l3_list", "_tech_l2_list", "_tech_l1_list"):
        if level in df.columns and df[level].map(len).any():
            df["_tech_list"] = df[level]
            return df
    df["_tech_list"] = [[] for _ in range(len(df))]
    return df


def build_l1_lookup(df):
    """소/중분류 → 대분류 매핑 dict (색상 그룹용). 다중값은 첫 대응 대분류 사용."""
    lookup = {}
    if "_tech_l1_list" not in df.columns:
        return lookup
    for child_col in ("_tech_l3_list", "_tech_l2_list"):
        if child_col not in df.columns:
            continue
        for childs, l1s in zip(df[child_col], df["_tech_l1_list"]):
            if not childs or not l1s:
                continue
            for c in childs:
                if c not in lookup:
                    lookup[c] = l1s[0]
    for l1s in df["_tech_l1_list"]:
        for v in (l1s or []):
            lookup.setdefault(v, v)
    return lookup


# ---------------------------------------------------------------------------
# 법적상태 정규화
# ---------------------------------------------------------------------------
def normalize_legal_status(value):
    """법적상태 원본값 → 표준 카테고리. 매칭 실패·결측 시 'Unknown'."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "Unknown"
    s = str(value).strip().lower()
    if not s or s in ("nan", "none"):
        return "Unknown"
    for pattern, category in LEGAL_STATUS_PATTERNS:
        if pattern in s:
            return category
    return "Unknown"


def derive_active_flag(row):
    """유효특허 여부 파생: is_active 컬럼 → 법적상태 → 등록여부+만료일 순으로 판단.

    판단 불가 시 None (임의 생성 금지 — 분석에서는 'Unknown' 취급).
    """
    v = row.get("_is_active_bool")
    if v is not None:
        return v
    status = row.get("legal_status_norm")
    if status and status != "Unknown":
        return status in ACTIVE_LEGAL_STATUSES
    return None


# ---------------------------------------------------------------------------
# 출원인 표준화
# ---------------------------------------------------------------------------
_CORP_SUFFIXES = [
    "co., ltd.", "co.,ltd.", "co., ltd", "co.,ltd", "co. ltd", "co ltd", "company limited",
    "corporation", "incorporated", "corp.", "corp", "inc.", "inc", "ltd.", "ltd", "llc",
    "l.l.c.", "gmbh & co. kg", "gmbh", "ag", "s.a.", "sa", "s.p.a.", "spa", "b.v.", "bv",
    "n.v.", "nv", "k.k.", "kk", "kabushiki kaisha", "co", "limited", "plc",
    "주식회사", "(주)", "㈜", "유한회사", "유한책임회사", "합자회사", "재단법인", "사단법인", "학교법인",
    "국립대학법인", "주)",
]
_PAREN_RE = re.compile(r"[\(\)\[\]\{\}（）]")
_MULTISPACE_RE = re.compile(r"\s+")
_SPECIAL_RE = re.compile(r"[\"'`!@#$%^*+=~?<>]")


def auto_standardize_name(name):
    """출원인/권리자명 자동 표준화(검토 대상 후보값).

    규칙: 트림 → 괄호류 제거 → 특수문자 제거 → 법인 접미사 제거(반복) → 공백 정리 →
    영문은 대문자 통일. 결과가 비면 원본 트림값 유지.
    """
    if name is None or (isinstance(name, float) and np.isnan(name)):
        return ""
    s = str(name).strip()
    if not s or s.lower() in ("nan", "none"):
        return ""
    original = s
    for marker in ("(주)", "㈜", "（주）", "주식회사", "(유)", "(재)", "(사)", "(학)"):
        s = s.replace(marker, " ")
    s = _PAREN_RE.sub(" ", s)
    s = _SPECIAL_RE.sub(" ", s)
    s = _MULTISPACE_RE.sub(" ", s).strip()
    changed = True
    while changed and s:
        changed = False
        low = s.lower()
        for suf in _CORP_SUFFIXES:
            if low.endswith(" " + suf) or low == suf or low.endswith(suf):
                cut = len(s) - len(suf)
                trimmed = s[:cut].strip(" ,.-·")
                if trimmed:
                    s = trimmed
                    changed = True
                    break
        low2 = s.lower()
        for pre in ("주식회사 ", "(주)", "㈜", "유한회사 "):
            if low2.startswith(pre.lower()):
                trimmed = s[len(pre):].strip(" ,.-·")
                if trimmed:
                    s = trimmed
                    changed = True
                break
    s = _MULTISPACE_RE.sub(" ", s).strip()
    if not s:
        return original
    if re.fullmatch(r"[\x00-\x7F]+", s):
        s = s.upper()
    return s


def split_names(value):
    """출원인/발명자 셀에서 복수 이름 분리 (세미콜론/파이프/쉼표+공백)."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return []
    s = str(value).strip()
    if not s or s.lower() in ("nan", "none"):
        return []
    for sep in ("|", ";", "\n"):
        if sep in s:
            return [p.strip() for p in s.split(sep) if p.strip()]
    # 쉼표는 "성, 이름" 오분리 위험이 있어 ', ' + 대문자/한글 시작 패턴만 분리
    if ", " in s and len(s.split(", ")) > 1 and all(len(p.strip()) > 1 for p in s.split(", ")):
        return [p.strip() for p in s.split(", ") if p.strip()]
    return [s]


def standardize_applicants(df, applicant_rules=None):
    """출원인 표준화 컬럼 생성.

    applicant_rules: storage 에 저장된 사용자 규칙
      {"mapping": {원본명: 표준명}, "groups": {구성사 표준명: 그룹 대표명}}
    생성 컬럼:
      applicant_display : 분석에 사용하는 최종 표준명
        (우선순위: 사용자 mapping > 데이터의 표준화 출원인 컬럼 > 자동 표준화)
      applicant_auto_std: 자동 표준화 후보값 (사용자 검토·승인 대상)
      applicant_raw     : 원본 첫 출원인 (복원용)
    """
    rules = applicant_rules or {}
    user_map = {str(k).strip(): v for k, v in (rules.get("mapping") or {}).items()}
    groups = {str(k).strip(): v for k, v in (rules.get("groups") or {}).items()}

    if "applicant" in df.columns:
        raw_first = df["applicant"].map(lambda v: (split_names(v) or [""])[0])
    elif "applicant_std" in df.columns:
        raw_first = df["applicant_std"].map(lambda v: (split_names(v) or [""])[0])
    else:
        df["applicant_raw"] = ""
        df["applicant_auto_std"] = ""
        df["applicant_display"] = ""
        return df

    df["applicant_raw"] = raw_first
    df["applicant_auto_std"] = raw_first.map(auto_standardize_name)

    if "applicant_std" in df.columns:
        provided = df["applicant_std"].map(
            lambda v: (split_names(v) or [""])[0]).map(
            lambda s: auto_standardize_name(s) if s else "")
    else:
        provided = pd.Series([""] * len(df), index=df.index)

    def _final(raw, prov, auto):
        name = user_map.get(raw) or user_map.get(prov) or user_map.get(auto)
        if not name:
            name = prov or auto or raw
        return groups.get(name, name)

    df["applicant_display"] = [
        _final(r, p, a) for r, p, a in zip(df["applicant_raw"], provided, df["applicant_auto_std"])]
    df["_co_applicants"] = (df["applicant"].map(split_names)
                            if "applicant" in df.columns else [[] for _ in range(len(df))])
    return df


# ---------------------------------------------------------------------------
# 표준 프레임 생성
# ---------------------------------------------------------------------------
def build_standard_frame(raw_df, mapping, applicant_rules=None):
    """원본 DataFrame + 매핑 → 표준 개념 컬럼 DataFrame.

    - 매핑된 컬럼만 유지·rename (필요 컬럼 최소화)
    - 날짜/불리언/다중분류/법적상태/출원인 표준화 파생 컬럼 생성
    - _base_year: 출원일 → 우선일 → 공개일 순의 대표 연도
    """
    cols = {concept: col for concept, col in (mapping or {}).items()
            if col and col in raw_df.columns}
    df = raw_df[list(dict.fromkeys(cols.values()))].copy()
    df.columns = [c for c in df.columns]  # 유지
    rename = {}
    for concept, col in cols.items():
        if col not in rename.values():
            rename[col] = concept
    df = df.rename(columns=rename)
    # 동일 실제 컬럼이 두 개념에 매핑될 수는 없음(automap 이 보장) — 방어적으로 중복 제거
    df = df.loc[:, ~df.columns.duplicated()]

    for date_col in ("app_date", "pub_date", "reg_date", "priority_date", "expiry_date"):
        if date_col in df.columns:
            df[date_col] = parse_dates(df[date_col])
            df[date_col + "_year"] = df[date_col].dt.year

    base_year = pd.Series([np.nan] * len(df), index=df.index, dtype="float64")
    for date_col in ("app_date_year", "priority_date_year", "pub_date_year"):
        if date_col in df.columns:
            base_year = base_year.fillna(df[date_col])
    df["_base_year"] = base_year

    if "legal_status" in df.columns:
        df["legal_status_raw"] = df["legal_status"]
        df["legal_status_norm"] = df["legal_status"].map(normalize_legal_status)
    else:
        df["legal_status_raw"] = None
        df["legal_status_norm"] = "Unknown"

    def _obj_bool(values):
        """numpy bool → python bool 로 통일한 object 시리즈 (`v is True` 판정 안정화)."""
        return pd.Series([(bool(v) if isinstance(v, (bool, np.bool_)) else None)
                          for v in values], index=df.index, dtype=object)

    for bool_col, target in (("is_granted", "_is_granted_bool"), ("is_active", "_is_active_bool"),
                             ("is_own", "_is_own_bool")):
        df[target] = _obj_bool(df[bool_col].map(parse_bool)) if bool_col in df.columns \
            else pd.Series([None] * len(df), index=df.index, dtype=object)

    # 등록여부 폴백: 등록번호 존재 → 법적상태 순
    if all(v is None for v in df["_is_granted_bool"]):
        granted = pd.Series([None] * len(df), index=df.index, dtype=object)
        if "reg_number" in df.columns:
            granted = df["reg_number"].map(
                lambda v: True if (v is not None and str(v).strip() not in ("", "nan", "None")) else None)
        from_status = df["legal_status_norm"].map(
            lambda s: True if s in ("Granted-Active", "Granted-Expired")
            else (False if s in ("Pending", "Rejected", "Withdrawn") else None))
        df["_is_granted_bool"] = _obj_bool(
            [g if g is not None else f for g, f in zip(granted, from_status)])

    # 유효특허 플래그: is_active 컬럼 → 법적상태 순 (판단 불가 시 None)
    df["_active_flag"] = _obj_bool([
        (a if a is not None else
         ((s in ACTIVE_LEGAL_STATUSES) if (s and s != "Unknown") else None))
        for a, s in zip(df["_is_active_bool"], df["legal_status_norm"])])

    df = build_tech_lists(df)
    df = standardize_applicants(df, applicant_rules)

    for num_col in ("cites_backward", "cites_forward", "family_size",
                    "family_country_count", "class_confidence"):
        if num_col in df.columns:
            df[num_col] = pd.to_numeric(df[num_col], errors="coerce")

    if "inventors" in df.columns:
        df["_inventor_list"] = df["inventors"].map(split_names)

    if "embedding" in df.columns:
        df["_embedding"] = df["embedding"].map(parse_embedding)

    return df


# ---------------------------------------------------------------------------
# 패밀리 dedup
# ---------------------------------------------------------------------------
def _completeness_score(row, text_cols):
    """서지·청구항 완전성 점수: 존재하는 텍스트 컬럼 값 길이 합 (③ 기준)."""
    score = 0
    for c in text_cols:
        v = row.get(c)
        if v is not None and not (isinstance(v, float) and np.isnan(v)):
            score += min(len(str(v)), 2000)
    return score


COUNTRY_PRIORITY = {"US": 0, "EP": 1, "KR": 2, "JP": 3, "CN": 4, "WO": 5}


def dedupe_families(df):
    """패밀리 단위 dedup: 패밀리별 대표문헌 1건 선택.

    우선순위: ① 유효 등록특허(_active_flag & _is_granted_bool)
             → ② 가장 이른 우선일(없으면 출원일)
             → ③ 서지·청구항 완전성(제목+요약+독립청구항+청구항 길이)
             → ④ 지정국 우선순위(US>EP>KR>JP>CN>WO>기타)
             → ⑤ 공개번호 오름차순.
    family_id 가 없으면 dedup 하지 않고 원본 반환 (분석단위 안내는 API 계층 담당).
    패밀리 대표문헌 컬럼(family_rep)이 있으면 대표문헌 == 공개번호 행을 최우선 선택.
    """
    if "family_id" not in df.columns or df["family_id"].isna().all():
        return df
    text_cols = [c for c in ("title", "abstract", "indep_claim", "claims") if c in df.columns]

    work = df.copy()
    fam = work["family_id"].astype(str).str.strip()
    no_fam = fam.isin(["", "nan", "None"]) | work["family_id"].isna()
    work["_fam_key"] = fam.where(~no_fam, other=["__solo_%d" % i for i in range(len(work))])

    # 정렬 점수 계산 (낮을수록 우선)
    active = work["_active_flag"].map(lambda v: 0 if v else 1)
    granted = work["_is_granted_bool"].map(lambda v: 0 if v else 1)
    rep_match = pd.Series([1] * len(work), index=work.index)
    if "family_rep" in work.columns and "pub_number" in work.columns:
        rep_match = (work["family_rep"].astype(str).str.strip()
                     == work["pub_number"].astype(str).str.strip()).map(lambda b: 0 if b else 1)
    prio_date = work["priority_date"] if "priority_date" in work.columns else None
    if prio_date is None or prio_date.isna().all():
        prio_date = work["app_date"] if "app_date" in work.columns else pd.Series(
            [pd.NaT] * len(work), index=work.index)
    completeness = work.apply(lambda r: -_completeness_score(r, text_cols), axis=1) if text_cols \
        else pd.Series([0] * len(work), index=work.index)
    country_rank = (work["country"].astype(str).str.strip().str.upper().map(
        lambda c: COUNTRY_PRIORITY.get(c, 9)) if "country" in work.columns
        else pd.Series([9] * len(work), index=work.index))
    pub_no = (work["pub_number"].astype(str) if "pub_number" in work.columns
              else pd.Series([""] * len(work), index=work.index))

    work["_sort_rep"] = rep_match
    work["_sort_active_granted"] = active + granted
    work["_sort_prio"] = prio_date.fillna(pd.Timestamp("2262-01-01"))
    work["_sort_completeness"] = completeness
    work["_sort_country"] = country_rank
    work["_sort_pub"] = pub_no
    work = work.sort_values(
        ["_fam_key", "_sort_rep", "_sort_active_granted", "_sort_prio",
         "_sort_completeness", "_sort_country", "_sort_pub"])
    deduped = work.drop_duplicates(subset="_fam_key", keep="first")
    deduped = deduped.drop(columns=[c for c in deduped.columns if c.startswith("_sort_")])
    return deduped.drop(columns=["_fam_key"])


def apply_analysis_unit(df, unit):
    """분석 단위 적용: family=패밀리 dedup / registration=등록건만 / 그 외 원본."""
    if unit == "family":
        return dedupe_families(df)
    if unit == "registration":
        mask = df["_is_granted_bool"].map(lambda v: v is True)
        sub = df[mask]
        return sub if len(sub) else df.iloc[0:0]
    return df  # publication / application: 문헌 단위 그대로


# ---------------------------------------------------------------------------
# 공통 필터
# ---------------------------------------------------------------------------
def apply_filters(df, filters):
    """공통 필터 적용.

    filters 예:
      {"year_from": 2015, "year_to": 2024, "applicants": [...], "countries": [...],
       "legal_statuses": [...(정규화값)...], "tech_l1": [...], "tech_l2": [...],
       "tech_l3": [...], "tech": [...(=_tech_list 항목)...], "active_only": true}
    존재하지 않는 컬럼 관련 필터는 무시 (graceful degradation).
    """
    f = filters or {}
    mask = pd.Series(True, index=df.index)

    yf, yt = f.get("year_from"), f.get("year_to")
    if yf not in (None, "") or yt not in (None, ""):
        years = df["_base_year"]
        if yf not in (None, ""):
            mask &= years.notna() & (years >= float(yf))
        if yt not in (None, ""):
            mask &= years.notna() & (years <= float(yt))

    if f.get("applicants"):
        wanted = set(map(str, f["applicants"]))
        mask &= df["applicant_display"].astype(str).isin(wanted)

    if f.get("countries") and "country" in df.columns:
        wanted = set(str(c).strip().upper() for c in f["countries"])
        mask &= df["country"].astype(str).str.strip().str.upper().isin(wanted)

    if f.get("legal_statuses"):
        wanted = set(map(str, f["legal_statuses"]))
        mask &= df["legal_status_norm"].isin(wanted)

    for level, col in (("tech_l1", "_tech_l1_list"), ("tech_l2", "_tech_l2_list"),
                       ("tech_l3", "_tech_l3_list")):
        if f.get(level) and col in df.columns:
            wanted = set(map(str, f[level]))
            mask &= df[col].map(lambda lst: bool(set(lst or []) & wanted))

    if f.get("tech"):
        wanted = set(map(str, f["tech"]))
        mask &= df["_tech_list"].map(lambda lst: bool(set(lst or []) & wanted))

    if f.get("active_only"):
        mask &= df["_active_flag"].map(lambda v: v is True)

    return df[mask]


# ---------------------------------------------------------------------------
# 다중분류 explode
# ---------------------------------------------------------------------------
def explode_tech(df, mode=None, level=None):
    """행×기술분류 long-format 변환.

    mode:
      duplicate     — 각 기술분류에 1건씩 중복 계산 (weight=1)
      fractional    — 1/N 가중치 배분 (weight=1/분류수)
      primary       — 대표(첫) 기술분류만 사용 (weight=1)
      level_separate— level 인자('l1'|'l2'|'l3')의 분류 리스트 사용
    반환: 원본 컬럼 + [tech, weight]. 기술분류 없는 행은 제외.
    """
    mode = mode or DEFAULT_MULTICLASS_MODE
    col = "_tech_list"
    if mode == "level_separate" and level:
        cand = "_tech_%s_list" % level
        col = cand if cand in df.columns else "_tech_list"

    lists = df[col].map(lambda lst: list(lst or []))
    if mode == "primary":
        lists = lists.map(lambda lst: lst[:1])
    n = lists.map(len)
    keep = n > 0
    sub = df[keep].copy()
    sub["_x_tech"] = lists[keep]
    sub["_x_n"] = n[keep]
    exploded = sub.explode("_x_tech")
    exploded = exploded.rename(columns={"_x_tech": "tech"})
    if mode == "fractional":
        exploded["weight"] = 1.0 / exploded["_x_n"].astype(float)
    else:
        exploded["weight"] = 1.0
    return exploded.drop(columns=["_x_n"])


def filter_options(df):
    """필터바 옵션 생성: 연도범위/출원인/국가/법적상태/기술분류 목록 (Top 값 순)."""
    years = df["_base_year"].dropna()
    opts = {
        "year_min": int(years.min()) if len(years) else None,
        "year_max": int(years.max()) if len(years) else None,
        "applicants": df["applicant_display"].astype(str).replace("", np.nan).dropna()
                        .value_counts().head(300).index.tolist(),
        "countries": (df["country"].astype(str).str.strip().str.upper().replace("", np.nan)
                      .replace("NAN", np.nan).dropna().value_counts().index.tolist()
                      if "country" in df.columns else []),
        "legal_statuses": df["legal_status_norm"].value_counts().index.tolist(),
        "tech_l1": _level_values(df, "_tech_l1_list"),
        "tech_l2": _level_values(df, "_tech_l2_list"),
        "tech_l3": _level_values(df, "_tech_l3_list"),
        "tech": pd.Series([t for lst in df["_tech_list"] for t in lst])
                  .value_counts().head(300).index.tolist() if len(df) else [],
    }
    return opts


def _level_values(df, col):
    if col not in df.columns or not len(df):
        return []
    return pd.Series([t for lst in df[col] for t in (lst or [])]) \
        .value_counts().head(200).index.tolist()


# ===========================================================================
# src/metrics.py
# ===========================================================================
# -*- coding: utf-8 -*-
"""
metrics.py — 공통 지표 계산 모듈.

포함 지표와 계산식:
- lift(a,b)  = P(A∩B) / (P(A)·P(B))                    (독립 대비 동시출현 배수)
- pmi(a,b)   = log2( P(A∩B) / (P(A)·P(B)) )
- npmi(a,b)  = pmi / (-log2 P(A∩B))                     (정규화 PMI, [-1,1])
- jaccard    = |A∩B| / |A∪B|
- hhi        = Σ share_i^2                              (허핀달 집중도, [0,1])
- shannon_entropy = -Σ p_i log2 p_i                     (다양성)
- CAGR 대체지표 사다리 (robust_growth):
    ① CAGR = (end/start)^(1/y) - 1  (start>0, end>0 일 때만)
    ② 최근 N년 선형회귀 기울기(연평균 건수 대비 비율)
    ③ 과거 N년 대비 최근 N년 증가율
    ④ Poisson trend (log-link GLM 근사: log1p 회귀 기울기)
    ⑤ log1p slope
  각 단계는 데이터 조건이 안 되면 다음 단계로 폴백하며 사용한 방법명을 함께 반환.
- 정규화 파이프라인 (normalize_series):
    log1p 변환(옵션) → Winsorization(양측 pct) → Robust scaling(IQR) 또는 Min-Max
    → [0,1] 클리핑. 분모 0(상수 시리즈)이면 전체 0.5 반환.
- weighted_geometric_mean: Π x_i^{w_i} ^ (1/Σw), x는 [0,1]+ε 클리핑 (점수 지배 방지)

예외처리: 분모 0, 결측, 표본<2 등은 모두 명시적으로 처리하고 None 또는 폴백 반환.
"""
import math

import numpy as np
import pandas as pd


def safe_div(a, b, default=0.0):
    """0 나눗셈 방지 나눗셈."""
    try:
        b = float(b)
        if b == 0 or math.isnan(b):
            return default
        return float(a) / b
    except (TypeError, ValueError):
        return default


def lift(n_ab, n_a, n_b, n_total):
    """Lift = (n_ab/N) / ((n_a/N)(n_b/N)). 분모 0 이면 0."""
    if min(n_a, n_b, n_total) <= 0:
        return 0.0
    return safe_div(n_ab * n_total, n_a * n_b, 0.0)


def pmi(n_ab, n_a, n_b, n_total):
    """PMI(log2). P(A∩B)=0 이면 None."""
    if n_ab <= 0 or min(n_a, n_b, n_total) <= 0:
        return None
    val = safe_div(n_ab * n_total, n_a * n_b, 0.0)
    return math.log2(val) if val > 0 else None


def npmi(n_ab, n_a, n_b, n_total):
    """정규화 PMI = pmi / (-log2 P(A∩B)), 범위 [-1,1]. 계산 불가 시 None."""
    p = pmi(n_ab, n_a, n_b, n_total)
    if p is None:
        return None
    p_ab = safe_div(n_ab, n_total, 0.0)
    if p_ab <= 0 or p_ab >= 1:
        return None
    denom = -math.log2(p_ab)
    return p / denom if denom > 0 else None


def jaccard(n_ab, n_a, n_b):
    """Jaccard = |A∩B| / |A∪B|."""
    union = n_a + n_b - n_ab
    return safe_div(n_ab, union, 0.0)


def hhi(counts):
    """허핀달-허쉬만 지수: Σ(share^2). 빈 입력이면 None."""
    arr = np.asarray([c for c in counts if c and c > 0], dtype=float)
    if arr.size == 0:
        return None
    shares = arr / arr.sum()
    return float(np.sum(shares ** 2))


def shannon_entropy(counts, normalize=False):
    """샤논 엔트로피(-Σ p log2 p). normalize=True 면 log2(k)로 나눠 [0,1]."""
    arr = np.asarray([c for c in counts if c and c > 0], dtype=float)
    if arr.size == 0:
        return None
    p = arr / arr.sum()
    ent = float(-np.sum(p * np.log2(p)))
    if normalize:
        return ent / math.log2(len(p)) if len(p) > 1 else 0.0
    return ent


def year_counts(years, weights=None, year_min=None, year_max=None):
    """연도 배열 → 연속 연도 인덱스의 건수 Series (누락 연도 0 채움)."""
    s = pd.Series(years).dropna().astype(int)
    if weights is not None:
        w = pd.Series(weights)
        w = w[s.index] if len(w) == len(pd.Series(years)) else None
    else:
        w = None
    if not len(s):
        return pd.Series(dtype=float)
    counts = (pd.Series(1.0, index=s.index).groupby(s.values).sum() if w is None
              else w.groupby(s.values).sum())
    lo = int(year_min) if year_min is not None else int(counts.index.min())
    hi = int(year_max) if year_max is not None else int(counts.index.max())
    full = pd.Series(0.0, index=range(lo, hi + 1))
    full.update(counts)
    return full


def cagr(series):
    """CAGR = (end/start)^(1/years)-1. start<=0 또는 end<=0 또는 기간<1 이면 None."""
    s = pd.Series(series).dropna()
    if len(s) < 2:
        return None
    start, end = float(s.iloc[0]), float(s.iloc[-1])
    years = len(s) - 1
    if start <= 0 or end <= 0 or years < 1:
        return None
    return (end / start) ** (1.0 / years) - 1.0


def linreg_slope(series):
    """최소제곱 선형회귀 기울기 (x=0..n-1). 표본<2 이면 None."""
    s = pd.Series(series).dropna().astype(float)
    if len(s) < 2:
        return None
    x = np.arange(len(s), dtype=float)
    return float(np.polyfit(x, s.values, 1)[0])


def robust_growth(counts_by_year, recent_years=3):
    """최근 성장률 계산 (CAGR 대체지표 사다리). 반환: (growth, method).

    ① 최근 recent_years 구간 CAGR
    ② 최근 구간 선형회귀 기울기 ÷ 구간 평균 (비율화)
    ③ 과거 recent_years 대비 최근 recent_years 증가율
    ④ Poisson trend: log(count+1) 회귀 기울기 → exp(slope)-1
    ⑤ log1p slope (그대로)
    계산 가능한 첫 방법을 사용. 전부 불가하면 (None, "insufficient").
    """
    s = pd.Series(counts_by_year).dropna().astype(float)
    if len(s) == 0:
        return None, "insufficient"
    recent = s.iloc[-recent_years:] if len(s) >= recent_years else s
    # ① CAGR
    val = cagr(recent)
    if val is not None:
        return float(val), "cagr"
    # ② 선형회귀 기울기 / 평균
    slope = linreg_slope(recent)
    mean = float(recent.mean()) if len(recent) else 0.0
    if slope is not None and mean > 0:
        return float(slope / mean), "linreg_slope_ratio"
    # ③ 기간 대비 증가율
    if len(s) >= 2 * recent_years:
        prev = float(s.iloc[-2 * recent_years:-recent_years].sum())
        cur = float(s.iloc[-recent_years:].sum())
        if prev > 0:
            return (cur - prev) / prev, "period_over_period"
        if cur > 0:
            return 1.0, "period_over_period_newzero"
    # ④ Poisson trend 근사: log1p 회귀 기울기 → exp-1
    log_slope = linreg_slope(np.log1p(recent.values))
    if log_slope is not None:
        return float(math.exp(log_slope) - 1.0), "poisson_trend_approx"
    # ⑤ log1p slope
    if len(s) >= 2:
        log_slope_all = linreg_slope(np.log1p(s.values))
        if log_slope_all is not None:
            return float(log_slope_all), "log1p_slope"
    return None, "insufficient"


def winsorize(arr, pct=0.02):
    """양측 pct 백분위 Winsorization."""
    a = np.asarray(arr, dtype=float)
    if a.size == 0:
        return a
    lo, hi = np.nanpercentile(a, pct * 100), np.nanpercentile(a, (1 - pct) * 100)
    return np.clip(a, lo, hi)


def normalize_series(values, log=True, winsor_pct=0.02, method="robust"):
    """정규화 파이프라인: log1p → winsorize → robust(IQR) 또는 minmax → [0,1] 클립.

    상수 시리즈(분모 0)는 전체 0.5. NaN 은 0.0 으로 치환.
    """
    a = np.asarray(values, dtype=float)
    if a.size == 0:
        return a
    a = np.where(np.isnan(a), 0.0, a)
    if log:
        a = np.log1p(np.clip(a, a.min() if a.min() < 0 else 0, None) - min(a.min(), 0.0)) \
            if a.min() < 0 else np.log1p(a)
    a = winsorize(a, winsor_pct)
    if method == "robust":
        med = np.median(a)
        q1, q3 = np.percentile(a, 25), np.percentile(a, 75)
        iqr = q3 - q1
        if iqr <= 1e-12:
            return _minmax(a)
        scaled = (a - med) / iqr
        return _minmax(scaled)
    return _minmax(a)


def _minmax(a):
    lo, hi = float(np.min(a)), float(np.max(a))
    if hi - lo <= 1e-12:
        return np.full_like(a, 0.5, dtype=float)
    return (a - lo) / (hi - lo)


def weighted_geometric_mean(components, weights):
    """가중 기하평균: Π max(x,ε)^w ^ (1/Σw). components/weights: {name: value/weight}.

    특정 변수의 점수 지배를 방지하기 위해 각 성분은 [ε,1] 로 클리핑된 정규화 점수를
    가정한다. 가중치 합이 0 이면 None.
    """
    eps = 1e-6
    total_w = sum(w for w in weights.values() if w > 0)
    if total_w <= 0:
        return None
    log_sum = 0.0
    for name, w in weights.items():
        if w <= 0:
            continue
        x = components.get(name)
        x = eps if x is None else min(max(float(x), eps), 1.0)
        log_sum += w * math.log(x)
    return math.exp(log_sum / total_w)


def percentile_rank(values, value):
    """value 의 백분위(0~100). 빈 배열이면 None."""
    a = np.asarray([v for v in values if v is not None and not
                    (isinstance(v, float) and math.isnan(v))], dtype=float)
    if a.size == 0 or value is None:
        return None
    return float((a <= float(value)).mean() * 100.0)


def cross_correlation_lag(series_a, series_b, max_lag=3, min_overlap=4):
    """두 연도 시계열의 lagged correlation.

    lag>0: A 가 B 를 lag 년 선행(A[t] ~ B[t+lag]).
    반환: (best_lag, best_corr) — |corr| 최대 lag. 표본 부족 시 (None, None).
    """
    a = pd.Series(series_a).astype(float)
    b = pd.Series(series_b).astype(float)
    idx = a.index.intersection(b.index)
    if len(idx) < min_overlap:
        return None, None
    best_lag, best_corr = None, None
    for lag in range(-max_lag, max_lag + 1):
        a_idx = [i for i in idx if (i + lag) in b.index]
        if len(a_idx) < min_overlap:
            continue
        x = a.loc[a_idx].values
        y = b.loc[[i + lag for i in a_idx]].values
        if np.std(x) < 1e-12 or np.std(y) < 1e-12:
            continue
        corr = float(np.corrcoef(x, y)[0, 1])
        if best_corr is None or abs(corr) > abs(best_corr):
            best_lag, best_corr = lag, corr
    return best_lag, best_corr


def cosine_sim_vec(u, v):
    """두 벡터의 코사인 유사도. 영벡터면 0."""
    u = np.asarray(u, dtype=float)
    v = np.asarray(v, dtype=float)
    nu, nv = np.linalg.norm(u), np.linalg.norm(v)
    if nu <= 1e-12 or nv <= 1e-12:
        return 0.0
    return float(np.dot(u, v) / (nu * nv))


# ===========================================================================
# src/storage.py
# ===========================================================================
# -*- coding: utf-8 -*-
"""
storage.py — 설정·매핑·프로젝트 상태 영속화.

저장 체인 (가용한 첫 방법 사용):
1. Dataiku 프로젝트 변수 (dataiku.api_client().get_default_project().get_variables())
   — key: variables["standard"]["ip_landscape"][store_key]
2. 로컬 JSON 파일 (개발·테스트 환경 폴백): ./ip_landscape_store.json

저장 대상 store_key:
- "column_mapping"   : {dataset명: {concept: column}}
- "settings"         : 사용자 설정 (config.DEFAULT_SETTINGS overlay)
- "applicant_rules"  : {"mapping": {원본: 표준}, "groups": {표준: 그룹대표},
                        "history": [{"ts","action","from","to"}...]}  (합병·사명변경 이력)
- "projects"         : {프로젝트명: {"filters":…, "settings":…, "saved_at":…}}
- "filter_state"     : 마지막 필터 상태

모든 함수는 실패 시 예외를 삼키고 빈 dict 를 반환한다 (webapp 이 중단되지 않도록).
"""
import json
import logging
import os
import threading

logger = logging.getLogger("ip_landscape")

_VAR_ROOT = "ip_landscape"
_LOCAL_STORE_PATH = os.environ.get("IP_LANDSCAPE_STORE",
                                   os.path.join(os.path.abspath("."), "ip_landscape_store.json"))
_STORE_LOCK = threading.Lock()

try:
    import dataiku as _dataiku_mod
except ImportError:
    _dataiku_mod = None


def _project_variables():
    """Dataiku 프로젝트 변수 핸들. 미가용 시 None."""
    if _dataiku_mod is None:
        return None
    try:
        client = _dataiku_mod.api_client()
        return client.get_default_project()
    except Exception as e:
        logger.warning("Dataiku project variables unavailable: %s", e)
        return None


def _read_local():
    try:
        if os.path.exists(_LOCAL_STORE_PATH):
            with open(_LOCAL_STORE_PATH, "r", encoding="utf-8") as fh:
                return json.load(fh)
    except (OSError, ValueError) as e:
        logger.warning("local store read failed: %s", e)
    return {}


def _write_local(data):
    try:
        with open(_LOCAL_STORE_PATH, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1, default=str)
        return True
    except OSError as e:
        logger.warning("local store write failed: %s", e)
        return False


def load_store(store_key):
    """store_key 의 저장값 로드 (dict). 없으면 {}."""
    with _STORE_LOCK:
        project = _project_variables()
        if project is not None:
            try:
                variables = project.get_variables()
                return dict(variables.get("standard", {}).get(_VAR_ROOT, {}).get(store_key, {}))
            except Exception as e:
                logger.warning("project variable read failed (%s): %s", store_key, e)
        return dict(_read_local().get(store_key, {}))


def save_store(store_key, value):
    """store_key 에 값 저장. 성공 여부 반환."""
    with _STORE_LOCK:
        project = _project_variables()
        if project is not None:
            try:
                variables = project.get_variables()
                std = variables.setdefault("standard", {})
                root = std.setdefault(_VAR_ROOT, {})
                root[store_key] = value
                project.set_variables(variables)
                return True
            except Exception as e:
                logger.warning("project variable write failed (%s): %s", store_key, e)
        data = _read_local()
        data[store_key] = value
        return _write_local(data)


# --- 편의 함수 ---
def load_settings():
    return load_store("settings")


def save_settings(settings):
    return save_store("settings", settings)


def load_mapping_for(dataset_name):
    return load_store("column_mapping").get(str(dataset_name), {})


def save_mapping_for(dataset_name, mapping):
    all_mappings = load_store("column_mapping")
    all_mappings[str(dataset_name)] = mapping
    return save_store("column_mapping", all_mappings)


def load_applicant_rules():
    return load_store("applicant_rules")


def save_applicant_rules(rules):
    return save_store("applicant_rules", rules)


def load_projects():
    return load_store("projects")


def save_projects(projects):
    return save_store("projects", projects)


def load_filter_state():
    return load_store("filter_state")


def save_filter_state(state):
    return save_store("filter_state", state)

# (병합 shim) src.storage 모듈 네임스페이스
import types as _types
storage = _types.SimpleNamespace(
    load_store=load_store, save_store=save_store,
    load_settings=load_settings, save_settings=save_settings,
    load_mapping_for=load_mapping_for, save_mapping_for=save_mapping_for,
    load_applicant_rules=load_applicant_rules, save_applicant_rules=save_applicant_rules,
    load_projects=load_projects, save_projects=save_projects,
    load_filter_state=load_filter_state, save_filter_state=save_filter_state)



# ===========================================================================
# src/data_access.py
# ===========================================================================
# -*- coding: utf-8 -*-
"""
data_access.py — Dataiku Dataset 로딩 + 전처리 파이프라인 진입점.

- list_datasets(): 프로젝트 내 Dataset 이름 목록 (화이트리스트의 원천)
- validate_dataset_name(): 사용자 입력 Dataset 명을 목록과 대조 (임의 문자열 차단)
- get_dataset_columns(): 스키마에서 컬럼명 목록
- load_raw_dataframe(): 필요한 컬럼만 로딩 (dataiku.Dataset.get_dataframe(columns=...))
- get_prepared(): 표준 프레임(전처리 완료) 캐시 조회/생성 — 모든 분석의 공통 진입점.
  캐시 키 = (dataset, mapping, applicant_rules, analysis_unit).
  분석 단위(family dedup 등) 적용 결과를 캐시한다.

로컬 개발·테스트 폴백: dataiku 미설치 시 CSV 디렉터리(IP_LANDSCAPE_DATA_DIR)의
<dataset>.csv 를 로딩하고, 데모 모드에서는 등록된 in-memory DataFrame 을 사용한다.
Demo mode 는 사용자가 Settings 에서 명시적으로 켠 경우에만 동작한다.
"""
import logging
import os

import pandas as pd


logger = logging.getLogger("ip_landscape")

try:
    import dataiku as _dataiku_mod
except ImportError:
    _dataiku_mod = None

_LOCAL_DATA_DIR = os.environ.get("IP_LANDSCAPE_DATA_DIR", os.path.abspath("."))

# 테스트/데모용 in-memory 데이터 주입 지점 {name: DataFrame}
_INJECTED_DATASETS = {}


def inject_dataset(name, df):
    """테스트·데모용 DataFrame 등록 (Dataiku 미가용 환경 전용)."""
    _INJECTED_DATASETS[str(name)] = df
    DF_CACHE.clear()


def list_datasets():
    """사용 가능한 Dataset 이름 목록 (화이트리스트)."""
    names = list(_INJECTED_DATASETS.keys())
    if _dataiku_mod is not None:
        try:
            client = _dataiku_mod.api_client()
            project = client.get_default_project()
            names += [d["name"] for d in project.list_datasets()]
        except Exception as e:
            logger.warning("list_datasets via dataiku failed: %s", e)
    else:
        try:
            for fn in sorted(os.listdir(_LOCAL_DATA_DIR)):
                if fn.lower().endswith(".csv"):
                    names.append(os.path.splitext(fn)[0])
        except OSError:
            pass
    # 순서 유지 중복 제거
    return list(dict.fromkeys(names))


def validate_dataset_name(name):
    """Dataset 명 화이트리스트 검증. 유효하면 원래 이름, 아니면 None."""
    if not name:
        return None
    name = str(name)
    return name if name in set(list_datasets()) else None


def get_dataset_columns(dataset_name):
    """Dataset 의 컬럼명 목록. 실패 시 []."""
    name = validate_dataset_name(dataset_name)
    if name is None:
        return []
    if name in _INJECTED_DATASETS:
        return list(_INJECTED_DATASETS[name].columns)
    if _dataiku_mod is not None:
        try:
            ds = _dataiku_mod.Dataset(name)
            schema = ds.read_schema()
            return [c["name"] for c in schema]
        except Exception as e:
            logger.warning("read_schema failed for %s: %s", name, e)
            return []
    path = os.path.join(_LOCAL_DATA_DIR, name + ".csv")
    try:
        return list(pd.read_csv(path, nrows=0).columns)
    except (OSError, ValueError):
        return []


def load_raw_dataframe(dataset_name, columns=None):
    """원본 DataFrame 로딩. columns 지정 시 해당 컬럼만 (50,000건 대비 메모리 절약)."""
    name = validate_dataset_name(dataset_name)
    if name is None:
        raise ValueError("허용되지 않은 Dataset: %r" % dataset_name)
    if name in _INJECTED_DATASETS:
        df = _INJECTED_DATASETS[name]
        if columns:
            cols = [c for c in columns if c in df.columns]
            return df[cols].copy()
        return df.copy()
    if _dataiku_mod is not None:
        ds = _dataiku_mod.Dataset(name)
        kwargs = {"infer_with_pandas": True}
        if columns:
            kwargs["columns"] = [c for c in columns if c]
        return ds.get_dataframe(**kwargs)
    path = os.path.join(_LOCAL_DATA_DIR, name + ".csv")
    df = pd.read_csv(path)
    if columns:
        cols = [c for c in columns if c in df.columns]
        df = df[cols]
    return df


def needed_raw_columns(mapping):
    """매핑에서 실제 로딩할 원본 컬럼 목록."""
    return sorted(set(c for c in (mapping or {}).values() if c))


def get_prepared(dataset_name, mapping, applicant_rules=None, analysis_unit="family"):
    """전처리 완료 표준 프레임 (캐시). 모든 분석 API 의 공통 진입점.

    반환: (df, from_cache). 매핑이 비어 있으면 ValueError.
    """
    mapping = {k: v for k, v in (mapping or {}).items() if v and k in CONCEPTS}
    if not mapping:
        raise ValueError("컬럼 매핑이 비어 있습니다. 컬럼 매핑 화면에서 매핑을 설정하세요.")
    key = make_cache_key("prepared", dataset_name, mapping, applicant_rules or {}, analysis_unit)
    cached = DF_CACHE.get(key)
    if cached is not None:
        return cached, True
    raw = load_raw_dataframe(dataset_name, columns=needed_raw_columns(mapping))
    df = build_standard_frame(raw, mapping, applicant_rules)
    df = apply_analysis_unit(df, analysis_unit)
    df = df.reset_index(drop=True)
    DF_CACHE.set(key, df)
    return df, False


# ===========================================================================
# src/embedding_adapter.py
# ===========================================================================
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


# ===========================================================================
# src/llm_client.py
# ===========================================================================
# -*- coding: utf-8 -*-
"""
llm_client.py — Dataiku LLM Mesh 호출 (고정 모델 목록, 인젝션 방지, 폴백).

보안 원칙:
- 허용 모델은 config.ALLOWED_LLM_CANDIDATES 로 고정. 그 외 llm_id 는 거부.
- LLM 호출은 Backend 전용. 프론트에는 표시명(label)만 전달하고 llm_id·키를 노출하지 않음.
- 원문 특허 데이터를 전송하지 않고 요약 통계 문자열만 전달 (호출부 책임 + 길이 상한).
- sanitize_for_llm(): 제어문자 제거, 프롬프트 인젝션 유도 패턴 무력화, 길이 제한.
- 호출 실패/미가용 시 호출부가 규칙 기반 인사이트로 폴백할 수 있도록 None 반환.
"""
import logging
import re


logger = logging.getLogger("ip_landscape")

try:
    import dataiku as _dataiku_mod
except ImportError:
    _dataiku_mod = None

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# 프롬프트 인젝션에 흔한 지시 패턴 (대소문자 무시) — 통계 요약에 나타날 이유가 없는 문자열
_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|above|prior)\s+instructions?",
    r"disregard\s+(all\s+)?(previous|above|prior)",
    r"system\s*prompt", r"you\s+are\s+now", r"act\s+as\s+", r"jailbreak",
    r"이전\s*지시(를|사항)?\s*무시", r"시스템\s*프롬프트",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)


def sanitize_for_llm(text, max_chars=None):
    """LLM 입력 sanitization: 제어문자 제거 + 인젝션 패턴 마스킹 + 길이 제한."""
    if text is None:
        return ""
    s = str(text)
    s = _CONTROL_RE.sub(" ", s)
    s = _INJECTION_RE.sub("[제거됨]", s)
    limit = int(max_chars or LIMITS["insight_llm_max_chars"])
    return s[:limit]


def resolve_llm_id(requested_id):
    """요청된 llm_id 를 허용 목록과 대조. 허용되지 않으면 기본 모델."""
    if requested_id in ALLOWED_LLM_IDS:
        return requested_id
    if requested_id:
        logger.warning("허용되지 않은 LLM ID 요청 차단: %r", requested_id)
    return DEFAULT_LLM_ID


def llm_available():
    """LLM Mesh 사용 가능 여부."""
    return _dataiku_mod is not None


def call_llm(prompt, llm_id=None, max_tokens=800, temperature=0.2):
    """LLM Mesh 호출. 성공 시 응답 텍스트, 실패·미가용 시 None (호출부 폴백).

    dataiku.api_client().get_default_project().get_llm(llm_id) 방식 사용.
    """
    if _dataiku_mod is None:
        logger.info("LLM Mesh 미가용 환경 — 규칙 기반 폴백")
        return None
    llm_id = resolve_llm_id(llm_id)
    safe_prompt = sanitize_for_llm(prompt)
    try:
        client = _dataiku_mod.api_client()
        project = client.get_default_project()
        llm = project.get_llm(llm_id)
        completion = llm.new_completion()
        completion.settings["maxOutputTokens"] = int(max_tokens)
        completion.settings["temperature"] = float(temperature)
        completion.with_message(
            "당신은 특허 데이터 분석 결과를 요약하는 조수입니다. 전달된 요약 통계만 근거로, "
            "법률적 판단이나 인과관계 주장 없이 한국어로 간결한 인사이트를 작성하세요. "
            "통계에 없는 수치를 만들어내지 마세요.", role="system")
        completion.with_message(safe_prompt, role="user")
        resp = completion.execute()
        if getattr(resp, "success", False):
            return getattr(resp, "text", None)
        logger.warning("LLM 응답 실패: %s", getattr(resp, "raw", None))
        return None
    except Exception as e:
        logger.warning("LLM 호출 오류: %s", e)
        return None


# ===========================================================================
# src/viz_payload.py
# ===========================================================================
# -*- coding: utf-8 -*-
"""
viz_payload.py — 시각화용 JSON 생성 모듈 + 분석 결과 공통 envelope.

모든 분석 결과는 다음 envelope 로 통일한다 (프론트 렌더러 공통 처리):
  {"status": "ok" | "empty" | "disabled" | "error",
   "message": str (empty/disabled/error 시 안내문),
   "missing_columns": [필수 컬럼 라벨...] (disabled 시),
   "figure"/"figures"/"network"/... : 시각화 payload,
   "insight": {"sentences":[...], "metrics":{...}, "source":"rule|llm"},
   "meta": {"generated_at":…, "n_rows":…, "cache_hit":…, "disclaimer":…}}

Plotly payload 는 {"data":[trace...], "layout":{...}} 그대로 프론트에서
Plotly.newPlot 에 전달 가능한 형태로 생성한다.
Cytoscape payload 는 {"nodes":[{data:{...}}], "edges":[{data:{...}}]}.
ECharts payload 는 옵션 dict 자체.

숫자는 모두 python float/int 로 변환하여 JSON 직렬화 오류(np.int64 등)를 방지한다.
"""
import math

import numpy as np


# 색상 팔레트 (대분류·기업 등 범주형)
PALETTE = ["#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F", "#EDC948",
           "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC", "#2F4B7C", "#FFA600"]


def jsonable(obj):
    """numpy/pandas 스칼라·배열을 JSON 직렬화 가능한 python 기본형으로 재귀 변환."""
    if obj is None or isinstance(obj, (str, bool, int)):
        return obj
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return [jsonable(v) for v in obj.tolist()]
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [jsonable(v) for v in obj]
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


def ok_result(payload, insight=None, meta=None, disclaimer=True):
    """정상 결과 envelope."""
    out = {"status": "ok"}
    out.update(payload or {})
    out["insight"] = insight or {"sentences": [], "metrics": {}, "source": "rule"}
    m = dict(meta or {})
    if disclaimer:
        m["disclaimer"] = MESSAGES["disclaimer"]
    out["meta"] = m
    return jsonable(out)


def empty_result(message=None, meta=None):
    """데이터 없음/계산 불가 envelope (값 임의 생성 금지 원칙)."""
    return jsonable({"status": "empty", "message": message or MESSAGES["no_data"],
                     "insight": {"sentences": [message or MESSAGES["no_data"]],
                                 "metrics": {}, "source": "rule"},
                     "meta": dict(meta or {})})


def disabled_result(missing_labels, message=None, meta=None):
    """필수 컬럼 누락으로 비활성화된 분석 envelope."""
    msg = message or MESSAGES["missing_columns"].format(cols=", ".join(missing_labels))
    return jsonable({"status": "disabled", "message": msg,
                     "missing_columns": list(missing_labels),
                     "insight": {"sentences": [msg], "metrics": {}, "source": "rule"},
                     "meta": dict(meta or {})})


def color_for(key, registry, palette=None):
    """범주 키 → 팔레트 색상 (registry dict 에 배정 상태 유지)."""
    palette = palette or PALETTE
    if key not in registry:
        registry[key] = palette[len(registry) % len(palette)]
    return registry[key]


# ---------------------------------------------------------------------------
# Plotly 빌더
# ---------------------------------------------------------------------------
def base_layout(title=None, **overrides):
    """공통 Plotly layout (여백·폰트·범례·hover 설정)."""
    layout = {
        "font": {"family": "'Pretendard','Malgun Gothic','Apple SD Gothic Neo',sans-serif",
                 "size": 12},
        "margin": {"l": 60, "r": 30, "t": 48 if title else 24, "b": 60},
        "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "rgba(0,0,0,0)",
        "hovermode": "closest",
        "legend": {"orientation": "h", "y": -0.18},
    }
    if title:
        layout["title"] = {"text": title, "font": {"size": 15}}
    layout.update(overrides)
    return layout


def bubble_chart(points, x_title, y_title, title=None, quadrants=None,
                 size_ref_max=40.0, colorbar_title=None):
    """버블 차트 payload.

    points: [{x, y, size, color(수치), label, hover, customdata, line_width?}, ...]
    quadrants: {"x_mid":…, "y_mid":…, "labels":[좌상,우상,우하,좌하]} — 4분면 주석.
    """
    if not points:
        return None
    sizes = [max(float(p.get("size") or 1.0), 0.1) for p in points]
    smax = max(sizes)
    trace = {
        "type": "scatter", "mode": "markers",
        "x": [p["x"] for p in points], "y": [p["y"] for p in points],
        "text": [p.get("label", "") for p in points],
        "hovertext": [p.get("hover", "") for p in points],
        "hoverinfo": "text",
        "customdata": [p.get("customdata") for p in points],
        "marker": {
            "size": sizes, "sizemode": "area",
            "sizeref": 2.0 * smax / (size_ref_max ** 2), "sizemin": 4,
            "color": [p.get("color", 0) for p in points],
            "colorscale": "Viridis", "showscale": True,
            "colorbar": {"title": colorbar_title or "", "thickness": 12},
            "line": {"width": [p.get("line_width", 1) for p in points],
                     "color": "#333"},
            "opacity": 0.85,
        },
    }
    layout = base_layout(title, xaxis={"title": x_title}, yaxis={"title": y_title})
    if quadrants:
        xm, ym = quadrants["x_mid"], quadrants["y_mid"]
        layout["shapes"] = [
            {"type": "line", "x0": xm, "x1": xm, "yref": "paper", "y0": 0, "y1": 1,
             "line": {"color": "#bbb", "dash": "dot", "width": 1}},
            {"type": "line", "y0": ym, "y1": ym, "xref": "paper", "x0": 0, "x1": 1,
             "line": {"color": "#bbb", "dash": "dot", "width": 1}},
        ]
        labels = quadrants.get("labels") or []
        positions = [(0.02, 0.98), (0.98, 0.98), (0.98, 0.02), (0.02, 0.02)]
        anchors = [("left", "top"), ("right", "top"), ("right", "bottom"), ("left", "bottom")]
        layout["annotations"] = [
            {"x": px, "y": py, "xref": "paper", "yref": "paper", "text": lab,
             "showarrow": False, "xanchor": ax, "yanchor": ay,
             "font": {"size": 11, "color": "#888"}}
            for lab, (px, py), (ax, ay) in zip(labels, positions, anchors)]
    return {"data": [trace], "layout": layout}


def heatmap(z, x_labels, y_labels, title=None, colorscale="YlOrRd", hovertext=None,
            colorbar_title=None, zmid=None):
    """Plotly 히트맵 payload. 셀 수가 LIMITS 초과인 경우 호출부에서 ECharts 로 전환."""
    trace = {"type": "heatmap", "z": z, "x": x_labels, "y": y_labels,
             "colorscale": colorscale, "colorbar": {"thickness": 12}}
    if colorbar_title:
        trace["colorbar"]["title"] = colorbar_title
    if hovertext is not None:
        trace["hovertext"] = hovertext
        trace["hoverinfo"] = "text"
    if zmid is not None:
        trace["zmid"] = zmid
    return {"data": [trace],
            "layout": base_layout(title, xaxis={"tickangle": -40, "automargin": True},
                                  yaxis={"automargin": True})}


def echarts_heatmap(z, x_labels, y_labels, title=None):
    """대규모(10만+ 셀) 히트맵용 Apache ECharts 옵션."""
    data = []
    vmin, vmax = None, None
    for yi, row in enumerate(z):
        for xi, v in enumerate(row):
            if v is None:
                continue
            data.append([xi, yi, round(float(v), 4)])
            vmin = v if vmin is None else min(vmin, v)
            vmax = v if vmax is None else max(vmax, v)
    return {
        "engine": "echarts",
        "title": {"text": title or "", "textStyle": {"fontSize": 14}},
        "tooltip": {"position": "top"},
        "grid": {"left": 120, "bottom": 100, "right": 40, "top": 40},
        "xAxis": {"type": "category", "data": x_labels,
                  "axisLabel": {"rotate": 45, "fontSize": 10}},
        "yAxis": {"type": "category", "data": y_labels, "axisLabel": {"fontSize": 10}},
        "visualMap": {"min": vmin or 0, "max": vmax or 1, "calculable": True,
                      "orient": "horizontal", "left": "center", "bottom": 0},
        "series": [{"type": "heatmap", "data": data,
                    "emphasis": {"itemStyle": {"shadowBlur": 6}},
                    "progressive": 2000, "animation": False}],
    }


def sankey(nodes, links, title=None):
    """Plotly Sankey payload. nodes:[{label,color}], links:[{source,target,value,color,hover,customdata}]."""
    trace = {
        "type": "sankey",
        "node": {"label": [n["label"] for n in nodes],
                 "color": [n.get("color", "#4E79A7") for n in nodes],
                 "pad": 12, "thickness": 14,
                 "line": {"width": 0.5, "color": "#999"}},
        "link": {"source": [l["source"] for l in links],
                 "target": [l["target"] for l in links],
                 "value": [l["value"] for l in links],
                 "color": [l.get("color", "rgba(120,140,180,0.35)") for l in links],
                 "customdata": [l.get("customdata") for l in links],
                 "hovertemplate": "%{source.label} → %{target.label}<br>%{value}<extra></extra>"},
    }
    return {"data": [trace], "layout": base_layout(title, margin={"l": 10, "r": 10, "t": 40, "b": 10})}


def line_chart(series_list, x_title, y_title, title=None):
    """복수 시계열 라인차트. series_list: [{name, x:[..], y:[..], color?}]."""
    data = []
    for i, s in enumerate(series_list):
        data.append({"type": "scatter", "mode": "lines+markers", "name": s["name"],
                     "x": s["x"], "y": s["y"],
                     "line": {"color": s.get("color", PALETTE[i % len(PALETTE)])}})
    return {"data": data, "layout": base_layout(
        title, xaxis={"title": x_title}, yaxis={"title": y_title})}


def bar_chart(x, y, title=None, orientation="v", hovertext=None, colors=None,
              customdata=None, x_title=None, y_title=None):
    """막대차트 payload (수평/수직)."""
    trace = {"type": "bar", "orientation": orientation}
    if orientation == "h":
        trace["x"], trace["y"] = y, x
    else:
        trace["x"], trace["y"] = x, y
    if hovertext is not None:
        trace["hovertext"] = hovertext
        trace["hoverinfo"] = "text"
    if colors is not None:
        trace["marker"] = {"color": colors}
    if customdata is not None:
        trace["customdata"] = customdata
    return {"data": [trace], "layout": base_layout(
        title, xaxis={"title": x_title or "", "automargin": True},
        yaxis={"title": y_title or "", "automargin": True})}


def radar_chart(categories, series_list, title=None):
    """레이더 차트. series_list: [{name, values(카테고리 순, 0~1 표준화), raw(원값 hover)}]."""
    data = []
    for i, s in enumerate(series_list):
        vals = list(s["values"]) + [s["values"][0]]
        cats = list(categories) + [categories[0]]
        raws = list(s.get("raw", s["values"]))
        raws = raws + [raws[0]]
        data.append({
            "type": "scatterpolar", "name": s["name"], "r": vals, "theta": cats,
            "fill": "toself", "opacity": 0.55,
            "line": {"color": PALETTE[i % len(PALETTE)]},
            "hovertext": ["%s<br>%s: 표준화 %.2f / 원값 %s" % (s["name"], c, v, r)
                          for c, v, r in zip(cats, vals, raws)],
            "hoverinfo": "text",
        })
    return {"data": data, "layout": base_layout(
        title, polar={"radialaxis": {"visible": True, "range": [0, 1]}})}


def cytoscape_network(nodes, edges):
    """Cytoscape.js elements payload.

    nodes: [{id, label, size, color, border_color?, border_width?, meta...}]
    edges: [{source, target, weight, width, color?, label?, meta...}]
    """
    elements = {"nodes": [], "edges": []}
    for n in nodes:
        data = {str(k): jsonable(v) for k, v in n.items()}
        elements["nodes"].append({"data": data})
    for i, e in enumerate(edges):
        data = {str(k): jsonable(v) for k, v in e.items()}
        data.setdefault("id", "e%d" % i)
        elements["edges"].append({"data": data})
    return elements


# ===========================================================================
# src/insights.py
# ===========================================================================
# -*- coding: utf-8 -*-
"""
insights.py — 자동 인사이트 문장 생성 (규칙 기반 + LLM 기반).

규칙 기반 (1단계):
- 계산된 수치·임계값에 근거한 문장만 생성한다 (데이터 근거 없는 서술 금지).
- 문장 필수 요소: 분석 기간, 비교 기준, 핵심 수치, 상위/하위 백분위, 긍정 요인,
  위험 요인. 근거 특허 링크는 insight["drill"] 로 전달되어 프론트가 버튼을 렌더링한다.
- 표본 부족(임계값 미만) 시 MESSAGES["small_sample"] 문장으로 대체한다.

LLM 기반 (3단계):
- Dataiku LLM Mesh 사용. 원문 데이터가 아닌 요약 통계(JSON 문자열)만 전달.
- llm_client.sanitize_for_llm 으로 입력 정화, 실패 시 규칙 기반 문장으로 자동 폴백.
- 생성 문장과 함께 근거 지표(metrics)를 항상 함께 반환한다.
"""
import json



def fmt_num(v, digits=1):
    """수치 포맷 (천 단위 구분, None 안전)."""
    if v is None:
        return "-"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if abs(f - round(f)) < 1e-9 and abs(f) < 1e15:
        return format(int(round(f)), ",")
    return format(round(f, digits), ",")


def fmt_pct(v, digits=1):
    """비율(0.15) → 퍼센트 문자열('15.0%')."""
    if v is None:
        return "-"
    try:
        return "%s%%" % round(float(v) * 100.0, digits)
    except (TypeError, ValueError):
        return "-"


def period_label(df):
    """분석 기간 라벨 (예: '2015–2024년')."""
    years = df["_base_year"].dropna() if "_base_year" in df.columns else []
    if len(years):
        return "%d–%d년" % (int(min(years)), int(max(years)))
    return "기간 미상"


def build_insight(sentences, metrics=None, drills=None, source="rule",
                  small_sample=False):
    """인사이트 dict 조립. drills: [{"label":버튼명,"drill":{...}}] — 근거 특허 이동 버튼."""
    sents = list(sentences or [])
    if small_sample:
        sents.append(MESSAGES["small_sample"])
    return {"sentences": sents, "metrics": dict(metrics or {}),
            "drills": list(drills or []), "source": source}


def check_small_sample(n, settings):
    """표본 수가 임계값 미만인지."""
    return n < get_threshold(settings, "insight_small_sample")


def llm_augment_insight(analysis_name, rule_insight, summary_stats, settings):
    """LLM 인사이트 생성 시도. 실패 시 규칙 기반 그대로 반환 (+폴백 안내).

    summary_stats: 요약 통계 dict (원문 데이터 금지 — 호출부 책임).
    """
    if not (settings or {}).get("llm_insights_enabled"):
        return rule_insight
    if not llm_available():
        out = dict(rule_insight)
        out["llm_note"] = MESSAGES["llm_fallback"]
        return out
    try:
        stats_json = json.dumps(summary_stats, ensure_ascii=False, default=str)[:3500]
    except (TypeError, ValueError):
        stats_json = str(summary_stats)[:3500]
    prompt = (
        "다음은 특허 IP Landscape 분석 '%s' 의 요약 통계입니다.\n"
        "요약 통계(JSON): %s\n\n"
        "위 통계만 근거로 3문장 이내의 한국어 인사이트를 작성하세요. "
        "각 문장에는 분석 기간·비교 기준·핵심 수치를 포함하고, 긍정 요인과 위험 요인을 "
        "구분하세요. 통계에 없는 수치·법률적 판단·인과관계 주장은 금지합니다."
        % (sanitize_for_llm(analysis_name, 100), sanitize_for_llm(stats_json)))
    text = call_llm(prompt, llm_id=(settings or {}).get("llm_id"))
    out = dict(rule_insight)
    if text:
        out["sentences"] = [s.strip() for s in text.strip().split("\n") if s.strip()][:5]
        out["source"] = "llm"
        out["rule_sentences"] = rule_insight.get("sentences", [])
    else:
        out["llm_note"] = MESSAGES["llm_fallback"]
    return out


# ===========================================================================
# src/analyses/common.py
# ===========================================================================
# -*- coding: utf-8 -*-
"""
analyses/common.py — 분석 모듈 공통 유틸.

- combo_counts(): 행별 기술분류 리스트 → 조합(pair) 동시출현 집계 (전체/최근/신규출원인)
- tech_year_matrix(): 기술분류 × 연도 건수 매트릭스 (가중치 지원)
- select_patents(): drill-down 조건 → 근거 특허 행 선택 (모든 그래프 클릭의 근거)
- patent_records(): 특허 목록 직렬화 (페이지네이션)
- company_tech_shares(): 기업×기술분류 구성비 벡터
"""
from itertools import combinations

import numpy as np
import pandas as pd



def _pair_key(a, b):
    return (a, b) if a <= b else (b, a)


def combo_counts(df, recent_year_from=None):
    """기술분류 pair 동시출현 집계.

    반환 DataFrame: [a, b, n_ab(전체), n_recent(최근), applicants(set), new_applicants(set),
                     years(list)] — new_applicants 는 최근 구간에 처음 등장한 출원인.
    개별 기술 건수는 dict 로 함께 반환: (pairs_df, tech_counts, n_docs)
    """
    rows = []
    tech_counts = {}
    first_year_by_pair_applicant = {}
    pair_rows = {}
    n_docs = 0
    for techs, year, applicant in zip(df["_tech_list"], df["_base_year"],
                                      df["applicant_display"]):
        techs = sorted(set(techs or []))
        if not techs:
            continue
        n_docs += 1
        for t in techs:
            tech_counts[t] = tech_counts.get(t, 0) + 1
        if len(techs) < 2:
            continue
        y = int(year) if not (year is None or (isinstance(year, float) and np.isnan(year))) else None
        for a, b in combinations(techs, 2):
            key = _pair_key(a, b)
            rec = pair_rows.setdefault(key, {"a": key[0], "b": key[1], "n_ab": 0,
                                             "n_recent": 0, "applicants": set(),
                                             "recent_applicants": set(), "years": []})
            rec["n_ab"] += 1
            if y is not None:
                rec["years"].append(y)
            if applicant:
                rec["applicants"].add(applicant)
            if recent_year_from is not None and y is not None and y >= recent_year_from:
                rec["n_recent"] += 1
                if applicant:
                    rec["recent_applicants"].add(applicant)
            if applicant and y is not None:
                fk = (key, applicant)
                prev = first_year_by_pair_applicant.get(fk)
                if prev is None or y < prev:
                    first_year_by_pair_applicant[fk] = y
        rows.append(techs)
    # 신규 출원인: 해당 조합에 최근 구간에 처음 등장
    for (key, applicant), first_y in first_year_by_pair_applicant.items():
        if recent_year_from is not None and first_y >= recent_year_from:
            pair_rows[key].setdefault("new_applicants", set()).add(applicant)
    records = []
    for key, rec in pair_rows.items():
        rec.setdefault("new_applicants", set())
        records.append(rec)
    pairs_df = pd.DataFrame(records) if records else pd.DataFrame(
        columns=["a", "b", "n_ab", "n_recent", "applicants", "recent_applicants",
                 "new_applicants", "years"])
    return pairs_df, tech_counts, n_docs


def tech_year_matrix(df, multiclass_mode="duplicate", level=None):
    """기술분류 × 연도 건수 매트릭스 (pivot). 반환: DataFrame(index=tech, columns=year)."""
    ex = explode_tech(df, mode=multiclass_mode, level=level)
    ex = ex[ex["_base_year"].notna()]
    if not len(ex):
        return pd.DataFrame()
    ex["_year_int"] = ex["_base_year"].astype(int)
    mat = ex.pivot_table(index="tech", columns="_year_int", values="weight",
                         aggfunc="sum", fill_value=0.0)
    if len(mat.columns):
        full_years = range(int(mat.columns.min()), int(mat.columns.max()) + 1)
        mat = mat.reindex(columns=full_years, fill_value=0.0)
    return mat


def company_tech_shares(df, multiclass_mode="duplicate", by_year=False):
    """기업(×연도)별 기술분류 구성비 벡터.

    반환: DataFrame(index=(company[,year]), columns=tech, values=구성비 0~1).
    """
    ex = explode_tech(df, mode=multiclass_mode)
    ex = ex[ex["applicant_display"].astype(str) != ""]
    if by_year:
        ex = ex[ex["_base_year"].notna()]
        if not len(ex):
            return pd.DataFrame()
        ex["_year_int"] = ex["_base_year"].astype(int)
        counts = ex.pivot_table(index=["applicant_display", "_year_int"], columns="tech",
                                values="weight", aggfunc="sum", fill_value=0.0)
    else:
        if not len(ex):
            return pd.DataFrame()
        counts = ex.pivot_table(index="applicant_display", columns="tech",
                                values="weight", aggfunc="sum", fill_value=0.0)
    sums = counts.sum(axis=1)
    sums[sums == 0] = 1.0
    return counts.div(sums, axis=0)


# ---------------------------------------------------------------------------
# Drill-down
# ---------------------------------------------------------------------------
def select_patents(df, drill):
    """drill-down 조건 → 근거 특허 행 선택.

    drill 예:
      {"type":"tech","tech":"본딩"}                — 해당 기술분류 포함
      {"type":"combo","a":"본딩","b":"몰딩"}       — 두 분류 동시 포함
      {"type":"applicant","applicant":"삼성전자"}  — 해당 출원인
      {"type":"cell","problem":"...","solution":"..."} — 문제-해결수단 셀
      {"type":"tech_applicant","tech":…,"applicant":…}
      {"type":"transition","source":…,"target":…} — 두 분류 중 하나 이상 포함
      {"type":"year","year":2021}                  — 해당 연도
      {"type":"inventor","inventor":"홍길동"}      — 발명자 이력
      {"type":"ids","ids":[공개번호...]}           — 명시적 문헌 목록
      조합 필드는 and 로 결합 (예: tech + year).
    알 수 없는 type 이면 전체 반환.
    """
    if not drill:
        return df
    mask = pd.Series(True, index=df.index)
    dtype = drill.get("type", "")

    def has_tech(t):
        return df["_tech_list"].map(lambda lst: t in (lst or []))

    if dtype == "tech" or "tech" in drill:
        t = drill.get("tech")
        if t:
            mask &= has_tech(str(t))
    if dtype == "combo":
        a, b = drill.get("a"), drill.get("b")
        if a:
            mask &= has_tech(str(a))
        if b:
            mask &= has_tech(str(b))
    if dtype == "transition":
        a, b = drill.get("source"), drill.get("target")
        m = pd.Series(False, index=df.index)
        if a:
            m |= has_tech(str(a))
        if b:
            m |= has_tech(str(b))
        mask &= m
    if drill.get("applicant"):
        mask &= df["applicant_display"].astype(str) == str(drill["applicant"])
    if drill.get("year") not in (None, ""):
        mask &= df["_base_year"] == float(drill["year"])
    if dtype == "cell":
        p, s = drill.get("problem"), drill.get("solution")
        if p and "problem" in df.columns:
            mask &= df["problem"].astype(str).str.strip() == str(p)
        if s and "solution" in df.columns:
            mask &= df["solution"].astype(str).str.strip() == str(s)
    if drill.get("inventor") and "_inventor_list" in df.columns:
        inv = str(drill["inventor"])
        mask &= df["_inventor_list"].map(lambda lst: inv in (lst or []))
    if dtype == "ids" and drill.get("ids"):
        wanted = set(map(str, drill["ids"]))
        id_col = "pub_number" if "pub_number" in df.columns else \
            ("app_number" if "app_number" in df.columns else None)
        if id_col:
            mask &= df[id_col].astype(str).isin(wanted)
        else:
            mask &= df.index.astype(str).isin(wanted)
    if drill.get("legal_status"):
        mask &= df["legal_status_norm"] == str(drill["legal_status"])
    if drill.get("country") and "country" in df.columns:
        mask &= df["country"].astype(str).str.upper() == str(drill["country"]).upper()
    return df[mask]


_RECORD_FIELDS = [
    ("pub_number", "공개번호"), ("app_number", "출원번호"), ("reg_number", "등록번호"),
    ("title", "발명의 명칭"), ("applicant_display", "출원인"), ("country", "국가"),
    ("legal_status_norm", "법적상태"), ("family_id", "패밀리 ID"),
    ("cites_forward", "피인용 수"), ("family_size", "패밀리 수"),
]


def patent_records(df, page=1, page_size=25, max_page_size=200, extra_fields=None):
    """특허 목록 직렬화 + 페이지네이션.

    반환: {"total", "page", "page_size", "records": [...]} — 대용량 JSON 응답 방지.
    """
    page = max(1, int(page or 1))
    page_size = min(max(1, int(page_size or 25)), int(max_page_size))
    total = len(df)
    start = (page - 1) * page_size
    sub = df.iloc[start:start + page_size]
    fields = list(_RECORD_FIELDS) + list(extra_fields or [])
    records = []
    for _, row in sub.iterrows():
        rec = {}
        for col, label in fields:
            if col in sub.columns:
                v = row.get(col)
                if isinstance(v, float) and np.isnan(v):
                    v = None
                rec[label] = v if v is None or isinstance(v, (int, float, bool)) else str(v)
        y = row.get("_base_year")
        rec["연도"] = int(y) if y is not None and not (isinstance(y, float) and np.isnan(y)) else None
        techs = row.get("_tech_list") or []
        rec["기술분류"] = "; ".join(map(str, techs[:6]))
        active = row.get("_active_flag")
        rec["유효특허"] = ("Y" if active is True else ("N" if active is False else "?"))
        records.append(rec)
    return {"total": int(total), "page": page, "page_size": page_size, "records": records}


def export_dataframe(df, extra_fields=None, max_rows=20000):
    """Excel export 용 DataFrame (행 상한 적용)."""
    fields = list(_RECORD_FIELDS) + list(extra_fields or [])
    cols, labels = [], []
    for col, label in fields:
        if col in df.columns:
            cols.append(col)
            labels.append(label)
    out = df[cols].head(int(max_rows)).copy()
    out.columns = labels
    techs = df["_tech_list"].head(int(max_rows)).map(lambda lst: "; ".join(map(str, lst or [])))
    out["기술분류"] = techs
    years = df["_base_year"].head(int(max_rows))
    out["연도"] = years
    return out


# ===========================================================================
# src/analyses/overview.py
# ===========================================================================
# -*- coding: utf-8 -*-
"""
analyses/overview.py — Executive Overview.

분석 목적:
  포트폴리오 전반의 핵심 신호를 KPI 카드·Top 리스트로 요약하고, 각 카드에서 관련
  상세 메뉴/근거 특허로 이동(drill-down)하게 한다.

필수 컬럼: 기술분류(any), 날짜(any)
선택 컬럼: 출원인, 법적상태, 국가, 피인용 수, 만료예정일

계산식:
- 성장/쇠퇴 기술 Top10: 기술×연도 매트릭스에서 표본>=min_class_patents 인 기술의
  robust_growth(최근 recent_years) 상위/하위.
- 신규 기술조합 Top10: 최초 출현연도가 최근 구간에 속한 조합을 건수순 정렬.
- 경쟁사 전략변화 Top5: 기업별 [이전 구간 vs 최근 구간] 기술 구성비 벡터의
  코사인 거리(1-유사도). 두 구간 각각 최소 표본 필요.
- 권리장벽 높은 영역 Top5: 기술별 유효등록 건수 × 상위3사 점유율(CR3).
- 진입 가능 공백영역 Top5: 성장률>0 이면서 유효등록 건수·집중도가 낮은 기술
  (경량 스크리닝 — 상세는 White Space 메뉴).
- 경보: 피인용 상위 특허(핵심특허), 3년 내 만료 예정 + 피인용 상위(만료 경보).

예외처리: 각 항목별로 필요한 컬럼이 없으면 그 항목만 비우고 reason 표기.
Drill-down: 각 리스트 항목에 drill 파라미터 포함.
자동 인사이트: 성장 1위 기술·신규 조합 수·전략 변화 1위 기업을 규칙 기반 문장으로.
"""
import numpy as np
import pandas as pd



def _tech_growth_lists(df, settings, top_n):
    mat = tech_year_matrix(df, multiclass_mode=settings.get("multiclass_mode", "duplicate"))
    if mat.empty:
        return [], [], {}
    recent = int(get_threshold(settings, "recent_years"))
    min_n = get_threshold(settings, "min_class_patents")
    rows = []
    for tech, series in mat.iterrows():
        total = float(series.sum())
        if total < min_n:
            continue
        growth, method = robust_growth(series, recent_years=recent)
        if growth is None:
            continue
        recent_cnt = float(series.iloc[-recent:].sum())
        rows.append({"tech": str(tech), "growth": round(growth, 4), "method": method,
                     "total": round(total, 1), "recent": round(recent_cnt, 1),
                     "drill": {"type": "tech", "tech": str(tech)}})
    rows_g = sorted([r for r in rows if r["growth"] > 0], key=lambda r: -r["growth"])[:top_n]
    rows_d = sorted([r for r in rows if r["growth"] < 0], key=lambda r: r["growth"])[:top_n]
    return rows_g, rows_d, {"n_tech": len(rows)}


def _new_combos(df, settings, top_n):
    recent = int(get_threshold(settings, "recent_years"))
    years = df["_base_year"].dropna()
    if not len(years):
        return []
    recent_from = int(years.max()) - recent + 1
    pairs, _, _ = combo_counts(df, recent_year_from=recent_from)
    if not len(pairs):
        return []
    min_n = get_threshold(settings, "min_combo_patents")
    out = []
    for _, r in pairs.iterrows():
        ys = r["years"]
        if not ys or min(ys) < recent_from or r["n_ab"] < min_n:
            continue
        out.append({"a": r["a"], "b": r["b"], "count": int(r["n_ab"]),
                    "first_year": int(min(ys)),
                    "new_applicants": len(r["new_applicants"]),
                    "drill": {"type": "combo", "a": r["a"], "b": r["b"]}})
    return sorted(out, key=lambda x: (-x["count"], -x["new_applicants"]))[:top_n]


def _strategy_changes(df, settings, top_n):
    recent = int(get_threshold(settings, "recent_years"))
    years = df["_base_year"].dropna()
    if not len(years):
        return []
    y_max = int(years.max())
    recent_from = y_max - recent + 1
    prev_from = recent_from - recent
    cur = df[df["_base_year"] >= recent_from]
    prev = df[(df["_base_year"] >= prev_from) & (df["_base_year"] < recent_from)]
    if not len(cur) or not len(prev):
        return []
    mode = settings.get("multiclass_mode", "duplicate")
    cur_sh = company_tech_shares(cur, multiclass_mode=mode)
    prev_sh = company_tech_shares(prev, multiclass_mode=mode)
    if cur_sh.empty or prev_sh.empty:
        return []
    min_n = get_threshold(settings, "min_class_patents")
    counts_cur = cur["applicant_display"].value_counts()
    counts_prev = prev["applicant_display"].value_counts()
    all_techs = sorted(set(cur_sh.columns) | set(prev_sh.columns))
    out = []
    for company in set(cur_sh.index) & set(prev_sh.index):
        if counts_cur.get(company, 0) < min_n or counts_prev.get(company, 0) < min_n:
            continue
        u = cur_sh.loc[company].reindex(all_techs, fill_value=0.0).values
        v = prev_sh.loc[company].reindex(all_techs, fill_value=0.0).values
        dist = 1.0 - cosine_sim_vec(u, v)
        grown = (pd.Series(u, index=all_techs) - pd.Series(v, index=all_techs)) \
            .sort_values(ascending=False)
        out.append({"company": str(company), "change": round(float(dist), 4),
                    "top_shift": str(grown.index[0]) if len(grown) else "",
                    "recent_count": int(counts_cur.get(company, 0)),
                    "drill": {"type": "applicant", "applicant": str(company)}})
    return sorted(out, key=lambda x: -x["change"])[:top_n]


def _barrier_and_whitespace(df, settings, top_n):
    mode = settings.get("multiclass_mode", "duplicate")
    mat = tech_year_matrix(df, multiclass_mode=mode)
    if mat.empty:
        return [], []
    recent = int(get_threshold(settings, "recent_years"))
    min_n = get_threshold(settings, "min_class_patents")
    active_mask = df["_active_flag"].map(lambda v: v is True)
    granted_mask = df["_is_granted_bool"].map(lambda v: v is True)
    barrier_rows, white_rows = [], []
    for tech in mat.index:
        in_tech = df["_tech_list"].map(lambda lst: tech in (lst or []))
        n_total = int(in_tech.sum())
        if n_total < min_n:
            continue
        n_active_granted = int((in_tech & active_mask & granted_mask).sum())
        applicant_counts = df.loc[in_tech, "applicant_display"] \
            .replace("", np.nan).dropna().value_counts()
        cr3 = float(applicant_counts.head(3).sum()) / n_total if n_total else 0.0
        conc = hhi(applicant_counts.values) or 0.0
        growth, _ = robust_growth(mat.loc[tech], recent_years=recent)
        barrier_score = (n_active_granted / max(n_total, 1)) * cr3 * np.log1p(n_active_granted)
        barrier_rows.append({"tech": str(tech), "active_granted": n_active_granted,
                             "cr3": round(cr3, 3), "hhi": round(conc, 3),
                             "score": round(float(barrier_score), 4),
                             "drill": {"type": "tech", "tech": str(tech)}})
        if growth is not None and growth > 0 and cr3 < 0.6:
            white_rows.append({"tech": str(tech), "growth": round(growth, 4),
                               "active_granted": n_active_granted, "cr3": round(cr3, 3),
                               "score": round(float(growth * (1 - cr3) / np.log1p(n_active_granted + 1)), 4),
                               "drill": {"type": "tech", "tech": str(tech)}})
    barrier_rows = sorted(barrier_rows, key=lambda x: -x["score"])[:top_n]
    white_rows = sorted(white_rows, key=lambda x: -x["score"])[:top_n]
    return barrier_rows, white_rows


def _alerts(df, top_n=5):
    alerts = {"key_patents": [], "expiring": [], "key_companies": []}
    if "cites_forward" in df.columns and df["cites_forward"].notna().any():
        top_cited = df[df["cites_forward"].notna()].nlargest(top_n, "cites_forward")
        for _, r in top_cited.iterrows():
            alerts["key_patents"].append({
                "id": str(r.get("pub_number", r.name)),
                "title": str(r.get("title", ""))[:80],
                "applicant": str(r.get("applicant_display", "")),
                "cites": int(r["cites_forward"]),
            })
        counts = df["applicant_display"].replace("", np.nan).dropna().value_counts()
        cited_by_company = df.groupby("applicant_display")["cites_forward"].sum() \
            .sort_values(ascending=False).head(top_n)
        for comp, c in cited_by_company.items():
            if comp:
                alerts["key_companies"].append({
                    "company": str(comp), "total_cites": int(c),
                    "patents": int(counts.get(comp, 0)),
                    "drill": {"type": "applicant", "applicant": str(comp)}})
    if "expiry_date" in df.columns and df["expiry_date"].notna().any():
        now = pd.Timestamp.now()
        soon = df[(df["expiry_date"].notna()) & (df["expiry_date"] > now)
                  & (df["expiry_date"] <= now + pd.DateOffset(years=3))]
        if "cites_forward" in soon.columns and soon["cites_forward"].notna().any():
            soon = soon.nlargest(top_n, "cites_forward")
        else:
            soon = soon.head(top_n)
        for _, r in soon.iterrows():
            alerts["expiring"].append({
                "id": str(r.get("pub_number", r.name)),
                "title": str(r.get("title", ""))[:80],
                "applicant": str(r.get("applicant_display", "")),
                "expiry": str(r["expiry_date"].date()),
            })
    return alerts


def compute_overview(df, settings):
    """Executive Overview 결과 생성."""
    if not len(df):
        return empty_result()
    top_n = int(get_limit(settings, "top_n_default"))
    growing, declining, tech_meta = _tech_growth_lists(df, settings, top_n)
    new_combos = _new_combos(df, settings, top_n)
    strategy = _strategy_changes(df, settings, 5)
    barriers, whitespace = _barrier_and_whitespace(df, settings, 5)
    alerts = _alerts(df)

    years = df["_base_year"].dropna()
    active_flags = df["_active_flag"]
    n_active_known = int(active_flags.map(lambda v: v is not None).sum())
    n_active = int(active_flags.map(lambda v: v is True).sum())
    kpi = {
        "total": int(len(df)),
        "families": int(df["family_id"].nunique()) if "family_id" in df.columns else None,
        "applicants": int(df["applicant_display"].replace("", np.nan).nunique()),
        "countries": int(df["country"].astype(str).str.upper().nunique())
        if "country" in df.columns else None,
        "active_share": round(n_active / n_active_known, 3) if n_active_known else None,
        "year_min": int(years.min()) if len(years) else None,
        "year_max": int(years.max()) if len(years) else None,
    }

    sentences, metrics = [], {}
    period = period_label(df)
    if growing:
        g0 = growing[0]
        sentences.append(
            "%s 기준 전체 %s건 중 최근 성장률 1위 기술은 '%s'(성장률 %s, 최근 %s건)로 "
            "상위 %s 내 성장 기술로 분류됩니다."
            % (period, fmt_num(kpi["total"]), g0["tech"], fmt_pct(g0["growth"]),
               fmt_num(g0["recent"]), "10%"))
        metrics["top_growth_tech"] = g0["tech"]
        metrics["top_growth_rate"] = g0["growth"]
    if new_combos:
        sentences.append(
            "최근 %d년 내 처음 출현한 기술조합이 %s개 관측되었으며, 최다 조합은 '%s × %s'(%s건)입니다."
            % (int(get_threshold(settings, "recent_years")), fmt_num(len(new_combos)),
               new_combos[0]["a"], new_combos[0]["b"], fmt_num(new_combos[0]["count"])))
        metrics["new_combo_count"] = len(new_combos)
    if strategy:
        sentences.append(
            "포트폴리오 구성 변화가 가장 큰 기업은 '%s'(코사인 거리 %s)이며, 비중 확대 1위 분류는 '%s'입니다."
            % (strategy[0]["company"], fmt_num(strategy[0]["change"], 3),
               strategy[0]["top_shift"]))
    if barriers:
        sentences.append(
            "권리장벽이 가장 높은 영역은 '%s'(유효등록 %s건, 상위3사 점유율 %s)로 진입 시 "
            "선행 권리 검토가 필요한 위험 요인입니다."
            % (barriers[0]["tech"], fmt_num(barriers[0]["active_granted"]),
               fmt_pct(barriers[0]["cr3"])))
    insight = build_insight(sentences, metrics,
                            small_sample=check_small_sample(len(df), settings))
    return ok_result({
        "kpi": kpi, "growing": growing, "declining": declining,
        "new_combos": new_combos, "strategy_changes": strategy,
        "barriers": barriers, "whitespace": whitespace, "alerts": alerts,
    }, insight=insight)


# ===========================================================================
# src/analyses/tech_network.py
# ===========================================================================
# -*- coding: utf-8 -*-
"""
analyses/tech_network.py — 4.2 기술분류 조합 네트워크.

분석 목적:
  기술분류 간 동시분류(co-classification) 구조를 네트워크로 표현하여 기술융합의
  중심축·커뮤니티·최근 성장 조합을 파악한다.

필수 컬럼: 기술분류(any)
선택 컬럼: 패밀리 ID(노드 크기=패밀리 수), 날짜(성장률·최근 조합), 출원인(신규 출원인)

그래프 구성 (Cytoscape.js):
- 노드: 기술분류 / 크기: 패밀리(문헌) 수 / 색상: 대분류 또는 Louvain 커뮤니티
- 테두리 색: 최근 성장률 (양수=초록, 음수=빨강, 불명=회색)
- 엣지: 동시분류 / 두께: 동시분류 강도(Jaccard) / hover: 지표 전체

계산 지표(엣지): 동시출현 건수, Jaccard, Lift, PMI/NPMI, 최근 recent_years 조합
성장률(robust_growth), 신규 출원인 수.

노드·엣지 수 상한: Top-N by weight (config.LIMITS, 설정 가능).
기업 비교: scope 파라미터 (all | company | market_excl) — 탭 3종.
Drill-down: 노드 클릭 {"type":"tech"}, 엣지 클릭 {"type":"combo"}.
자동 인사이트: 최대 연결 노드, Lift 상위 조합, 신규출원인 다수 조합.
예외처리: 조합이 없으면(단일 분류만) empty. 표본<min_combo_patents 조합 제외.
"""
import numpy as np

lift_fn = lift  # [merged import alias]
pmi_fn = pmi  # [merged import alias]
npmi_fn = npmi  # [merged import alias]
jaccard_fn = jaccard  # [merged import alias]

try:
    import networkx as nx
except ImportError:
    nx = None


def _louvain_communities(nodes, edges):
    """Louvain(가능 시) 또는 greedy modularity 커뮤니티. 실패 시 모두 0."""
    if nx is None:
        return {n: 0 for n in nodes}
    try:
        g = nx.Graph()
        g.add_nodes_from(nodes)
        for e in edges:
            g.add_edge(e["a"], e["b"], weight=e["n_ab"])
        try:
            comms = nx.community.louvain_communities(g, weight="weight", seed=42)
        except (AttributeError, Exception):
            comms = nx.community.greedy_modularity_communities(g, weight="weight")
        out = {}
        for i, c in enumerate(comms):
            for n in c:
                out[n] = i
        return out
    except Exception:
        return {n: 0 for n in nodes}


def _scope_frame(df, scope, company):
    """scope: all | company | market_excl → 대상 DataFrame."""
    if scope == "company" and company:
        return df[df["applicant_display"].astype(str) == str(company)]
    if scope == "market_excl" and company:
        return df[df["applicant_display"].astype(str) != str(company)]
    return df


def compute_tech_network(df, settings, scope="all", company=None, color_by="l1"):
    """기술분류 조합 네트워크 계산. color_by: 'l1'(대분류) | 'community'."""
    sub = _scope_frame(df, scope, company)
    if not len(sub):
        return empty_result()
    recent = int(get_threshold(settings, "recent_years"))
    years = sub["_base_year"].dropna()
    recent_from = (int(years.max()) - recent + 1) if len(years) else None
    pairs, tech_counts, n_docs = combo_counts(sub, recent_year_from=recent_from)
    if not len(pairs) or n_docs == 0:
        return empty_result("동시분류(2개 이상 기술분류) 데이터가 없어 네트워크를 만들 수 없습니다.")

    min_combo = get_threshold(settings, "min_combo_patents")
    pairs = pairs[pairs["n_ab"] >= min_combo]
    if not len(pairs):
        return empty_result("최소 표본(%d건) 이상의 기술조합이 없습니다." % int(min_combo))

    max_edges = get_limit(settings, "network_max_edges")
    max_nodes = get_limit(settings, "network_max_nodes")
    pairs = pairs.sort_values("n_ab", ascending=False).head(max_edges)

    # 엣지 지표 계산
    edge_rows = []
    for _, r in pairs.iterrows():
        a, b, n_ab = r["a"], r["b"], int(r["n_ab"])
        n_a, n_b = tech_counts.get(a, 0), tech_counts.get(b, 0)
        combo_series = year_counts(r["years"]) if r["years"] else None
        growth, g_method = (robust_growth(combo_series, recent_years=recent)
                            if combo_series is not None and len(combo_series) else (None, "none"))
        edge_rows.append({
            "a": a, "b": b, "n_ab": n_ab,
            "jaccard": round(jaccard_fn(n_ab, n_a, n_b), 4),
            "lift": round(lift_fn(n_ab, n_a, n_b, n_docs), 3),
            "pmi": round(pmi_fn(n_ab, n_a, n_b, n_docs), 3) if pmi_fn(n_ab, n_a, n_b, n_docs) is not None else None,
            "npmi": round(npmi_fn(n_ab, n_a, n_b, n_docs), 3) if npmi_fn(n_ab, n_a, n_b, n_docs) is not None else None,
            "growth": round(growth, 4) if growth is not None else None,
            "growth_method": g_method,
            "new_applicants": len(r["new_applicants"]),
        })

    # 노드 상한: 엣지에 등장하는 기술 중 건수 상위 max_nodes
    node_names = {}
    for e in edge_rows:
        for t in (e["a"], e["b"]):
            node_names[t] = tech_counts.get(t, 0)
    keep_nodes = set(sorted(node_names, key=lambda t: -node_names[t])[:max_nodes])
    edge_rows = [e for e in edge_rows if e["a"] in keep_nodes and e["b"] in keep_nodes]

    # 노드 성장률·색상
    l1_lookup = build_l1_lookup(sub)
    comm = _louvain_communities(keep_nodes, edge_rows) if color_by == "community" else {}
    color_registry = {}
    nodes_payload = []
    tech_growth = {}
    year_lists = {}
    for techs, y in zip(sub["_tech_list"], sub["_base_year"]):
        if y is None or (isinstance(y, float) and np.isnan(y)):
            continue
        for t in set(techs or []):
            if t in keep_nodes:
                year_lists.setdefault(t, []).append(int(y))
    for t in keep_nodes:
        series = year_counts(year_lists.get(t, []))
        g, _ = robust_growth(series, recent_years=recent) if len(series) else (None, "none")
        tech_growth[t] = g
        group = ("커뮤니티 %d" % comm.get(t, 0)) if color_by == "community" \
            else str(l1_lookup.get(t, "기타"))
        border = "#2e9e4f" if (g is not None and g > 0.05) else \
            ("#d64545" if (g is not None and g < -0.05) else "#999999")
        nodes_payload.append({
            "id": t, "label": t, "count": int(node_names.get(t, 0)),
            "size": float(12 + 28 * np.sqrt(node_names.get(t, 0) / max(max(node_names.values()), 1))),
            "color": color_for(group, color_registry), "group": group,
            "growth": round(g, 4) if g is not None else None,
            "border_color": border,
            "drill": {"type": "tech", "tech": t},
        })

    max_j = max((e["jaccard"] for e in edge_rows), default=1) or 1
    edges_payload = [{
        "source": e["a"], "target": e["b"], "weight": e["n_ab"],
        "width": float(1 + 7 * (e["jaccard"] / max_j)),
        "jaccard": e["jaccard"], "lift": e["lift"], "pmi": e["pmi"], "npmi": e["npmi"],
        "growth": e["growth"], "new_applicants": e["new_applicants"],
        "drill": {"type": "combo", "a": e["a"], "b": e["b"]},
    } for e in edge_rows]

    # 인사이트
    sentences, metrics = [], {}
    period = period_label(sub)
    if nodes_payload:
        hub = max(nodes_payload, key=lambda n: n["count"])
        degree = {}
        for e in edges_payload:
            degree[e["source"]] = degree.get(e["source"], 0) + 1
            degree[e["target"]] = degree.get(e["target"], 0) + 1
        hub_deg = max(degree, key=degree.get) if degree else hub["id"]
        sentences.append("%s 기준 네트워크에서 연결이 가장 많은 기술은 '%s'(연결 %s개)이며, "
                         "최대 규모 노드는 '%s'(%s건)입니다."
                         % (period, hub_deg, fmt_num(degree.get(hub_deg, 0)),
                            hub["id"], fmt_num(hub["count"])))
        metrics["hub_tech"] = hub_deg
    top_lift = sorted([e for e in edges_payload if e["lift"]], key=lambda e: -e["lift"])[:1]
    if top_lift:
        e = top_lift[0]
        sentences.append("독립 대비 동시출현 강도(Lift)가 가장 높은 조합은 '%s × %s'(Lift %s, %s건)입니다."
                         % (e["source"], e["target"], fmt_num(e["lift"], 2), fmt_num(e["weight"])))
        metrics["top_lift"] = e["lift"]
    top_new = sorted(edges_payload, key=lambda e: -e["new_applicants"])[:1]
    if top_new and top_new[0]["new_applicants"] > 0:
        e = top_new[0]
        sentences.append("최근 %d년 신규 출원인이 가장 많이 진입한 조합은 '%s × %s'(신규 %s개사)로 "
                         "경쟁 심화 위험 요인입니다."
                         % (recent, e["source"], e["target"], fmt_num(e["new_applicants"])))
    insight = build_insight(sentences, metrics,
                            small_sample=check_small_sample(len(sub), settings))
    return ok_result({
        "network": cytoscape_network(nodes_payload, edges_payload),
        "scope": scope, "company": company,
        "n_nodes": len(nodes_payload), "n_edges": len(edges_payload),
    }, insight=insight, meta={"truncated": len(pairs) >= get_limit(settings, "network_max_edges")})


# ===========================================================================
# src/analyses/emerging.py
# ===========================================================================
# -*- coding: utf-8 -*-
"""
analyses/emerging.py — 4.3 Emerging Combination Radar (기술융합 선행지표).

분석 목적:
  개별 기술 A·B 가 오래되었어도 A+B 조합이 최근 처음 증가하기 시작하면 신기술 방향
  후보로 포착한다.

필수 컬럼: 기술분류(any), 날짜(any)
선택 컬럼: 출원인(신규 진입), 유효특허 여부(테두리)

계산식:
  Emerging Combination Score
    = 가중 기하평균( 최근 3년 조합 성장률, 조합 Lift, 최근 신규 출원인 수, 기술분류 다양성 )
  - 각 성분은 log1p → Winsorization(2%) → Robust/MinMax scaling 으로 [0,1] 정규화
    (특정 변수의 점수 지배 방지). 가중치는 Settings(weights.emerging)에서 변경 가능.
  - 다양성 = 조합 A,B 가 서로 다른 대분류에 속하면 1, 같으면 0.5 (대분류 없으면 0.5).
  - 성장률은 metrics.robust_growth 사다리(CAGR→회귀기울기→기간증가율→Poisson→log1p).
  - 최소 표본: n_ab < min_combo_patents 조합 제외. 분모 0 은 safe_div/에психlon 처리.

그래프 구성 (Plotly 버블):
  X=조합 누적 특허 수(log축), Y=최근 3년 성장률, 크기=신규 진입 출원인 수+1,
  색상=Lift, 테두리 두께=유효특허 비율. 4분면 주석(좌상:초기 고성장/우상:핵심/
  우하:성숙·정체/좌하:미성숙).

Drill-down: 버블 클릭 → {"type":"combo","a":…,"b":…}.
자동 인사이트: Score 상위 조합, 신규 출원인·Lift 근거 문장. 표본 부족 문구 처리.
예외처리: 조합 없음/전부 표본 미달 시 empty.
"""
import numpy as np

lift_fn = lift  # [merged import alias]


def compute_emerging(df, settings):
    """Emerging Combination Radar 계산."""
    if not len(df):
        return empty_result()
    years = df["_base_year"].dropna()
    if not len(years):
        return empty_result("연도 정보(출원일/우선일/공개일)가 없어 계산할 수 없습니다.")
    recent = int(get_threshold(settings, "recent_years"))
    recent_from = int(years.max()) - recent + 1
    pairs, tech_counts, n_docs = combo_counts(df, recent_year_from=recent_from)
    min_combo = get_threshold(settings, "min_combo_patents")
    pairs = pairs[pairs["n_ab"] >= min_combo] if len(pairs) else pairs
    if not len(pairs):
        return empty_result("최소 표본(%d건) 이상의 기술조합이 없어 계산 불가입니다." % int(min_combo))

    l1_lookup = build_l1_lookup(df)
    rows = []
    for _, r in pairs.iterrows():
        a, b = r["a"], r["b"]
        series = year_counts(r["years"]) if r["years"] else None
        growth, g_method = (robust_growth(series, recent_years=recent)
                            if series is not None and len(series) else (None, "insufficient"))
        lift_v = lift_fn(int(r["n_ab"]), tech_counts.get(a, 0), tech_counts.get(b, 0), n_docs)
        n_new = len(r["new_applicants"])
        l1a, l1b = l1_lookup.get(a), l1_lookup.get(b)
        diversity = 1.0 if (l1a and l1b and l1a != l1b) else 0.5
        # 유효특허 비율 (해당 조합 문헌 기준)
        in_combo = df["_tech_list"].map(lambda lst: a in (lst or []) and b in (lst or []))
        flags = df.loc[in_combo, "_active_flag"]
        known = flags.map(lambda v: v is not None)
        active_ratio = (float(flags[known].map(lambda v: v is True).mean())
                        if known.any() else None)
        rows.append({"a": a, "b": b, "n_ab": int(r["n_ab"]),
                     "growth": growth if growth is not None else 0.0,
                     "growth_available": growth is not None, "growth_method": g_method,
                     "lift": float(lift_v), "new_applicants": n_new,
                     "diversity": diversity, "active_ratio": active_ratio})
    if not rows:
        return empty_result()

    winsor = get_threshold(settings, "winsor_pct")
    norm_growth = normalize_series([max(r["growth"], 0.0) for r in rows], log=False,
                                   winsor_pct=winsor)
    norm_lift = normalize_series([r["lift"] for r in rows], log=True, winsor_pct=winsor)
    norm_new = normalize_series([r["new_applicants"] for r in rows], log=True,
                                winsor_pct=winsor)
    weights = get_weights(settings, "emerging")
    for i, r in enumerate(rows):
        r["score"] = weighted_geometric_mean(
            {"growth": float(norm_growth[i]), "lift": float(norm_lift[i]),
             "new_entrants": float(norm_new[i]), "diversity": r["diversity"]},
            weights)
        r["score"] = round(r["score"], 4) if r["score"] is not None else None
    rows.sort(key=lambda r: -(r["score"] or 0))
    max_points = get_limit(settings, "bubble_max_points")
    shown = rows[:max_points]

    points = []
    for r in shown:
        hover = ("<b>%s × %s</b><br>누적 %s건 / 최근성장률 %s (%s)<br>"
                 "Lift %s / 신규 출원인 %s / Score %s<br>유효특허 비율 %s"
                 % (r["a"], r["b"], fmt_num(r["n_ab"]),
                    fmt_pct(r["growth"]) if r["growth_available"] else "계산 불가",
                    r["growth_method"], fmt_num(r["lift"], 2), fmt_num(r["new_applicants"]),
                    r["score"], fmt_pct(r["active_ratio"]) if r["active_ratio"] is not None else "미상"))
        points.append({
            "x": max(r["n_ab"], 1), "y": r["growth"],
            "size": r["new_applicants"] + 1, "color": r["lift"],
            "label": "%s×%s" % (r["a"][:8], r["b"][:8]), "hover": hover,
            "line_width": 1 + 3 * (r["active_ratio"] or 0),
            "customdata": {"drill": {"type": "combo", "a": r["a"], "b": r["b"]},
                           "score": r["score"]},
        })
    x_vals = [p["x"] for p in points]
    y_vals = [p["y"] for p in points]
    fig = bubble_chart(
        points, "조합 누적 특허 수 (log)", "최근 %d년 성장률" % recent,
        title="Emerging Combination Radar",
        quadrants={"x_mid": float(np.median(x_vals)), "y_mid": max(float(np.median(y_vals)), 0.0),
                   "labels": ["초기 고성장", "핵심", "성숙·정체", "미성숙"]},
        colorbar_title="Lift")
    if fig:
        fig["layout"]["xaxis"]["type"] = "log"

    sentences, metrics = [], {}
    top = shown[0] if shown else None
    if top and top["score"]:
        sentences.append(
            "%s 기준 Emerging Score 1위 조합은 '%s × %s'(Score %s, 상위 %.0f%%)로, "
            "최근 %d년 성장률 %s·Lift %s·신규 출원인 %s개사가 근거입니다."
            % (period_label(df), top["a"], top["b"], top["score"],
               100.0 / max(len(rows), 1), recent,
               fmt_pct(top["growth"]) if top["growth_available"] else "계산 불가",
               fmt_num(top["lift"], 2), fmt_num(top["new_applicants"])))
        metrics.update({"top_combo": "%s × %s" % (top["a"], top["b"]),
                        "top_score": top["score"], "n_combos": len(rows)})
    high_new = [r for r in shown if r["new_applicants"] >= 3]
    if high_new:
        sentences.append("신규 출원인이 3개사 이상 진입한 조합이 %s개로, 융합 경쟁이 시작된 "
                         "신호입니다 (위험 요인: 선점 경쟁)." % fmt_num(len(high_new)))
    insight = build_insight(sentences, metrics,
                            drills=[{"label": "상위 조합 근거 특허",
                                     "drill": {"type": "combo", "a": top["a"], "b": top["b"]}}]
                            if top else [],
                            small_sample=check_small_sample(len(rows), settings))
    return ok_result({"figure": fig, "combos": shown[:50]}, insight=insight,
                     meta={"weights": get_weights(settings, "emerging"),
                           "truncated": len(rows) > len(shown)})


# ===========================================================================
# src/analyses/lifecycle.py
# ===========================================================================
# -*- coding: utf-8 -*-
"""
analyses/lifecycle.py — 4.7 기술 생애주기 Phase Map.

분석 목적:
  기술분류별 성숙도·모멘텀 지표로 생애주기 단계(Emerging/Growing/Competitive/
  Mature/Declining/Re-emerging)를 판정하고 버블맵으로 표현한다.

필수 컬럼: 기술분류(any), 날짜(any)
선택 컬럼: 출원인(집중도·신규출원인), 유효특허 여부, 피인용 수, 후속출원 정보

지표(기술분류별):
  - growth: 최근 출원 성장률 (robust_growth)
  - new_entrant_growth: 신규 출원인 증가율 (최근 구간 신규 출원인 / 전체 출원인)
  - age: 최초 진입 후 경과연수
  - concentration: 출원인 HHI
  - active_ratio: 유효특허 비율
  - combo_growth: 해당 분류가 참여한 신규 조합 수 증가율
  - avg_citations: 등록특허 평균 피인용도 (있을 때)
  - maturity(X축) = 정규화( age ) 와 정규화( 누적건수 ) 의 평균
  - momentum(Y축) = 정규화( growth ) 와 정규화( new_entrant_growth ) 의 평균

단계 판정 규칙 (임계값은 Settings thresholds 로 조정 가능):
  Re-emerging: 과거 reemerging_decline_years 간 감소·정체(합계 기울기<=0) AND
               최근 3년 연속 증가 AND 신규 출원인 존재 AND 신규 기술조합 동반 증가
  Emerging   : age<=5 AND growth>=emerging_min_growth
  Growing    : growth>=emerging_min_growth
  Declining  : growth<-0.1
  Competitive: 성장 정체(-0.1<=growth<emerging_min_growth) AND 집중도 낮음(HHI<0.15)
               AND 신규 출원인 유입 지속
  Mature     : 그 외

그래프: X=성숙도, Y=모멘텀, 크기=유효 패밀리 수, 색상=경쟁 강도(출원인 수),
        화살표=전년 대비 (성숙도, 모멘텀) 이동 방향.
Drill-down: 버블 클릭 {"type":"tech"}.
자동 인사이트: 단계별 분포, Re-emerging 탐지 결과.
예외처리: 표본<min_class_patents 분류 제외, 연도 없으면 empty.
"""
import numpy as np
import pandas as pd



def detect_reemerging(series, new_entrants_recent, combo_growth,
                      decline_years=3, recent_increase_years=3):
    """Re-emerging 탐지 규칙 (별도 함수).

    조건(모두 충족):
      ① 과거 구간(최근 recent_increase_years 이전의 decline_years)이 감소·정체
         (선형회귀 기울기 <= 0)
      ② 최근 recent_increase_years 년 연속 증가
      ③ 신규 출원인 증가 (recent 신규 출원인 >= 1)
      ④ 신규 기술조합 동반 증가 (combo_growth > 0)
    """
    s = pd.Series(series).dropna().astype(float)
    need = decline_years + recent_increase_years
    if len(s) < need:
        return False
    recent_part = s.iloc[-recent_increase_years:]
    past_part = s.iloc[-(need):-recent_increase_years]
    past_slope = linreg_slope(past_part)
    if past_slope is None or past_slope > 0:
        return False
    diffs = np.diff(recent_part.values)
    if not (len(diffs) > 0 and all(d > 0 for d in diffs)):
        return False
    if not new_entrants_recent or new_entrants_recent < 1:
        return False
    return combo_growth is not None and combo_growth > 0


def _phase_of(row, settings):
    """단계 판정 (Re-emerging 우선)."""
    g_min = get_threshold(settings, "emerging_min_growth")
    if row["reemerging"]:
        return "Re-emerging"
    growth = row["growth"] if row["growth"] is not None else 0.0
    if row["age"] is not None and row["age"] <= 5 and growth >= g_min:
        return "Emerging"
    if growth >= g_min:
        return "Growing"
    if growth < -0.1:
        return "Declining"
    if (row["concentration"] is not None and row["concentration"] < 0.15
            and row["new_entrants"] >= 1):
        return "Competitive"
    return "Mature"


def compute_lifecycle(df, settings):
    """기술 생애주기 Phase Map 계산."""
    if not len(df):
        return empty_result()
    mode = settings.get("multiclass_mode", "duplicate")
    mat = tech_year_matrix(df, multiclass_mode=mode)
    if mat.empty:
        return empty_result("연도·기술분류 데이터가 없어 계산할 수 없습니다.")
    recent = int(get_threshold(settings, "recent_years"))
    min_n = get_threshold(settings, "min_class_patents")
    decline_years = int(get_threshold(settings, "reemerging_decline_years"))
    y_max = int(mat.columns.max())
    recent_from = y_max - recent + 1

    # 조합 성장률 (기술별): 최근 구간 첫 출현 조합 수
    pairs, _, _ = combo_counts(df, recent_year_from=recent_from)
    combo_new_by_tech, combo_old_by_tech = {}, {}
    for _, r in (pairs.iterrows() if len(pairs) else []):
        first = min(r["years"]) if r["years"] else None
        bucket = combo_new_by_tech if (first is not None and first >= recent_from) \
            else combo_old_by_tech
        for t in (r["a"], r["b"]):
            bucket[t] = bucket.get(t, 0) + 1

    rows = []
    for tech, series in mat.iterrows():
        total = float(series.sum())
        if total < min_n:
            continue
        in_tech = df["_tech_list"].map(lambda lst: tech in (lst or []))
        sub = df[in_tech]
        growth, g_method = robust_growth(series, recent_years=recent)
        first_year = int(series[series > 0].index.min()) if (series > 0).any() else None
        age = (y_max - first_year) if first_year is not None else None
        applicants_all = sub["applicant_display"].replace("", np.nan).dropna()
        counts = applicants_all.value_counts()
        conc = hhi(counts.values)
        recent_apps = set(sub.loc[sub["_base_year"] >= recent_from, "applicant_display"]
                          .replace("", np.nan).dropna())
        old_apps = set(sub.loc[sub["_base_year"] < recent_from, "applicant_display"]
                       .replace("", np.nan).dropna())
        new_entrants = len(recent_apps - old_apps)
        flags = sub["_active_flag"]
        known = flags.map(lambda v: v is not None)
        active_ratio = float(flags[known].map(lambda v: v is True).mean()) if known.any() else None
        n_active = int(flags.map(lambda v: v is True).sum())
        combo_new = combo_new_by_tech.get(tech, 0)
        combo_old = combo_old_by_tech.get(tech, 0)
        combo_growth = ((combo_new - combo_old) / combo_old) if combo_old else \
            (1.0 if combo_new else 0.0)
        avg_cites = (float(sub["cites_forward"].dropna().mean())
                     if "cites_forward" in sub.columns and sub["cites_forward"].notna().any()
                     else None)
        reemerging = detect_reemerging(series, new_entrants, combo_growth,
                                       decline_years=decline_years,
                                       recent_increase_years=recent)
        rows.append({"tech": str(tech), "total": round(total, 1),
                     "growth": round(growth, 4) if growth is not None else None,
                     "growth_method": g_method, "age": age,
                     "concentration": round(conc, 3) if conc is not None else None,
                     "new_entrants": new_entrants,
                     "n_applicants": int(len(counts)),
                     "active_ratio": round(active_ratio, 3) if active_ratio is not None else None,
                     "n_active": n_active, "combo_growth": round(combo_growth, 3),
                     "avg_citations": round(avg_cites, 2) if avg_cites is not None else None,
                     "reemerging": bool(reemerging)})
    if not rows:
        return empty_result("최소 표본(%d건) 이상의 기술분류가 없습니다." % int(min_n))

    ages = normalize_series([r["age"] if r["age"] is not None else 0 for r in rows], log=False)
    totals = normalize_series([r["total"] for r in rows], log=True)
    growths = normalize_series([r["growth"] if r["growth"] is not None else 0 for r in rows],
                               log=False)
    entrants = normalize_series([r["new_entrants"] for r in rows], log=True)
    for i, r in enumerate(rows):
        r["maturity"] = round(float((ages[i] + totals[i]) / 2), 4)
        r["momentum"] = round(float((growths[i] + entrants[i]) / 2), 4)
        r["phase"] = _phase_of(r, settings)

    # 전년 대비 이동 방향 (직전 연도 제외 데이터로 재계산한 성숙도·모멘텀 근사)
    arrows = []
    if mat.shape[1] > 2:
        mat_prev = mat.iloc[:, :-1]
        prev_metrics = {}
        for tech, series in mat_prev.iterrows():
            if float(series.sum()) < min_n:
                continue
            g, _ = robust_growth(series, recent_years=recent)
            first_year = int(series[series > 0].index.min()) if (series > 0).any() else None
            prev_metrics[str(tech)] = {
                "age": (int(mat_prev.columns.max()) - first_year) if first_year else 0,
                "total": float(series.sum()), "growth": g if g is not None else 0.0}
        if prev_metrics:
            p_ages = normalize_series([m["age"] for m in prev_metrics.values()], log=False)
            p_totals = normalize_series([m["total"] for m in prev_metrics.values()], log=True)
            p_growth = normalize_series([m["growth"] for m in prev_metrics.values()], log=False)
            for i, (tech, m) in enumerate(prev_metrics.items()):
                m["maturity"] = float((p_ages[i] + p_totals[i]) / 2)
                m["momentum"] = float(p_growth[i])
            for r in rows:
                pm = prev_metrics.get(r["tech"])
                if pm:
                    arrows.append({"tech": r["tech"], "x0": pm["maturity"], "y0": pm["momentum"],
                                   "x1": r["maturity"], "y1": r["momentum"]})

    max_points = get_limit(settings, "bubble_max_points")
    shown = sorted(rows, key=lambda r: -r["total"])[:max_points]
    points = []
    for r in shown:
        hover = ("<b>%s</b> — %s<br>누적 %s건 / 성장률 %s (%s)<br>경과 %s년 / HHI %s / "
                 "신규 출원인 %s<br>유효비율 %s / 조합증가율 %s / 평균 피인용 %s"
                 % (r["tech"], r["phase"], fmt_num(r["total"]),
                    fmt_pct(r["growth"]) if r["growth"] is not None else "계산 불가",
                    r["growth_method"], fmt_num(r["age"]), r["concentration"],
                    fmt_num(r["new_entrants"]), fmt_pct(r["active_ratio"]) if r["active_ratio"] is not None else "미상",
                    fmt_pct(r["combo_growth"]), r["avg_citations"] if r["avg_citations"] is not None else "-"))
        points.append({"x": r["maturity"], "y": r["momentum"],
                       "size": (r["n_active"] or r["total"]),
                       "color": r["n_applicants"], "label": r["tech"], "hover": hover,
                       "customdata": {"drill": {"type": "tech", "tech": r["tech"]},
                                      "phase": r["phase"]}})
    fig = bubble_chart(points, "기술 성숙도 (정규화)", "최근 성장 모멘텀 (정규화)",
                       title="기술 생애주기 Phase Map",
                       quadrants={"x_mid": 0.5, "y_mid": 0.5,
                                  "labels": ["Emerging/Growing", "Growing 핵심", "Mature", "초기 미성숙"]},
                       colorbar_title="경쟁 강도(출원인 수)")
    if fig and arrows:
        fig["layout"].setdefault("annotations", [])
        for a in arrows[:60]:
            fig["layout"]["annotations"].append({
                "x": a["x1"], "y": a["y1"], "ax": a["x0"], "ay": a["y0"],
                "xref": "x", "yref": "y", "axref": "x", "ayref": "y",
                "showarrow": True, "arrowhead": 3, "arrowsize": 0.8,
                "arrowwidth": 1, "arrowcolor": "rgba(100,100,100,0.45)", "text": ""})

    phase_counts = {p: sum(1 for r in rows if r["phase"] == p) for p in LIFECYCLE_PHASES}
    sentences = ["%s 기준 %s개 기술분류 중 단계 분포는 %s 입니다."
                 % (period_label(df), fmt_num(len(rows)),
                    ", ".join("%s %d" % (p, c) for p, c in phase_counts.items() if c))]
    reems = [r["tech"] for r in rows if r["phase"] == "Re-emerging"]
    if reems:
        sentences.append("재부상(Re-emerging) 신호가 탐지된 기술: %s — 과거 정체 후 최근 %d년 "
                         "연속 증가와 신규 출원인·신규 조합 증가가 동반되었습니다 (긍정 요인)."
                         % (", ".join(reems[:5]), recent))
    decl = [r["tech"] for r in sorted(rows, key=lambda x: (x["growth"] or 0))
            if r["phase"] == "Declining"][:3]
    if decl:
        sentences.append("쇠퇴 단계 기술(%s)은 신규 투자 시 위험 요인입니다." % ", ".join(decl))
    insight = build_insight(sentences, {"phase_counts": phase_counts},
                            small_sample=check_small_sample(len(rows), settings))
    return ok_result({"figure": fig, "phases": rows, "phase_counts": phase_counts},
                     insight=insight)


# ===========================================================================
# src/analyses/whitespace.py
# ===========================================================================
# -*- coding: utf-8 -*-
"""
analyses/whitespace.py — 4.8 Actionable White Space Map.

분석 목적:
  단순 저출원 영역이 아니라 「매력도 × 진입 가능성」으로 평가한 실행 가능한
  화이트스페이스를 도출한다.

필수 컬럼: 기술분류(any), 날짜(any)
선택 컬럼: 출원인, 법적상태/유효특허, 해결과제, 제품/공정(키워드), 패밀리 국가 수,
          만료예정일, 자사 특허 여부, 임베딩(자사 역량 인접도)

계산식:
  Opportunity Score = 가중 기하평균(기회 성분) ÷ (barrier_w 가중 권리장벽 성분)
  - 기회 지표: 최근 3년 성장률, 신규 출원인 수, 기술조합 증가율,
    제품·공정 키워드 증가율, 해결과제 반복 등장(고유 과제 대비 반복 비율),
    인접 기술 연결성(공동출현 이웃 수)
  - 위험 지표(권리장벽): 유효 등록특허 수, 상위 출원인 점유율(CR3), 핵심특허 집중도
    (피인용 상위 특허 비중), 주요 패밀리 국가 범위(평균), 권리 잔존기간(평균 잔여년)
    — 각 성분 정규화 후 가중 평균.
  - 모든 성분: log1p → Winsorization → 정규화([0,1]) — 점수 지배 방지.
  - 매력도(X) = 기회 성분 가중 기하평균 / 진입 가능성(Y) = 1 - 장벽 점수.
  - 가중치는 Settings 슬라이더로 조정. 응답에 성분별 정규화 점수를 포함하여
    프론트가 서버 재계산 없이 가중치 변경을 즉시 반영한다.

자사 역량 (가용한 방식만 적용, 임의 생성 금지):
  ① is_own 컬럼 → 자사 특허의 기술분류 분포와의 겹침
  ② 자사 임베딩 평균 벡터와 영역 평균 벡터의 코사인 유사도 (임베딩 있을 때)
  ③ settings.own_capability_keywords 와 기술분류명 부분일치

그래프: 2×2 Opportunity Matrix — X=매력도, Y=진입 가능성, 크기=관련 특허 수,
        색상=권리장벽 점수, 자사 역량 보유 영역은 별도 마커(다이아몬드 테두리).
Drill-down: {"type":"tech"}.
자동 인사이트: Score 상위 영역 + 근거 성분, 장벽 높은 영역 경고.
예외처리: 표본 미달 분류 제외, 연도 없으면 empty.
"""
import numpy as np
import pandas as pd



def _keyword_growth(sub, recent_from, cols=("product", "process")):
    """제품·공정 키워드 증가율: 최근 구간 고유 키워드 수 / 과거 고유 키워드 수 - 1."""
    texts_recent, texts_old = set(), set()
    found = False
    for col in cols:
        if col not in sub.columns:
            continue
        found = True
        for v, y in zip(sub[col], sub["_base_year"]):
            if v is None or (isinstance(v, float) and np.isnan(v)):
                continue
            for token in str(v).replace(";", ",").split(","):
                token = token.strip()
                if not token:
                    continue
                if y is not None and not (isinstance(y, float) and np.isnan(y)) \
                        and y >= recent_from:
                    texts_recent.add(token)
                else:
                    texts_old.add(token)
    if not found:
        return None
    if not texts_old:
        return 1.0 if texts_recent else 0.0
    return (len(texts_recent) - len(texts_old)) / float(len(texts_old))


def _problem_recurrence(sub):
    """해결과제 반복 등장 비율: 1 - 고유 과제 수/과제 보유 문헌 수 (0=모두 상이)."""
    if "problem" not in sub.columns:
        return None
    probs = sub["problem"].dropna().astype(str).str.strip()
    probs = probs[(probs != "") & (probs.str.lower() != "nan")]
    if not len(probs):
        return None
    return 1.0 - probs.nunique() / float(len(probs))


def _own_capability(df, tech, settings):
    """자사 역량 보유 여부·점수 (가용한 방식만, 없으면 None)."""
    in_tech = df["_tech_list"].map(lambda lst: tech in (lst or []))
    # ① 자사 특허 분포
    own_mask = df["_is_own_bool"].map(lambda v: v is True)
    if own_mask.any():
        n_own = int((in_tech & own_mask).sum())
        if n_own > 0:
            return True, 1.0, "자사 특허 %d건 보유" % n_own
        own_techs = set(t for lst in df.loc[own_mask, "_tech_list"] for t in (lst or []))
        neighbors, _, _ = combo_counts(df)
        adj = set()
        for _, r in (neighbors.iterrows() if len(neighbors) else []):
            if r["a"] == tech:
                adj.add(r["b"])
            elif r["b"] == tech:
                adj.add(r["a"])
        overlap = own_techs & adj
        if overlap:
            return True, 0.5, "인접 분류(%s)에 자사 특허 보유" % ", ".join(list(overlap)[:3])
        return False, 0.0, None
    # ② 임베딩 거리
    if "_embedding" in df.columns:
        own_vecs = [v for v, o in zip(df["_embedding"], df["_is_own_bool"]) if o is True and v is not None]
        area_vecs = [v for v, t in zip(df["_embedding"], in_tech) if t and v is not None]
        if own_vecs and area_vecs:
            sim = cosine_sim_vec(np.mean(own_vecs, axis=0), np.mean(area_vecs, axis=0))
            return sim > 0.5, float(max(sim, 0.0)), "자사 임베딩 유사도 %.2f" % sim
    # ③ 사용자 입력 보유 기술목록
    keywords = [str(k).strip().lower() for k in (settings or {}).get("own_capability_keywords", []) if str(k).strip()]
    if keywords:
        t_low = str(tech).lower()
        hit = [k for k in keywords if k in t_low or t_low in k]
        if hit:
            return True, 0.8, "보유 기술목록 일치: %s" % hit[0]
        return False, 0.0, None
    return None, None, None


def compute_opportunity(df, settings):
    """Actionable White Space Map 계산."""
    if not len(df):
        return empty_result()
    mode = settings.get("multiclass_mode", "duplicate")
    mat = tech_year_matrix(df, multiclass_mode=mode)
    if mat.empty:
        return empty_result("연도·기술분류 데이터가 없어 계산할 수 없습니다.")
    recent = int(get_threshold(settings, "recent_years"))
    min_n = get_threshold(settings, "min_class_patents")
    y_max = int(mat.columns.max())
    recent_from = y_max - recent + 1
    now = pd.Timestamp.now()

    pairs, _, _ = combo_counts(df, recent_year_from=recent_from)
    combo_new_by_tech, combo_old_by_tech, adjacency = {}, {}, {}
    for _, r in (pairs.iterrows() if len(pairs) else []):
        first = min(r["years"]) if r["years"] else None
        bucket = combo_new_by_tech if (first is not None and first >= recent_from) \
            else combo_old_by_tech
        for t in (r["a"], r["b"]):
            bucket[t] = bucket.get(t, 0) + 1
            adjacency[t] = adjacency.get(t, 0) + 1

    rows = []
    for tech, series in mat.iterrows():
        total = float(series.sum())
        if total < min_n:
            continue
        in_tech = df["_tech_list"].map(lambda lst: tech in (lst or []))
        sub = df[in_tech]
        growth, g_method = robust_growth(series, recent_years=recent)
        recent_apps = set(sub.loc[sub["_base_year"] >= recent_from, "applicant_display"]
                          .replace("", np.nan).dropna())
        old_apps = set(sub.loc[sub["_base_year"] < recent_from, "applicant_display"]
                       .replace("", np.nan).dropna())
        new_entrants = len(recent_apps - old_apps)
        combo_new = combo_new_by_tech.get(tech, 0)
        combo_old = combo_old_by_tech.get(tech, 0)
        combo_growth = safe_div(combo_new - combo_old, combo_old,
                                1.0 if combo_new else 0.0)
        kw_growth = _keyword_growth(sub, recent_from)
        prob_rec = _problem_recurrence(sub)
        adjacency_n = adjacency.get(tech, 0)

        # 권리장벽 성분
        active_granted = int((sub["_active_flag"].map(lambda v: v is True)
                              & sub["_is_granted_bool"].map(lambda v: v is True)).sum())
        counts = sub["applicant_display"].replace("", np.nan).dropna().value_counts()
        cr3 = float(counts.head(3).sum()) / total if total else 0.0
        if "cites_forward" in sub.columns and sub["cites_forward"].notna().any():
            cites = sub["cites_forward"].fillna(0)
            top_cites = float(cites.nlargest(max(int(len(cites) * 0.1), 1)).sum())
            core_conc = safe_div(top_cites, float(cites.sum()), 0.0)
        else:
            core_conc = None
        fam_scope = (float(sub["family_country_count"].dropna().mean())
                     if "family_country_count" in sub.columns
                     and sub["family_country_count"].notna().any() else None)
        if "expiry_date" in sub.columns and sub["expiry_date"].notna().any():
            remain = (sub["expiry_date"] - now).dt.days / 365.25
            remain_years = float(remain[remain > 0].mean()) if (remain > 0).any() else 0.0
        else:
            remain_years = None

        own_flag, own_score, own_reason = _own_capability(df, tech, settings)
        rows.append({
            "tech": str(tech), "total": round(total, 1),
            "growth": growth if growth is not None else 0.0, "growth_method": g_method,
            "new_entrants": new_entrants, "combo_growth": float(combo_growth),
            "keyword_growth": kw_growth, "problem_recurrence": prob_rec,
            "adjacency": adjacency_n, "active_granted": active_granted,
            "cr3": round(cr3, 3), "core_concentration": core_conc,
            "family_scope": fam_scope, "remain_years": remain_years,
            "own_capability": own_flag, "own_score": own_score, "own_reason": own_reason,
        })
    if not rows:
        return empty_result("최소 표본(%d건) 이상의 기술분류가 없습니다." % int(min_n))

    winsor = get_threshold(settings, "winsor_pct")

    def norm(key, log=True, default=0.0):
        return normalize_series(
            [r[key] if r[key] is not None else default for r in rows],
            log=log, winsor_pct=winsor)

    comp = {
        "growth": normalize_series([max(r["growth"], 0.0) for r in rows], log=False,
                                   winsor_pct=winsor),
        "new_entrants": norm("new_entrants"),
        "combo_growth": normalize_series([max(r["combo_growth"], 0.0) for r in rows],
                                         log=False, winsor_pct=winsor),
        "keyword_growth": normalize_series(
            [max(r["keyword_growth"], 0.0) if r["keyword_growth"] is not None else 0.0
             for r in rows], log=False, winsor_pct=winsor),
        "problem_recurrence": norm("problem_recurrence", log=False),
        "adjacency": norm("adjacency"),
    }
    barrier_parts = {
        "active_granted": norm("active_granted"),
        "cr3": norm("cr3", log=False),
        "core_concentration": norm("core_concentration", log=False),
        "family_scope": norm("family_scope"),
        "remain_years": norm("remain_years"),
    }
    weights = get_weights(settings, "opportunity")
    opp_keys = ["growth", "new_entrants", "combo_growth", "keyword_growth",
                "problem_recurrence", "adjacency"]
    for i, r in enumerate(rows):
        components = {k: float(comp[k][i]) for k in opp_keys}
        barrier = float(np.mean([barrier_parts[k][i] for k in barrier_parts]))
        attractiveness = weighted_geometric_mean(
            components, {k: weights.get(k, 1.0) for k in opp_keys}) or 0.0
        entry = 1.0 - min(barrier * max(weights.get("barrier", 1.0), 0.01), 1.0)
        r["components"] = components
        r["barrier"] = round(barrier, 4)
        r["attractiveness"] = round(attractiveness, 4)
        r["entry_possibility"] = round(entry, 4)
        r["opportunity_score"] = round(attractiveness * max(entry, 1e-3), 4)
    rows.sort(key=lambda r: -r["opportunity_score"])
    max_points = get_limit(settings, "bubble_max_points")
    shown = rows[:max_points]

    points, own_points = [], []
    for r in shown:
        hover = ("<b>%s</b><br>Opportunity %s (매력도 %s × 진입 %s)<br>"
                 "특허 %s건 / 성장률 %s / 신규 %s개사<br>장벽 %s (유효등록 %s건, CR3 %s)%s"
                 % (r["tech"], r["opportunity_score"], r["attractiveness"],
                    r["entry_possibility"], fmt_num(r["total"]), fmt_pct(r["growth"]),
                    fmt_num(r["new_entrants"]), r["barrier"],
                    fmt_num(r["active_granted"]), fmt_pct(r["cr3"]),
                    ("<br>자사 역량: " + r["own_reason"]) if r["own_reason"] else ""))
        p = {"x": r["attractiveness"], "y": r["entry_possibility"], "size": r["total"],
             "color": r["barrier"], "label": r["tech"], "hover": hover,
             "customdata": {"drill": {"type": "tech", "tech": r["tech"]},
                            "components": r["components"], "barrier": r["barrier"],
                            "total": r["total"], "tech": r["tech"],
                            "own": bool(r["own_capability"])}}
        (own_points if r["own_capability"] else points).append(p)

    def _trace(pts, symbol, name):
        if not pts:
            return None
        sizes = [max(float(p["size"]), 1.0) for p in pts]
        smax = max(sizes)
        return {"type": "scatter", "mode": "markers", "name": name,
                "x": [p["x"] for p in pts], "y": [p["y"] for p in pts],
                "hovertext": [p["hover"] for p in pts], "hoverinfo": "text",
                "customdata": [p["customdata"] for p in pts],
                "marker": {"symbol": symbol, "size": sizes, "sizemode": "area",
                           "sizeref": 2.0 * smax / (40 ** 2), "sizemin": 5,
                           "color": [p["color"] for p in pts], "colorscale": "RdYlGn",
                           "reversescale": True, "showscale": symbol == "circle",
                           "colorbar": {"title": "권리장벽", "thickness": 12},
                           "line": {"width": 2 if symbol != "circle" else 1,
                                    "color": "#1f5fbf" if symbol != "circle" else "#333"},
                           "opacity": 0.85}}
    traces = [t for t in (_trace(points, "circle", "일반 영역"),
                          _trace(own_points, "diamond", "자사 역량 보유")) if t]
    fig = {"data": traces, "layout": base_layout(
        "Actionable White Space Map (Opportunity Matrix)",
        xaxis={"title": "매력도 (기회 점수)", "range": [-0.05, 1.05]},
        yaxis={"title": "진입 가능성 (1 - 권리장벽)", "range": [-0.05, 1.05]},
        shapes=[{"type": "line", "x0": 0.5, "x1": 0.5, "y0": -0.05, "y1": 1.05,
                 "line": {"color": "#bbb", "dash": "dot", "width": 1}},
                {"type": "line", "y0": 0.5, "y1": 0.5, "x0": -0.05, "x1": 1.05,
                 "line": {"color": "#bbb", "dash": "dot", "width": 1}}],
        annotations=[
            {"x": 0.97, "y": 0.97, "xref": "x", "yref": "y", "text": "우선 공략",
             "showarrow": False, "font": {"size": 11, "color": "#2e7d32"}},
            {"x": 0.97, "y": 0.03, "xref": "x", "yref": "y", "text": "매력적·고장벽 (제휴/라이선스)",
             "showarrow": False, "font": {"size": 11, "color": "#c62828"}, "xanchor": "right"},
            {"x": 0.03, "y": 0.97, "xref": "x", "yref": "y", "text": "저매력·저장벽",
             "showarrow": False, "font": {"size": 11, "color": "#888"}, "xanchor": "left"}])}

    sentences, metrics = [], {}
    top = shown[0] if shown else None
    if top:
        strongest = max(top["components"], key=top["components"].get)
        comp_labels = {"growth": "성장률", "new_entrants": "신규 출원인",
                       "combo_growth": "조합 증가", "keyword_growth": "키워드 증가",
                       "problem_recurrence": "과제 반복", "adjacency": "인접 연결성"}
        sentences.append(
            "%s 기준 Opportunity Score 1위 영역은 '%s'(%s, 상위 %.0f%%)이며 핵심 근거는 "
            "%s(정규화 %s)입니다. 성장률 %s·신규 %s개사가 긍정 요인, 유효등록 %s건·CR3 %s가 "
            "위험 요인입니다."
            % (period_label(df), top["tech"], top["opportunity_score"],
               100.0 / max(len(rows), 1), comp_labels.get(strongest, strongest),
               fmt_num(top["components"][strongest], 2), fmt_pct(top["growth"]),
               fmt_num(top["new_entrants"]), fmt_num(top["active_granted"]),
               fmt_pct(top["cr3"])))
        metrics.update({"top_area": top["tech"], "top_score": top["opportunity_score"]})
    high_barrier = [r for r in shown if r["barrier"] > 0.7]
    if high_barrier:
        sentences.append("권리장벽 점수 0.7 초과 영역이 %s개 있어 해당 영역 진입 시 선행 권리 "
                         "검토가 필요합니다." % fmt_num(len(high_barrier)))
    insight = build_insight(sentences, metrics,
                            drills=[{"label": "1위 영역 근거 특허",
                                     "drill": {"type": "tech", "tech": top["tech"]}}] if top else [],
                            small_sample=check_small_sample(len(rows), settings))
    return ok_result({"figure": fig, "areas": shown[:60],
                      "weights": weights, "opportunity_keys": opp_keys},
                     insight=insight, meta={"truncated": len(rows) > len(shown)})


# ===========================================================================
# src/analyses/problem_solution.py
# ===========================================================================
# -*- coding: utf-8 -*-
"""
analyses/problem_solution.py — 문제–해결수단 매트릭스 (1단계).

분석 목적:
  해결과제(행) × 해결수단(열) 매트릭스로 R&D 접근 조합의 밀집/공백을 파악한다.

필수 컬럼: 해결과제, 해결수단 — 없으면 분석 비활성화 + 텍스트 추출 모듈 연결
  인터페이스 안내만 제공 (임의 추출 결과 생성 금지).
선택 컬럼: 날짜(성장률), 출원인(상위 출원인), 독립청구항(대표 청구항), 유효특허 여부

계산식:
  셀 값 = 특허 수 / 셀 색상 = 최근 성장률(robust_growth) / 셀 테두리 = 권리장벽
  (유효등록 비율 — hover 로 제공). 행·열은 빈도 상위 matrix_max_rows/cols 로 제한.
  Opportunity Score(셀) = 정규화(성장률) × (1 - 유효등록비율) — 경량 산식.

그래프: Plotly 히트맵 (셀 수가 heatmap_max_cells 초과 시 ECharts 옵션 반환).
Drill-down: 셀 클릭 → {"type":"cell","problem":…,"solution":…} → 패널에
  관련 특허 리스트·상위 출원인·연도별 추이·대표 청구항·유효특허 비율·Score·인사이트.
자동 인사이트: 최다 셀, 최근 고성장 셀, 공백(행·열 존재하나 셀 0) 개수.
예외처리: 두 컬럼 중 하나라도 없으면 disabled_result(필요 컬럼 안내).
"""
import numpy as np
import pandas as pd



def _clean_text_series(s):
    out = s.astype(str).str.strip()
    return out.where(~out.str.lower().isin(["nan", "none", ""]), other=None)


def compute_problem_solution(df, settings):
    """문제–해결수단 매트릭스 계산."""
    missing = [label for col, label in (("problem", "해결과제"), ("solution", "해결수단"))
               if col not in df.columns]
    if missing:
        return disabled_result(
            missing,
            message=("필수 컬럼(%s)이 없어 문제–해결수단 매트릭스를 사용할 수 없습니다. "
                     "사전 추출 결과 컬럼을 매핑하거나, 텍스트 추출 모듈(요약/청구항 → "
                     "해결과제·해결수단)을 연결한 뒤 결과 컬럼을 매핑하세요. "
                     "임의 추출은 수행하지 않습니다." % ", ".join(missing)))
    if not len(df):
        return empty_result()
    work = df.copy()
    work["problem"] = _clean_text_series(work["problem"])
    work["solution"] = _clean_text_series(work["solution"])
    work = work[work["problem"].notna() & work["solution"].notna()]
    if not len(work):
        return empty_result("해결과제·해결수단 값이 있는 특허가 없습니다.")

    max_rows = get_limit(settings, "matrix_max_rows")
    max_cols = get_limit(settings, "matrix_max_cols")
    top_problems = work["problem"].value_counts().head(max_rows).index.tolist()
    top_solutions = work["solution"].value_counts().head(max_cols).index.tolist()
    sub = work[work["problem"].isin(top_problems) & work["solution"].isin(top_solutions)]
    if not len(sub):
        return empty_result()

    recent = int(get_threshold(settings, "recent_years"))
    counts = sub.pivot_table(index="problem", columns="solution", values="_base_year",
                             aggfunc="size", fill_value=0)
    counts = counts.reindex(index=top_problems, columns=top_solutions, fill_value=0)

    # 셀별 성장률·유효비율·상위 출원인
    growth_z, hover, cell_meta = [], [], {}
    for p in top_problems:
        g_row, h_row = [], []
        for s in top_solutions:
            cell = sub[(sub["problem"] == p) & (sub["solution"] == s)]
            n = len(cell)
            if n == 0:
                g_row.append(None)
                h_row.append("%s × %s<br>0건 (공백)" % (p[:40], s[:40]))
                continue
            years = cell["_base_year"].dropna()
            growth, _ = (robust_growth(year_counts(years.astype(int)), recent_years=recent)
                         if len(years) >= 2 else (None, "insufficient"))
            flags = cell["_active_flag"]
            known = flags.map(lambda v: v is not None)
            active_ratio = (float(flags[known].map(lambda v: v is True).mean())
                            if known.any() else None)
            top_apps = cell["applicant_display"].replace("", np.nan).dropna() \
                .value_counts().head(3)
            g_row.append(growth if growth is not None else 0.0)
            h_row.append("<b>%s × %s</b><br>%s건 / 성장률 %s / 유효비율 %s<br>상위: %s"
                         % (p[:40], s[:40], fmt_num(n),
                            fmt_pct(growth) if growth is not None else "-",
                            fmt_pct(active_ratio) if active_ratio is not None else "미상",
                            ", ".join("%s(%d)" % (a[:14], c) for a, c in top_apps.items())))
            cell_meta["%s|||%s" % (p, s)] = {
                "count": n, "growth": growth, "active_ratio": active_ratio,
                "top_applicants": [{"name": str(a), "count": int(c)}
                                   for a, c in top_apps.items()]}
        growth_z.append(g_row)
        hover.append(h_row)

    n_cells = len(top_problems) * len(top_solutions)
    use_echarts = n_cells > get_limit(settings, "heatmap_max_cells")
    z_counts = [[int(counts.loc[p, s]) for s in top_solutions] for p in top_problems]
    if use_echarts and n_cells > get_limit(settings, "echarts_threshold_cells"):
        fig = echarts_heatmap(z_counts, top_solutions, top_problems,
                              title="문제–해결수단 매트릭스 (건수)")
    else:
        fig = heatmap(growth_z, top_solutions, top_problems,
                      title="문제–해결수단 매트릭스 (색=최근 성장률, hover=건수·장벽)",
                      colorscale="RdYlGn", hovertext=hover, colorbar_title="성장률", zmid=0)
        fig["counts_z"] = z_counts

    zeros = int(sum(1 for row in z_counts for v in row if v == 0))
    flat = [(p, s, int(counts.loc[p, s])) for p in top_problems for s in top_solutions
            if counts.loc[p, s] > 0]
    flat.sort(key=lambda t: -t[2])
    sentences, metrics = [], {"n_cells": n_cells, "empty_cells": zeros}
    if flat:
        p0, s0, c0 = flat[0]
        sentences.append("%s 기준 최다 조합은 '%s × %s'(%s건)이며, 매트릭스 %s개 셀 중 "
                         "%s개(%s)가 공백입니다."
                         % (period_label(work), p0, s0, fmt_num(c0), fmt_num(n_cells),
                            fmt_num(zeros), fmt_pct(zeros / float(n_cells))))
    growth_cells = [(p, s, g) for p, row in zip(top_problems, growth_z)
                    for s, g in zip(top_solutions, row) if g is not None and g > 0.3
                    and cell_meta.get("%s|||%s" % (p, s), {}).get("count", 0) >= 3]
    if growth_cells:
        growth_cells.sort(key=lambda t: -t[2])
        p1, s1, g1 = growth_cells[0]
        sentences.append("최근 성장률이 가장 높은 조합은 '%s × %s'(%s)로 긍정 요인이며, "
                         "동일 셀 진입 기업 증가는 위험 요인입니다."
                         % (p1, s1, fmt_pct(g1)))
    insight = build_insight(
        sentences, metrics,
        drills=[{"label": "최다 셀 근거 특허",
                 "drill": {"type": "cell", "problem": flat[0][0], "solution": flat[0][1]}}]
        if flat else [],
        small_sample=check_small_sample(len(sub), settings))
    return ok_result({"figure": fig, "problems": top_problems, "solutions": top_solutions,
                      "cells": cell_meta, "engine": "echarts" if use_echarts else "plotly"},
                     insight=insight,
                     meta={"n_with_ps": int(len(work)), "truncated":
                           len(work["problem"].unique()) > len(top_problems)
                           or len(work["solution"].unique()) > len(top_solutions)})


def cell_detail(df, settings, problem, solution):
    """셀 클릭 패널 데이터: 연도별 추이·상위 출원인·대표 청구항·유효비율·인사이트."""
    if "problem" not in df.columns or "solution" not in df.columns:
        return disabled_result(["해결과제", "해결수단"])
    cell = df[(df["problem"].astype(str).str.strip() == str(problem))
              & (df["solution"].astype(str).str.strip() == str(solution))]
    if not len(cell):
        return empty_result("해당 조합의 특허가 없습니다.")
    years = cell["_base_year"].dropna().astype(int)
    trend = year_counts(years) if len(years) else pd.Series(dtype=float)
    recent = int(get_threshold(settings, "recent_years"))
    growth, _ = robust_growth(trend, recent_years=recent) if len(trend) else (None, "n/a")
    flags = cell["_active_flag"]
    known = flags.map(lambda v: v is not None)
    active_ratio = float(flags[known].map(lambda v: v is True).mean()) if known.any() else None
    top_apps = cell["applicant_display"].replace("", np.nan).dropna().value_counts().head(5)
    rep_claim = None
    if "indep_claim" in cell.columns:
        claims = cell["indep_claim"].dropna().astype(str)
        claims = claims[claims.str.strip() != ""]
        if len(claims):
            rep_claim = claims.iloc[0][:600]
    norm_growth = float(normalize_series([max(growth or 0, 0)], log=False)[0]) if growth else 0.0
    opp = round(norm_growth * (1 - (active_ratio or 0)), 4)
    sentences = ["'%s × %s' 조합은 총 %s건이며 최근 성장률 %s, 유효특허 비율 %s입니다."
                 % (str(problem)[:40], str(solution)[:40], fmt_num(len(cell)),
                    fmt_pct(growth) if growth is not None else "계산 불가",
                    fmt_pct(active_ratio) if active_ratio is not None else "미상")]
    insight = build_insight(sentences, {"opportunity_score": opp},
                            small_sample=check_small_sample(len(cell), settings))
    return ok_result({
        "count": int(len(cell)), "growth": growth, "active_ratio": active_ratio,
        "opportunity_score": opp,
        "trend": {"years": [int(y) for y in trend.index], "counts": [float(v) for v in trend.values]},
        "top_applicants": [{"name": str(a), "count": int(c)} for a, c in top_apps.items()],
        "representative_claim": rep_claim,
    }, insight=insight)


# ===========================================================================
# src/analyses/transition.py
# ===========================================================================
# -*- coding: utf-8 -*-
"""
analyses/transition.py — 4.1 기술분류 전이 Sankey Diagram (2단계).

분석 목적:
  기간별로 포트폴리오의 기술 중심이 어떤 기술분류에서 다른 기술분류로 이동했는지
  Sankey 로 표현한다.

필수 컬럼: 기술분류(any), 날짜(any)
선택 컬럼: 패밀리 ID(모드1), 출원인(모드2), 출원번호/패밀리(모드3 근사)

전이 정의 4종 (mode 파라미터, 드롭다운):
  family      ① 동일 패밀리 내 기술분류 변화: 같은 family_id 문헌들을 시간순 정렬,
                 이전 기간 분류 → 다음 기간 분류 링크.
  applicant   ② 동일 출원인의 기간별 포트폴리오 변화: 출원인별 (이전 기간 분류 집합
                 × 다음 기간 분류 집합) 링크 — 규모 왜곡 방지 위해 1/(|S|·|T|) 가중.
  continuation③ 후속출원 기준: 동일 패밀리 내 출원일이 다른 문헌 쌍(선→후)의 분류
                 변화 (계속·분할출원 데이터가 별도로 없으므로 패밀리 내 시차 출원을
                 후속출원으로 간주 — 근사임을 meta 에 명시).
  cooccurrence④ 기술분류 간 공동출현 증가 기준: 이전 기간 대비 다음 기간에 공동출현이
                 증가한 조합을 전이 신호 링크로 표시 (링크값 = 증가량).

기간 분할: 사용자 지정 period_years(기본 recent_years)로 [이전 기간 | 다음 기간]
을 나눈다 (연도 필터 적용 후 최근 2개 구간).

그래프: Source=이전 기간 분류, Target=다음 기간 분류, Link=전이량, 색=대분류.
Drill-down: 링크 클릭 {"type":"transition","source":…,"target":…}.
자동 인사이트: 최대 전이 링크, 순유입 상위 분류.
예외처리: 구간 데이터 부족 시 empty. 링크 수 상한 sankey_max_links.
"""
import numpy as np


TRANSITION_MODES = ["family", "applicant", "continuation", "cooccurrence"]


def _split_periods(df, period_years):
    years = df["_base_year"].dropna()
    if not len(years):
        return None
    y_max = int(years.max())
    cur_from = y_max - period_years + 1
    prev_from = cur_from - period_years
    prev = df[(df["_base_year"] >= prev_from) & (df["_base_year"] < cur_from)]
    cur = df[df["_base_year"] >= cur_from]
    label_prev = "%d–%d" % (prev_from, cur_from - 1)
    label_cur = "%d–%d" % (cur_from, y_max)
    return prev, cur, label_prev, label_cur


def _links_family(prev, cur):
    """모드①/③: 동일 패밀리의 이전 기간 분류 → 다음 기간 분류."""
    links = {}
    if "family_id" not in prev.columns:
        return None
    prev_map = {}
    for fid, techs in zip(prev["family_id"], prev["_tech_list"]):
        if fid is None or (isinstance(fid, float) and np.isnan(fid)):
            continue
        prev_map.setdefault(str(fid), set()).update(techs or [])
    for fid, techs in zip(cur["family_id"], cur["_tech_list"]):
        key = str(fid)
        if key not in prev_map:
            continue
        src_set, tgt_set = prev_map[key], set(techs or [])
        if not src_set or not tgt_set:
            continue
        w = 1.0 / (len(src_set) * len(tgt_set))
        for s in src_set:
            for t in tgt_set:
                links[(s, t)] = links.get((s, t), 0.0) + w
    return links


def _links_applicant(prev, cur):
    """모드②: 동일 출원인의 기간별 포트폴리오 변화 (1/(|S||T|) 가중)."""
    links = {}
    prev_map = {}
    for app, techs in zip(prev["applicant_display"], prev["_tech_list"]):
        if app:
            prev_map.setdefault(str(app), set()).update(techs or [])
    cur_map = {}
    for app, techs in zip(cur["applicant_display"], cur["_tech_list"]):
        if app:
            cur_map.setdefault(str(app), set()).update(techs or [])
    for app, tgt_set in cur_map.items():
        src_set = prev_map.get(app)
        if not src_set or not tgt_set:
            continue
        w = 1.0 / (len(src_set) * len(tgt_set))
        for s in src_set:
            for t in tgt_set:
                links[(s, t)] = links.get((s, t), 0.0) + w
    return links


def _links_cooccurrence(prev, cur):
    """모드④: 공동출현 증가 조합 (증가량을 링크값으로)."""
    def pair_counts(frame):
        from itertools import combinations
        counts = {}
        for techs in frame["_tech_list"]:
            uniq = sorted(set(techs or []))
            for a, b in combinations(uniq, 2):
                counts[(a, b)] = counts.get((a, b), 0) + 1
        return counts
    p_prev, p_cur = pair_counts(prev), pair_counts(cur)
    links = {}
    for pair, n_cur in p_cur.items():
        inc = n_cur - p_prev.get(pair, 0)
        if inc > 0:
            links[pair] = float(inc)
    return links


def compute_transition(df, settings, mode=None, period_years=None):
    """기술분류 전이 Sankey 계산."""
    if not len(df):
        return empty_result()
    mode = mode if mode in TRANSITION_MODES else settings.get("transition_mode", "cooccurrence")
    period_years = int(period_years or get_threshold(settings, "recent_years"))
    split = _split_periods(df, period_years)
    if split is None:
        return empty_result("연도 정보가 없어 기간을 나눌 수 없습니다.")
    prev, cur, label_prev, label_cur = split
    if not len(prev) or not len(cur):
        return empty_result("이전/다음 기간 중 한쪽에 데이터가 없어 전이를 계산할 수 없습니다.")

    if mode == "family":
        links = _links_family(prev, cur)
        if links is None:
            return empty_result("패밀리 ID 컬럼이 없어 '동일 패밀리' 전이를 계산할 수 없습니다. "
                                "다른 전이 정의를 선택하세요.")
    elif mode == "continuation":
        links = _links_family(prev, cur)  # 패밀리 내 시차 출원을 후속출원으로 근사
        if links is None:
            return empty_result("패밀리 ID 컬럼이 없어 후속출원 기준 전이를 계산할 수 없습니다.")
    elif mode == "applicant":
        links = _links_applicant(prev, cur)
    else:
        links = _links_cooccurrence(prev, cur)
    links = {k: v for k, v in links.items() if v > 0}
    if not links:
        return empty_result("선택한 전이 정의로 관측된 전이가 없습니다.")

    max_links = get_limit(settings, "sankey_max_links")
    top_links = sorted(links.items(), key=lambda kv: -kv[1])[:max_links]

    l1_lookup = build_l1_lookup(df)
    color_reg = {}
    node_index, nodes = {}, []

    def node_id(name, side):
        key = (name, side)
        if key not in node_index:
            node_index[key] = len(nodes)
            l1 = str(l1_lookup.get(name, "기타"))
            label = "%s (%s)" % (name, label_prev if side == "src" else label_cur)
            nodes.append({"label": label, "color": color_for(l1, color_reg),
                          "tech": name, "side": side})
        return node_index[key]

    link_payload = []
    for (s, t), v in top_links:
        si, ti = node_id(s, "src"), node_id(t, "tgt")
        l1 = str(l1_lookup.get(s, "기타"))
        base = color_for(l1, color_reg)
        link_payload.append({"source": si, "target": ti, "value": round(float(v), 3),
                             "color": base + "59",  # 알파 추가
                             "customdata": {"drill": {"type": "transition",
                                                      "source": s, "target": t}}})
    fig = sankey(nodes, link_payload,
                 title="기술분류 전이 (%s → %s, 정의: %s)" % (label_prev, label_cur, mode))

    inflow = {}
    for (s, t), v in top_links:
        if s != t:
            inflow[t] = inflow.get(t, 0.0) + v
            inflow[s] = inflow.get(s, 0.0) - v
    sentences = []
    if top_links:
        (s0, t0), v0 = top_links[0]
        sentences.append("%s → %s 구간 최대 전이 링크는 '%s → %s'(전이량 %s, 정의=%s)입니다."
                         % (label_prev, label_cur, s0, t0, fmt_num(v0, 2), mode))
    if inflow:
        top_in = max(inflow, key=inflow.get)
        if inflow[top_in] > 0:
            sentences.append("순유입이 가장 큰 분류는 '%s'(순유입 %s)로 포트폴리오 중심 이동의 "
                             "목적지로 해석됩니다 (탐색적 신호)." % (top_in, fmt_num(inflow[top_in], 2)))
    insight = build_insight(sentences, {"n_links": len(top_links)},
                            small_sample=check_small_sample(len(cur), settings))
    return ok_result({"figure": fig, "mode": mode,
                      "period_prev": label_prev, "period_cur": label_cur},
                     insight=insight,
                     meta={"note": ("후속출원 기준은 패밀리 내 시차 출원 근사입니다."
                                    if mode == "continuation" else None),
                           "truncated": len(links) > len(top_links)})


# ===========================================================================
# src/analyses/trajectory.py
# ===========================================================================
# -*- coding: utf-8 -*-
"""
analyses/trajectory.py — 4.4 Technology Trajectory Map (기업별 전략 이동 궤적, 2단계).

분석 목적:
  기업·연도별 기술분류 구성비 벡터를 2차원에 투영하여, 기업 전략의 이동 궤적을
  화살표로 연결해 시각화한다.

필수 컬럼: 기술분류(any), 날짜(any), 출원인(any)
선택 컬럼: 유효특허 여부(점 크기), 패밀리 ID

계산식:
  1) 기업·연도별 기술분류 구성비 벡터 (company_tech_shares(by_year=True))
     - 출원량 차이 왜곡 방지: weighting='share'(구성비) 또는 'tfidf'
       (구성비 × log(전체 기업 수 / 해당 분류 보유 기업 수)) 선택 옵션.
  2) 차원축소: method='pca'(기본) | 'umap' — UMAP 불가 시 PCA 자동 폴백 (gpu_utils).
  3) 기업별 연도 순 점 연결 화살표, 이동거리 = 연속 연도 좌표 간 유클리드 거리 합.

그래프: 점(기업×연도), 크기=해당 연도 유효 패밀리 수, 색=기업,
        hover=주요 기술분류 Top3·비중, 화살표=연도 순 이동.
Drill-down: 점 클릭 {"type":"applicant","applicant":…,"year":…}.
자동 인사이트: 이동거리 상위 기업, 최근 방향 전환 기업.
예외처리: 최소 관측(기업당 2개 연도, 연도당 min_class_patents 건) 미달 기업 제외.
대상 기업: companies 파라미터 또는 출원 상위 trajectory_max_companies 개.
"""
import numpy as np



def compute_trajectory(df, settings, companies=None, method="pca", weighting=None):
    """Technology Trajectory Map 계산."""
    if not len(df):
        return empty_result()
    weighting = weighting or settings.get("trajectory_weighting", "share")
    shares = company_tech_shares(df, multiclass_mode=settings.get("multiclass_mode", "duplicate"),
                                 by_year=True)
    if shares.empty:
        return empty_result("기업·연도별 구성비를 만들 데이터가 없습니다.")

    min_n = get_threshold(settings, "min_class_patents")
    max_companies = get_limit(settings, "trajectory_max_companies")
    tmp = df[df["_base_year"].notna()].copy()
    tmp["_year_int"] = tmp["_base_year"].astype(int)
    counts = tmp.groupby(["applicant_display", "_year_int"]).size()

    if companies:
        wanted = [str(c) for c in companies][:max_companies]
    else:
        totals = df["applicant_display"].replace("", np.nan).dropna().value_counts()
        wanted = totals.head(max_companies).index.tolist()

    rows = []
    for (company, year) in shares.index:
        if str(company) not in wanted:
            continue
        n = counts.get((company, year), 0)
        if n < min_n:
            continue
        rows.append((str(company), int(year)))
    # 기업당 최소 2개 연도
    by_company = {}
    for c, y in rows:
        by_company.setdefault(c, []).append(y)
    by_company = {c: sorted(ys) for c, ys in by_company.items() if len(ys) >= 2}
    if not by_company:
        return empty_result("연도당 최소 %d건·2개 연도 이상 관측된 기업이 없습니다." % int(min_n))

    keys = [(c, y) for c, ys in by_company.items() for y in ys]
    X = np.vstack([shares.loc[(c, y)].values for c, y in keys])
    if weighting == "tfidf":
        presence = (shares.loc[[k for k in keys]] > 0).sum(axis=0).values.astype(float)
        idf = np.log((len(keys) + 1.0) / (presence + 1.0)) + 1.0
        X = X * idf

    if X.shape[0] < 3 or X.shape[1] < 2:
        return empty_result("차원축소에 필요한 표본이 부족합니다.")
    if method == "umap":
        emb, used_method = run_umap(X, n_components=2)
    else:
        emb, used_method = run_pca(X, n_components=2)
    if emb.shape[1] < 2:
        emb = np.hstack([emb, np.zeros((emb.shape[0], 1))])

    coords = {k: (float(emb[i, 0]), float(emb[i, 1])) for i, k in enumerate(keys)}
    act = tmp[tmp["_active_flag"].map(lambda v: v is True)]
    active_counts = act.groupby(["applicant_display", "_year_int"]).size() if len(act) else None

    traces, annotations = [], []
    company_stats = []
    for ci, (company, years) in enumerate(sorted(by_company.items())):
        color = PALETTE[ci % len(PALETTE)]
        xs, ys_, sizes, hovers, custom = [], [], [], [], []
        dist = 0.0
        for j, y in enumerate(years):
            x, yy = coords[(company, y)]
            xs.append(x)
            ys_.append(yy)
            top_shares = shares.loc[(company, y)].sort_values(ascending=False).head(3)
            share_txt = ", ".join("%s %.0f%%" % (t[:14], s * 100)
                                  for t, s in top_shares.items() if s > 0)
            n_total = int(counts.get((company, y), 0))
            n_active = int(active_counts.get((company, y), 0)) if active_counts is not None else n_total
            sizes.append(max(n_active, 1))
            hovers.append("<b>%s — %d</b><br>%s건 (유효 %s)<br>주요: %s"
                          % (company, y, fmt_num(n_total), fmt_num(n_active), share_txt))
            custom.append({"drill": {"type": "applicant", "applicant": company, "year": y}})
            if j > 0:
                px, py = coords[(company, years[j - 1])]
                dist += float(np.hypot(x - px, yy - py))
                annotations.append({"x": x, "y": yy, "ax": px, "ay": py,
                                    "xref": "x", "yref": "y", "axref": "x", "ayref": "y",
                                    "showarrow": True, "arrowhead": 3, "arrowsize": 0.9,
                                    "arrowwidth": 1.2, "arrowcolor": color, "text": "",
                                    "opacity": 0.7})
        smax = max(sizes)
        traces.append({"type": "scatter", "mode": "markers+text", "name": company,
                       "x": xs, "y": ys_, "text": [str(y) for y in years],
                       "textposition": "top center", "textfont": {"size": 9},
                       "hovertext": hovers, "hoverinfo": "text", "customdata": custom,
                       "marker": {"size": sizes, "sizemode": "area",
                                  "sizeref": 2.0 * smax / (26 ** 2), "sizemin": 6,
                                  "color": color, "opacity": 0.85,
                                  "line": {"width": 1, "color": "#333"}}})
        company_stats.append({"company": company, "distance": round(dist, 3),
                              "years": years,
                              "drill": {"type": "applicant", "applicant": company}})
    layout = base_layout("Technology Trajectory Map (%s, %s 가중)" % (used_method, weighting),
                         xaxis={"title": "Dim 1", "zeroline": False},
                         yaxis={"title": "Dim 2", "zeroline": False})
    layout["annotations"] = annotations
    fig = {"data": traces, "layout": layout}

    company_stats.sort(key=lambda r: -r["distance"])
    sentences = []
    if company_stats:
        top = company_stats[0]
        sentences.append("%s 기준 전략 이동거리가 가장 큰 기업은 '%s'(누적 이동거리 %s, "
                         "관측 %d–%d년)로 포트폴리오 재편 신호입니다."
                         % (period_label(df), top["company"], fmt_num(top["distance"], 2),
                            top["years"][0], top["years"][-1]))
        stable = company_stats[-1]
        sentences.append("가장 안정적인 기업은 '%s'(이동거리 %s)입니다."
                         % (stable["company"], fmt_num(stable["distance"], 2)))
    insight = build_insight(sentences, {"n_companies": len(company_stats)},
                            small_sample=check_small_sample(len(keys), settings))
    return ok_result({"figure": fig, "companies": company_stats, "method": used_method,
                      "weighting": weighting}, insight=insight)


# ===========================================================================
# src/analyses/company_dna.py
# ===========================================================================
# -*- coding: utf-8 -*-
"""
analyses/company_dna.py — 4.5 경쟁사 기술 DNA Fingerprint (+전략 유사도·포트폴리오
중첩도, 2단계).

분석 목적:
  기업별 12개 전략 지표로 기술 DNA 를 정량화하고, 규칙 기반으로 기업 유형을
  자동 분류한다.

필수 컬럼: 기술분류(any), 날짜(any), 출원인(any)
선택 컬럼: 패밀리 수, 패밀리 국가 수, 피인용 수, 법적상태, 발명자, 패밀리 ID

12개 지표 (기업별):
   1 tech_concentration  기술 집중도 (분류 분포 HHI)
   2 tech_diversity      기술 다양성 (Shannon entropy, 정규화)
   3 new_class_entry     신규분류 진입률 (최근 구간 신규 분류 수 / 활동 분류 수)
   4 combo_diversity     기술조합 다양성 (고유 조합 수 / 문헌 수)
   5 family_size         평균 패밀리 규모
   6 intl_scope          해외 출원 범위 (평균 패밀리 국가 수)
   7 grant_keep_ratio    등록 유지율 (유효등록 / 등록)
   8 avg_citations       평균 피인용도
   9 continuation_ratio  후속출원 비율 (패밀리 내 2건 이상 보유 패밀리 비율 근사)
  10 co_apply_ratio      공동출원 비율 (출원인 2인 이상)
  11 inventor_concentration 발명자 집중도 (발명자 HHI)
  12 recent_growth       최근 3년 성장률 (robust_growth)

지표별 원값(raw)과 표준화값(0~1, normalize_series)을 함께 제공 (Hover/토글).

그래프: 기업 수 <= max_companies_compare → 레이더, 초과 → 히트맵.
        세부 비교용 평행좌표(parcoords) payload 도 항상 포함.

규칙 기반 기업 유형 (기준값 dna_type_cutoff, Settings 조정 가능):
  선도 개척형: 신규분류 진입률·최근 성장률 높음 + 피인용 높음
  권리 장벽형: 등록 유지율·패밀리 규모·해외 범위 높음
  집중 방어형: 기술 집중도 높음 + 다양성 낮음
  융합 확장형: 조합 다양성·다양성 높음
  추격 확장형: 최근 성장률 높음 + 피인용 낮음
  양적 출원형: 출원량 상위 + 피인용·유지율 낮음
  (우선순위 순서로 첫 매칭. 매칭 없으면 '균형형')

전략 유사도: 기업 간 기술 구성비 벡터 코사인 유사도 행렬.
포트폴리오 중첩도: 기업 간 분류 집합 Jaccard 중첩 행렬.
Drill-down: {"type":"applicant"}.
예외처리: 표본<min_class_patents 기업 제외.
"""
import numpy as np
import pandas as pd


DNA_METRICS = [
    ("tech_concentration", "기술 집중도(HHI)"), ("tech_diversity", "기술 다양성"),
    ("new_class_entry", "신규분류 진입률"), ("combo_diversity", "조합 다양성"),
    ("family_size", "패밀리 규모"), ("intl_scope", "해외 범위"),
    ("grant_keep_ratio", "등록 유지율"), ("avg_citations", "평균 피인용"),
    ("continuation_ratio", "후속출원 비율"), ("co_apply_ratio", "공동출원 비율"),
    ("inventor_concentration", "발명자 집중도"), ("recent_growth", "최근 성장률"),
]


def _company_metrics(sub, recent_from, recent):
    techs_flat = [t for lst in sub["_tech_list"] for t in (lst or [])]
    tech_counts = pd.Series(techs_flat).value_counts() if techs_flat else pd.Series(dtype=int)
    combos = set()
    for lst in sub["_tech_list"]:
        uniq = sorted(set(lst or []))
        from itertools import combinations
        combos.update(combinations(uniq, 2))
    recent_techs = set(t for lst, y in zip(sub["_tech_list"], sub["_base_year"])
                       for t in (lst or []) if y is not None and not
                       (isinstance(y, float) and np.isnan(y)) and y >= recent_from)
    old_techs = set(t for lst, y in zip(sub["_tech_list"], sub["_base_year"])
                    for t in (lst or []) if y is not None and not
                    (isinstance(y, float) and np.isnan(y)) and y < recent_from)
    granted = sub["_is_granted_bool"].map(lambda v: v is True)
    active_granted = granted & sub["_active_flag"].map(lambda v: v is True)
    inventors = [i for lst in (sub["_inventor_list"] if "_inventor_list" in sub.columns else [])
                 for i in (lst or [])]
    inv_counts = pd.Series(inventors).value_counts() if inventors else None
    co_apply = sub["_co_applicants"].map(lambda lst: len(lst or []) >= 2) \
        if "_co_applicants" in sub.columns else pd.Series(dtype=bool)
    fam_multi = None
    if "family_id" in sub.columns and sub["family_id"].notna().any():
        fam_sizes = sub["family_id"].astype(str).value_counts()
        fam_multi = float((fam_sizes >= 2).mean())
    elif "family_size" in sub.columns and sub["family_size"].notna().any():
        fam_multi = float((sub["family_size"].dropna() >= 2).mean())
    years = sub["_base_year"].dropna().astype(int)
    growth, _ = (robust_growth(year_counts(years), recent_years=recent)
                 if len(years) else (None, "n/a"))
    return {
        "n": len(sub),
        "tech_concentration": hhi(tech_counts.values) if len(tech_counts) else None,
        "tech_diversity": shannon_entropy(tech_counts.values, normalize=True)
        if len(tech_counts) else None,
        "new_class_entry": (len(recent_techs - old_techs) / max(len(recent_techs | old_techs), 1))
        if (recent_techs or old_techs) else None,
        "combo_diversity": len(combos) / max(len(sub), 1),
        "family_size": float(sub["family_size"].dropna().mean())
        if "family_size" in sub.columns and sub["family_size"].notna().any() else None,
        "intl_scope": float(sub["family_country_count"].dropna().mean())
        if "family_country_count" in sub.columns and sub["family_country_count"].notna().any() else None,
        "grant_keep_ratio": (float(active_granted.sum()) / float(granted.sum()))
        if granted.sum() else None,
        "avg_citations": float(sub["cites_forward"].dropna().mean())
        if "cites_forward" in sub.columns and sub["cites_forward"].notna().any() else None,
        "continuation_ratio": fam_multi,
        "co_apply_ratio": float(co_apply.mean()) if len(co_apply) else None,
        "inventor_concentration": hhi(inv_counts.values) if inv_counts is not None else None,
        "recent_growth": growth,
    }


def _classify(std, n_rank, cutoff):
    """규칙 기반 기업 유형 (표준화 점수 std: {metric: 0~1}, n_rank: 출원량 백분위)."""
    hi = lambda k: (std.get(k) or 0) >= cutoff
    lo = lambda k: (std.get(k) or 0) <= (1 - cutoff)
    if hi("new_class_entry") and hi("recent_growth") and (std.get("avg_citations") or 0) >= 0.5:
        return "선도 개척형"
    if hi("grant_keep_ratio") and ((std.get("family_size") or 0) >= 0.5
                                   or (std.get("intl_scope") or 0) >= 0.5):
        return "권리 장벽형"
    if hi("tech_concentration") and lo("tech_diversity"):
        return "집중 방어형"
    if hi("combo_diversity") and (std.get("tech_diversity") or 0) >= 0.5:
        return "융합 확장형"
    if hi("recent_growth") and lo("avg_citations"):
        return "추격 확장형"
    if n_rank >= 0.7 and lo("avg_citations") and lo("grant_keep_ratio"):
        return "양적 출원형"
    return "균형형"


def compute_company_dna(df, settings, companies=None):
    """경쟁사 기술 DNA Fingerprint 계산."""
    if not len(df):
        return empty_result()
    recent = int(get_threshold(settings, "recent_years"))
    years = df["_base_year"].dropna()
    recent_from = (int(years.max()) - recent + 1) if len(years) else 0
    min_n = get_threshold(settings, "min_class_patents")
    max_cmp = get_limit(settings, "max_companies_compare")

    totals = df["applicant_display"].replace("", np.nan).dropna().value_counts()
    if companies:
        wanted = [c for c in map(str, companies) if totals.get(c, 0) >= min_n][:30]
    else:
        wanted = [c for c in totals.index if totals[c] >= min_n][:30]
    if not wanted:
        return empty_result("최소 표본(%d건) 이상의 기업이 없습니다." % int(min_n))

    raw_by_company = {}
    for c in wanted:
        sub = df[df["applicant_display"].astype(str) == c]
        raw_by_company[c] = _company_metrics(sub, recent_from, recent)

    keys = [k for k, _ in DNA_METRICS]
    std_by_metric = {}
    for k in keys:
        vals = [raw_by_company[c][k] if raw_by_company[c][k] is not None else 0.0
                for c in wanted]
        std_by_metric[k] = normalize_series(vals, log=(k in ("family_size", "avg_citations", "intl_scope")))
    n_ranks = normalize_series([raw_by_company[c]["n"] for c in wanted], log=True)
    try:
        cutoff = float((settings or {}).get("dna_type_cutoffs", {}).get("default")
                       or WEIGHTS["dna_type_cutoff"])
    except (TypeError, ValueError):
        cutoff = WEIGHTS["dna_type_cutoff"]

    companies_payload = []
    for i, c in enumerate(wanted):
        raw = raw_by_company[c]
        std = {k: round(float(std_by_metric[k][i]), 4) for k in keys}
        ctype = _classify(std, float(n_ranks[i]), cutoff)
        companies_payload.append({
            "company": c, "n": raw["n"], "type": ctype,
            "raw": {k: (round(raw[k], 4) if isinstance(raw[k], float) else raw[k]) for k in keys},
            "std": std, "drill": {"type": "applicant", "applicant": c},
        })

    labels = [label for _, label in DNA_METRICS]
    if len(companies_payload) <= max_cmp:
        fig = radar_chart(labels, [
            {"name": p["company"], "values": [p["std"][k] for k in keys],
             "raw": [p["raw"][k] if p["raw"][k] is not None else "-" for k in keys]}
            for p in companies_payload], title="경쟁사 기술 DNA Fingerprint")
        chart_kind = "radar"
    else:
        z = [[p["std"][k] for k in keys] for p in companies_payload]
        hover = [["%s<br>%s: 표준화 %.2f / 원값 %s"
                  % (p["company"], label, p["std"][k],
                     p["raw"][k] if p["raw"][k] is not None else "-")
                  for k, label in DNA_METRICS] for p in companies_payload]
        fig = heatmap(z, labels, [p["company"] for p in companies_payload],
                      title="기술 DNA 히트맵 (표준화)", colorscale="Blues", hovertext=hover)
        chart_kind = "heatmap"

    parcoords = {"data": [{
        "type": "parcoords",
        "line": {"color": list(range(len(companies_payload))), "colorscale": "Turbo"},
        "dimensions": [{"label": label, "values": [p["std"][k] for p in companies_payload],
                        "range": [0, 1]} for k, label in DNA_METRICS],
    }], "layout": {"margin": {"l": 80, "r": 60, "t": 40, "b": 30},
                   "title": {"text": "지표별 평행좌표 비교 (표준화)", "font": {"size": 14}}}}

    # 전략 유사도·포트폴리오 중첩도
    shares = company_tech_shares(df, multiclass_mode=settings.get("multiclass_mode", "duplicate"))
    sim_matrix, overlap_matrix = None, None
    names = [p["company"] for p in companies_payload]
    if not shares.empty:
        available = [c for c in names if c in shares.index]
        vecs = {c: shares.loc[c].values for c in available}
        sets = {c: set(shares.columns[shares.loc[c].values > 0]) for c in available}
        sim_z, ov_z = [], []
        for a in available:
            sim_row, ov_row = [], []
            for b in available:
                sim_row.append(round(cosine_sim_vec(vecs[a], vecs[b]), 3))
                inter = len(sets[a] & sets[b])
                union = len(sets[a] | sets[b]) or 1
                ov_row.append(round(inter / union, 3))
            sim_z.append(sim_row)
            ov_z.append(ov_row)
        sim_matrix = heatmap(sim_z, available, available, title="전략 유사도 (코사인)",
                             colorscale="Blues", colorbar_title="유사도")
        overlap_matrix = heatmap(ov_z, available, available,
                                 title="포트폴리오 중첩도 (Jaccard)",
                                 colorscale="Purples", colorbar_title="중첩도")

    type_counts = {}
    for p in companies_payload:
        type_counts[p["type"]] = type_counts.get(p["type"], 0) + 1
    sentences = ["%s 기준 %s개 기업의 유형 분포: %s."
                 % (period_label(df), fmt_num(len(companies_payload)),
                    ", ".join("%s %d" % (t, c) for t, c in type_counts.items()))]
    pioneers = [p["company"] for p in companies_payload if p["type"] == "선도 개척형"]
    if pioneers:
        sentences.append("선도 개척형(%s)은 신규분류 진입률과 성장률·피인용이 동시에 높아 "
                         "핵심 경쟁 위험 요인입니다." % ", ".join(pioneers[:4]))
    grow = sorted(companies_payload, key=lambda p: -(p["raw"]["recent_growth"] or -9))[:1]
    if grow and grow[0]["raw"]["recent_growth"] is not None:
        sentences.append("최근 성장률 1위는 '%s'(%s)입니다."
                         % (grow[0]["company"], fmt_pct(grow[0]["raw"]["recent_growth"])))
    insight = build_insight(sentences, {"type_counts": type_counts},
                            small_sample=check_small_sample(len(companies_payload), settings))
    return ok_result({"figure": fig, "chart_kind": chart_kind, "parcoords": parcoords,
                      "companies": companies_payload, "metric_labels": dict(DNA_METRICS),
                      "similarity": sim_matrix, "overlap": overlap_matrix},
                     insight=insight)


# ===========================================================================
# src/analyses/lead_lag.py
# ===========================================================================
# -*- coding: utf-8 -*-
"""
analyses/lead_lag.py — 4.6 기업 간 기술 선도–추종 분석 (2단계).

분석 목적:
  기업별·기술분류별 연도 시계열의 시차 상관으로 「시계열상 선행 관계」를 탐지한다.
  (표현 주의: 인과관계·Granger causality 로 단정하지 않고 "시계열상 선행 신호",
  "전략적 선행 신호" 로만 표기한다.)

필수 컬럼: 기술분류(any), 날짜(any), 출원인(any)

계산식:
  1) 기업×기술분류×연도 건수 시계열 (연속 연도, 결측 0).
  2) 각 기술분류에서 기업쌍 (A,B) 에 대해 metrics.cross_correlation_lag:
     corr(A[t], B[t+lag]) 를 lag ∈ [-max_lag, +max_lag] 에서 탐색.
     lag>0 & corr>=leadlag_min_corr → "A 가 B 를 lag 년 선행" 관측 1건.
  3) 필터: 관측연도 >= min_years_leadlag, 기술분류 내 기업별 특허 수 >= min_patents_leadlag.
  4) 여러 기술분류에서 반복되는 선도 관계 집계: 같은 방향 관측 횟수(n_obs),
     평균 시차(avg_lag), 평균 상관(avg_corr). n_obs>=2 만 네트워크에 표시(옵션).

그래프 (Cytoscape Lead-Lag Network):
  노드=기업(크기=특허 수), 화살표=선도→추종, 두께=관계 강도(평균 상관×관측 수),
  엣지 색=대표 기술분류, 라벨=평균 시차.
Drill-down: 엣지 클릭 → 관련 기술분류 목록 + 양사 특허.
자동 인사이트: 최다 선도 기업, 반복 관측 관계.
예외처리: 조건 충족 시계열이 없으면 empty.
"""
import numpy as np



def compute_lead_lag(df, settings, min_repeat=1):
    """선도–추종 분석 계산."""
    if not len(df):
        return empty_result()
    min_years = int(get_threshold(settings, "min_years_leadlag"))
    min_patents = int(get_threshold(settings, "min_patents_leadlag"))
    max_lag = int(get_threshold(settings, "max_lag_years"))
    min_corr = get_threshold(settings, "leadlag_min_corr")
    max_companies = get_limit(settings, "leadlag_max_companies")

    ex = explode_tech(df, mode=settings.get("multiclass_mode", "duplicate"))
    ex = ex[ex["_base_year"].notna() & (ex["applicant_display"].astype(str) != "")]
    if not len(ex):
        return empty_result("기업·기술분류·연도 시계열을 만들 데이터가 없습니다.")
    ex["_year_int"] = ex["_base_year"].astype(int)

    top_companies = set(ex["applicant_display"].value_counts().head(max_companies).index)
    ex = ex[ex["applicant_display"].isin(top_companies)]

    observations = []
    for tech, tech_group in ex.groupby("tech"):
        pivot = tech_group.pivot_table(index="_year_int", columns="applicant_display",
                                       values="weight", aggfunc="sum", fill_value=0.0)
        if len(pivot) < min_years:
            continue
        full_years = range(int(pivot.index.min()), int(pivot.index.max()) + 1)
        pivot = pivot.reindex(full_years, fill_value=0.0)
        eligible = [c for c in pivot.columns if pivot[c].sum() >= min_patents]
        for i, a in enumerate(eligible):
            for b in eligible[i + 1:]:
                lag, corr = cross_correlation_lag(pivot[a], pivot[b], max_lag=max_lag,
                                                  min_overlap=min_years)
                if lag is None or corr is None or abs(corr) < min_corr or lag == 0:
                    continue
                leader, follower = (a, b) if lag > 0 else (b, a)
                observations.append({"leader": str(leader), "follower": str(follower),
                                     "tech": str(tech), "lag": abs(int(lag)),
                                     "corr": round(float(corr), 3)})
    if not observations:
        return empty_result("조건(최소 %d년 관측·%d건 이상·상관 %.2f 이상)을 충족하는 "
                            "시계열상 선행 관계가 없습니다."
                            % (min_years, min_patents, min_corr))

    # 기업쌍 방향별 집계 (여러 기술분류 반복 관측)
    agg = {}
    for o in observations:
        key = (o["leader"], o["follower"])
        rec = agg.setdefault(key, {"leader": o["leader"], "follower": o["follower"],
                                   "techs": [], "lags": [], "corrs": []})
        rec["techs"].append(o["tech"])
        rec["lags"].append(o["lag"])
        rec["corrs"].append(abs(o["corr"]))
    relations = []
    for rec in agg.values():
        n_obs = len(rec["techs"])
        if n_obs < min_repeat:
            continue
        relations.append({
            "leader": rec["leader"], "follower": rec["follower"], "n_obs": n_obs,
            "avg_lag": round(float(np.mean(rec["lags"])), 2),
            "avg_corr": round(float(np.mean(rec["corrs"])), 3),
            "strength": round(float(np.mean(rec["corrs"]) * n_obs), 3),
            "techs": sorted(set(rec["techs"]))[:8],
        })
    if not relations:
        return empty_result("반복 관측된 선행 관계가 없습니다.")
    relations.sort(key=lambda r: -r["strength"])

    counts = df["applicant_display"].value_counts()
    node_names = sorted(set([r["leader"] for r in relations] + [r["follower"] for r in relations]))
    max_count = max((counts.get(n, 1) for n in node_names), default=1)
    nodes = [{"id": n, "label": n, "count": int(counts.get(n, 0)),
              "size": float(14 + 26 * np.sqrt(counts.get(n, 1) / max_count)),
              "color": "#4E79A7",
              "drill": {"type": "applicant", "applicant": n}} for n in node_names]
    color_reg = {}
    max_strength = max(r["strength"] for r in relations) or 1
    edges = [{"source": r["leader"], "target": r["follower"], "weight": r["strength"],
              "width": float(1.5 + 6 * r["strength"] / max_strength),
              "label": "평균 %s년 선행" % r["avg_lag"],
              "color": color_for(r["techs"][0] if r["techs"] else "기타", color_reg),
              "avg_lag": r["avg_lag"], "avg_corr": r["avg_corr"], "n_obs": r["n_obs"],
              "techs": r["techs"], "arrow": True} for r in relations]

    lead_counts = {}
    for r in relations:
        lead_counts[r["leader"]] = lead_counts.get(r["leader"], 0) + r["n_obs"]
    sentences = []
    if lead_counts:
        top_leader = max(lead_counts, key=lead_counts.get)
        sentences.append("%s 기준 시계열상 선행 신호가 가장 많이 관측된 기업은 '%s'"
                         "(%s개 관계)입니다. 이는 통계적 선행 관계이며 인과관계를 "
                         "의미하지 않습니다."
                         % (period_label(df), top_leader, fmt_num(lead_counts[top_leader])))
    repeated = [r for r in relations if r["n_obs"] >= 2]
    if repeated:
        r0 = repeated[0]
        sentences.append("'%s → %s' 관계는 %s개 기술분류에서 반복 관측(평균 시차 %s년, "
                         "평균 상관 %s)되어 전략적 선행 신호로 주목할 만합니다."
                         % (r0["leader"], r0["follower"], fmt_num(r0["n_obs"]),
                            r0["avg_lag"], r0["avg_corr"]))
    insight = build_insight(sentences, {"n_relations": len(relations)},
                            small_sample=check_small_sample(len(observations), settings))
    return ok_result({"network": cytoscape_network(nodes, edges),
                      "relations": relations[:50]},
                     insight=insight,
                     meta={"note": "시계열상 선행 관계이며 인과관계가 아닙니다."})


# ===========================================================================
# src/analyses/claim_density.py
# ===========================================================================
# -*- coding: utf-8 -*-
"""
analyses/claim_density.py — 4.9 청구항 중첩도 기반 권리장벽 지형도 (3단계).

분석 목적:
  독립청구항 의미 유사도로 권리 밀집 지형을 그려 「우선 검토 대상 스크리닝」을
  지원한다. FTO 판단의 대체가 아님을 화면·meta 에 명시한다.

필수 컬럼: 독립청구항, 기술분류(any)
선택 컬럼: 임베딩 벡터(또는 embedding adapter), 법적상태, 만료예정일, 출원인,
          피인용 수, 패밀리 ID

절차 (Docstring 선행 서술 요구사항):
  1) 독립청구항 전처리: 공백 정리·소문자화(영문)·최소 길이 필터.
  2) 임베딩: ① Dataset 임베딩 컬럼 ② embedding adapter(REST/Dataset)
     ③ 둘 다 없으면 TF-IDF 벡터(문자 n-gram, 한·영·일 혼재 대응) — 명시적 폴백이며
     임의 값 생성이 아님(청구항 텍스트 기반 결정적 벡터).
  3) 유사도: 기술분류 내부 코사인 유사도 (GPU cuML/cupy 우선, CPU 폴백).
     상위 sim_topk_per_doc 이웃만 유지 (메모리 상한).
  4) 2D 투영: UMAP(GPU→CPU) → PCA 자동 폴백.
  5) 클러스터: HDBSCAN(GPU→CPU) → DBSCAN 폴백.
  6) 밀도: 가우시안 KDE (scipy) → 히스토그램 폴백. 등고선 payload 생성.
  7) 법적상태·출원인·잔존기간 결합: 점 색=출원인, 투명도=권리 유효성,
     크기=영향력(피인용), 테두리=등록 여부.

Drill-down: 점 클릭 {"type":"ids"}. 클러스터 요약 표 포함.
자동 인사이트: 최고 밀도 클러스터의 지배 출원인·유효비율.
예외처리: 독립청구항 부족(<10건) 시 empty, 컬럼 없으면 disabled.
"""
import numpy as np
import pandas as pd



def _preprocess_claims(series):
    s = series.astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    s = s.where(~s.str.lower().isin(["nan", "none", ""]), other=None)
    return s.map(lambda v: v if (v and len(v) >= 30) else None)


def _tfidf_vectors(texts):
    """TF-IDF 폴백 벡터 (문자 2-4gram — 한글·영문·일문 혼재 대응)."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.decomposition import TruncatedSVD
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), max_features=5000,
                          min_df=2)
    X = vec.fit_transform(texts)
    n_comp = min(64, X.shape[1] - 1, X.shape[0] - 1)
    if n_comp < 2:
        return X.toarray()
    svd = TruncatedSVD(n_components=n_comp, random_state=42)
    return svd.fit_transform(X)


def _kde_density(xy):
    """KDE 밀도 그리드. 실패 시 2D 히스토그램 폴백. 반환: (xs, ys, zz)."""
    x, y = xy[:, 0], xy[:, 1]
    xs = np.linspace(x.min(), x.max(), 60)
    ys = np.linspace(y.min(), y.max(), 60)
    try:
        from scipy.stats import gaussian_kde
        kde = gaussian_kde(np.vstack([x, y]))
        gx, gy = np.meshgrid(xs, ys)
        zz = kde(np.vstack([gx.ravel(), gy.ravel()])).reshape(gx.shape)
    except Exception:
        zz, xe, ye = np.histogram2d(x, y, bins=[xs, ys])
        zz = zz.T
        xs, ys = xe[:-1], ye[:-1]
    return xs, ys, zz


def compute_claim_density(df, settings, tech=None):
    """청구항 밀집 지형도 계산. tech 지정 시 해당 분류 내부만."""
    if "indep_claim" not in df.columns:
        return disabled_result(["독립청구항"],
                               message="독립청구항 컬럼이 없어 권리장벽 지형도를 사용할 수 "
                                       "없습니다. 컬럼 매핑에서 '독립청구항'(텍스트)을 매핑하세요.")
    work = df.copy()
    if tech:
        work = work[work["_tech_list"].map(lambda lst: str(tech) in (lst or []))]
    work["_claim_clean"] = _preprocess_claims(work["indep_claim"])
    work = work[work["_claim_clean"].notna()].reset_index(drop=True)
    if len(work) < 10:
        return empty_result("전처리 후 독립청구항 보유 특허가 %d건뿐이라 지형도를 만들 수 "
                            "없습니다 (최소 10건)." % len(work))
    max_points = get_limit(settings, "claim_density_max_points")
    truncated = len(work) > max_points
    if truncated:
        work = work.sample(n=max_points, random_state=42).reset_index(drop=True)

    id_col = "pub_number" if "pub_number" in work.columns else \
        ("app_number" if "app_number" in work.columns else None)
    ids = list((work[id_col].astype(str) if id_col else work.index.astype(str)))

    # 임베딩 확보: 컬럼 → adapter → TF-IDF 폴백
    vectors, emb_source = None, None
    adapter = get_adapter(settings, df=work, id_series=ids)
    if adapter is not None:
        emb_map = adapter.get_embeddings(list(ids), list(work["_claim_clean"]))
        got = [emb_map.get(str(i)) for i in ids]
        n_got = sum(1 for v in got if v is not None)
        if n_got >= max(10, len(work) * 0.5):
            dims = {len(v) for v in got if v is not None}
            if len(dims) == 1:
                keep = [i for i, v in enumerate(got) if v is not None]
                work = work.iloc[keep].reset_index(drop=True)
                ids = [ids[i] for i in keep]
                vectors = np.vstack([got[i] for i in keep])
                emb_source = "adapter:%s" % adapter.name
    if vectors is None:
        vectors = _tfidf_vectors(list(work["_claim_clean"]))
        emb_source = "tfidf_fallback"
    if vectors.shape[0] < 10:
        return empty_result("임베딩 확보 후 표본이 부족합니다.")

    xy, proj_method = run_umap(np.asarray(vectors, dtype=np.float64), n_components=2)
    labels, cluster_method = run_hdbscan(xy, min_cluster_size=max(5, len(work) // 60))
    xs, ys, zz = _kde_density(xy)

    # 유사도 밀도 (상위 K 이웃 평균) — 권리 중첩 근사
    topk = int(get_threshold(settings, "sim_topk_per_doc"))
    sim = cosine_similarity_matrix(np.asarray(vectors, dtype=np.float64))
    np.fill_diagonal(sim, 0.0)
    k = min(topk, sim.shape[1] - 1)
    if k > 0:
        part = np.partition(sim, -k, axis=1)[:, -k:]
        overlap_density = part.mean(axis=1)
    else:
        overlap_density = np.zeros(sim.shape[0])

    now = pd.Timestamp.now()
    remain_years = None
    if "expiry_date" in work.columns and work["expiry_date"].notna().any():
        remain_years = ((work["expiry_date"] - now).dt.days / 365.25).clip(lower=0)

    color_reg = {}
    top_apps = work["applicant_display"].replace("", np.nan).dropna().value_counts() \
        .head(11).index.tolist()
    cites = work["cites_forward"].fillna(0) if "cites_forward" in work.columns \
        else pd.Series(0.0, index=work.index)
    cmax = float(cites.max()) or 1.0

    points_by_app = {}
    for i in range(len(work)):
        row = work.iloc[i]
        app = str(row.get("applicant_display") or "")
        app_group = app if app in top_apps else "기타"
        active = row.get("_active_flag")
        granted = row.get("_is_granted_bool")
        rm = float(remain_years.iloc[i]) if remain_years is not None and \
            not np.isnan(remain_years.iloc[i]) else None
        hover = ("<b>%s</b><br>%s<br>%s / %s / 클러스터 %s<br>중첩밀도 %.2f%s"
                 % (str(ids[i])[:30],
                    str(row.get("title", ""))[:60], app_group,
                    row.get("legal_status_norm", "Unknown"), int(labels[i]),
                    float(overlap_density[i]),
                    (" / 잔존 %.1f년" % rm) if rm is not None else ""))
        points_by_app.setdefault(app_group, {"x": [], "y": [], "size": [], "opacity": [],
                                             "line": [], "hover": [], "custom": []})
        p = points_by_app[app_group]
        p["x"].append(float(xy[i, 0]))
        p["y"].append(float(xy[i, 1]))
        p["size"].append(float(6 + 18 * np.sqrt(float(cites.iloc[i]) / cmax)))
        p["opacity"].append(0.9 if active is True else (0.35 if active is False else 0.6))
        p["line"].append(2 if granted is True else 0.5)
        p["hover"].append(hover)
        p["custom"].append({"drill": {"type": "ids", "ids": [str(ids[i])]}})

    traces = [{"type": "contour", "x": xs.tolist(), "y": ys.tolist(),
               "z": zz.tolist(), "colorscale": "YlOrRd", "opacity": 0.45,
               "showscale": True, "colorbar": {"title": "청구항 밀도", "thickness": 12},
               "contours": {"showlines": False}, "hoverinfo": "skip", "name": "밀도"}]
    for app_group, p in points_by_app.items():
        traces.append({"type": "scatter", "mode": "markers", "name": app_group,
                       "x": p["x"], "y": p["y"], "hovertext": p["hover"],
                       "hoverinfo": "text", "customdata": p["custom"],
                       "marker": {"size": p["size"], "color": color_for(app_group, color_reg),
                                  "opacity": p["opacity"],
                                  "line": {"width": p["line"], "color": "#222"}}})
    fig = {"data": traces, "layout": base_layout(
        "Claim Density Contour Map%s" % ((" — " + str(tech)) if tech else ""),
        xaxis={"title": "Dim 1 (%s)" % proj_method}, yaxis={"title": "Dim 2"})}

    # 클러스터 요약
    clusters = []
    for cl in sorted(set(int(l) for l in labels)):
        if cl < 0:
            continue
        mask = labels == cl
        sub = work[mask]
        flags = sub["_active_flag"]
        known = flags.map(lambda v: v is not None)
        active_ratio = float(flags[known].map(lambda v: v is True).mean()) if known.any() else None
        apps = sub["applicant_display"].replace("", np.nan).dropna().value_counts()
        clusters.append({
            "cluster": cl, "n": int(mask.sum()),
            "density": round(float(overlap_density[mask].mean()), 3),
            "active_ratio": round(active_ratio, 3) if active_ratio is not None else None,
            "top_applicants": [{"name": str(a), "count": int(c)} for a, c in apps.head(3).items()],
            "drill": {"type": "ids",
                      "ids": [str(ids[i]) for i in np.where(mask)[0]][:200]},
        })
    clusters.sort(key=lambda c: -c["density"])

    sentences = []
    if clusters:
        c0 = clusters[0]
        dom = c0["top_applicants"][0]["name"] if c0["top_applicants"] else "-"
        sentences.append("청구항 중첩밀도가 가장 높은 클러스터 #%d(%s건)는 '%s' 중심이며 "
                         "유효특허 비율 %s로, 우선 검토 대상 영역입니다 (FTO 판단 아님)."
                         % (c0["cluster"], fmt_num(c0["n"]), dom,
                            fmt_pct(c0["active_ratio"]) if c0["active_ratio"] is not None else "미상"))
    sentences.append("본 지형도는 의미 유사도 기반 스크리닝 도구이며 법률적 권리범위 "
                     "판단을 대체하지 않습니다.")
    insight = build_insight(sentences, {"n_clusters": len(clusters),
                                        "embedding_source": emb_source},
                            small_sample=check_small_sample(len(work), settings))
    return ok_result({"figure": fig, "clusters": clusters[:20],
                      "methods": {"embedding": emb_source, "projection": proj_method,
                                  "clustering": cluster_method}},
                     insight=insight,
                     meta={"purpose": "우선 검토 대상 스크리닝 도구 (FTO 판단 대체 아님)",
                           "truncated": truncated})


# ===========================================================================
# src/analyses/citation_influence.py
# ===========================================================================
# -*- coding: utf-8 -*-
"""
analyses/citation_influence.py — 4.10 핵심특허 영향력 전파 (3단계).

분석 목적:
  피인용·패밀리·권리 지표를 결합한 Influence Score 로 핵심특허를 선별하고,
  Citation Diffusion Sankey 로 영향력 전파 경로를 표현한다.

필수 컬럼: 피인용 수, 기술분류(any)
선택 컬럼: 인용 수, 패밀리 수, 패밀리 국가 수, 법적상태, 만료예정일, 출원인, 제품

계산식:
  Influence Score = Σ( 표준화된 지표 × 가중치 ) / Σ가중치   (가중치 Settings 조정 가능)
  지표:
    direct_citations   직접 피인용 수
    indirect_citations 간접 피인용 근사 = 피인용 수 × log1p(인용 수)  (2-hop 데이터가
                       없는 WIPS 다운로드 환경에서의 명시적 근사 — meta 에 표기)
    cross_class        타 기술분류 확산 = 문헌의 다중분류 수 (자신이 걸친 분류 수)
    cross_company      타 기업 확산 근사 = 동일 분류 내 타 출원인 비율 × 피인용
    family_expansion   후속 패밀리 확장 = 패밀리 수
    legal_strength     유지·권리범위 = 유효여부(0/1) × 패밀리 국가 수(log1p) + 잔존기간
  개별 인용 문헌 간 링크 데이터(인용쌍)가 없으므로 Sankey 는
  「핵심특허 → 기술분류 → 상위 출원인(→ 제품)」 집계 흐름으로 구성한다.

인용 데이터 없으면: disabled + 필요 컬럼 안내 (임의 생성 금지).
그래프: Influence Top-N 막대 + Citation Diffusion Sankey.
Drill-down: {"type":"ids"}.
자동 인사이트: 최고 영향력 특허·만료 임박 핵심특허 경고.
"""
import numpy as np
import pandas as pd



def compute_citation_influence(df, settings, top_n=None):
    """핵심특허 영향력 전파 계산."""
    if "cites_forward" not in df.columns or not df["cites_forward"].notna().any():
        return disabled_result(
            ["피인용 수"],
            message="피인용 수 컬럼이 없어 영향력 분석을 사용할 수 없습니다. 컬럼 매핑에서 "
                    "'피인용 수'(정수)를 매핑하세요. 인용쌍(citing-cited) 데이터가 있으면 "
                    "더 정밀한 전파 분석이 가능합니다.")
    work = df[df["cites_forward"].notna()].copy()
    if not len(work):
        return empty_result()
    top_n = int(top_n or get_limit(settings, "top_n_default"))
    now = pd.Timestamp.now()

    direct = work["cites_forward"].astype(float)
    backward = work["cites_backward"].fillna(0).astype(float) \
        if "cites_backward" in work.columns else pd.Series(0.0, index=work.index)
    indirect = direct * np.log1p(backward)
    cross_class = work["_tech_list"].map(lambda lst: len(set(lst or [])))
    # 동일 분류 내 타 출원인 비율 (분류별 사전 계산)
    other_ratio_by_tech = {}
    all_apps = work["applicant_display"]
    for tech in set(t for lst in work["_tech_list"] for t in (lst or [])):
        in_tech = work["_tech_list"].map(lambda lst: tech in (lst or []))
        apps = all_apps[in_tech]
        counts = apps.value_counts()
        total = float(len(apps)) or 1.0
        other_ratio_by_tech[tech] = {a: 1.0 - c / total for a, c in counts.items()}
    cross_company = [
        (np.mean([other_ratio_by_tech.get(t, {}).get(a, 0.0) for t in (lst or [])])
         if lst else 0.0) * d
        for lst, a, d in zip(work["_tech_list"], all_apps, direct)]
    family_exp = work["family_size"].fillna(0).astype(float) \
        if "family_size" in work.columns else pd.Series(0.0, index=work.index)
    active = work["_active_flag"].map(lambda v: 1.0 if v is True else 0.0)
    fam_countries = work["family_country_count"].fillna(0).astype(float) \
        if "family_country_count" in work.columns else pd.Series(0.0, index=work.index)
    if "expiry_date" in work.columns and work["expiry_date"].notna().any():
        remain = ((work["expiry_date"] - now).dt.days / 365.25).clip(lower=0).fillna(0)
    else:
        remain = pd.Series(0.0, index=work.index)
    legal_strength = active * np.log1p(fam_countries) + remain / 20.0

    parts = {
        "direct_citations": normalize_series(direct.values),
        "indirect_citations": normalize_series(np.asarray(indirect.values, dtype=float)),
        "cross_class": normalize_series(np.asarray(cross_class.values, dtype=float), log=False),
        "cross_company": normalize_series(np.asarray(cross_company, dtype=float)),
        "family_expansion": normalize_series(family_exp.values),
        "legal_strength": normalize_series(np.asarray(legal_strength.values, dtype=float),
                                           log=False),
    }
    weights = get_weights(settings, "influence")
    total_w = sum(max(w, 0) for w in weights.values()) or 1.0
    scores = np.zeros(len(work))
    for k, arr in parts.items():
        scores += max(weights.get(k, 0.0), 0.0) * arr
    scores /= total_w
    work["_influence"] = scores
    work["_influence_parts"] = [
        {k: round(float(parts[k][i]), 3) for k in parts} for i in range(len(work))]

    top = work.nlargest(top_n, "_influence")
    id_col = "pub_number" if "pub_number" in work.columns else \
        ("app_number" if "app_number" in work.columns else None)

    def _pid(row, idx):
        return str(row[id_col]) if id_col else str(idx)

    bars_labels, bars_vals, hover, custom = [], [], [], []
    top_records = []
    for idx, row in top.iterrows():
        pid = _pid(row, idx)
        label = "%s %s" % (pid[:18], str(row.get("title", ""))[:24])
        bars_labels.append(label)
        bars_vals.append(round(float(row["_influence"]), 4))
        pd_parts = row["_influence_parts"]
        hover.append("<b>%s</b><br>%s<br>Influence %.3f<br>%s"
                     % (pid, str(row.get("title", ""))[:70], row["_influence"],
                        " / ".join("%s %.2f" % (k, v) for k, v in pd_parts.items())))
        custom.append({"drill": {"type": "ids", "ids": [pid]}})
        top_records.append({"id": pid, "title": str(row.get("title", ""))[:90],
                            "applicant": str(row.get("applicant_display", "")),
                            "score": round(float(row["_influence"]), 4),
                            "cites": int(row["cites_forward"]),
                            "parts": pd_parts,
                            "expiry": str(row["expiry_date"].date())
                            if "expiry_date" in work.columns and pd.notna(row.get("expiry_date")) else None,
                            "drill": {"type": "ids", "ids": [pid]}})
    fig_bar = bar_chart(bars_labels[::-1], bars_vals[::-1], title="핵심특허 Influence Top %d" % top_n,
                        orientation="h", hovertext=hover[::-1], customdata=custom[::-1],
                        x_title="Influence Score")

    # Citation Diffusion Sankey: 핵심특허 → 기술분류 → 상위 출원인(피인용 가중)
    color_reg = {}
    nodes, node_idx = [], {}

    def nid(label, kind):
        key = (label, kind)
        if key not in node_idx:
            node_idx[key] = len(nodes)
            nodes.append({"label": label, "color": color_for(kind, color_reg)})
        return node_idx[key]

    links = {}
    max_links = get_limit(settings, "sankey_max_links")
    for idx, row in top.iterrows():
        pid = _pid(row, idx)
        src = nid(pid[:20], "patent")
        w_total = float(row["cites_forward"]) or 1.0
        techs = list(set(row["_tech_list"] or []))[:4] or ["미분류"]
        for t in techs:
            t_node = nid(str(t)[:24], "tech")
            links[(src, t_node)] = links.get((src, t_node), 0) + w_total / len(techs)
            in_tech = work["_tech_list"].map(lambda lst: t in (lst or []))
            apps = work.loc[in_tech & (work.index != idx), "applicant_display"] \
                .replace("", np.nan).dropna().value_counts().head(3)
            a_total = float(apps.sum()) or 1.0
            for a, c in apps.items():
                a_node = nid(str(a)[:20], "applicant")
                links[(t_node, a_node)] = links.get((t_node, a_node), 0) + \
                    (w_total / len(techs)) * (c / a_total)
    link_list = sorted(links.items(), key=lambda kv: -kv[1])[:max_links]
    fig_sankey = sankey(nodes, [{"source": s, "target": t, "value": round(v, 2)}
                                for (s, t), v in link_list],
                        title="Citation Diffusion (핵심특허 → 기술분류 → 주요 출원인)")

    sentences = []
    if top_records:
        t0 = top_records[0]
        sentences.append("영향력 1위 특허는 %s('%s', %s, Influence %s, 피인용 %s건)입니다."
                         % (t0["id"], t0["title"][:40], t0["applicant"], t0["score"],
                            fmt_num(t0["cites"])))
        expiring = [r for r in top_records if r["expiry"] and
                    pd.Timestamp(r["expiry"]) <= now + pd.DateOffset(years=3)]
        if expiring:
            sentences.append("핵심특허 중 %s건이 3년 내 만료 예정으로, 만료 후 해당 영역의 "
                             "설계 자유도가 확대될 수 있습니다 (탐색적 신호)."
                             % fmt_num(len(expiring)))
    insight = build_insight(sentences, {"weights": weights},
                            small_sample=check_small_sample(len(work), settings))
    return ok_result({"figure": fig_bar, "sankey": fig_sankey, "top_patents": top_records},
                     insight=insight,
                     meta={"note": ("간접 피인용·타 기업 확산은 인용쌍 데이터가 없어 "
                                    "피인용 수 기반 근사값입니다.")})


# ===========================================================================
# src/analyses/inventor_mobility.py
# ===========================================================================
# -*- coding: utf-8 -*-
"""
analyses/inventor_mobility.py — 4.11 발명자 이동 및 기술 전파 네트워크 (3단계).

분석 목적:
  발명자의 소속(출원인) 변화를 추적하여 기업 간 인력·기술 이동 신호를 네트워크로
  표현한다.

필수 컬럼: 발명자, 출원인(any), 날짜(any)
선택 컬럼: 기술분류(엣지 색), 국가(동명이인 식별)

동명이인 처리 (식별 신뢰도 점수):
  같은 이름의 두 기록(이동 전/후)이 동일인인지에 대한 신뢰도를
    confidence = 0.35·공동발명자 겹침(Jaccard)
               + 0.25·기술분류 겹침(Jaccard)
               + 0.20·시간 근접성(간격<=3년 → 1, 이후 연 0.1 감쇠)
               + 0.10·국가 일치
               + 0.10·이름 희소성(전체에서 해당 이름 문헌 수가 적을수록 1)
  으로 계산한다. confidence < inventor_match_confidence(기본 0.6)면 "추정 이동"으로
  표시하고 기본 그래프에서 제외한다 (include_uncertain=True 로 포함 선택 가능).

이동 정의: 발명자 이름별 문헌을 연도순 정렬 후, 연속 문헌의 표준화 출원인이
  다르면 이동 후보 1건. 같은 (from,to,inventor) 는 1회만 집계.

그래프 (Cytoscape): 노드=기업, 엣지=이동 발명자 수, 엣지 색=대표 기술분류,
  시간 슬라이더용 year 속성 포함. 발명자 클릭 시 특허 이력(drill).
Drill-down: 엣지 → 이동 발명자 목록, 발명자 → {"type":"inventor"} 특허 이력.
자동 인사이트: 최대 유출→유입 경로, 추정 이동 비율.
예외처리: 발명자·출원인 없으면 disabled, 이동 없으면 empty.
"""
import numpy as np



def _jaccard_sets(a, b):
    a, b = set(a or []), set(b or [])
    if not a and not b:
        return 0.0
    union = a | b
    return len(a & b) / float(len(union)) if union else 0.0


def compute_inventor_mobility(df, settings, include_uncertain=False):
    """발명자 이동 네트워크 계산."""
    if "_inventor_list" not in df.columns:
        return disabled_result(["발명자"],
                               message="발명자 컬럼이 없어 발명자 이동 분석을 사용할 수 "
                                       "없습니다. 컬럼 매핑에서 '발명자'를 매핑하세요.")
    work = df[df["_base_year"].notna()].copy()
    if not len(work):
        return empty_result("연도 정보가 없어 이동 순서를 정할 수 없습니다.")
    conf_cutoff = get_threshold(settings, "inventor_match_confidence")
    max_edges = get_limit(settings, "inventor_network_max_edges")

    # 발명자 이름별 기록 구축
    records_by_name = {}
    name_doc_counts = {}
    for idx, row in work.iterrows():
        invs = row.get("_inventor_list") or []
        app = str(row.get("applicant_display") or "")
        if not app:
            continue
        year = int(row["_base_year"])
        techs = set(row.get("_tech_list") or [])
        country = str(row.get("country") or "").upper() if "country" in work.columns else ""
        pid = str(row.get("pub_number", idx))
        for inv in invs:
            inv = str(inv).strip()
            if not inv:
                continue
            name_doc_counts[inv] = name_doc_counts.get(inv, 0) + 1
            records_by_name.setdefault(inv, []).append({
                "year": year, "app": app, "techs": techs,
                "coinv": set(i for i in invs if i != inv),
                "country": country, "pid": pid})
    if not records_by_name:
        return empty_result("발명자·출원인 정보가 있는 문헌이 없습니다.")
    max_docs = max(name_doc_counts.values())

    moves = []
    for inv, recs in records_by_name.items():
        recs.sort(key=lambda r: r["year"])
        seen_pairs = set()
        for prev, cur in zip(recs, recs[1:]):
            if prev["app"] == cur["app"]:
                continue
            pair = (prev["app"], cur["app"])
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            gap = cur["year"] - prev["year"]
            time_score = 1.0 if gap <= 3 else max(0.0, 1.0 - 0.1 * (gap - 3))
            rarity = 1.0 - (name_doc_counts[inv] - 1) / float(max(max_docs - 1, 1))
            confidence = (0.35 * _jaccard_sets(prev["coinv"], cur["coinv"])
                          + 0.25 * _jaccard_sets(prev["techs"], cur["techs"])
                          + 0.20 * time_score
                          + 0.10 * (1.0 if prev["country"] and prev["country"] == cur["country"] else 0.0)
                          + 0.10 * rarity)
            techs = sorted(prev["techs"] | cur["techs"])
            moves.append({"inventor": inv, "from": prev["app"], "to": cur["app"],
                          "year": cur["year"], "confidence": round(float(confidence), 3),
                          "uncertain": confidence < conf_cutoff,
                          "techs": techs[:5]})
    if not moves:
        return empty_result("기업 간 발명자 이동이 관측되지 않았습니다.")

    n_uncertain = sum(1 for m in moves if m["uncertain"])
    used = moves if include_uncertain else [m for m in moves if not m["uncertain"]]
    if not used:
        return empty_result("신뢰도 %.2f 이상 이동이 없습니다. '추정 이동 포함' 옵션으로 "
                            "%d건의 추정 이동을 볼 수 있습니다." % (conf_cutoff, n_uncertain))

    edge_map = {}
    for m in used:
        key = (m["from"], m["to"])
        rec = edge_map.setdefault(key, {"from": m["from"], "to": m["to"], "inventors": [],
                                        "years": [], "techs": {}, "uncertain": 0})
        rec["inventors"].append({"name": m["inventor"], "year": m["year"],
                                 "confidence": m["confidence"],
                                 "label": (MESSAGES["estimated_move"] if m["uncertain"] else "확인 이동")})
        rec["years"].append(m["year"])
        for t in m["techs"]:
            rec["techs"][t] = rec["techs"].get(t, 0) + 1
        if m["uncertain"]:
            rec["uncertain"] += 1
    edges_data = sorted(edge_map.values(), key=lambda r: -len(r["inventors"]))[:max_edges]

    companies = sorted(set([e["from"] for e in edges_data] + [e["to"] for e in edges_data]))
    counts = work["applicant_display"].value_counts()
    max_count = max((counts.get(c, 1) for c in companies), default=1)
    nodes = [{"id": c, "label": c, "count": int(counts.get(c, 0)),
              "size": float(14 + 24 * np.sqrt(counts.get(c, 1) / max_count)),
              "color": "#59A14F", "drill": {"type": "applicant", "applicant": c}}
             for c in companies]
    color_reg = {}
    max_inv = max(len(e["inventors"]) for e in edges_data)
    edges = []
    for e in edges_data:
        top_tech = max(e["techs"], key=e["techs"].get) if e["techs"] else "기타"
        edges.append({
            "source": e["from"], "target": e["to"],
            "weight": len(e["inventors"]),
            "width": float(1.5 + 6 * len(e["inventors"]) / max_inv),
            "color": color_for(top_tech, color_reg), "tech": top_tech,
            "years": sorted(set(e["years"])),
            "year_min": min(e["years"]), "year_max": max(e["years"]),
            "uncertain": e["uncertain"],
            "inventors": e["inventors"][:30], "arrow": True,
            "label": "%d명" % len(e["inventors"]),
        })

    sentences = []
    if edges:
        e0 = max(edges, key=lambda e: e["weight"])
        sentences.append("%s 기준 최대 이동 경로는 '%s → %s'(%s명, 주요 분류 %s)입니다."
                         % (period_label(work), e0["source"], e0["target"],
                            fmt_num(e0["weight"]), e0["tech"]))
    sentences.append("전체 이동 후보 %s건 중 %s(%s건)이 신뢰도 %.2f 미만의 '추정 이동'으로 "
                     "분류되었습니다%s."
                     % (fmt_num(len(moves)), fmt_pct(n_uncertain / len(moves)),
                        fmt_num(n_uncertain), conf_cutoff,
                        " (그래프에 포함됨)" if include_uncertain else " (기본 그래프에서 제외)"))
    insight = build_insight(sentences, {"n_moves": len(used), "n_uncertain": n_uncertain},
                            small_sample=check_small_sample(len(used), settings))
    years_all = sorted(set(y for e in edges for y in e["years"]))
    return ok_result({"network": cytoscape_network(nodes, edges),
                      "years": years_all, "include_uncertain": bool(include_uncertain),
                      "n_uncertain": n_uncertain},
                     insight=insight,
                     meta={"note": "동명이인 가능성이 있어 이동은 식별 신뢰도 기반 추정입니다."})


# ===========================================================================
# src/analyses/classification_quality.py
# ===========================================================================
# -*- coding: utf-8 -*-
"""
analyses/classification_quality.py — 4.12 기술분류 품질·경계 진단 (3단계).

분석 목적:
  당사가 수행한 기술분류 결과의 품질(응집도·분리도·경계 모호성)을 진단하고
  분류 수정 후보를 제안한다.

필수 컬럼: 기술분류(any)
선택 컬럼: 임베딩(응집도·분리도·실루엣), 분류 신뢰도, 제목/요약(대표 키워드),
          날짜(드리프트)

지표:
  - cohesion(분류 내 응집도): 분류 내 문서-중심 벡터 평균 코사인 유사도
  - separation(분류 간 분리도): 분류 중심 간 평균 코사인 거리(1-유사도)
  - silhouette: sklearn silhouette (표본 상한 2000, 임베딩 필요)
  - multi_ratio: 다중분류 비율 (분류 2개 이상 문헌 비중)
  - low_conf_ratio: 분류 신뢰도 < low_confidence_class 문헌 비중
  - drift: 연도별 분류 중심 임베딩 이동 평균 거리
  - keyword_stability: 전·후반 기간 대표 키워드(TF 상위) Jaccard

탐지 규칙 → 수정 후보 제안:
  - 두 분류 중심 유사도 > 0.8 → "통합 검토"
  - cohesion < 0.3 → "분리 검토(이질 기술군 혼재)"
  - keyword_stability < 0.3 → "대표 키워드 재정의"
  - multi_ratio > 0.6 → "다중분류 기준 검토"
  - 표본 < min_class_patents → "과세분화 의심(표본 부족)"

그래프: Classification Confusion Map (히트맵, 행·열=기술분류, 셀=중심 간 의미
  유사도 또는 (임베딩 없으면) 중복 특허 비율. 빨강=모호, 파랑=분리 명확).
  보조: 분류별 응집도 막대, 저신뢰 특허 목록, 연도별 중심 이동, 키워드 변화.
Drill-down: 히트맵 셀 → 두 분류 동시 포함 특허 {"type":"combo"}.
예외처리: 임베딩 없으면 임베딩 기반 지표는 null + 중복 비율 기반으로 degrade.
"""
import re

import numpy as np
import pandas as pd


_TOKEN_RE = re.compile(r"[A-Za-z가-힣一-龥ぁ-んァ-ン0-9]{2,}")
_STOP = frozenset(["및", "또는", "위한", "있는", "하는", "the", "and", "for", "with",
                   "of", "in", "to", "method", "device", "system", "장치", "방법"])


def _top_keywords(texts, k=8):
    counts = {}
    for t in texts:
        if t is None or (isinstance(t, float) and np.isnan(t)):
            continue
        for tok in _TOKEN_RE.findall(str(t).lower()):
            if tok not in _STOP:
                counts[tok] = counts.get(tok, 0) + 1
    return [w for w, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:k]]


def compute_classification_quality(df, settings):
    """기술분류 품질·경계 진단 계산."""
    if not len(df):
        return empty_result()
    techs_all = pd.Series([t for lst in df["_tech_list"] for t in (lst or [])])
    if not len(techs_all):
        return empty_result("기술분류 데이터가 없습니다.")
    min_n = get_threshold(settings, "min_class_patents")
    low_conf_cut = get_threshold(settings, "low_confidence_class")
    tech_counts = techs_all.value_counts()
    techs = tech_counts.head(get_limit(settings, "network_max_nodes")).index.tolist()

    has_emb = "_embedding" in df.columns and df["_embedding"].map(lambda v: v is not None).any()
    emb_dim = None
    if has_emb:
        dims = {len(v) for v in df["_embedding"] if v is not None}
        emb_dim = dims.pop() if len(dims) == 1 else None
        has_emb = emb_dim is not None

    # 분류별 문서 인덱스
    idx_by_tech = {t: df.index[df["_tech_list"].map(lambda lst: t in (lst or []))].tolist()
                   for t in techs}

    centroids, cohesion = {}, {}
    if has_emb:
        for t in techs:
            vecs = [df.loc[i, "_embedding"] for i in idx_by_tech[t]
                    if df.loc[i, "_embedding"] is not None]
            if len(vecs) >= 2:
                V = np.vstack(vecs)
                c = V.mean(axis=0)
                centroids[t] = c
                sims = cosine_similarity_matrix(V, c.reshape(1, -1)).ravel()
                cohesion[t] = float(np.mean(sims))
            elif len(vecs) == 1:
                centroids[t] = np.asarray(vecs[0])
                cohesion[t] = 1.0

    # Confusion Map: 임베딩 → 중심 유사도 / 폴백 → 중복 특허 비율(Jaccard)
    z, hover = [], []
    for a in techs:
        row_z, row_h = [], []
        set_a = set(idx_by_tech[a])
        for b in techs:
            if a == b:
                row_z.append(None)
                row_h.append("%s (대각)" % a)
                continue
            if has_emb and a in centroids and b in centroids:
                v = float(cosine_similarity_matrix(
                    centroids[a].reshape(1, -1), centroids[b].reshape(1, -1))[0, 0])
                row_h.append("%s ↔ %s<br>중심 의미 유사도 %.2f" % (a, b, v))
            else:
                set_b = set(idx_by_tech[b])
                union = len(set_a | set_b) or 1
                v = len(set_a & set_b) / float(union)
                row_h.append("%s ↔ %s<br>중복 특허 비율(Jaccard) %.2f" % (a, b, v))
            row_z.append(round(v, 3))
        z.append(row_z)
        hover.append(row_h)
    n_cells = len(techs) ** 2
    if n_cells > get_limit(settings, "echarts_threshold_cells"):
        fig_confusion = echarts_heatmap(z, techs, techs, title="Classification Confusion Map")
    else:
        fig_confusion = heatmap(z, techs, techs,
                                title="Classification Confusion Map (빨강=모호, 파랑=분리 명확)",
                                colorscale="RdBu", hovertext=hover,
                                colorbar_title="유사도/중복", zmid=0.5)
        fig_confusion["data"][0]["reversescale"] = True

    # 실루엣 (단일 분류 문헌만, 표본 상한)
    silhouette = None
    if has_emb:
        try:
            from sklearn.metrics import silhouette_score
            rows = [(i, (lst or [None])[0]) for i, lst in zip(df.index, df["_tech_list"])
                    if lst and len(set(lst)) == 1 and df.loc[i, "_embedding"] is not None
                    and (lst[0] in set(techs))]
            if len(rows) > 2000:
                rows = rows[:2000]
            labels = [t for _, t in rows]
            if len(set(labels)) >= 2 and len(rows) >= 10:
                X = np.vstack([df.loc[i, "_embedding"] for i, _ in rows])
                silhouette = float(silhouette_score(X, labels, metric="cosine"))
        except Exception:
            silhouette = None

    multi_ratio = float(df["_tech_list"].map(lambda lst: len(set(lst or [])) >= 2).mean())
    low_conf_ratio = None
    low_conf_list = []
    if "class_confidence" in df.columns and df["class_confidence"].notna().any():
        conf = df["class_confidence"]
        low_mask = conf.notna() & (conf < low_conf_cut)
        low_conf_ratio = float(low_mask.mean())
        id_col = "pub_number" if "pub_number" in df.columns else None
        for i in df.index[low_mask][:50]:
            low_conf_list.append({
                "id": str(df.loc[i, id_col]) if id_col else str(i),
                "title": str(df.loc[i].get("title", ""))[:70],
                "confidence": round(float(conf.loc[i]), 3),
                "techs": list(df.loc[i, "_tech_list"] or [])[:4]})

    # 드리프트: 연도별 중심 이동 평균 거리
    drift_by_tech = {}
    if has_emb and "_base_year" in df.columns:
        for t in techs:
            pts = [(int(df.loc[i, "_base_year"]), df.loc[i, "_embedding"])
                   for i in idx_by_tech[t]
                   if df.loc[i, "_embedding"] is not None and pd.notna(df.loc[i, "_base_year"])]
            by_year = {}
            for y, v in pts:
                by_year.setdefault(y, []).append(v)
            years_sorted = sorted(by_year)
            if len(years_sorted) >= 2:
                cents = [np.vstack(by_year[y]).mean(axis=0) for y in years_sorted]
                dists = [1.0 - float(cosine_similarity_matrix(
                    cents[j].reshape(1, -1), cents[j + 1].reshape(1, -1))[0, 0])
                    for j in range(len(cents) - 1)]
                drift_by_tech[t] = round(float(np.mean(dists)), 4)

    # 대표 키워드 안정성
    keyword_info = {}
    text_col = "title" if "title" in df.columns else ("abstract" if "abstract" in df.columns else None)
    if text_col:
        years = df["_base_year"].dropna()
        mid = float(years.median()) if len(years) else None
        for t in techs:
            sub = df.loc[idx_by_tech[t]]
            kws = _top_keywords(sub[text_col], 8)
            stability = None
            if mid is not None:
                early = _top_keywords(sub.loc[sub["_base_year"] <= mid, text_col], 10)
                late = _top_keywords(sub.loc[sub["_base_year"] > mid, text_col], 10)
                if early and late:
                    inter = len(set(early) & set(late))
                    union = len(set(early) | set(late)) or 1
                    stability = round(inter / float(union), 3)
            keyword_info[t] = {"keywords": kws, "stability": stability}

    # 수정 후보 제안
    suggestions = []
    for i, a in enumerate(techs):
        for j in range(i + 1, len(techs)):
            b = techs[j]
            v = z[i][j]
            if v is not None and has_emb and v > 0.8:
                suggestions.append({"type": "통합 검토", "targets": [a, b],
                                    "reason": "중심 의미 유사도 %.2f (>0.8)" % v,
                                    "drill": {"type": "combo", "a": a, "b": b}})
            elif v is not None and not has_emb and v > 0.5:
                suggestions.append({"type": "통합 검토", "targets": [a, b],
                                    "reason": "중복 특허 비율 %.2f (>0.5)" % v,
                                    "drill": {"type": "combo", "a": a, "b": b}})
    for t in techs:
        if t in cohesion and cohesion[t] < 0.3:
            suggestions.append({"type": "분리 검토", "targets": [t],
                                "reason": "응집도 %.2f (<0.3) — 이질 기술군 혼재 의심" % cohesion[t],
                                "drill": {"type": "tech", "tech": t}})
        ki = keyword_info.get(t, {})
        if ki.get("stability") is not None and ki["stability"] < 0.3:
            suggestions.append({"type": "대표 키워드 재정의", "targets": [t],
                                "reason": "전·후반 키워드 안정성 %.2f (<0.3)" % ki["stability"],
                                "drill": {"type": "tech", "tech": t}})
        if int(tech_counts.get(t, 0)) < min_n:
            suggestions.append({"type": "과세분화 검토", "targets": [t],
                                "reason": "표본 %d건 (<%d)" % (int(tech_counts.get(t, 0)), int(min_n)),
                                "drill": {"type": "tech", "tech": t}})
    if multi_ratio > 0.6:
        suggestions.append({"type": "다중분류 기준 검토", "targets": [],
                            "reason": "다중분류 비율 %s (>60%%)" % fmt_pct(multi_ratio)})

    cohesion_fig = None
    if cohesion:
        items = sorted(cohesion.items(), key=lambda kv: kv[1])
        cohesion_fig = bar_chart([k for k, _ in items], [round(v, 3) for _, v in items],
                                 title="분류별 임베딩 응집도", orientation="h",
                                 x_title="응집도(중심 코사인 평균)")

    sentences = ["기술분류 %s개 진단: 다중분류 비율 %s%s%s."
                 % (fmt_num(len(techs)), fmt_pct(multi_ratio),
                    (", 실루엣 %.3f" % silhouette) if silhouette is not None else "",
                    (", 저신뢰(<%.1f) 비율 %s" % (low_conf_cut, fmt_pct(low_conf_ratio)))
                    if low_conf_ratio is not None else "")]
    merges = [s for s in suggestions if s["type"] == "통합 검토"]
    if merges:
        m0 = merges[0]
        sentences.append("경계가 가장 모호한 분류쌍은 '%s ↔ %s'(%s)로 통합 검토 대상입니다."
                         % (m0["targets"][0], m0["targets"][1], m0["reason"]))
    if not has_emb:
        sentences.append("임베딩 벡터가 없어 의미 기반 지표(응집도·실루엣·드리프트) 없이 "
                         "중복 특허 비율 기반으로 진단했습니다. '임베딩 벡터' 컬럼을 매핑하면 "
                         "정밀 진단이 가능합니다.")
    insight = build_insight(sentences, {"multi_ratio": multi_ratio, "silhouette": silhouette},
                            small_sample=check_small_sample(len(df), settings))
    return ok_result({
        "confusion": fig_confusion, "cohesion_figure": cohesion_fig,
        "cohesion": {k: round(v, 3) for k, v in cohesion.items()},
        "separation": None if not centroids else round(float(np.mean(
            [1.0 - z[i][j] for i in range(len(techs)) for j in range(len(techs))
             if i != j and z[i][j] is not None])), 3),
        "silhouette": silhouette, "multi_ratio": round(multi_ratio, 3),
        "low_conf_ratio": low_conf_ratio, "low_conf_list": low_conf_list,
        "drift": drift_by_tech, "keywords": keyword_info,
        "suggestions": suggestions[:40], "has_embedding": bool(has_emb),
    }, insight=insight)


# ===========================================================================
# src/api.py
# ===========================================================================
# -*- coding: utf-8 -*-
"""
api.py — API 응답 모듈. register_routes(app) 로 모든 엔드포인트를 등록한다.

공통 규약:
- 요청: POST JSON {"dataset"?, "filters"?, ...분석별 옵션}. dataset 미지정 시
  Settings 에 저장된 dataset 사용.
- 정상 응답: 분석 envelope (viz_payload.ok_result/empty_result/disabled_result).
- 오류 응답: {"status":"error","code":<HTTP코드>,"message":<안내문>} (표준 형식).
- 데이터 없음: {"status":"empty", ...} / 컬럼 누락: {"status":"disabled", ...}.
- 모든 분석 결과는 cache.cached_analysis 로 (dataset, 필터, 설정) 키 캐싱.
- 보안: dataset 명 화이트리스트 검증, 매핑된 컬럼만 사용, LLM ID 는 프론트에
  노출하지 않음(라벨만), 오류 메시지에 내부 경로·스택 미노출.

엔드포인트 목록 (Docstring 에 요청/응답 명세):
  GET  /api/config              앱 구성·분석 가용성 매트릭스·실행 로그
  GET  /api/datasets            Dataset 목록
  GET  /api/columns             Dataset 컬럼 목록 (?dataset=)
  GET/POST /api/column-mapping  자동 추천/저장/검증
  POST /api/filter-options      필터바 옵션
  POST /api/overview            Executive Overview
  POST /api/technology-network  4.2 조합 네트워크
  POST /api/technology-transition 4.1 전이 Sankey
  POST /api/emerging-combinations 4.3 Emerging Radar
  POST /api/trajectory          4.4 궤적
  POST /api/company-dna         4.5 DNA (+유사도·중첩도)
  POST /api/lead-lag            4.6 선도-추종
  POST /api/lifecycle           4.7 생애주기
  POST /api/opportunity         4.8 White Space
  POST /api/claim-density       4.9 권리장벽 지형도
  POST /api/citation-diffusion  4.10 영향력 전파
  POST /api/inventor-mobility   4.11 발명자 이동
  POST /api/classification-quality 4.12 분류 품질
  POST /api/problem-solution    문제-해결수단 매트릭스 (+cell 상세)
  POST /api/patents             근거 특허 drill-down (페이지네이션)
  POST /api/insight             LLM 인사이트 (요약 통계만 전달, 실패 시 규칙 기반)
  POST /api/export              Excel 다운로드
  POST /api/project/save|load   프로젝트 저장·불러오기 (+list)
  GET/POST /api/settings        설정 조회/저장
  GET/POST /api/applicant-rules 출원인 표준화 규칙
  POST /api/filter-state        필터 상태 저장
"""
import io
import json
import logging
import time
import traceback

import numpy as np
import pandas as pd

# [merged] from src import storage → shim 은 병합부에서 정의됨

logger = logging.getLogger("ip_landscape")

DEMO_DATASET_NAME = "__demo__"


def _error(code, message):
    return {"status": "error", "code": int(code), "message": str(message)}, int(code)


def _settings():
    return merged_settings(storage.load_settings())


def _make_demo_dataframe(n=400, seed=7):
    """Demo mode 전용 최소 합성 데이터 (반도체 패키징 도메인).

    사용자가 Settings 에서 demo_mode 를 명시적으로 켠 경우에만 사용된다.
    분석 본체는 실제 데이터 없이 값을 생성하지 않는다는 원칙의 예외가 아니라,
    '사용자가 명시적으로 선택한 Demo mode' 규칙에 따른 화면 확인용 데이터이다.
    """
    rng = np.random.default_rng(seed)
    l1 = ["패키징", "본딩", "테스트"]
    l2 = {"패키징": ["FOWLP", "FOPLP", "2.5D 인터포저", "3D 적층"],
          "본딩": ["하이브리드 본딩", "TCB", "와이어 본딩"],
          "테스트": ["웨이퍼 테스트", "번인 테스트"]}
    companies = ["삼성전자", "SK하이닉스", "TSMC", "Intel", "ASE", "Amkor", "네패스", "LB세미콘"]
    problems = ["휨(warpage) 저감", "미세피치 접합", "방열 개선", "수율 향상", "두께 감소"]
    solutions = ["몰드 소재 개선", "범프 구조 변경", "공정 온도 제어", "적층 구조 변경", "검사 알고리즘"]
    rows = []
    for i in range(n):
        a = l1[rng.integers(0, len(l1))]
        bs = l2[a]
        b = bs[rng.integers(0, len(bs))]
        multi = [b] + ([l2[l1[rng.integers(0, len(l1))]][0]] if rng.random() < 0.4 else [])
        year = int(rng.integers(2014, 2025))
        comp = companies[rng.integers(0, len(companies))]
        granted = rng.random() < 0.55
        rows.append({
            "공개번호": "KR10-%d-%07dA" % (year, i),
            "출원번호": "KR10-%d-%07d" % (year, i),
            "패밀리 ID": "F%05d" % (i // 2),
            "발명의 명칭": "%s 기반 %s 개선 기술" % (b, problems[i % len(problems)]),
            "요약": "%s 분야에서 %s 을(를) 위한 %s 접근." % (a, problems[i % len(problems)],
                                                     solutions[i % len(solutions)]),
            "독립청구항": ("반도체 패키지에 있어서, %s 구조를 포함하고 %s 특징을 갖는 "
                      "것을 특징으로 하는 %s 장치." % (b, solutions[i % len(solutions)], a)) * 2,
            "출원인": comp, "발명자": "발명자%d; 발명자%d" % (i % 40, (i + 7) % 40),
            "출원일": "%d-0%d-15" % (year, (i % 9) + 1), "국가": ["KR", "US", "JP", "CN"][i % 4],
            "법적상태": "등록" if granted else ["공개", "심사중", "거절", "소멸"][i % 4],
            "등록 여부": "Y" if granted else "N",
            "존속 여부": "Y" if granted and rng.random() < 0.8 else "N",
            "피인용 수": int(rng.poisson(3)), "인용 수": int(rng.poisson(5)),
            "패밀리 수": int(rng.integers(1, 8)), "패밀리 국가 수": int(rng.integers(1, 5)),
            "기술 대분류": a, "기술 중분류": b, "다중 기술분류": "; ".join(multi),
            "해결과제": problems[i % len(problems)], "해결수단": solutions[i % len(solutions)],
            "만료예정일": "%d-06-30" % (year + 20),
            "자사 특허 여부": "Y" if comp == "네패스" else "N",
        })
    return pd.DataFrame(rows)


def _resolve_dataset(body):
    """요청/설정에서 dataset 결정. demo_mode 면 데모 데이터 주입."""
    settings = _settings()
    name = (body or {}).get("dataset") or settings.get("dataset")
    if settings.get("demo_mode"):
        if DEMO_DATASET_NAME not in list_datasets():
            inject_dataset(DEMO_DATASET_NAME, _make_demo_dataframe())
        if not name or validate_dataset_name(name) is None:
            name = DEMO_DATASET_NAME
    if not name:
        raise LookupError(MESSAGES["no_dataset"])
    valid = validate_dataset_name(name)
    if valid is None:
        raise LookupError("허용되지 않은 Dataset 입니다: %s" % name)
    return valid, settings


def _prepared_for(body):
    """요청 → (필터 적용된 표준 프레임, settings, dataset, mapping). 공통 진입점."""
    dataset, settings = _resolve_dataset(body)
    saved = storage.load_mapping_for(dataset)
    actual_cols = get_dataset_columns(dataset)
    mapping, warnings = clean_mapping(saved, actual_cols)
    if not mapping:
        auto = suggest_mapping(actual_cols)
        mapping = {k: v["column"] for k, v in auto.items()}
    rules = storage.load_applicant_rules()
    df, _ = get_prepared(dataset, mapping, rules, settings.get("analysis_unit", "family"))
    filters = (body or {}).get("filters") or {}
    filtered = apply_filters(df, filters)
    return filtered, settings, dataset, mapping, filters


def _analysis_route(analysis_name, compute_fn, extra_key_fields=()):
    """분석 엔드포인트 공통 핸들러 생성 (캐싱 + 오류 표준화)."""
    def handler(body):
        df, settings, dataset, mapping, filters = _prepared_for(body)
        avail = analysis_availability(mapping)
        req = avail.get(analysis_name)
        if req and not req["available"]:
            return disabled_result(req["missing"])
        extra = {k: (body or {}).get(k) for k in extra_key_fields}
        key_parts = [dataset, filters, extra,
                     {"unit": settings.get("analysis_unit"),
                      "mode": settings.get("multiclass_mode"),
                      "limits": settings.get("limits"), "thresholds": settings.get("thresholds"),
                      "weights": settings.get("weights")}]
        return cached_analysis(analysis_name, key_parts,
                               lambda: (compute_fn(df, settings, body or {}), len(df)))
    return handler


def register_routes(app):
    """Flask app 에 모든 라우트 등록. Dataiku Standard Webapp 의 app 객체를 받는다."""
    from flask import request, jsonify, send_file

    def json_body():
        try:
            return request.get_json(force=True, silent=True) or {}
        except Exception:
            return {}

    def wrap(fn):
        """표준 오류 처리 래퍼."""
        def inner(*args, **kwargs):
            try:
                out = fn(*args, **kwargs)
                if hasattr(out, "status_code") and hasattr(out, "headers"):
                    return out  # send_file 등 Flask Response 는 그대로 통과
                if isinstance(out, tuple):
                    payload, code = out
                    return jsonify(jsonable(payload)), code
                return jsonify(jsonable(out))
            except LookupError as e:
                return jsonify(jsonable(_error(404, str(e))[0])), 404
            except (ValueError, KeyError, TypeError) as e:
                logger.warning("bad request: %s\n%s", e, traceback.format_exc())
                return jsonify(jsonable(_error(400, "요청 처리 오류: %s" % e)[0])), 400
            except Exception as e:
                logger.error("internal error: %s\n%s", e, traceback.format_exc())
                return jsonify(jsonable(_error(500, "내부 오류가 발생했습니다: %s" % e)[0])), 500
        inner.__name__ = "route_" + fn.__name__
        return inner

    # ---------------- 구성·메타 ----------------
    @app.route("/api/config", methods=["GET"])
    @wrap
    def api_config():
        """GET /api/config → 앱 정보, 설정(민감값 제외), 분석 가용성, 실행 로그.

        응답: {"app","version","settings","llm_options":[label...],"availability",
               "concepts","legal_status_categories","analysis_units","multiclass_modes",
               "limits_defaults","thresholds_defaults","weights_defaults","run_log",
               "filter_state","disclaimer"}
        """
        settings = _settings()
        dataset = settings.get("dataset")
        availability, mapping = {}, {}
        if settings.get("demo_mode") and not dataset:
            dataset = DEMO_DATASET_NAME
        if dataset:
            try:
                if settings.get("demo_mode") and dataset == DEMO_DATASET_NAME \
                        and DEMO_DATASET_NAME not in list_datasets():
                    inject_dataset(DEMO_DATASET_NAME, _make_demo_dataframe())
                cols = get_dataset_columns(dataset)
                mapping, _w = clean_mapping(storage.load_mapping_for(dataset), cols)
                if not mapping and cols:
                    mapping = {k: v["column"] for k, v in suggest_mapping(cols).items()}
                availability = analysis_availability(mapping)
            except Exception as e:
                logger.warning("config availability failed: %s", e)
        public_settings = {k: v for k, v in settings.items() if k != "llm_id"}
        llm_labels = [label for label, _id in ALLOWED_LLM_CANDIDATES]
        current_label = next((label for label, _id in ALLOWED_LLM_CANDIDATES
                              if _id == settings.get("llm_id")), llm_labels[0])
        return {"app": APP_NAME, "version": APP_VERSION,
                "settings": public_settings, "llm_options": llm_labels,
                "llm_current": current_label,
                "availability": availability, "mapping": mapping,
                "concepts": concept_catalog(),
                "legal_status_categories": LEGAL_STATUS_CATEGORIES,
                "analysis_units": ANALYSIS_UNITS, "multiclass_modes": MULTICLASS_MODES,
                "transition_modes": TRANSITION_MODES,
                "limits_defaults": LIMITS, "thresholds_defaults": THRESHOLDS,
                "weights_defaults": WEIGHTS,
                "run_log": get_run_log(50), "filter_state": storage.load_filter_state(),
                "disclaimer": MESSAGES["disclaimer"]}

    @app.route("/api/datasets", methods=["GET"])
    @wrap
    def api_datasets():
        """GET /api/datasets → {"datasets":[이름...]}"""
        return {"status": "ok", "datasets": list_datasets()}

    @app.route("/api/columns", methods=["GET"])
    @wrap
    def api_columns():
        """GET /api/columns?dataset=NAME → {"columns":[...]}. 404: 미허용 dataset."""
        name = validate_dataset_name(request.args.get("dataset"))
        if name is None:
            raise LookupError("허용되지 않은 Dataset 입니다.")
        return {"status": "ok", "dataset": name, "columns": get_dataset_columns(name)}

    @app.route("/api/column-mapping", methods=["GET", "POST"])
    @wrap
    def api_column_mapping():
        """컬럼 매핑 관리.

        GET  ?dataset= → 저장 매핑 + 자동 추천 + 가용성 매트릭스.
        POST {"dataset","mapping":{concept:column}} → 검증 후 저장.
        오류 400: 알 수 없는 개념/컬럼.
        """
        if request.method == "GET":
            name = validate_dataset_name(request.args.get("dataset"))
            if name is None:
                raise LookupError("허용되지 않은 Dataset 입니다.")
            cols = get_dataset_columns(name)
            saved, warnings = clean_mapping(storage.load_mapping_for(name), cols)
            suggestion = suggest_mapping(cols)
            effective = dict({k: v["column"] for k, v in suggestion.items()}, **saved)
            return {"status": "ok", "dataset": name, "columns": cols,
                    "saved": saved, "suggested": suggestion,
                    "effective": effective, "warnings": warnings,
                    "availability": analysis_availability(effective),
                    "concepts": concept_catalog()}
        body = json_body()
        name = validate_dataset_name(body.get("dataset"))
        if name is None:
            raise LookupError("허용되지 않은 Dataset 입니다.")
        mapping = body.get("mapping") or {}
        cols = set(get_dataset_columns(name))
        clean = {}
        for concept, col in mapping.items():
            if concept not in CONCEPTS:
                return _error(400, "알 수 없는 개념 컬럼: %s" % concept)
            if col:
                if col not in cols:
                    return _error(400, "Dataset 에 없는 컬럼: %s" % col)
                clean[concept] = col
        storage.save_mapping_for(name, clean)
        clear_all_caches()
        return {"status": "ok", "saved": clean,
                "availability": analysis_availability(clean)}

    @app.route("/api/filter-options", methods=["POST"])
    @wrap
    def api_filter_options():
        """POST {"dataset"?} → 필터바 옵션 (연도범위·출원인·국가·법적상태·기술분류)."""
        df, settings, dataset, mapping, _f = _prepared_for(json_body())
        return {"status": "ok", "options": filter_options(df), "dataset": dataset,
                "n_rows": len(df)}

    # ---------------- 분석 ----------------
    handlers = {
        "overview": _analysis_route(
            "overview", lambda df, s, b: compute_overview(df, s)),
        "technology-network": _analysis_route(
            "technology-network",
            lambda df, s, b: compute_tech_network(df, s, scope=b.get("scope", "all"),
                                                  company=b.get("company"),
                                                  color_by=b.get("color_by", "l1")),
            extra_key_fields=("scope", "company", "color_by")),
        "emerging-combinations": _analysis_route(
            "emerging-combinations", lambda df, s, b: compute_emerging(df, s)),
        "lifecycle": _analysis_route(
            "lifecycle", lambda df, s, b: compute_lifecycle(df, s)),
        "opportunity": _analysis_route(
            "opportunity", lambda df, s, b: compute_opportunity(df, s)),
        "problem-solution": _analysis_route(
            "problem-solution",
            lambda df, s, b: (cell_detail(df, s, b.get("problem"), b.get("solution"))
                              if b.get("cell") else compute_problem_solution(df, s)),
            extra_key_fields=("cell", "problem", "solution")),
        "technology-transition": _analysis_route(
            "technology-transition",
            lambda df, s, b: compute_transition(df, s, mode=b.get("mode"),
                                                period_years=b.get("period_years")),
            extra_key_fields=("mode", "period_years")),
        "trajectory": _analysis_route(
            "trajectory",
            lambda df, s, b: compute_trajectory(df, s, companies=b.get("companies"),
                                                method=b.get("method", "pca"),
                                                weighting=b.get("weighting")),
            extra_key_fields=("companies", "method", "weighting")),
        "company-dna": _analysis_route(
            "company-dna",
            lambda df, s, b: compute_company_dna(df, s, companies=b.get("companies")),
            extra_key_fields=("companies",)),
        "lead-lag": _analysis_route(
            "lead-lag",
            lambda df, s, b: compute_lead_lag(df, s, min_repeat=int(b.get("min_repeat", 1))),
            extra_key_fields=("min_repeat",)),
        "claim-density": _analysis_route(
            "claim-density",
            lambda df, s, b: compute_claim_density(df, s, tech=b.get("tech")),
            extra_key_fields=("tech",)),
        "citation-diffusion": _analysis_route(
            "citation-diffusion",
            lambda df, s, b: compute_citation_influence(df, s, top_n=b.get("top_n")),
            extra_key_fields=("top_n",)),
        "inventor-mobility": _analysis_route(
            "inventor-mobility",
            lambda df, s, b: compute_inventor_mobility(
                df, s, include_uncertain=bool(b.get("include_uncertain"))),
            extra_key_fields=("include_uncertain",)),
        "classification-quality": _analysis_route(
            "classification-quality", lambda df, s, b: compute_classification_quality(df, s)),
    }

    def make_analysis_view(path_name, handler):
        @wrap
        def view():
            return handler(json_body())
        view.__name__ = "api_" + path_name.replace("-", "_")
        return view

    for path_name, handler in handlers.items():
        app.add_url_rule("/api/%s" % path_name, "api_" + path_name.replace("-", "_"),
                         make_analysis_view(path_name, handler), methods=["POST"])

    # ---------------- Drill-down / Export ----------------
    @app.route("/api/patents", methods=["POST"])
    @wrap
    def api_patents():
        """POST {"dataset"?,"filters"?,"drill"?,"page","page_size"} → 근거 특허 목록.

        응답: {"status":"ok","total","page","page_size","records":[...]}.
        """
        body = json_body()
        df, settings, dataset, mapping, _f = _prepared_for(body)
        sub = select_patents(df, body.get("drill") or {})
        result = patent_records(sub, page=body.get("page", 1),
                                page_size=body.get("page_size",
                                                   get_limit(settings, "patents_page_size")),
                                max_page_size=get_limit(settings, "patents_max_page_size"))
        result["status"] = "ok"
        return result

    @app.route("/api/export", methods=["POST"])
    @wrap
    def api_export():
        """POST {"dataset"?,"filters"?,"drill"?,"filename"?} → Excel 파일 스트림."""
        body = json_body()
        df, settings, dataset, mapping, _f = _prepared_for(body)
        sub = select_patents(df, body.get("drill") or {})
        if not len(sub):
            return _error(404, "내보낼 데이터가 없습니다.")
        out_df = export_dataframe(sub, max_rows=get_limit(settings, "export_max_rows"))
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            out_df.to_excel(writer, index=False, sheet_name="patents")
        buf.seek(0)
        fname = str(body.get("filename") or "ip_landscape_export.xlsx")
        fname = "".join(ch for ch in fname if ch.isalnum() or ch in "._-가-힣") or "export.xlsx"
        if not fname.endswith(".xlsx"):
            fname += ".xlsx"
        return send_file(buf, as_attachment=True, download_name=fname,
                         mimetype="application/vnd.openxmlformats-officedocument"
                                  ".spreadsheetml.sheet")

    # ---------------- 인사이트 (LLM) ----------------
    @app.route("/api/insight", methods=["POST"])
    @wrap
    def api_insight():
        """POST {"analysis","metrics":{요약 통계},"sentences":[규칙 문장...]} →
        LLM 인사이트 (실패·비활성 시 규칙 기반 그대로). 원문 데이터는 전달하지 않는다.
        """
        body = json_body()
        settings = _settings()
        rule = build_insight(body.get("sentences") or [], body.get("metrics") or {})
        out = llm_augment_insight(str(body.get("analysis", ""))[:60], rule,
                                  body.get("metrics") or {}, settings)
        out["status"] = "ok"
        return out

    # ---------------- 설정 ----------------
    @app.route("/api/settings", methods=["GET", "POST"])
    @wrap
    def api_settings():
        """GET → 현재 설정(민감값 제외). POST {settings...} → 저장.

        llm 선택은 라벨("llm_label")로 받으며 서버가 고정 목록에서 ID 로 변환한다.
        """
        if request.method == "GET":
            s = _settings()
            return {"status": "ok",
                    "settings": {k: v for k, v in s.items() if k != "llm_id"}}
        body = json_body()
        current = storage.load_settings() or {}
        allowed_keys = set(DEFAULT_SETTINGS.keys()) | {"llm_label"}
        for k, v in body.items():
            if k not in allowed_keys:
                continue
            if k == "llm_label":
                match = next((_id for label, _id in ALLOWED_LLM_CANDIDATES if label == v), None)
                if match:
                    current["llm_id"] = match
                continue
            if k == "llm_id":
                continue  # 직접 지정 금지 (라벨 경유만 허용)
            if k == "analysis_unit" and v not in ANALYSIS_UNITS:
                return _error(400, "잘못된 분석 단위: %s" % v)
            if k == "multiclass_mode" and v not in MULTICLASS_MODES:
                return _error(400, "잘못된 다중분류 처리방식: %s" % v)
            if k == "dataset" and v and validate_dataset_name(v) is None:
                return _error(400, "허용되지 않은 Dataset: %s" % v)
            current[k] = v
        storage.save_settings(current)
        clear_all_caches()
        s = merged_settings(current)
        return {"status": "ok", "settings": {k: v for k, v in s.items() if k != "llm_id"}}

    @app.route("/api/applicant-rules", methods=["GET", "POST"])
    @wrap
    def api_applicant_rules():
        """출원인·권리자 표준화 관리.

        GET ?dataset= → 원본명/자동표준명/현재표준명 목록 + 저장 규칙 (검토·승인 UI 용).
        POST {"mapping":{원본:표준}, "groups":{표준:그룹}, "history_entry"?,
              "import"?:{...}} → 저장. "reset":[원본명...] → 해당 매핑 제거(원복).
        """
        if request.method == "GET":
            rules = storage.load_applicant_rules()
            names = []
            try:
                df, settings, dataset, mapping, _f = _prepared_for(
                    {"dataset": request.args.get("dataset")})
                raw_counts = df["applicant_raw"].replace("", np.nan).dropna().value_counts()
                user_map = (rules.get("mapping") or {})
                for raw, cnt in raw_counts.head(500).items():
                    auto = auto_standardize_name(raw)
                    names.append({"raw": str(raw), "auto": auto,
                                  "current": user_map.get(str(raw), auto),
                                  "approved": str(raw) in user_map, "count": int(cnt)})
            except (LookupError, ValueError):
                pass
            return {"status": "ok", "rules": rules, "names": names,
                    "note": "자동 표준화 결과는 확정값이 아니라 검토·승인 대상입니다."}
        body = json_body()
        rules = storage.load_applicant_rules() or {}
        if body.get("import"):
            imported = body["import"]
            if not isinstance(imported, dict):
                return _error(400, "가져오기 형식 오류: JSON 객체가 필요합니다.")
            rules = {"mapping": dict(imported.get("mapping") or {}),
                     "groups": dict(imported.get("groups") or {}),
                     "history": list(imported.get("history") or [])}
        if isinstance(body.get("mapping"), dict):
            rules.setdefault("mapping", {}).update(
                {str(k): str(v) for k, v in body["mapping"].items() if v})
        for raw in (body.get("reset") or []):
            rules.get("mapping", {}).pop(str(raw), None)
        if isinstance(body.get("groups"), dict):
            rules.setdefault("groups", {}).update(
                {str(k): str(v) for k, v in body["groups"].items() if v})
        for raw in (body.get("reset_groups") or []):
            rules.get("groups", {}).pop(str(raw), None)
        if body.get("history_entry"):
            rules.setdefault("history", []).append(
                {"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "entry": str(body["history_entry"])[:300]})
        storage.save_applicant_rules(rules)
        clear_all_caches()
        return {"status": "ok", "rules": rules}

    # ---------------- 프로젝트 저장·불러오기 / 필터 상태 ----------------
    @app.route("/api/project/save", methods=["POST"])
    @wrap
    def api_project_save():
        """POST {"name","filters","settings"?,"note"?} → 프로젝트 상태 저장."""
        body = json_body()
        name = str(body.get("name") or "").strip()
        if not name:
            return _error(400, "프로젝트 이름이 필요합니다.")
        projects = storage.load_projects()
        projects[name] = {"filters": body.get("filters") or {},
                          "settings": body.get("settings") or {},
                          "note": str(body.get("note") or "")[:500],
                          "saved_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        storage.save_projects(projects)
        return {"status": "ok", "projects": sorted(projects.keys())}

    @app.route("/api/project/load", methods=["POST"])
    @wrap
    def api_project_load():
        """POST {"name"?} → name 지정 시 해당 프로젝트, 미지정 시 목록."""
        body = json_body()
        projects = storage.load_projects()
        name = body.get("name")
        if not name:
            return {"status": "ok",
                    "projects": [{"name": k, "saved_at": v.get("saved_at"),
                                  "note": v.get("note")} for k, v in projects.items()]}
        if name not in projects:
            raise LookupError("프로젝트를 찾을 수 없습니다: %s" % name)
        if body.get("delete"):
            projects.pop(name)
            storage.save_projects(projects)
            return {"status": "ok", "deleted": name}
        return {"status": "ok", "project": projects[name], "name": name}

    @app.route("/api/filter-state", methods=["POST"])
    @wrap
    def api_filter_state():
        """POST {"filters":{...}} → 마지막 필터 상태 저장 (재방문 시 복원)."""
        storage.save_filter_state((json_body() or {}).get("filters") or {})
        return {"status": "ok"}

    return app


# ===========================================================================
# Webapp 부트스트랩
# ===========================================================================
# Dataiku Standard Webapp 은 전역 `app`(Flask) 을 주입한다.
# 로컬 개발·테스트 실행: python webapp/backend.py --serve [포트]
try:
    app  # noqa: F821  (Dataiku 주입 여부 확인)
except NameError:
    from flask import Flask
    app = Flask(__name__)

register_routes(app)

if __name__ == "__main__":
    import sys as _sys
    if "--serve" in _sys.argv:
        _port = 5000
        _idx = _sys.argv.index("--serve")
        if len(_sys.argv) > _idx + 1:
            try:
                _port = int(_sys.argv[_idx + 1])
            except ValueError:
                pass
        app.run(host="127.0.0.1", port=_port, debug=False)
