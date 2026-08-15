# -*- coding: utf-8 -*-
"""
analyses/semantic_insights.py — 임베딩 기반 의미 분석 3종 (추가 인사이트).

공통: embed_corpus() 가 문헌 텍스트(요약+명칭 우선 → 독립청구항 → 명칭)를
KR-SBERT(embedding adapter 체인)로 임베딩하고, 모델 미가용 시 TF-IDF 문자
n-gram 벡터로 명시적 폴백한다 (임의 값 생성 아님 — 텍스트 기반 결정적 벡터,
사용 방식은 methods 로 화면 표기).

1. compute_emerging_clusters — 신흥 기술 조기 탐지 (Emerging Cluster Detection)
   전체 임베딩을 KMeans 군집화한 뒤 군집별 출원 시점 분포를 본다.
   최근 N년 비중이 높고, 신규 출원인이 늘고 있으며, 이전에 없던 새 군집이면
   "신흥 기술" 후보. 군집 중심에 가까운 특허들의 특징 키워드(군집 내 빈도/전역
   빈도 비율 상위)로 자동 라벨링한다.

2. compute_semantic_influence — 의미 기반 인용/영향력 대체 지표
   인용 데이터가 부실한 한국 특허 보완: 어떤 특허 이후에 의미적으로 매우
   유사한(코사인 ≥ 임계값) 후속 특허가 여러 '타 기업'에서 출원되었으면 명시적
   인용이 없어도 영향력 신호로 본다. 원천 특허 → 후속 기업 확산 Sankey +
   피인용 수와의 비교 산점도. **인용의 대체 신호일 뿐 인과관계·모방의 증거가
   아님을 meta 에 명시한다.**

3. compute_similarity_network — 특허 유사도 네트워크 (권리 중첩 그래프)
   코사인 유사도 ≥ 임계값(기본 0.85)인 특허쌍을 엣지로 연결한 Cytoscape
   네트워크. 촘촘한 연결 성분 = 유사 특허 밀집 지대(중첩 지대), 성분 내부를
   잇는 관절점(articulation point) = 브리지 특허. 노드 색 = 출원인.
   의미 유사도 신호이며 법적 권리범위 중첩 판단이 아니다.

예외처리: 텍스트 표본 부족 시 empty (+어떤 컬럼을 매핑하면 되는지 안내),
날짜 필요 분석은 연도 해석 불가 시 empty.
"""
import numpy as np
import pandas as pd

from src.config import get_limit, get_threshold
from src.gpu_utils import cosine_similarity_matrix
from src.embedding_adapter import get_adapter
from src.analyses.claim_density import _tfidf_vectors
from src.analyses.scope_entropy import doc_terms
from src.insights import build_insight, fmt_num, fmt_pct, check_small_sample
from src.viz_payload import YLGNBU, ok_result, empty_result, base_layout, color_for, \
    cytoscape_network, PALETTE


# ---------------------------------------------------------------------------
# 공통: 코퍼스 임베딩
# ---------------------------------------------------------------------------
def _corpus_texts(df):
    """문헌 대표 텍스트 시리즈 + 출처 설명. 우선순위: 요약+명칭 → 독립청구항 → 명칭."""
    if "abstract" in df.columns and df["abstract"].astype(str).str.len().ge(30).sum() \
            >= max(20, len(df) * 0.3):
        t = df["title"].astype(str) + ". " if "title" in df.columns else ""
        return (t + df["abstract"].astype(str)).str.replace(r"\s+", " ", regex=True) \
            .str.strip(), "명칭+요약"
    if "indep_claim" in df.columns:
        s = df["indep_claim"].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
        if s.str.len().ge(30).sum() >= 20:
            return s, "독립청구항"
    if "title" in df.columns:
        s = df["title"].astype(str).str.strip()
        if s.str.len().ge(10).sum() >= 20:
            return s, "발명의 명칭"
    return None, None


def embed_corpus(df, settings, max_docs, min_docs=20):
    """문헌 임베딩 확보. 반환 (work, ids, vectors, methods) 또는 (None,None,None,사유)."""
    texts, text_source = _corpus_texts(df)
    if texts is None:
        return None, None, None, ("임베딩할 텍스트가 없습니다 — 컬럼 매핑에서 "
                                  "'요약' 또는 '독립청구항'(권장) 혹은 '발명의 명칭'을 "
                                  "매핑하세요.")
    work = df.copy()
    work["_sem_text"] = texts.where(texts.str.len() >= 15, other=None)
    work = work[work["_sem_text"].notna()].reset_index(drop=True)
    if len(work) < min_docs:
        return None, None, None, ("유효 텍스트 보유 문헌이 %d건뿐입니다 (최소 %d건)."
                                  % (len(work), min_docs))
    truncated = len(work) > int(max_docs)
    if truncated:
        work = work.sample(n=int(max_docs), random_state=42).reset_index(drop=True)
    id_col = "pub_number" if "pub_number" in work.columns else \
        ("app_number" if "app_number" in work.columns else None)
    ids = list(work[id_col].astype(str)) if id_col else list(work.index.astype(str))

    vectors, emb_source = None, None
    adapter = get_adapter(settings, df=work, id_series=ids)
    if adapter is not None:
        emb = adapter.get_embeddings(ids, [t[:2000] for t in work["_sem_text"]])
        got = [emb.get(str(i)) for i in ids]
        keep = [i for i, v in enumerate(got) if v is not None]
        dims = {len(got[i]) for i in keep}
        if len(keep) >= max(min_docs, int(len(work) * 0.5)) and len(dims) == 1:
            work = work.iloc[keep].reset_index(drop=True)
            ids = [ids[i] for i in keep]
            vectors = np.vstack([got[i] for i in keep]).astype(np.float64)
            emb_source = "adapter:%s" % adapter.name
    if vectors is None:
        vectors = np.asarray(_tfidf_vectors(list(work["_sem_text"])), dtype=np.float64)
        emb_source = "tfidf_fallback"
    if vectors.shape[0] < min_docs:
        return None, None, None, "임베딩 확보 후 표본이 부족합니다."
    methods = {"embedding": emb_source, "text_source": text_source,
               "truncated": truncated, "n_docs": int(vectors.shape[0])}
    return work, ids, vectors, methods


def _distinct_keywords(cluster_texts, global_freq, n_global, top_k=4):
    """군집 특징 키워드 (c-TF-IDF 유사 점수).

    개선점 (애매한 라벨 방지):
    - 조사 제거·확장 불용어 정제 토큰 사용 (clean_tokens — scope_entropy 공유)
    - 인접 2어절 구문(bigram)을 단일어보다 1.6배 가중해 우선 선택
      ("소재" 보다 "재배선 소재" 가 라벨로 유의미)
    - 변별력(lift) 1.3 미만 항 제외 — 전역에서도 흔한 단어는 라벨에서 배제
    - 선택된 구문에 이미 포함된 단일어는 중복 제거
    계산은 카운트·정규식 뿐이라 속도 영향은 무시할 수준이다.
    """
    freq = {}
    for t in cluster_texts:
        for term in doc_terms(t):
            freq[term] = freq.get(term, 0) + 1
    n_c = max(len(cluster_texts), 1)
    scored = []
    for term, c in freq.items():
        is_bigram = " " in term
        min_c = max(2, int(n_c * (0.12 if is_bigram else 0.18)))
        if c < min_c:
            continue
        lift = (c / n_c) / ((global_freq.get(term, 0) + 1.0) / n_global)
        if lift < 1.3:
            continue
        scored.append((lift * c * (1.6 if is_bigram else 1.0), term))
    scored.sort(reverse=True)
    picked = []
    picked_words = set()
    for _s, term in scored:
        words = set(term.split())
        if " " not in term and words & picked_words:
            continue  # 이미 뽑힌 구문에 포함된 단일어
        if " " in term and words <= picked_words:
            continue  # 뽑힌 구문들과 완전히 겹치는 구문
        picked.append(term)
        picked_words |= words
        if len(picked) >= top_k:
            break
    if not picked:  # 변별 항이 없으면 빈도 상위로 폴백 (라벨 공백 방지)
        picked = [t for _c, t in sorted(((c, t) for t, c in freq.items()),
                                        reverse=True)[:top_k]]
    return picked


def _sim_matrix(vectors):
    sim = cosine_similarity_matrix(vectors)
    np.fill_diagonal(sim, 0.0)
    return sim


def _llm_cluster_names(clusters, settings):
    """LLM 으로 사람이 읽기 좋은 군집 명칭 생성 (1회 일괄 호출).

    입력: 군집별 특징 키워드 + 중심 최근접 대표 특허 명칭 3건.
    출력: {cluster_id: 명칭}. LLM 미가용·실패 시 {} (키워드 라벨 유지 — 폴백).
    명칭 규칙: 한국어 기술 용어 4~16자, 조사·서술어 없이 명사구.
    """
    from src.llm_client import call_llm, sanitize_for_llm, llm_available
    if not (settings or {}).get("llm_insights_enabled") or not llm_available():
        return {}
    lines = [
        "다음은 특허 임베딩 군집별 특징 키워드와 대표 특허 명칭입니다.",
        "각 군집에 기술 내용을 요약하는 짧은 한국어 명칭을 지어주세요.",
        "규칙: 4~16자 명사구(예: '하이브리드 본딩 접합', '저유전 몰딩 소재'), "
        "조사·서술어·따옴표 금지, 키워드 나열 금지, 대표 명칭에 없는 기술 지어내기 금지.",
        "응답은 각 줄에 '번호: 명칭' 형식만 출력하세요.",
    ]
    for c in clusters[:18]:
        lines.append("%d) 키워드: %s / 대표 특허명: %s"
                     % (c["cluster"],
                        sanitize_for_llm(", ".join(c["keywords"][:5]), 120),
                        sanitize_for_llm(" | ".join(c.get("rep_titles", [])[:3]), 220)))
    text = call_llm("\n".join(lines), llm_id=(settings or {}).get("llm_id"),
                    max_tokens=600, temperature=0.1)
    if not text:
        return {}
    import re as _re
    names = {}
    for line in str(text).splitlines():
        m = _re.match(r"^\s*(\d+)\s*[):.\-]\s*(.+?)\s*$", line)
        if m:
            name = m.group(2).strip().strip("'\"“”")
            if 2 <= len(name) <= 30:
                names[int(m.group(1))] = name
    return names


# ---------------------------------------------------------------------------
# 1) 신흥 기술 조기 탐지
# ---------------------------------------------------------------------------
def compute_emerging_clusters(df, settings, company=None, recent_years=None):
    """임베딩 군집 × 출원 시점 분포로 신흥 기술 후보 탐지 + 키워드 자동 라벨.

    company 지정 시 해당 출원인의 문헌만으로 군집화 — "이 회사가 어떤 신흥
    주제로 움직이는가"를 본다 (표본이 줄어 군집 수·안정성이 달라질 수 있음).
    공동출원 건은 해당 출원인이 공동출원인으로 포함되어 있으면 함께 집계한다.
    """
    if company:
        from src.analyses.common import applicant_mask
        df = df[applicant_mask(df, company, scope="any")]
        if len(df) < 30:
            return empty_result("출원인 '%s'의 문헌이 %d건뿐이라 군집 기반 신흥 기술 "
                                "탐지가 어렵습니다 (최소 30건). 전체 보기로 확인하세요."
                                % (company, len(df)))
    if not df["_base_year"].notna().any():
        return empty_result("연도를 해석할 수 있는 문헌이 없어 시점 분포 기반 신흥 기술 "
                            "탐지를 할 수 없습니다 — 출원일/우선일/공개일 매핑을 확인하세요.")
    work, ids, vectors, methods = embed_corpus(
        df, settings, get_limit(settings, "semantic_max_docs"))
    if work is None:
        return empty_result(methods)
    if not work["_base_year"].notna().any():
        # 전체 df 에는 연도가 있어도 텍스트 보유 문헌엔 없을 수 있음 (crash 방지)
        return empty_result("초록·청구항 텍스트가 있는 문헌들의 출원연도를 해석할 수 "
                            "없어 시점 기반 신흥 군집을 계산할 수 없습니다.")

    from sklearn.cluster import KMeans
    k = int(min(18, max(6, vectors.shape[0] // 40)))
    km = KMeans(n_clusters=k, n_init=4, random_state=42)
    labels = km.fit_predict(vectors)
    centers = km.cluster_centers_

    # recent_years 인자로 Y축 '최근 N년' 창을 조절할 수 있다 (2~10년 클램프)
    try:
        recent_n = int(recent_years) if recent_years else \
            int(get_threshold(settings, "recent_years"))
    except (TypeError, ValueError):
        recent_n = int(get_threshold(settings, "recent_years"))
    recent_n = max(2, min(10, recent_n))
    max_year = int(work["_base_year"].dropna().max())
    recent_from = max_year - recent_n + 1
    recent_share_min = float(get_threshold(settings, "emerging_cluster_recent_share"))

    # 전역 항(단일어+2어절 구문) 문헌빈도 — 특징 키워드 lift 의 분모
    global_freq = {}
    for t in work["_sem_text"]:
        for term in doc_terms(t):
            global_freq[term] = global_freq.get(term, 0) + 1

    clusters = []
    for cl in range(k):
        mask = labels == cl
        sub = work[mask]
        if len(sub) < 3:
            continue
        years = sub["_base_year"].dropna().astype(int)
        if not len(years):
            continue
        recent_share = float((years >= recent_from).mean())
        first_year = int(years.min())
        mean_year = float(years.mean())
        # 신규 출원인: 이 군집에서의 첫 출원이 최근 구간인 출원인 비율.
        # 특정 출원인 하나로 좁힌 보기에서는 '신규 출원인' 개념이 무의미하므로
        # 계산·표시하지 않고 점수에서도 제외한다 (가중치 재정규화).
        new_ratio = None
        apps = sub[sub["applicant_display"].astype(str) != ""]
        if not company and len(apps):
            first_by_app = apps.groupby("applicant_display")["_base_year"].min()
            new_ratio = float((first_by_app >= recent_from).mean())
        is_new = first_year >= recent_from
        if company:
            score = round((0.5 * recent_share + 0.2 * (1.0 if is_new else 0.0))
                          / 0.7, 3)
        else:
            score = round(0.5 * recent_share + 0.3 * (new_ratio or 0.0)
                          + 0.2 * (1.0 if is_new else 0.0), 3)
        # 키워드: 군집 중심에 가까운 문헌 상위 30건에서 추출
        d = np.linalg.norm(vectors[mask] - centers[cl], axis=1)
        near_idx = np.argsort(d)[:30]
        keywords = _distinct_keywords(
            [sub["_sem_text"].iloc[i] for i in near_idx], global_freq, len(work))
        label_txt = ", ".join(keywords[:3]) or ("군집 %d" % cl)
        # 대표 특허 명칭 (중심 최근접 3건) — 사람이 군집을 이해하는 근거 + LLM 명명 입력
        title_col = "title" if "title" in sub.columns else "_sem_text"
        rep_titles = [str(sub[title_col].iloc[i])[:60] for i in near_idx[:3]]
        top_apps = apps["applicant_display"].value_counts().head(3) if len(apps) \
            else pd.Series(dtype=int)
        clusters.append({
            "cluster": int(cl), "label": label_txt, "keywords": keywords,
            "rep_titles": rep_titles,
            "n": int(mask.sum()), "first_year": first_year,
            "mean_year": round(mean_year, 1), "recent_share": round(recent_share, 3),
            "new_applicant_ratio": round(new_ratio, 3) if new_ratio is not None else None,
            "is_new_cluster": bool(is_new), "score": score,
            "emerging": bool(recent_share >= recent_share_min and mask.sum() >= 5),
            "top_applicants": [{"name": str(a), "count": int(c)}
                               for a, c in top_apps.items()],
            "drill": {"type": "ids",
                      "ids": [ids[i] for i in np.where(mask)[0]][:200]},
        })
    if not clusters:
        return empty_result("군집을 형성할 표본이 부족합니다.")
    clusters.sort(key=lambda c: -c["score"])

    # 사람이 읽기 좋은 군집 명칭: LLM 일괄 명명 (미가용 시 키워드 라벨 유지)
    llm_names = _llm_cluster_names(clusters, settings)
    for c in clusters:
        if c["cluster"] in llm_names:
            c["label"] = llm_names[c["cluster"]]
            c["label_source"] = "llm"
        else:
            c["label_source"] = "keywords"
    label_method = "llm" if llm_names else "keywords"

    color_reg = {}
    if company:
        # 단일 출원인 보기: '신규 출원인 비율' 색·hover 표기 제거 (무의미)
        hovers = ["<b>%s</b><br>%d건 · 최초 %d년 · 최근 %d년 비중 %s"
                  "<br>점수 %.2f%s"
                  % (c["label"], c["n"], c["first_year"], recent_n,
                     fmt_pct(c["recent_share"]), c["score"],
                     " · 🆕 새 군집" if c["is_new_cluster"] else "")
                  for c in clusters]
        marker = {
            "size": [max(14.0, min(56.0, 10 + 2.2 * np.sqrt(c["n"]))) for c in clusters],
            "color": "#4E79A7",
            "line": {"width": [2.5 if c["is_new_cluster"] else 0.6 for c in clusters],
                     "color": "#E15759"}}
        title = ("신흥 기술 조기 탐지 — %s (크기=건수, 빨간 테두리=새 군집)"
                 % company)
    else:
        hovers = ["<b>%s</b><br>%d건 · 최초 %d년 · 최근 %d년 비중 %s"
                  "<br>신규 출원인 비율 %s · 점수 %.2f%s"
                  % (c["label"], c["n"], c["first_year"], recent_n,
                     fmt_pct(c["recent_share"]),
                     fmt_pct(c["new_applicant_ratio"])
                     if c["new_applicant_ratio"] is not None else "미상",
                     c["score"], " · 🆕 새 군집" if c["is_new_cluster"] else "")
                  for c in clusters]
        marker = {
            "size": [max(14.0, min(56.0, 10 + 2.2 * np.sqrt(c["n"]))) for c in clusters],
            "color": [c["new_applicant_ratio"] if c["new_applicant_ratio"] is not None
                      else 0.0 for c in clusters],
            "colorscale": YLGNBU, "cmin": 0, "cmax": 1,
            "colorbar": {"title": "신규 출원인 비율", "thickness": 12},
            "line": {"width": [2.5 if c["is_new_cluster"] else 0.6 for c in clusters],
                     "color": "#E15759"}}
        title = "신흥 기술 조기 탐지 — 임베딩 군집 × 출원 시점 (크기=건수, 빨간 테두리=새 군집)"
    fig = {"data": [{
        "type": "scatter", "mode": "markers", "cliponaxis": False,
        "x": [c["mean_year"] for c in clusters],
        "y": [c["recent_share"] for c in clusters],
        "hovertext": hovers,
        "hoverinfo": "text",
        "customdata": [{"drill": c["drill"],
                        "m": {"건수": c["n"], "최초연도": c["first_year"],
                              "최근비중": c["recent_share"],
                              "신규출원인비율": c["new_applicant_ratio"],
                              "점수": c["score"]}} for c in clusters],
        "marker": marker}],
        "layout": base_layout(
            title,
            xaxis={"title": "군집 평균 출원연도", "tickformat": "d"},
            yaxis={"title": "최근 %d년 출원 비중" % recent_n, "range": [-0.08, 1.1],
                   "tickformat": ".0%"}, height=520)}
    # 군집 라벨: 지시선 주석으로 겹침 없이 배치 (점수 높은 군집 우선,
    # 신흥/새 군집은 굵게 강조)
    from src.viz_payload import leader_labels
    lbl_order = sorted(clusters, key=lambda c: -c["score"])
    pts_lbl = [{"x": c["mean_year"], "y": c["recent_share"],
                "text": c["label"][:22],
                "bold": bool(c["emerging"] or c["is_new_cluster"]),
                "color": ("#c0392b" if (c["emerging"] or c["is_new_cluster"])
                          else "#38506b"),
                "line_color": ("#c0392b" if (c["emerging"] or c["is_new_cluster"])
                               else "#9fb2c2")}
               for c in lbl_order]
    fig["layout"].setdefault("annotations", [])
    fig["layout"]["annotations"] += leader_labels(pts_lbl, plot_h=490.0,
                                                  box_w=0.16)

    emergings = [c for c in clusters if c["emerging"]]
    sentences = []
    if emergings:
        c0 = emergings[0]
        dom = c0["top_applicants"][0]["name"] if c0["top_applicants"] else "-"
        if company:
            sentences.append("'%s'에서 가장 유력한 신흥 기술 후보는 '%s' 군집(%s건)으로, "
                             "출원의 %s가 최근 %d년에 몰려 있습니다 (단일 출원인 보기 — "
                             "신규 출원인 지표는 계산에서 제외)."
                             % (company, c0["label"], fmt_num(c0["n"]),
                                fmt_pct(c0["recent_share"]), recent_n))
        else:
            sentences.append("가장 유력한 신흥 기술 후보는 '%s' 군집(%s건)으로, 출원의 %s가 "
                             "최근 %d년에 몰려 있고 신규 출원인 비율이 %s입니다 (주도: %s)."
                             % (c0["label"], fmt_num(c0["n"]), fmt_pct(c0["recent_share"]),
                                recent_n,
                                fmt_pct(c0["new_applicant_ratio"])
                                if c0["new_applicant_ratio"] is not None else "미상", dom))
        news = [c for c in emergings if c["is_new_cluster"]]
        if news:
            sentences.append("이전 기간에는 존재하지 않던 새 군집이 %d개 관찰됩니다: %s."
                             % (len(news), "; ".join(c["label"] for c in news[:3])))
    else:
        sentences.append("최근 %d년 비중 %s 이상인 신흥 군집이 없습니다 — 포트폴리오가 "
                         "기존 기술 축 중심으로 유지되고 있습니다."
                         % (recent_n, fmt_pct(recent_share_min)))
    sentences.append("군집 라벨은 특징 키워드 자동 추출 결과이며, 신흥 여부는 출원 시점 "
                     "분포 신호입니다 (기술 가치 판단 아님).")

    insight = build_insight(
        sentences,
        {"n_clusters": len(clusters), "n_emerging": len(emergings),
         "recent_window": "%d–%d년" % (recent_from, max_year),
         "embedding": methods["embedding"], "text_source": methods["text_source"]},
        drills=[{"label": "후보 군집 특허 보기", "drill": emergings[0]["drill"]}]
        if emergings else None,
        small_sample=check_small_sample(len(work), settings))
    methods = dict(methods, scope=("출원인 '%s' 문헌만 (공동출원 포함)" % company)
                   if company else "전체 문헌")
    methods = dict(methods, labeling=label_method)
    return ok_result({"figure": fig, "clusters": clusters[:20], "methods": methods},
                     insight=insight,
                     meta={"note": "임베딩: %s (%s 기반). 군집 명칭: %s. 표본 상한 "
                                   "초과 시 무작위 샘플링됩니다."
                                   % (methods["embedding"], methods["text_source"],
                                      "LLM 이 키워드·대표 특허명으로 생성"
                                      if label_method == "llm"
                                      else "특징 키워드 자동 (LLM 활성화 시 읽기 쉬운 "
                                           "기술 명칭으로 자동 개선)"),
                           "truncated": methods["truncated"]})


# ---------------------------------------------------------------------------
# 2) 의미 기반 인용/영향력 대체 지표
# ---------------------------------------------------------------------------
def compute_semantic_influence(df, settings):
    """의미적으로 유사한 '타 기업 후속 특허' 수 기반 영향력 대체 지표 + 확산 Sankey."""
    if not df["_base_year"].notna().any():
        return empty_result("연도를 해석할 수 있는 문헌이 없어 선·후행 판정을 할 수 "
                            "없습니다 — 출원일/우선일/공개일 매핑을 확인하세요.")
    work, ids, vectors, methods = embed_corpus(
        df, settings, get_limit(settings, "semantic_max_docs"))
    if work is None:
        return empty_result(methods)
    has_year = work["_base_year"].notna()
    work = work[has_year].reset_index(drop=True)
    keep = np.where(has_year.values)[0]
    ids = [ids[i] for i in keep]
    vectors = vectors[keep]
    if len(work) < 20:
        return empty_result("연도 보유 문헌이 부족합니다 (최소 20건).")

    th = float(get_threshold(settings, "semantic_sim_threshold"))
    sim = _sim_matrix(vectors)
    years = work["_base_year"].astype(int).to_numpy()
    apps = work["applicant_display"].astype(str).to_numpy()
    later = years[None, :] > years[:, None]          # j 가 i 보다 늦은 출원
    similar = sim >= th
    follower = later & similar

    records = []
    for i in range(len(work)):
        js = np.where(follower[i])[0]
        if not len(js):
            continue
        cross = [j for j in js if apps[j] and apps[j] != apps[i]]
        comp_counts = {}
        for j in cross:
            comp_counts[apps[j]] = comp_counts.get(apps[j], 0) + 1
        records.append({
            "idx": i, "id": ids[i],
            "title": str(work["title"].iloc[i])[:60] if "title" in work.columns else "",
            "applicant": apps[i] or "-", "year": int(years[i]),
            "followers": int(len(js)), "cross_followers": int(len(cross)),
            "companies": len(comp_counts), "company_counts": comp_counts,
            "avg_sim": round(float(sim[i, js].mean()), 3),
            "score": round(float(sim[i, cross].sum()), 2) if cross else 0.0,
            "cites": (int(work["cites_forward"].iloc[i])
                      if "cites_forward" in work.columns
                      and pd.notna(work["cites_forward"].iloc[i]) else None),
            "follower_ids": [ids[j] for j in js][:200],
        })
    records.sort(key=lambda r: (-r["score"], -r["followers"]))
    top = [r for r in records if r["cross_followers"] >= 2][:12]
    if not top:
        return empty_result("코사인 %.2f 이상으로 유사한 '타 기업 후속 특허'를 2건 이상 "
                            "가진 문헌이 없습니다. Settings → 임계값에서 "
                            "semantic_sim_threshold 를 낮추면 더 느슨한 기준으로 "
                            "탐지합니다." % th)

    # Sankey: 원천 특허 → 후속 기업
    # 라벨은 문헌번호 전체를 사용한다 (뒤 몇 자리만 자르면 앞자리가 사라져
    # 번호가 잘못 보임). 흐름선은 원천 특허 색의 반투명으로 명시해 잘 보이게 한다.
    def _rgba(hex_color, alpha):
        h = hex_color.lstrip("#")
        return "rgba(%d,%d,%d,%.2f)" % (int(h[0:2], 16), int(h[2:4], 16),
                                        int(h[4:6], 16), alpha)
    src_nodes = top[:8]
    node_labels, node_colors = [], []
    comp_index = {}
    for i, r in enumerate(src_nodes):
        # 라벨: 출원번호 (출원인) — 어느 회사의 원천 특허인지 바로 식별
        node_labels.append("%s (%s)" % (r["id"], (r["applicant"] or "-")[:16]))
        node_colors.append(PALETTE[i % len(PALETTE)])
    links = {"source": [], "target": [], "value": [], "label": [], "color": []}
    for i, r in enumerate(src_nodes):
        for comp, cnt in sorted(r["company_counts"].items(), key=lambda kv: -kv[1])[:6]:
            if comp not in comp_index:
                comp_index[comp] = len(node_labels)
                node_labels.append(comp)
                node_colors.append("#8fa6b8")
            links["source"].append(i)
            links["target"].append(comp_index[comp])
            links["value"].append(int(cnt))
            links["label"].append("%s → %s: 유사 후속 %d건" % (r["id"], comp, cnt))
            links["color"].append(_rgba(PALETTE[i % len(PALETTE)], 0.45))
    n_side = max(len(src_nodes), len(comp_index))
    sankey = {"data": [{"type": "sankey", "orientation": "h",
                        "textfont": {"size": 11},
                        "node": {"label": node_labels, "color": node_colors,
                                 "pad": 22, "thickness": 18,
                                 "line": {"width": 0.5, "color": "#7a8b99"},
                                 "hovertemplate": "%{label}<extra></extra>"},
                        "link": dict(links, hovertemplate="%{label}<extra></extra>")}],
              "layout": base_layout("의미 기반 영향력 확산 — 왼쪽=원천 특허, 오른쪽=유사 "
                                    "후속 특허를 낸 기업, 띠 두께=후속 출원 수",
                                    height=max(480, 140 + 52 * n_side))}

    scatter = None
    with_cites = [r for r in records if r["cites"] is not None]
    if len(with_cites) >= 10:
        scatter = {"data": [{
            "type": "scatter", "mode": "markers",
            "x": [r["cites"] for r in with_cites],
            "y": [r["followers"] for r in with_cites],
            "hovertext": ["%s · %s<br>피인용 %d vs 의미 후속 %d"
                          % (r["id"], r["applicant"], r["cites"], r["followers"])
                          for r in with_cites],
            "hoverinfo": "text",
            "customdata": [{"drill": {"type": "ids", "ids": [r["id"]]}}
                           for r in with_cites],
            "marker": {"size": 8, "color": "#4E79A7", "opacity": 0.65}}],
            "layout": base_layout(
                "명시적 피인용 vs 의미 기반 후속 수 — 좌상단=인용에 안 잡히는 숨은 영향력",
                xaxis={"title": "피인용 수 (명시적 인용)"},
                yaxis={"title": "의미 유사 후속 특허 수"})}

    top_rows = []
    for r in top:
        row = {k: r[k] for k in ("id", "title", "applicant", "year", "followers",
                                 "cross_followers", "companies", "avg_sim",
                                 "score", "cites")}
        row["drill"] = {"type": "ids", "ids": [r["id"]] + r["follower_ids"]}
        top_rows.append(row)
    r0 = top[0]
    sentences = [
        "의미 기반 영향력 1위는 %s(%s, %d년)로, 이후 코사인 %.2f 이상 유사한 후속 "
        "특허가 %s건(타 기업 %s건, %d개사) 출원되었습니다%s."
        % (r0["id"], r0["applicant"], r0["year"], th, fmt_num(r0["followers"]),
           fmt_num(r0["cross_followers"]), r0["companies"],
           (" — 명시적 피인용은 %s건" % fmt_num(r0["cites"]))
           if r0["cites"] is not None else ""),
    ]
    hidden = [r for r in top if r["cites"] is not None and r["cites"] <= 1
              and r["cross_followers"] >= 3]
    if hidden:
        sentences.append("피인용은 %d건 이하지만 의미 후속이 많은 '숨은 영향력' 특허가 "
                         "%d건 있습니다 (인용 데이터가 부실한 KR 특허에서 유용한 신호)."
                         % (1, len(hidden)))
    sentences.append("이 지표는 의미 유사도 기반 '인용 대체 신호'이며, 후속 출원이 해당 "
                     "특허를 참고했다는 인과관계·모방의 증거가 아닙니다.")
    insight = build_insight(
        sentences,
        {"threshold": th, "n_influencers": len(top),
         "embedding": methods["embedding"], "text_source": methods["text_source"]},
        drills=[{"label": "1위 원천+후속 특허 보기", "drill": top_rows[0]["drill"]}],
        small_sample=check_small_sample(len(work), settings))
    return ok_result({"sankey": sankey, "scatter": scatter, "top_patents": top_rows,
                      "methods": dict(methods, threshold=th)},
                     insight=insight,
                     meta={"note": "의미 유사 후속 = 출원연도가 늦고 코사인 유사도 ≥ "
                                   "%.2f 인 문헌. 인용의 대체 신호일 뿐 인과관계가 "
                                   "아닙니다. 임계값은 Settings → 임계값에서 조정 "
                                   "가능합니다." % th,
                           "truncated": methods["truncated"]})


# ---------------------------------------------------------------------------
# 3) 특허 유사도 네트워크 (권리 중첩 그래프)
# ---------------------------------------------------------------------------
def _articulation_points(adj, nodes):
    """무향 그래프 관절점 (반복 DFS, Tarjan). adj: {node:set(node)}."""
    disc, low, parent = {}, {}, {}
    points = set()
    timer = [0]
    for root in nodes:
        if root in disc:
            continue
        stack = [(root, iter(adj[root]))]
        disc[root] = low[root] = timer[0]
        timer[0] += 1
        child_of_root = 0
        while stack:
            u, it = stack[-1]
            advanced = False
            for v in it:
                if v not in disc:
                    parent[v] = u
                    if u == root:
                        child_of_root += 1
                    disc[v] = low[v] = timer[0]
                    timer[0] += 1
                    stack.append((v, iter(adj[v])))
                    advanced = True
                    break
                elif v != parent.get(u):
                    low[u] = min(low[u], disc[v])
            if not advanced:
                stack.pop()
                p = parent.get(u)
                if p is not None:
                    low[p] = min(low[p], low[u])
                    if p != root and low[u] >= disc[p]:
                        points.add(p)
        if child_of_root >= 2:
            points.add(root)
    return points


def compute_similarity_network(df, settings, threshold=None):
    """임베딩 코사인 임계값 이상 특허쌍 네트워크 — 중첩 지대·브리지 특허."""
    work, ids, vectors, methods = embed_corpus(
        df, settings, get_limit(settings, "simnet_max_docs"))
    if work is None:
        return empty_result(methods)
    th = float(threshold) if threshold else \
        float(get_threshold(settings, "overlap_sim_threshold"))
    th = min(max(th, 0.5), 0.99)
    sim = _sim_matrix(vectors)
    iu, ju = np.triu_indices_from(sim, k=1)
    hit = sim[iu, ju] >= th
    pairs = list(zip(iu[hit], ju[hit], sim[iu, ju][hit]))
    if not pairs:
        return empty_result("코사인 유사도 %.2f 이상인 특허쌍이 없습니다. 위 임계값 "
                            "입력란(또는 Settings → 임계값 overlap_sim_threshold)을 "
                            "낮춰 다시 시도하세요. (문헌 %d건 분석, 임베딩: %s)"
                            % (th, len(work), methods["embedding"]))
    max_edges = get_limit(settings, "simnet_max_edges")
    pairs.sort(key=lambda p: -p[2])
    edge_truncated = len(pairs) > max_edges
    pairs = pairs[:max_edges]

    # 연결 성분 (union-find)
    parent = {}

    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent.setdefault(ra, ra)
            parent[rb] = ra
    adj = {}
    for i, j, s in pairs:
        adj.setdefault(int(i), set()).add(int(j))
        adj.setdefault(int(j), set()).add(int(i))
        union(int(i), int(j))
    node_idx = sorted(adj.keys())
    comp_of = {i: find(i) for i in node_idx}
    comp_members = {}
    for i, root in comp_of.items():
        comp_members.setdefault(root, []).append(i)
    bridges = _articulation_points(adj, node_idx)

    # 성분 요약 (크기순)
    comps = []
    for ci, (root, members) in enumerate(
            sorted(comp_members.items(), key=lambda kv: -len(kv[1]))):
        sub = work.iloc[members]
        app_counts = sub["applicant_display"].replace("", np.nan).dropna().value_counts()
        dom = str(app_counts.index[0]) if len(app_counts) else "-"
        dom_share = float(app_counts.iloc[0] / len(sub)) if len(app_counts) else None
        flags = sub["_active_flag"] if "_active_flag" in sub.columns else pd.Series(dtype=object)
        known = flags.map(lambda v: v is not None) if len(flags) else pd.Series(dtype=bool)
        active_ratio = float(flags[known].map(lambda v: v is True).mean()) \
            if len(flags) and known.any() else None
        internal = [s for i, j, s in pairs if comp_of.get(int(i)) == root]
        comps.append({
            "component": ci, "n": len(members), "dominant": dom,
            "dominant_share": round(dom_share, 3) if dom_share is not None else None,
            "active_ratio": round(active_ratio, 3) if active_ratio is not None else None,
            "avg_sim": round(float(np.mean(internal)), 3) if internal else None,
            "bridges": [ids[i] for i in members if i in bridges][:5],
            "drill": {"type": "ids", "ids": [ids[i] for i in members][:200]},
        })
    comp_rank = {root: ci for ci, (root, _m) in enumerate(
        sorted(comp_members.items(), key=lambda kv: -len(kv[1])))}

    color_reg = {}
    top_apps = work.iloc[node_idx]["applicant_display"].replace("", np.nan).dropna() \
        .value_counts().head(11).index.tolist()
    nodes_payload = []
    for i in node_idx:
        row = work.iloc[i]
        app = str(row.get("applicant_display") or "")
        group = app if app in top_apps else "기타"
        deg = len(adj[i])
        nodes_payload.append({
            "id": "n%d" % i, "label": str(ids[i]),  # 전체 번호 (잘림은 말줄임 처리)
            "full_id": ids[i],
            "title": str(row.get("title", ""))[:60],
            "applicant": app or "-", "group": group,
            "component": comp_rank[comp_of[i]], "degree": deg,
            "bridge": bool(i in bridges),
            "size": float(min(46, 16 + 3 * deg)),
            "color": color_for(group, color_reg),
            "border_color": "#E15759" if i in bridges else "#8899aa",
            "drill": {"type": "ids", "ids": [ids[i]]},
        })
    edges_payload = [{
        "source": "n%d" % i, "target": "n%d" % j,
        "weight": round(float(s), 3),
        "width": round(1.0 + 4.0 * (float(s) - th) / max(1e-6, 1.0 - th), 2),
        "drill": {"type": "ids", "ids": [ids[int(i)], ids[int(j)]]},
    } for i, j, s in pairs]
    network = cytoscape_network(nodes_payload, edges_payload)

    sentences = []
    if comps:
        c0 = comps[0]
        sentences.append("가장 큰 유사 특허 밀집 지대는 %s건 규모로 '%s'가 %s를 "
                         "차지합니다%s — 이 영역은 유사 청구가 몰린 권리 중첩 "
                         "후보 지대입니다."
                         % (fmt_num(c0["n"]), c0["dominant"],
                            fmt_pct(c0["dominant_share"])
                            if c0["dominant_share"] is not None else "일부",
                            (" (평균 유사도 %.2f)" % c0["avg_sim"])
                            if c0["avg_sim"] is not None else ""))
    n_bridges = sum(1 for n in nodes_payload if n["bridge"])
    if n_bridges:
        sentences.append("덩어리 사이를 잇는 브리지 특허(빨간 테두리)가 %d건 있습니다 — "
                         "이들이 소멸·회피되면 군집 간 연결이 끊어지는 구조적 요충 "
                         "문헌입니다." % n_bridges)
    sentences.append("이 네트워크는 의미 유사도(코사인 ≥ %.2f) 신호이며 법적 권리범위 "
                     "중첩 판단(FTO)을 대체하지 않습니다." % th)
    insight = build_insight(
        sentences,
        {"threshold": th, "n_nodes": len(nodes_payload), "n_edges": len(edges_payload),
         "n_components": len(comps), "n_bridges": n_bridges,
         "embedding": methods["embedding"]},
        drills=[{"label": "최대 밀집 지대 특허 보기", "drill": comps[0]["drill"]}]
        if comps else None,
        small_sample=check_small_sample(len(work), settings))
    return ok_result(
        {"network": network, "components": comps[:15],
         "methods": dict(methods, threshold=th, edge_truncated=edge_truncated)},
        insight=insight,
        meta={"note": "노드=특허(색=출원인, 크기=연결 수, 빨간 테두리=브리지/관절점), "
                      "엣지=코사인 유사도 ≥ %.2f. 의미 유사도 신호이며 FTO 판단이 "
                      "아닙니다.%s" % (th, " 엣지 %d개 상한 초과분은 유사도 상위만 "
                                         "표시." % max_edges if edge_truncated else ""),
              "truncated": methods["truncated"]})
