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

from src.config import get_threshold, get_limit
from src.gpu_utils import run_umap, run_hdbscan, cosine_similarity_matrix
from src.embedding_adapter import get_adapter
from src.insights import build_insight, fmt_num, fmt_pct, check_small_sample
from src.viz_payload import YLORRD, ok_result, empty_result, disabled_result, base_layout, \
    color_for, PALETTE


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
               "z": zz.tolist(), "colorscale": YLORRD, "opacity": 0.45,
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
