# -*- coding: utf-8 -*-
"""
analyses/exec_plus.py — 경영진 의사결정 차트 6종 (Executive Plus).

섹션 (필요 컬럼 — 없으면 사유와 함께 생략, graceful degradation):
  ① expiry_cliff   특허 만료 절벽 — 향후 10년, 누구의·어떤 기술의·얼마나 중요한
                   특허가 풀리는지 (만료예정일 또는 등록일+20년, 피인용 가중)
  ② rnd_efficiency R&D 효율 사분면 — X=출원 규모, Y=질적 임팩트(피인용·패밀리·
                   유효율 합성), 자사 강조. "특허비를 잘 쓰고 있나"
  ③ keyman         키맨 리스크 — 자사 특허의 핵심 발명자 집중도(상위 10% 점유율·
                   HHI)와 발명자별 최근 활동 (이탈 신호는 '최근 출원 없음'으로만
                   표현 — 인과 판단 아님)
  ④ catchup        추격 시계 — 기술별 자사 vs 선두 누적 격차와 최근 속도 기준
                   추월 소요 연수 추정 (현재 속도 유지 가정의 산술 추정임을 명시)
  ⑤ threat         신흥 위협 레이더 — 자사 주력 기술에 최근 진입한 신규 플레이어
                   탐지 (진입 시점·출원 속도·질)
  ⑥ pruning        포트폴리오 다이어트 — 자사 유효특허 중 유지 재검토 후보
                   (판단 기준을 화면에 명시; 비용 금액은 데이터가 없어 계산하지
                   않음 — 건수·연차 분포만)

자사(focal)는 executive._pick_focal 재사용 (선택 company → Settings 자사명 →
자사 특허 여부 컬럼 → 최다 출원인). 모든 수치는 매핑된 실제 데이터로만 계산.
"""
import numpy as np
import pandas as pd

from src.config import get_threshold, get_limit
from src.metrics import year_counts
from src.insights import build_insight, fmt_num, fmt_pct, period_label, \
    check_small_sample
from src.viz_payload import ok_result, empty_result, bar_chart, base_layout, \
    color_for, BLUES
from src.analyses.executive import _pick_focal


def _xp_ids_of(sub, cap=200):
    col = "pub_number" if "pub_number" in sub.columns else \
        ("app_number" if "app_number" in sub.columns else None)
    return [str(v) for v in (sub[col] if col else sub.index)][:cap]


def _xp_primary_tech(df):
    return df["_tech_list"].map(lambda lst: lst[0] if lst else None)


# ---------------------------------------------------------------------------
# ① 특허 만료 절벽
# ---------------------------------------------------------------------------
def _expiry_cliff_section(df, settings, focal):
    if "expiry_date" in df.columns and df["expiry_date"].notna().any():
        exp_year = df["expiry_date"].dt.year
        basis = "만료예정일 컬럼"
    elif "reg_date" in df.columns and df["reg_date"].notna().any():
        exp_year = df["reg_date"].dt.year + 20
        basis = "등록일 + 20년 (만료예정일 미매핑 — 근사치)"
    else:
        return None, "만료예정일 또는 등록일 컬럼 필요"
    now_y = pd.Timestamp.now().year
    sub = df[exp_year.notna()].copy()
    sub["_exp_y"] = exp_year[exp_year.notna()].astype(int)
    # 아직 만료되지 않았고(유효 판단 가능하면 유효만), 향후 10년 내 만료
    if "_active_flag" in sub.columns and \
            sub["_active_flag"].map(lambda v: v is True).any():
        sub = sub[sub["_active_flag"].map(lambda v: v is not False)]
    sub = sub[(sub["_exp_y"] >= now_y) & (sub["_exp_y"] <= now_y + 10)]
    if len(sub) < 5:
        return None, "향후 10년 내 만료 예정 특허 부족 (5건 미만)"
    years = list(range(now_y, now_y + 11))
    top_apps = list(sub["applicant_display"].replace("", np.nan).dropna()
                    .value_counts().head(7).index)
    color_reg = {}
    traces = []
    for comp in top_apps:
        g = sub[sub["applicant_display"] == comp]
        cnt = g.groupby("_exp_y").size()
        traces.append({"type": "bar", "name": str(comp)[:20],
                       "x": years, "y": [int(cnt.get(y, 0)) for y in years],
                       "marker": {"color": "#E15759" if comp == focal
                                  else color_for(str(comp), color_reg)},
                       "customdata": [{"drill": {"applicant": str(comp)}}] * len(years),
                       "hovertext": ["%s — %d년 만료 %d건" % (comp, y, int(cnt.get(y, 0)))
                                     for y in years], "hoverinfo": "text"})
    others = sub[~sub["applicant_display"].isin(top_apps)]
    if len(others):
        cnt = others.groupby("_exp_y").size()
        traces.append({"type": "bar", "name": "기타",
                       "x": years, "y": [int(cnt.get(y, 0)) for y in years],
                       "marker": {"color": "#BAB0AC"}})
    fig = {"data": traces, "layout": base_layout(
        "특허 만료 절벽 — 향후 10년 연도별 만료 예정 (기업별 적층, 빨강=자사)",
        barmode="stack",
        xaxis={"title": "만료 연도", "dtick": 1, "tickformat": "d"},
        yaxis={"title": "만료 예정 특허 수"})}

    # 핵심 만료 특허: 피인용 상위 (없으면 최근 만료 임박 순)
    if "cites_forward" in sub.columns and sub["cites_forward"].notna().any():
        key = sub.sort_values("cites_forward", ascending=False).head(15)
        key_basis = "피인용 상위"
    else:
        key = sub.sort_values("_exp_y").head(15)
        key_basis = "만료 임박 순 (피인용 미매핑)"
    key_rows = []
    for _i, r in key.iterrows():
        ids = _xp_ids_of(key.loc[[_i]])
        key_rows.append({
            "id": ids[0] if ids else "-",
            "title": str(r.get("title", ""))[:60],
            "applicant": str(r.get("applicant_display", "")),
            "tech": (r.get("_tech_list") or ["-"])[0],
            "exp_year": int(r["_exp_y"]),
            "cites": (int(r["cites_forward"]) if "cites_forward" in sub.columns
                      and pd.notna(r.get("cites_forward")) else None),
            "is_focal": str(r.get("applicant_display", "")) == focal,
            "drill": {"type": "ids", "ids": ids}})
    by_year = sub.groupby("_exp_y").size()
    peak_y = int(by_year.idxmax())
    n_focal = int((sub["applicant_display"] == focal).sum())
    comp_exp = sub[sub["applicant_display"] != focal]
    comp_top = comp_exp["applicant_display"].replace("", np.nan).dropna() \
        .value_counts()
    return {"fig": fig, "key_rows": key_rows, "basis": basis,
            "key_basis": key_basis,
            "peak_year": peak_y, "peak_n": int(by_year.max()),
            "n_focal_expiring": n_focal,
            "top_competitor": (str(comp_top.index[0]) if len(comp_top) else None),
            "top_competitor_n": (int(comp_top.iloc[0]) if len(comp_top) else 0),
            "note": "만료 기준: %s. 실제 존속 여부는 연차료 납부에 따라 달라질 수 "
                    "있으므로 등록원부 확인이 필요합니다." % basis}, None


# ---------------------------------------------------------------------------
# ② R&D 효율 사분면
# ---------------------------------------------------------------------------
def _rnd_efficiency_section(df, settings, focal):
    apps = df["applicant_display"].replace("", np.nan).dropna()
    counts = apps.value_counts()
    min_n = max(5, int(get_threshold(settings, "min_class_patents")))
    comps = [c for c in counts.index if counts[c] >= min_n][:12]
    if len(comps) < 3:
        return None, "비교 가능한 출원인 부족 (5건 이상 기업 3개 미만)"
    has_cites = "cites_forward" in df.columns and df["cites_forward"].notna().any()
    has_family = "family_size" in df.columns and df["family_size"].notna().any()
    has_active = df["_active_flag"].map(lambda v: v is not None).any() \
        if "_active_flag" in df.columns else False
    if not (has_cites or has_family or has_active):
        return None, "질 지표 컬럼 필요 (피인용/패밀리 수/법적상태 중 1개 이상)"
    recent = int(get_threshold(settings, "recent_years"))
    max_year = df["_base_year"].dropna().max()
    rows = []
    for comp in comps:
        g = df[df["applicant_display"] == comp]
        met = {}
        if has_cites:
            met["cites"] = float(g["cites_forward"].dropna().mean() or 0)
        if has_family:
            met["family"] = float(g["family_size"].dropna().mean() or 0)
        if has_active:
            known = g["_active_flag"].map(lambda v: v is not None)
            met["active"] = (float(g.loc[known, "_active_flag"]
                                   .map(lambda v: v is True).mean())
                             if known.any() else None)
        rec_n = int((g["_base_year"] >= (max_year - recent + 1)).sum()) \
            if pd.notna(max_year) else 0
        rows.append({"company": str(comp), "n": int(counts[comp]),
                     "recent_n": rec_n, "metrics": met})
    # 질 지수 = 가용 지표별 z-score 평균 (지표 구성은 definitions 로 명시)
    used_metrics = [k for k in ("cites", "family", "active")
                    if any(r["metrics"].get(k) is not None for r in rows)]
    for k in used_metrics:
        vals = np.array([r["metrics"].get(k) if r["metrics"].get(k) is not None
                         else np.nan for r in rows], dtype=float)
        mu, sd = np.nanmean(vals), (np.nanstd(vals) or 1.0)
        for r, v in zip(rows, vals):
            r.setdefault("_zs", []).append(0.0 if np.isnan(v) else (v - mu) / sd)
    for r in rows:
        r["quality"] = round(float(np.mean(r.pop("_zs", [0.0]))), 3)
    x_med = float(np.median([r["n"] for r in rows]))
    y_med = float(np.median([r["quality"] for r in rows]))
    for r in rows:
        r["quadrant"] = (("양·질 겸비" if r["quality"] >= y_med else "다작·저임팩트")
                         if r["n"] >= x_med else
                         ("소작·정예" if r["quality"] >= y_med else "양·질 모두 부족"))
    max_rec = max([r["recent_n"] for r in rows] + [1])
    trace = {"type": "scatter", "mode": "markers+text",
             "x": [r["n"] for r in rows], "y": [r["quality"] for r in rows],
             "text": [r["company"][:12] for r in rows],
             "textposition": "top center", "textfont": {"size": 10},
             "hovertext": ["%s — 출원 %s건 / 질 지수 %+.2f (%s) / 최근 %d건"
                           % (r["company"], fmt_num(r["n"]), r["quality"],
                              r["quadrant"], r["recent_n"]) for r in rows],
             "hoverinfo": "text",
             "customdata": [{"drill": {"applicant": r["company"]}} for r in rows],
             "marker": {"size": [10 + 24 * np.sqrt(r["recent_n"] / max_rec)
                                 for r in rows],
                        "color": ["#E15759" if r["company"] == focal else "#4E79A7"
                                  for r in rows],
                        "opacity": 0.85, "line": {"width": 1, "color": "#333"}}}
    layout = base_layout(
        "R&D 효율 사분면 — 출원 규모 vs 질적 임팩트 (버블=최근 출원, 빨강=자사)",
        xaxis={"title": "누적 출원 건수", "type": "log"},
        yaxis={"title": "질 지수 (가용 지표 z-score 평균)"},
        shapes=[{"type": "line", "x0": x_med, "x1": x_med, "yref": "paper",
                 "y0": 0, "y1": 1, "line": {"color": "#bbb", "dash": "dot", "width": 1}},
                {"type": "line", "y0": y_med, "y1": y_med, "xref": "paper",
                 "x0": 0, "x1": 1, "line": {"color": "#bbb", "dash": "dot", "width": 1}}],
        annotations=[
            {"x": 0.99, "y": 0.99, "xref": "paper", "yref": "paper",
             "text": "양·질 겸비", "showarrow": False,
             "font": {"size": 11, "color": "#59A14F"}},
            {"x": 0.01, "y": 0.99, "xref": "paper", "yref": "paper",
             "text": "소작·정예", "showarrow": False,
             "font": {"size": 11, "color": "#888"}, "xanchor": "left"},
            {"x": 0.99, "y": 0.01, "xref": "paper", "yref": "paper",
             "text": "다작·저임팩트", "showarrow": False,
             "font": {"size": 11, "color": "#E15759"}, "yanchor": "bottom"}])
    fig = {"data": [trace], "layout": layout}
    metric_labels = {"cites": "평균 피인용", "family": "평균 패밀리 수",
                     "active": "유효특허 비율"}
    focal_row = next((r for r in rows if r["company"] == focal), None)
    return {"fig": fig, "rows": rows,
            "quality_metrics": [metric_labels[k] for k in used_metrics],
            "focal_quadrant": (focal_row["quadrant"] if focal_row else None)}, None


# ---------------------------------------------------------------------------
# ③ 키맨 리스크
# ---------------------------------------------------------------------------
def _keyman_section(df, settings, focal):
    if "_inventor_list" not in df.columns:
        return None, "발명자 컬럼 필요"
    g = df[df["applicant_display"] == focal]
    inv_counts = {}
    inv_last = {}
    inv_techs = {}
    for _i, r in g.iterrows():
        y = r.get("_base_year")
        for inv in (r.get("_inventor_list") or []):
            inv = str(inv).strip()
            if not inv:
                continue
            inv_counts[inv] = inv_counts.get(inv, 0) + 1
            if pd.notna(y):
                inv_last[inv] = max(inv_last.get(inv, 0), int(y))
            for t in (r.get("_tech_list") or [])[:1]:
                inv_techs.setdefault(inv, {})
                inv_techs[inv][t] = inv_techs[inv].get(t, 0) + 1
    if len(inv_counts) < 5:
        return None, "'%s'의 발명자 표본 부족 (5명 미만)" % focal
    total = sum(inv_counts.values())
    s = pd.Series(inv_counts).sort_values(ascending=False)
    n_top10 = max(1, int(np.ceil(len(s) * 0.10)))
    top10_share = float(s.head(n_top10).sum()) / total
    hhi = float(((s / total) ** 2).sum())
    max_year = int(df["_base_year"].dropna().max())
    top = s.head(12)
    inv_rows = []
    for inv, n in top.items():
        techs = inv_techs.get(inv, {})
        last = inv_last.get(inv)
        inactive = last is not None and last <= max_year - 2
        inv_rows.append({
            "inventor": str(inv), "n": int(n),
            "share": round(float(n) / total, 3),
            "top_tech": (max(techs, key=techs.get) if techs else "-"),
            "last_year": last,
            "inactive": bool(inactive),
            "drill": {"type": "inventor", "inventor": str(inv)}})
    fig = bar_chart(
        [r["inventor"] for r in inv_rows][::-1],
        [r["n"] for r in inv_rows][::-1],
        title="'%s' 핵심 발명자 Top %d (빨강=최근 2년 출원 없음)" % (focal, len(inv_rows)),
        orientation="h", x_title="발명 참여 특허 수",
        hovertext=["%s — %d건 (%s) · 주력 %s · 마지막 출원 %s"
                   % (r["inventor"], r["n"], fmt_pct(r["share"]), r["top_tech"],
                      r["last_year"] or "-") for r in inv_rows][::-1],
        colors=[("#E15759" if r["inactive"] else "#4E79A7")
                for r in inv_rows][::-1],
        customdata=[{"drill": r["drill"]} for r in inv_rows][::-1])
    n_inactive = sum(1 for r in inv_rows if r["inactive"])
    return {"fig": fig, "rows": inv_rows, "focal": focal,
            "n_inventors": int(len(s)), "top10_share": round(top10_share, 3),
            "hhi": round(hhi, 4), "n_inactive_top": n_inactive,
            "note": "'최근 2년 출원 없음'은 관찰 신호일 뿐 퇴사·이탈의 인과 판단이 "
                    "아닙니다. 발명자 이동 분석(경쟁 인텔리전스)과 함께 확인하세요."}, None


# ---------------------------------------------------------------------------
# ④ 추격 시계
# ---------------------------------------------------------------------------
def _catchup_section(df, settings, focal):
    tech_flat = pd.Series([t for lst in df["_tech_list"] for t in (lst or [])])
    if not len(tech_flat):
        return None, "기술분류 컬럼 필요"
    max_year = df["_base_year"].dropna().max()
    if pd.isna(max_year):
        return None, "연도 정보 필요"
    max_year = int(max_year)
    rows = []
    for tech in tech_flat.value_counts().head(10).index:
        in_tech = df[df["_tech_list"].map(lambda lst: tech in (lst or []))]
        counts = in_tech["applicant_display"].replace("", np.nan).dropna() \
            .value_counts()
        if not len(counts) or counts.iloc[0] < 5:
            continue
        leader = str(counts.index[0])
        n_focal = int(counts.get(focal, 0))
        if leader == focal:
            runner = (str(counts.index[1]) if len(counts) > 1 else None)
            rows.append({"tech": str(tech), "leader": leader, "gap": 0,
                         "status": "선두", "years_to_catch": None,
                         "runner": runner,
                         "runner_gap": (n_focal - int(counts.iloc[1])
                                        if len(counts) > 1 else None),
                         "drill": {"type": "tech", "tech": str(tech)}})
            continue
        gap = int(counts.iloc[0]) - n_focal
        # 최근 3년 연평균 출원 속도
        def _speed(comp):
            yrs = in_tech[in_tech["applicant_display"] == comp]["_base_year"] \
                .dropna().astype(int)
            return float((yrs >= max_year - 2).sum()) / 3.0
        v_focal, v_leader = _speed(focal), _speed(leader)
        if v_focal > v_leader:
            t = gap / (v_focal - v_leader)
            years = round(float(min(t, 99.0)), 1)
            status = "추월 가능 (~%.0f년)" % years if years <= 30 else "30년+"
        else:
            years, status = None, "현재 속도로는 추월 불가"
        rows.append({"tech": str(tech), "leader": leader, "gap": gap,
                     "focal_n": n_focal, "leader_n": int(counts.iloc[0]),
                     "focal_speed": round(v_focal, 1),
                     "leader_speed": round(v_leader, 1),
                     "status": status, "years_to_catch": years,
                     "drill": {"type": "tech", "tech": str(tech)}})
    if not rows:
        return None, "기술별 비교 표본 부족"
    plot = [r for r in rows if r["status"] != "선두"]
    fig = None
    if plot:
        plot_sorted = sorted(plot, key=lambda r: r["gap"])
        fig = bar_chart(
            ["%s (%s)" % (r["tech"], r["status"]) for r in plot_sorted],
            [r["gap"] for r in plot_sorted],
            title="'%s' 추격 시계 — 기술별 선두와의 누적 격차 (건)" % focal,
            orientation="h", x_title="선두와의 격차 (누적 출원 건수)",
            hovertext=["%s — 선두 %s(%d건) vs 자사 %d건, 격차 %d건 · 최근 속도 "
                       "%s vs %s건/년 → %s"
                       % (r["tech"], r["leader"], r["leader_n"], r["focal_n"],
                          r["gap"], r["leader_speed"], r["focal_speed"],
                          r["status"]) for r in plot_sorted],
            colors=[("#59A14F" if r["years_to_catch"] is not None
                     and r["years_to_catch"] <= 5 else
                     ("#F1CE63" if r["years_to_catch"] is not None else "#E15759"))
                    for r in plot_sorted],
            customdata=[{"drill": r["drill"]} for r in plot_sorted])
    n_lead = sum(1 for r in rows if r["status"] == "선두")
    return {"fig": fig, "rows": rows, "focal": focal, "n_leading": n_lead,
            "note": "추월 소요 연수는 '최근 3년 출원 속도가 그대로 유지된다'는 "
                    "가정의 산술 추정이며 예측이 아닙니다."}, None


# ---------------------------------------------------------------------------
# ⑤ 신흥 위협 레이더
# ---------------------------------------------------------------------------
def _threat_section(df, settings, focal):
    max_year = df["_base_year"].dropna().max()
    if pd.isna(max_year):
        return None, "연도 정보 필요"
    max_year = int(max_year)
    g = df[df["applicant_display"] == focal]
    focal_techs = pd.Series([t for lst in g["_tech_list"] for t in (lst or [])]) \
        .value_counts().head(5)
    if not len(focal_techs):
        return None, "'%s'의 기술분류 정보 필요" % focal
    entrants = []
    for tech in focal_techs.index:
        in_tech = df[df["_tech_list"].map(lambda lst: tech in (lst or []))]
        for comp, grp in in_tech.groupby("applicant_display"):
            comp = str(comp).strip()
            if not comp or comp == focal:
                continue
            yrs = grp["_base_year"].dropna().astype(int)
            if not len(yrs):
                continue
            first = int(yrs.min())
            if first < max_year - 2:   # 최근 3년 내 첫 진입만
                continue
            n_tech = int(len(grp))
            if n_tech < 2:
                continue
            total_n = int((df["applicant_display"] == comp).sum())
            avg_c = (float(grp["cites_forward"].dropna().mean())
                     if "cites_forward" in grp.columns
                     and grp["cites_forward"].notna().any() else None)
            entrants.append({"company": comp, "tech": str(tech),
                             "entry_year": first, "n_in_tech": n_tech,
                             "total_n": total_n, "avg_cites": avg_c,
                             "drill": {"type": "tech_applicant",
                                       "tech": str(tech), "applicant": comp}})
    if not entrants:
        return None, ("최근 3년 내 자사 주력 기술(%s)에 신규 진입한 기업이 "
                      "관측되지 않았습니다." % ", ".join(map(str, focal_techs.index[:3])))
    n_max = max(e["n_in_tech"] for e in entrants)
    c_vals = [e["avg_cites"] for e in entrants if e["avg_cites"] is not None]
    c_max = max(c_vals) if c_vals else 1.0
    for e in entrants:
        score = 0.5 * (e["n_in_tech"] / n_max) \
            + 0.3 * (1.0 - (max_year - e["entry_year"]) / 3.0) \
            + 0.2 * ((e["avg_cites"] or 0) / (c_max or 1.0))
        e["threat"] = round(float(score), 3)
    entrants.sort(key=lambda e: -e["threat"])
    color_reg = {}
    max_tot = max(e["total_n"] for e in entrants)
    trace = {"type": "scatter", "mode": "markers+text",
             "x": [e["entry_year"] for e in entrants],
             "y": [e["n_in_tech"] for e in entrants],
             "text": [e["company"][:10] for e in entrants],
             "textposition": "top center", "textfont": {"size": 9},
             "hovertext": ["%s — '%s' %d년 첫 진입, 해당 기술 %d건 / 전체 %d건%s "
                           "· 위협도 %.2f"
                           % (e["company"], e["tech"], e["entry_year"],
                              e["n_in_tech"], e["total_n"],
                              (" / 평균 피인용 %.1f" % e["avg_cites"])
                              if e["avg_cites"] is not None else "",
                              e["threat"]) for e in entrants],
             "hoverinfo": "text",
             "customdata": [{"drill": e["drill"]} for e in entrants],
             "marker": {"size": [8 + 22 * np.sqrt(e["total_n"] / max_tot)
                                 for e in entrants],
                        "color": [color_for(e["tech"], color_reg)
                                  for e in entrants],
                        "opacity": 0.85, "line": {"width": 1, "color": "#333"}}}
    fig = {"data": [trace], "layout": base_layout(
        "신흥 위협 레이더 — 자사 주력 기술 신규 진입자 (색=기술, 크기=기업 전체 규모)",
        xaxis={"title": "첫 진입 연도", "dtick": 1, "tickformat": "d"},
        yaxis={"title": "해당 기술 출원 수"})}
    return {"fig": fig, "rows": entrants[:15], "focal": focal,
            "focal_techs": [str(t) for t in focal_techs.index],
            "note": "위협도 = 0.5×해당기술 출원량 + 0.3×진입 최신성 + 0.2×평균 "
                    "피인용 (정규화). 탐지 기준: 최근 3년 내 첫 출원 + 2건 이상."}, None


# ---------------------------------------------------------------------------
# ⑥ 포트폴리오 다이어트
# ---------------------------------------------------------------------------
def _pruning_section(df, settings, focal):
    if "reg_date" not in df.columns or not df["reg_date"].notna().any():
        return None, "등록일 컬럼 필요 (등록 후 경과 연차 계산)"
    g = df[(df["applicant_display"] == focal) & df["reg_date"].notna()].copy()
    if "_active_flag" in g.columns and \
            g["_active_flag"].map(lambda v: v is not None).any():
        g = g[g["_active_flag"].map(lambda v: v is True)]
        active_basis = "유효(존속) 특허만"
    else:
        active_basis = "법적상태 미매핑 — 등록 특허 전체 기준"
    if len(g) < 10:
        return None, "'%s'의 등록 특허 부족 (10건 미만)" % focal
    now = pd.Timestamp.now()
    g["_age"] = ((now - g["reg_date"]).dt.days / 365.25)
    criteria = ["등록 후 5년 이상 경과 (연차료 누진 구간)"]
    mask = g["_age"] >= 5
    if "cites_forward" in g.columns and g["cites_forward"].notna().any():
        mask &= g["cites_forward"].fillna(0) <= 0
        criteria.append("피인용 0건 (후속 기술에 인용되지 않음)")
    if "family_country_count" in g.columns and \
            g["family_country_count"].notna().any():
        mask &= g["family_country_count"].fillna(1) <= 1
        criteria.append("단일국 출원 (해외 확장 없음)")
    core = pd.Series([t for lst in g["_tech_list"] for t in (lst or [])]) \
        .value_counts().head(3)
    if len(core):
        core_set = set(core.index)
        mask &= g["_tech_list"].map(
            lambda lst: not (set(lst or []) & core_set))
        criteria.append("비핵심 기술 (자사 상위 3개 분류 제외: %s)"
                        % ", ".join(map(str, core.index)))
    cand = g[mask]
    if not len(cand):
        return {"fig_tech": None, "fig_age": None, "rows": [],
                "n_candidates": 0, "n_active": int(len(g)),
                "criteria": criteria, "focal": focal,
                "active_basis": active_basis,
                "note": "현재 기준을 모두 만족하는 재검토 후보가 없습니다 — "
                        "포트폴리오가 비교적 잘 정리되어 있다는 신호입니다."}, None
    by_tech = pd.Series([_t for lst in cand["_tech_list"]
                         for _t in (lst or ["미분류"])]).value_counts().head(10)
    fig_tech = bar_chart(
        [str(t) for t in by_tech.index][::-1],
        [int(v) for v in by_tech.values][::-1],
        title="유지 재검토 후보 — 기술분류별 분포", orientation="h",
        x_title="후보 건수",
        customdata=[{"drill": {"type": "tech", "tech": str(t)}}
                    for t in by_tech.index][::-1])
    age_bins = pd.cut(cand["_age"], bins=[5, 8, 11, 14, 17, 30],
                      labels=["5~8년", "8~11년", "11~14년", "14~17년", "17년+"])
    age_counts = age_bins.value_counts().reindex(
        ["5~8년", "8~11년", "11~14년", "14~17년", "17년+"]).fillna(0)
    fig_age = bar_chart(
        list(age_counts.index.astype(str)), [int(v) for v in age_counts.values],
        title="후보 특허의 등록 후 경과 연차 — 오래될수록 연차료 부담 큼",
        x_title="등록 후 경과", y_title="건수")
    rows = []
    for _i, r in cand.sort_values("_age", ascending=False).head(20).iterrows():
        ids = _xp_ids_of(cand.loc[[_i]])
        rows.append({"id": ids[0] if ids else "-",
                     "title": str(r.get("title", ""))[:60],
                     "tech": (r.get("_tech_list") or ["-"])[0],
                     "age": round(float(r["_age"]), 1),
                     "drill": {"type": "ids", "ids": ids}})
    return {"fig_tech": fig_tech, "fig_age": fig_age, "rows": rows,
            "n_candidates": int(len(cand)), "n_active": int(len(g)),
            "ratio": round(float(len(cand)) / len(g), 3),
            "criteria": criteria, "focal": focal, "active_basis": active_basis,
            "note": "재검토 후보는 명시된 기준의 기계적 선별이며 포기 권고가 "
                    "아닙니다. 실제 요율·감면은 국가별로 달라 금액은 계산하지 "
                    "않습니다 (%s)." % active_basis}, None


# ---------------------------------------------------------------------------
# 통합
# ---------------------------------------------------------------------------
_EXEC_SECTIONS = (("expiry_cliff", _expiry_cliff_section),
             ("rnd_efficiency", _rnd_efficiency_section),
             ("keyman", _keyman_section),
             ("catchup", _catchup_section),
             ("threat", _threat_section),
             ("pruning", _pruning_section))


def compute_exec_plus(df, settings, company=None, only_sections=None):
    """경영진 의사결정 차트 6종 (섹션별 graceful degradation)."""
    if not len(df):
        return empty_result()
    focal, focal_basis = _pick_focal(df, settings, company)
    if focal is None:
        return empty_result("출원인 정보가 없어 자사(focal)를 정할 수 없습니다.")
    wanted = set(only_sections) if only_sections else None
    sections, skipped = {}, []
    for key, fn in _EXEC_SECTIONS:
        if wanted is not None and key not in wanted:
            continue
        try:
            result, reason = fn(df, settings, focal)
        except Exception as e:   # 개별 섹션 오류가 전체를 막지 않도록
            result, reason = None, "계산 오류: %s" % e
        if result is not None:
            sections[key] = result
        else:
            skipped.append({"section": key, "reason": reason})
    if not sections:
        return empty_result("계산 가능한 섹션이 없습니다: "
                            + "; ".join("%(section)s(%(reason)s)" % s
                                        for s in skipped))
    sentences, metrics = [], {"focal": focal}
    period = period_label(df)
    if "expiry_cliff" in sections:
        ec = sections["expiry_cliff"]
        sentences.append("%s 기준 만료 절벽의 피크는 %d년(%s건)이며, 경쟁사 중 "
                         "'%s'의 만료 예정이 %s건으로 가장 많아 해당 시점 전후가 "
                         "진입 기회 검토 구간입니다."
                         % (period, ec["peak_year"], fmt_num(ec["peak_n"]),
                            ec["top_competitor"] or "-",
                            fmt_num(ec["top_competitor_n"])))
        metrics["expiry_peak_year"] = ec["peak_year"]
    if "rnd_efficiency" in sections:
        re_ = sections["rnd_efficiency"]
        if re_["focal_quadrant"]:
            sentences.append("R&D 효율 사분면에서 자사('%s')는 '%s' 영역에 "
                             "위치합니다 (질 지표: %s)."
                             % (focal, re_["focal_quadrant"],
                                ", ".join(re_["quality_metrics"])))
    if "keyman" in sections:
        km = sections["keyman"]
        sentences.append("'%s' 특허의 %s는 상위 10%% 발명자(%s명 중 %d명 규모)가 "
                         "만들었습니다%s — 집중도가 높을수록 핵심 인력 이탈 "
                         "리스크가 큽니다."
                         % (focal, fmt_pct(km["top10_share"]), km["n_inventors"],
                            max(1, int(np.ceil(km["n_inventors"] * 0.1))),
                            (" (핵심 발명자 중 %d명은 최근 2년 출원 없음)"
                             % km["n_inactive_top"]) if km["n_inactive_top"] else ""))
        metrics["keyman_top10_share"] = km["top10_share"]
    if "catchup" in sections:
        cu = sections["catchup"]
        catchable = [r for r in cu["rows"] if r.get("years_to_catch") is not None
                     and r["years_to_catch"] <= 5]
        if cu["n_leading"]:
            sentences.append("자사는 %d개 기술분류에서 선두입니다." % cu["n_leading"])
        if catchable:
            c0 = min(catchable, key=lambda r: r["years_to_catch"])
            sentences.append("'%s'는 현재 속도 유지 시 약 %.0f년 내 추월 가능한 "
                             "가장 가까운 추격 대상입니다 (가정 기반 추정)."
                             % (c0["tech"], c0["years_to_catch"]))
    if "threat" in sections:
        th = sections["threat"]
        t0 = th["rows"][0]
        sentences.append("자사 주력 기술에 최근 3년 내 %d개 기업이 신규 진입했고, "
                         "위협도 1위는 '%s'('%s'에 %d년 진입, %d건)입니다."
                         % (len(th["rows"]), t0["company"], t0["tech"],
                            t0["entry_year"], t0["n_in_tech"]))
    if "pruning" in sections:
        pr = sections["pruning"]
        if pr["n_candidates"]:
            sentences.append("유효 포트폴리오 %s건 중 %s건(%s)이 유지 재검토 후보로 "
                             "선별되었습니다 — 연차료 절감 검토 대상입니다 "
                             "(기계적 선별, 포기 권고 아님)."
                             % (fmt_num(pr["n_active"]), fmt_num(pr["n_candidates"]),
                                fmt_pct(pr["ratio"])))
    if not sentences:
        sentences.append("%s 기준 경영 차트 %d개 섹션이 계산되었습니다."
                         % (period, len(sections)))
    insight = build_insight(sentences, metrics,
                            small_sample=check_small_sample(len(df), settings))
    return ok_result(
        {"sections": sections, "skipped": skipped,
         "focal": focal, "focal_basis": focal_basis},
        insight=insight,
        meta={"note": "자사(focal)='%s' (%s). 모든 수치는 현재 필터가 적용된 "
                      "데이터셋 기준의 통계 신호이며 법률·재무 자문이 아닙니다."
                      % (focal, focal_basis)})
