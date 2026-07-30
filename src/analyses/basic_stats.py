# -*- coding: utf-8 -*-
"""
analyses/basic_stats.py — 기본 통계 분석 (WIPS/PatentSquare 스타일).

분석 목적:
  상용 특허 DB(WIPS 등)가 제공하는 표준 통계를 한 화면에서 제공한다:
  ① 연도별 출원 동향 (전체/등록/유효), ② 국가별 분포, ③ 출원인 순위,
  ④ 출원인×연도 활동 매트릭스, ⑤ 기술분류 순위, ⑥ 기술분류×연도 동향,
  ⑦ 등록률·유효율 KPI.

필수 컬럼: 날짜(any)
선택 컬럼: 출원인, 국가, 기술분류, 등록 여부, 존속 여부

계산식:
  - 연도별 건수: _base_year groupby (등록=_is_granted_bool, 유효=_active_flag)
  - 등록률 = 등록 건수 / 등록 여부 판정 가능 건수, 유효율 동일
  - 순위·매트릭스는 Top-N 상한 적용 (top_n_default, matrix_max_rows)

그래프: 라인(연도), 막대(국가/출원인/분류), 히트맵(출원인×연도, 분류×연도).
Drill-down: 연도 점 {"type":"year"}, 국가 막대 {"country"}, 출원인 막대
  {"type":"applicant"}, 분류 막대 {"type":"tech"}, 매트릭스 셀 {applicant+year 등}.
자동 인사이트: 최다 출원 연도, 전체 성장률, 1위 국가/출원인/분류 점유율.
예외처리: 연도 없으면 empty(진단 메시지), 선택 컬럼 없으면 해당 차트만 생략.
"""
import numpy as np
import pandas as pd

from src.config import get_threshold, get_limit
from src.metrics import robust_growth, year_counts
from src.insights import build_insight, fmt_num, fmt_pct, period_label, check_small_sample
from src.viz_payload import ok_result, empty_result, line_chart, bar_chart, heatmap, \
    base_layout
from src.analyses.common import diagnose_year_tech


def _year_series(df, mask=None):
    sub = df if mask is None else df[mask]
    years = sub["_base_year"].dropna().astype(int)
    return year_counts(years) if len(years) else pd.Series(dtype=float)


def compute_basic_stats(df, settings):
    """기본 통계 계산."""
    if not len(df):
        return empty_result()
    years_all = df["_base_year"].dropna()
    if not len(years_all):
        return empty_result(diagnose_year_tech(df))
    top_n = int(get_limit(settings, "top_n_default")) + 5  # 순위는 15개
    max_rows = min(int(get_limit(settings, "matrix_max_rows")), 12)
    recent = int(get_threshold(settings, "recent_years"))

    # ① 연도별 동향
    total_s = _year_series(df)
    granted_s = _year_series(df, df["_is_granted_bool"].map(lambda v: v is True))
    active_s = _year_series(df, df["_active_flag"].map(lambda v: v is True))
    series_list = [{"name": "전체 출원", "x": [int(y) for y in total_s.index],
                    "y": [float(v) for v in total_s.values]}]
    if granted_s.sum() > 0:
        series_list.append({"name": "등록", "x": [int(y) for y in granted_s.index],
                            "y": [float(v) for v in granted_s.values]})
    if active_s.sum() > 0:
        series_list.append({"name": "유효", "x": [int(y) for y in active_s.index],
                            "y": [float(v) for v in active_s.values]})
    fig_annual = line_chart(series_list, "연도", "건수", title="연도별 출원 동향",
                            year_axis=True)
    for tr in fig_annual["data"]:
        tr["customdata"] = [{"drill": {"type": "year", "year": int(x)}} for x in tr["x"]]

    # ② 국가별 분포
    fig_country = None
    if "country" in df.columns:
        counts = df["country"].astype(str).str.strip().str.upper() \
            .replace("", np.nan).replace("NAN", np.nan).dropna().value_counts().head(top_n)
        if len(counts):
            fig_country = bar_chart(
                [str(c) for c in counts.index], [int(v) for v in counts.values],
                title="국가별 출원 분포", x_title="국가", y_title="건수",
                customdata=[{"drill": {"country": str(c)}} for c in counts.index])

    # ③ 출원인 순위 + ④ 출원인×연도 매트릭스
    fig_applicants, fig_app_year = None, None
    app_counts = df["applicant_display"].replace("", np.nan).dropna().value_counts()
    if len(app_counts):
        top_apps = app_counts.head(top_n)
        fig_applicants = bar_chart(
            [str(a) for a in top_apps.index][::-1], [int(v) for v in top_apps.values][::-1],
            title="출원인 순위 Top %d" % len(top_apps), orientation="h", x_title="건수",
            customdata=[{"drill": {"type": "applicant", "applicant": str(a)}}
                        for a in top_apps.index][::-1])
        matrix_apps = app_counts.head(max_rows).index.tolist()
        year_lo, year_hi = int(years_all.min()), int(years_all.max())
        years_range = list(range(year_lo, year_hi + 1))
        z, hover = [], []
        for a in matrix_apps:
            s = _year_series(df, df["applicant_display"] == a)
            row = [float(s.get(y, 0.0)) for y in years_range]
            z.append(row)
            hover.append(["%s — %d년: %s건" % (a, y, fmt_num(v))
                          for y, v in zip(years_range, row)])
        fig_app_year = heatmap(z, [str(y) for y in years_range], matrix_apps,
                               title="출원인 × 연도 활동 매트릭스", colorscale="Blues",
                               hovertext=hover, colorbar_title="건수")

    # ③-b 출원인 × 출원연도 버블 (크기=출원건수)
    fig_app_bubble = None
    if len(app_counts):
        bub_apps = app_counts.head(max_rows).index.tolist()
        year_lo, year_hi = int(years_all.min()), int(years_all.max())
        pts = {"x": [], "y": [], "size": [], "color": [], "hover": [], "custom": []}
        vmax = 1.0
        for a in bub_apps:
            s = _year_series(df, df["applicant_display"] == a)
            vmax = max(vmax, float(s.max()) if len(s) else 1.0)
        for a in bub_apps:
            s = _year_series(df, df["applicant_display"] == a)
            for y, v in s.items():
                if v <= 0:
                    continue
                pts["x"].append(int(y))
                pts["y"].append(str(a))
                pts["size"].append(float(7 + 33 * np.sqrt(float(v) / vmax)))
                pts["color"].append(float(v))
                pts["hover"].append("%s — %d년 출원 %s건" % (a, int(y), fmt_num(v)))
                pts["custom"].append({"drill": {"type": "applicant",
                                                "applicant": str(a), "year": int(y)},
                                      "m": {"출원인": str(a), "연도": int(y),
                                            "출원건수": int(v)}})
        fig_app_bubble = {"data": [{
            "type": "scatter", "mode": "markers",
            "x": pts["x"], "y": pts["y"],
            "hovertext": pts["hover"], "hoverinfo": "text",
            "customdata": pts["custom"],
            "marker": {"size": pts["size"], "color": pts["color"],
                       "colorscale": "Blues", "cmin": 0,
                       "colorbar": {"title": "출원건수", "thickness": 12},
                       "line": {"width": 0.6, "color": "#5b7a8a"}}}],
            "layout": base_layout(
                "출원인 × 출원연도 버블 (크기·색=출원건수)",
                xaxis={"title": "출원연도", "dtick": 1, "tickformat": "d",
                       "range": [year_lo - 0.7, year_hi + 0.7]},
                yaxis={"title": "", "type": "category", "automargin": True,
                       "categoryorder": "array",
                       "categoryarray": [str(a) for a in bub_apps[::-1]]},
                height=max(420, 130 + 36 * len(bub_apps)))}

    # ⑤ 기술분류 순위 + ⑥ 분류×연도
    fig_tech, fig_tech_year = None, None
    tech_flat = pd.Series([t for lst in df["_tech_list"] for t in (lst or [])])
    if len(tech_flat):
        tech_counts = tech_flat.value_counts()
        top_techs = tech_counts.head(top_n)
        fig_tech = bar_chart(
            [str(t) for t in top_techs.index][::-1], [int(v) for v in top_techs.values][::-1],
            title="기술분류별 건수 Top %d" % len(top_techs), orientation="h", x_title="건수",
            customdata=[{"drill": {"type": "tech", "tech": str(t)}}
                        for t in top_techs.index][::-1])
        matrix_techs = tech_counts.head(max_rows).index.tolist()
        year_lo, year_hi = int(years_all.min()), int(years_all.max())
        years_range = list(range(year_lo, year_hi + 1))
        z2, hover2 = [], []
        for t in matrix_techs:
            in_tech = df["_tech_list"].map(lambda lst: t in (lst or []))
            s = _year_series(df, in_tech)
            row = [float(s.get(y, 0.0)) for y in years_range]
            z2.append(row)
            hover2.append(["%s — %d년: %s건" % (t, y, fmt_num(v))
                           for y, v in zip(years_range, row)])
        fig_tech_year = heatmap(z2, [str(y) for y in years_range], matrix_techs,
                                title="기술분류 × 연도 동향", colorscale="YlGnBu",
                                hovertext=hover2, colorbar_title="건수")

    # ⑦ KPI
    granted_known = df["_is_granted_bool"].map(lambda v: v is not None)
    active_known = df["_active_flag"].map(lambda v: v is not None)
    grant_rate = (float(df.loc[granted_known, "_is_granted_bool"]
                        .map(lambda v: v is True).mean()) if granted_known.any() else None)
    active_rate = (float(df.loc[active_known, "_active_flag"]
                         .map(lambda v: v is True).mean()) if active_known.any() else None)
    growth, g_method = robust_growth(total_s, recent_years=recent)
    kpi = {"total": int(len(df)),
           "grant_rate": round(grant_rate, 3) if grant_rate is not None else None,
           "active_rate": round(active_rate, 3) if active_rate is not None else None,
           "growth": round(growth, 4) if growth is not None else None,
           "growth_method": g_method,
           "peak_year": int(total_s.idxmax()) if len(total_s) else None}

    sentences, metrics = [], dict(kpi)
    period = period_label(df)
    sentences.append("%s 전체 %s건, 최다 출원 연도는 %s년(%s건)이며 최근 %d년 성장률은 %s입니다."
                     % (period, fmt_num(kpi["total"]), kpi["peak_year"],
                        fmt_num(total_s.max()) if len(total_s) else "-", recent,
                        fmt_pct(kpi["growth"]) if kpi["growth"] is not None else "계산 불가"))
    if len(app_counts):
        share = app_counts.iloc[0] / float(len(df))
        sentences.append("출원인 1위는 '%s'(%s건, 점유율 %s)입니다."
                         % (app_counts.index[0], fmt_num(app_counts.iloc[0]), fmt_pct(share)))
    if kpi["grant_rate"] is not None:
        sentences.append("등록률 %s%s — 등록·유효 정보는 법적상태/등록여부 컬럼 기준입니다."
                         % (fmt_pct(kpi["grant_rate"]),
                            (", 유효율 %s" % fmt_pct(kpi["active_rate"]))
                            if kpi["active_rate"] is not None else ""))
    insight = build_insight(sentences, metrics,
                            small_sample=check_small_sample(len(df), settings))
    return ok_result({
        "kpi": kpi, "annual": fig_annual, "country": fig_country,
        "applicants": fig_applicants, "applicant_year": fig_app_year,
        "applicant_year_bubble": fig_app_bubble,
        "tech": fig_tech, "tech_year": fig_tech_year,
    }, insight=insight)
