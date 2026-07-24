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
