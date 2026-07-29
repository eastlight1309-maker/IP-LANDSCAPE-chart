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

from src.config import get_threshold, get_limit, get_weights
from src.metrics import robust_growth, normalize_series, weighted_geometric_mean, \
    cosine_sim_vec, safe_div
from src.analyses.common import tech_year_matrix, combo_counts, diagnose_year_tech
from src.insights import build_insight, fmt_num, fmt_pct, period_label, check_small_sample
from src.viz_payload import ok_result, empty_result


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
        return empty_result(diagnose_year_tech(df))
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
                            "own": bool(r["own_capability"]),
                            # 축 선택 기능용 포인트별 지표
                            "m": {"attractiveness": r["attractiveness"],
                                  "entry_possibility": r["entry_possibility"],
                                  "opportunity_score": r["opportunity_score"],
                                  "barrier": r["barrier"], "total": r["total"],
                                  "growth": round(r["growth"], 4),
                                  "new_entrants": r["new_entrants"],
                                  "active_granted": r["active_granted"],
                                  "cr3": r["cr3"]}}}
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
    from src.viz_payload import base_layout
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
