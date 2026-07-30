# -*- coding: utf-8 -*-
"""
analyses/scope_entropy.py — 권리범위 엔트로피 레이더 · 시계열 (추가 인사이트).

핵심 질문:
  "한 회사의 특허가 다양한 기술방향을 커버하는가, 아니면 같은 청구구조를
   반복하는가?"

분석 개념:
  기업별 범주 분포에 대해 Shannon entropy 를 계산하고, 전체 범주 수 K 로
  정규화(H/log K, 0~1)하여 기업 간 비교 가능하게 만든다. 데이터에서 계산
  가능한 다양성 차원만 사용하며(임의 값 생성 금지), 차원별 근거 컬럼:

  1. 기술분류 다양성    — _tech_list (기술 대/중/소/다중 분류)
  2. IPC 다양성         — IPC/CPC 서브클래스 (예: H01L)
  3. 청구구조 다양성    — 독립청구항 임베딩(KR-SBERT)→KMeans 클러스터 분포.
                          임베딩 미가용 시 TF-IDF 벡터 폴백 (방식 표기).
  4. 청구 카테고리 다양성 — 독립청구항 말미 표현의 규칙 기반 분류
                          (조성물/필름·적층체/소자·장치/시스템/제조방법/용도)
  5. 시장(국가) 다양성  — 패밀리 국가 목록 (없으면 문헌 국가)
  6. 키워드 다양성      — 명칭·요약의 전역 상위 키워드 분포

차트:
  radar         — 기업별 차원 다양성 레이더 (scatterpolar)
  trend         — 기업×연도 기술분류 엔트로피 시계열 (선그래프, 정수 연도축)
  concentration — 전체 다양성(정규화 엔트로피 평균) vs 핵심 청구구조 집중도
                  (Top-1 범주 비중) 병렬 막대

해석 규칙 (자동 판정 — 최근 3년 vs 직전 3년 비교):
  다양성↑·출원↑ → 탐색적 R&D 확대 / 다양성↓·출원↑ → 핵심 후보 집중
  다양성↑·등록률↓ → 전략 분산 또는 특허성 검증 부족 가능성
  다양성↓·출원↓ → 수렴·정리 단계. 엔트로피 정점 연도로 탐색→수렴 전환
  시점을 추정한다 (통계적 신호이며 확정 판단 아님).

예외처리: 기업/표본 부족 시 empty, 기술분류·출원인 없으면 disabled.
"""
import math
import re

import numpy as np
import pandas as pd

from src.config import get_limit, get_threshold
from src.preprocessing import parse_multiclass_cell
from src.embedding_adapter import get_adapter
from src.analyses.claim_density import _preprocess_claims, _tfidf_vectors
from src.insights import build_insight, fmt_num, fmt_pct, check_small_sample
from src.viz_payload import ok_result, empty_result, disabled_result, base_layout, \
    color_for

_IPC_SUBCLASS_RE = re.compile(r"([A-H]\d{2}[A-Z])")

# 청구 카테고리 규칙 (우선순위 순서 — 먼저 맞는 규칙 적용)
_CLAIM_CATEGORY_RULES = [
    ("용도", re.compile(r"용도|use\b", re.IGNORECASE)),
    ("제조방법", re.compile(r"방법|method|process\b", re.IGNORECASE)),
    ("시스템", re.compile(r"시스템|system", re.IGNORECASE)),
    ("소자·장치", re.compile(r"장치|소자|디바이스|모듈|패키지|전지|셀|기기|apparatus|device",
                          re.IGNORECASE)),
    ("필름·적층체", re.compile(r"필름|적층체|적층판|시트|막\b|기판|film|laminate|sheet",
                           re.IGNORECASE)),
    ("조성물·재료", re.compile(r"조성물|수지|화합물|재료|중합체|폴리머|composition|polymer|"
                           r"compound|resin", re.IGNORECASE)),
]

_KW_TOKEN_RE = re.compile(r"[가-힣A-Za-z]{2,}")
_KW_STOP = {"및", "또는", "위한", "이를", "포함", "하는", "있는", "이상", "관한", "장치",
            "방법", "제조", "이용", "the", "and", "for", "with", "using", "method",
            "apparatus", "device", "thereof", "same", "based",
            "해결", "해결하기", "해결하는", "제공", "제공하는", "특징", "특징으로",
            "개선", "발명", "대한", "있어서", "구비", "구비한", "형성", "형성된",
            "포함하는", "따른", "통해", "위해", "관련"}


def _norm_entropy(counts, k_global):
    """정규화 Shannon entropy: H/log(K). counts: 범주→건수, K: 전역 범주 수."""
    total = float(sum(counts.values()))
    if total <= 0 or k_global < 2:
        return None
    h = 0.0
    for c in counts.values():
        p = c / total
        if p > 0:
            h -= p * math.log(p)
    return round(h / math.log(k_global), 4)


def _top1_share(counts):
    total = float(sum(counts.values()))
    if total <= 0:
        return None
    return round(max(counts.values()) / total, 4)


def _claim_category(text):
    tail = str(text)[-120:]  # "…을 특징으로 하는 X" 말미가 카테고리를 결정
    for name, rx in _CLAIM_CATEGORY_RULES:
        if rx.search(tail):
            return name
    return "기타"


def _dim_counts(rows_iter):
    """(company, [categories]) 이터러블 → (기업별 Counter, 전역 범주 set)."""
    per_company, global_cats = {}, set()
    for company, cats in rows_iter:
        if not company or not cats:
            continue
        bucket = per_company.setdefault(company, {})
        for cat in cats:
            bucket[cat] = bucket.get(cat, 0) + 1
            global_cats.add(cat)
    return per_company, global_cats


def _claim_clusters(work, settings):
    """독립청구항 임베딩 → KMeans 클러스터 라벨. (labels Series, method) 또는 (None, 이유)."""
    if "indep_claim" not in work.columns:
        return None, "독립청구항 미매핑"
    claims = _preprocess_claims(work["indep_claim"])
    idx = claims.dropna().index
    if len(idx) < 20:
        return None, "독립청구항 표본 부족 (%d건)" % len(idx)
    sub = work.loc[idx]
    id_col = "pub_number" if "pub_number" in sub.columns else \
        ("app_number" if "app_number" in sub.columns else None)
    ids = list(sub[id_col].astype(str)) if id_col else list(map(str, idx))
    vectors, method = None, None
    adapter = get_adapter(settings, df=sub, id_series=ids)
    if adapter is not None:
        emb = adapter.get_embeddings(ids, list(claims.loc[idx]))
        got = [emb.get(str(i)) for i in ids]
        keep = [i for i, v in enumerate(got) if v is not None]
        dims = {len(got[i]) for i in keep}
        if len(keep) >= 20 and len(dims) == 1:
            idx = idx[keep]
            vectors = np.vstack([got[i] for i in keep])
            method = "adapter:%s" % adapter.name
    if vectors is None:
        vectors = _tfidf_vectors(list(claims.loc[idx]))
        method = "tfidf_fallback"
    if getattr(vectors, "shape", (0,))[0] < 20:
        return None, "임베딩 확보 표본 부족"
    from sklearn.cluster import KMeans
    k = int(min(12, max(3, vectors.shape[0] // 25)))
    labels = KMeans(n_clusters=k, n_init=4, random_state=42).fit_predict(
        np.asarray(vectors, dtype=np.float64))
    return pd.Series(labels, index=idx), method


def _keyword_lists(work):
    """명칭+요약 → 전역 상위 키워드에 한정한 행별 토큰 리스트."""
    texts = None
    for col in ("title", "abstract"):
        if col in work.columns:
            s = work[col].astype(str)
            texts = s if texts is None else texts + " " + s
    if texts is None:
        return None
    token_rows = texts.map(lambda t: [w.lower() for w in _KW_TOKEN_RE.findall(str(t))
                                      if w.lower() not in _KW_STOP])
    freq = {}
    for row in token_rows:
        for w in set(row):
            freq[w] = freq.get(w, 0) + 1
    top = {w for w, _c in sorted(freq.items(), key=lambda kv: -kv[1])[:40]}
    if len(top) < 5:
        return None
    return token_rows.map(lambda row: [w for w in set(row) if w in top])


def compute_scope_entropy(df, settings, companies=None):
    """권리범위 엔트로피: 기업별 다양성 레이더 + 연도별 엔트로피 시계열."""
    if "applicant_display" not in df.columns or \
            not (df["applicant_display"].astype(str) != "").any():
        return disabled_result(["출원인"], message="출원인 정보가 없어 기업별 권리범위 "
                                               "엔트로피를 계산할 수 없습니다.")
    work = df[df["applicant_display"].astype(str) != ""].copy()
    min_docs = int(get_threshold(settings, "min_class_patents")) + 2  # 최소 5건
    counts = work["applicant_display"].value_counts()
    eligible = [c for c in counts.index if counts[c] >= min_docs]
    if companies:
        wanted = [str(c) for c in companies]
        eligible = [c for c in eligible if c in wanted]
    top_n = get_limit(settings, "entropy_top_companies")
    picked = eligible[:top_n]
    if len(picked) < 2:
        return empty_result("표본 %d건 이상인 기업이 %d개뿐이라 기업 간 다양성 비교를 "
                            "할 수 없습니다 (최소 2개 기업 필요)."
                            % (min_docs, len(picked)))
    work = work[work["applicant_display"].isin(picked)].copy()
    comp = work["applicant_display"]

    # ---- 차원별 (기업→범주 분포) 수집 --------------------------------------
    dims = []  # [{key,label,per_company,k,basis}]

    per, cats = _dim_counts(zip(comp, work["_tech_list"]))
    if len(cats) >= 2:
        dims.append({"key": "tech", "label": "기술분류 다양성", "per": per,
                     "k": len(cats), "basis": "기술 대/중/소/다중 분류"})

    if "ipc" in work.columns:
        ipc_lists = work["ipc"].map(
            lambda v: sorted({m for part in parse_multiclass_cell(v)
                              for m in _IPC_SUBCLASS_RE.findall(str(part))}))
        per, cats = _dim_counts(zip(comp, ipc_lists))
        if len(cats) >= 2:
            dims.append({"key": "ipc", "label": "IPC 다양성", "per": per,
                         "k": len(cats), "basis": "IPC/CPC 서브클래스"})

    cluster_labels, cluster_method = _claim_clusters(work, settings)
    if cluster_labels is not None:
        per, cats = _dim_counts(
            (comp.loc[i], ["c%d" % int(cluster_labels.loc[i])])
            for i in cluster_labels.index)
        if len(cats) >= 2:
            dims.append({"key": "claim_cluster", "label": "청구구조 다양성", "per": per,
                         "k": len(cats),
                         "basis": "독립청구항 임베딩 클러스터 (%s)" % cluster_method})

    if "indep_claim" in work.columns:
        cat_series = work["indep_claim"].map(
            lambda v: [_claim_category(v)] if isinstance(v, str) and len(str(v)) > 20
            else [])
        per, cats = _dim_counts(zip(comp, cat_series))
        if len(cats) >= 2:
            dims.append({"key": "claim_category", "label": "청구 카테고리 다양성",
                         "per": per, "k": len(cats),
                         "basis": "독립청구항 말미 표현 규칙 분류"})

    country_lists = None
    if "family_countries" in work.columns:
        country_lists = work["family_countries"].map(
            lambda v: sorted({str(c).strip().upper()[:2]
                              for c in parse_multiclass_cell(v)
                              if str(c).strip()}))
    elif "country" in work.columns:
        country_lists = work["country"].map(
            lambda v: [str(v).strip().upper()] if str(v).strip() else [])
    if country_lists is not None:
        per, cats = _dim_counts(zip(comp, country_lists))
        if len(cats) >= 2:
            dims.append({"key": "market", "label": "시장(국가) 다양성", "per": per,
                         "k": len(cats),
                         "basis": "패밀리 국가 목록" if "family_countries" in work.columns
                                  else "문헌 국가"})

    kw_rows = _keyword_lists(work)
    if kw_rows is not None:
        per, cats = _dim_counts(zip(comp, kw_rows))
        if len(cats) >= 5:
            dims.append({"key": "keyword", "label": "키워드 다양성", "per": per,
                         "k": len(cats), "basis": "명칭·요약 전역 상위 40 키워드"})

    if len(dims) < 2:
        return empty_result("다양성을 계산할 수 있는 차원이 %d개뿐입니다. 기술분류 외에 "
                            "IPC/독립청구항/패밀리 국가/명칭·요약 중 일부를 매핑하면 "
                            "레이더가 풍부해집니다." % len(dims))

    # ---- 레이더 ------------------------------------------------------------
    color_reg = {}
    radar_traces = []
    table_rows = []
    entropy_by_company = {}
    for company in picked:
        values, hovers = [], []
        for d in dims:
            e = _norm_entropy(d["per"].get(company, {}), d["k"])
            values.append(e if e is not None else 0.0)
            hovers.append("%s: %s (범주 %d개 사용 / 전역 %d개)"
                          % (d["label"], "%.2f" % e if e is not None else "계산 불가",
                             len(d["per"].get(company, {})), d["k"]))
        entropy_by_company[company] = {d["key"]: v for d, v in zip(dims, values)}
        radar_traces.append({
            "type": "scatterpolar", "name": company,
            "r": values + values[:1],
            "theta": [d["label"] for d in dims] + [dims[0]["label"]],
            "fill": "toself", "opacity": 0.55,
            "hovertext": hovers + hovers[:1], "hoverinfo": "text+name",
            "line": {"color": color_for(company, color_reg)}})
    radar_fig = {"data": radar_traces, "layout": base_layout(
        "권리범위 엔트로피 레이더 (정규화 Shannon Entropy, 0~1)",
        polar={"radialaxis": {"range": [0, 1], "tickfont": {"size": 10}}},
        height=460)}

    # ---- 시계열 (기술분류 엔트로피 × 연도) ---------------------------------
    trend_traces = []
    strategy_rows = {}
    tech_k = next((d["k"] for d in dims if d["key"] == "tech"), 0)
    yr = work[work["_base_year"].notna()].copy()
    if len(yr) and tech_k >= 2:
        yr["_y"] = yr["_base_year"].astype(int)
        for company in picked:
            sub = yr[yr["applicant_display"] == company]
            xs, es, ns = [], [], []
            for y, grp in sorted(sub.groupby("_y")):
                cnt = {}
                for lst in grp["_tech_list"]:
                    for t in (lst or []):
                        cnt[t] = cnt.get(t, 0) + 1
                if len(grp) < 3 or not cnt:
                    continue
                e = _norm_entropy(cnt, tech_k)
                if e is None:
                    continue
                xs.append(int(y))
                es.append(e)
                ns.append(len(grp))
            if len(xs) >= 3:
                trend_traces.append({
                    "type": "scatter", "mode": "lines+markers", "name": company,
                    "x": xs, "y": es,
                    "hovertext": ["%s %d년: 엔트로피 %.2f (출원 %d건)"
                                  % (company, x, e, n)
                                  for x, e, n in zip(xs, es, ns)],
                    "hoverinfo": "text",
                    "line": {"color": color_for(company, color_reg)}})
                strategy_rows[company] = _classify_strategy(company, xs, es, sub)
    trend_fig = {"data": trend_traces, "layout": base_layout(
        "연도별 기술분류 엔트로피 추이 (기업별)",
        xaxis={"title": "연도", "dtick": 1, "tickformat": "d"},
        yaxis={"title": "정규화 엔트로피 (0~1)", "range": [0, 1]})} \
        if trend_traces else None

    # ---- 다양성 vs 집중도 --------------------------------------------------
    conc_dim = next((d for d in dims if d["key"] == "claim_cluster"),
                    next(d for d in dims if d["key"] == "tech"))
    overall = [round(float(np.mean([v for v in entropy_by_company[c].values()])), 3)
               for c in picked]
    top1 = [_top1_share(conc_dim["per"].get(c, {})) for c in picked]
    conc_fig = {"data": [
        {"type": "bar", "name": "전체 다양성 (차원 평균)", "x": picked, "y": overall,
         "marker": {"color": "#4E79A7"}},
        {"type": "bar", "name": "핵심 청구구조 집중도 (Top-1 비중, %s)" % conc_dim["label"],
         "x": picked, "y": top1, "marker": {"color": "#E15759"}}],
        "layout": base_layout("전체 다양성 vs 핵심 청구구조 집중도",
                              barmode="group",
                              yaxis={"title": "0~1", "range": [0, 1]},
                              xaxis={"title": "기업"})}

    for i, company in enumerate(picked):
        row = {"company": company, "n": int(counts[company]),
               "entropies": entropy_by_company[company],
               "overall": overall[i], "top1_share": top1[i],
               "drill": {"type": "applicant", "applicant": company}}
        st = strategy_rows.get(company)
        if st:
            row.update(st)
        table_rows.append(row)

    definitions = [
        {"code": "H_norm", "name": "정규화 엔트로피",
         "definition": "기업의 범주 분포가 얼마나 고르게 퍼져 있는지 (0=한 범주 반복, "
                       "1=전 범주 균등)",
         "formula": "H/log(K), H=-Σ p·log(p), K=전역 범주 수",
         "basis": "차원별 근거: " + "; ".join("%s=%s" % (d["label"], d["basis"])
                                          for d in dims),
         "reading": "높을수록 다양한 기술방향 커버, 낮을수록 동일 구조 반복"},
        {"code": "Top-1", "name": "핵심 청구구조 집중도",
         "definition": "가장 많이 사용한 범주(%s)의 비중" % conc_dim["label"],
         "formula": "max(범주 건수)/총 건수",
         "basis": conc_dim["basis"],
         "reading": "높을수록 특정 청구구조에 권리 집중 (건수 대비 실질 커버리지 좁음)"},
    ]

    sentences = []
    ranked = sorted(table_rows, key=lambda r: -(r["overall"] or 0))
    hi, lo = ranked[0], ranked[-1]
    sentences.append("전체 다양성이 가장 높은 기업은 '%s'(%.2f, %s건)로 가치사슬을 넓게 "
                     "커버하고, 가장 낮은 기업은 '%s'(%.2f)로 유사 청구구조 반복 "
                     "가능성이 있습니다." % (hi["company"], hi["overall"],
                                      fmt_num(hi["n"]), lo["company"], lo["overall"]))
    conc_top = max(table_rows, key=lambda r: (r["top1_share"] or 0))
    if conc_top["top1_share"]:
        sentences.append("'%s'는 단일 청구구조 비중이 %s로 가장 높아, 건수(%s건) 대비 "
                         "실질 권리범위가 좁을 수 있습니다."
                         % (conc_top["company"], fmt_pct(conc_top["top1_share"]),
                            fmt_num(conc_top["n"])))
    for r in table_rows:
        if r.get("transition_year"):
            sentences.append("'%s'는 %d년을 정점으로 다양성이 축소되어 탐색→수렴 전환 "
                             "신호가 관찰됩니다 (%s)."
                             % (r["company"], r["transition_year"],
                                r.get("strategy", "")))
            break
    sentences.append("엔트로피는 분포 통계 신호이며 개별 청구항의 권리범위 판단을 "
                     "대체하지 않습니다.")

    insight = build_insight(
        sentences,
        {"companies": len(picked), "dimensions": [d["label"] for d in dims],
         "max_overall": hi["overall"], "min_overall": lo["overall"],
         "claim_cluster_method": cluster_method if cluster_labels is not None else None,
         "strategies": {r["company"]: r.get("strategy") for r in table_rows
                        if r.get("strategy")}},
        drills=[{"label": "%s 특허 보기" % hi["company"], "drill": hi["drill"]}],
        small_sample=check_small_sample(len(work), settings))
    return ok_result(
        {"radar": radar_fig, "trend": trend_fig, "concentration": conc_fig,
         "companies": table_rows, "definitions": definitions,
         "methods": {"claim_cluster": cluster_method if cluster_labels is not None
                     else "미사용", "dimensions": len(dims)}},
        insight=insight,
        meta={"note": "정규화 엔트로피(H/log K)는 전역 범주 수 기준이라 기업 간 비교 "
                      "가능합니다. 데이터에 없는 차원은 자동 제외되었습니다."})


def _classify_strategy(company, years, entropies, sub):
    """최근 3년 vs 직전 3년 비교로 전략 국면 판정 + 탐색→수렴 전환 연도."""
    out = {}
    if len(years) < 4:
        return out
    recent_e = float(np.mean(entropies[-3:]))
    prior_e = float(np.mean(entropies[-6:-3] or entropies[:-3]))
    ent_up = recent_e - prior_e
    yearly_n = sub.groupby(sub["_base_year"].astype(int)).size()
    ys = sorted(yearly_n.index)
    recent_n = float(yearly_n.loc[[y for y in ys[-3:]]].mean())
    prior_pool = [y for y in ys[:-3]][-3:]
    prior_n = float(yearly_n.loc[prior_pool].mean()) if prior_pool else recent_n
    fil_up = recent_n - prior_n
    grant_down = False
    if "_is_granted_bool" in sub.columns:
        g = sub[["_base_year", "_is_granted_bool"]].dropna()
        if len(g) >= 10:
            g["_y"] = g["_base_year"].astype(int)
            mid = ys[len(ys) // 2]
            recent_g = g[g["_y"] > mid]["_is_granted_bool"].map(
                lambda v: v is True).mean()
            prior_g = g[g["_y"] <= mid]["_is_granted_bool"].map(
                lambda v: v is True).mean()
            grant_down = bool(recent_g < prior_g - 0.05)
    eps = 0.03
    if ent_up > eps and grant_down:
        label = "전략 분산 또는 특허성 검증 부족 가능성 (다양성↑·등록률↓)"
    elif ent_up > eps and fil_up > 0:
        label = "탐색적 R&D 확대 (다양성↑·출원↑)"
    elif ent_up < -eps and fil_up > 0:
        label = "핵심 상용화 후보 집중 (다양성↓·출원↑)"
    elif ent_up < -eps and fil_up <= 0:
        label = "수렴·정리 단계 (다양성↓·출원↓)"
    else:
        label = "뚜렷한 국면 변화 없음"
    out["strategy"] = label
    out["entropy_change"] = round(ent_up, 3)
    out["filing_change"] = round(fil_up, 1)
    peak_i = int(np.argmax(entropies))
    if peak_i < len(years) - 2 and entropies[-1] < entropies[peak_i] - eps:
        out["transition_year"] = int(years[peak_i])
    return out
