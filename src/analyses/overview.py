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

from src.config import get_threshold, get_limit
from src.metrics import robust_growth, hhi, cosine_sim_vec
from src.analyses.common import combo_counts, tech_year_matrix, company_tech_shares
from src.insights import build_insight, fmt_num, fmt_pct, period_label, check_small_sample
from src.viz_payload import ok_result, empty_result


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
    # 전체 목록 반환 — 표시는 호출부에서 절단하고, 인사이트의 '관측 N개'는
    # 절단 전 전체 수를 사용한다
    return sorted(out, key=lambda x: (-x["count"], -x["new_applicants"]))


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
    new_combos_all = _new_combos(df, settings, top_n)
    new_combos = new_combos_all[:top_n]
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
            "%s 기준 전체 %s건 중 최근 성장률 1위 기술은 '%s'(성장률 %s, 최근 %s건)"
            "입니다 — 표본 조건을 충족한 %s개 분류 중 1위."
            % (period, fmt_num(kpi["total"]), g0["tech"], fmt_pct(g0["growth"]),
               fmt_num(g0["recent"]), fmt_num(tech_meta.get("n_tech", 0))))
        metrics["top_growth_tech"] = g0["tech"]
        metrics["top_growth_rate"] = g0["growth"]
    if new_combos:
        sentences.append(
            "최근 %d년 내 처음 출현한 기술조합이 %s개 관측되었으며, 최다 조합은 '%s × %s'(%s건)입니다."
            % (int(get_threshold(settings, "recent_years")), fmt_num(len(new_combos_all)),
               new_combos[0]["a"], new_combos[0]["b"], fmt_num(new_combos[0]["count"])))
        metrics["new_combo_count"] = len(new_combos_all)
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
