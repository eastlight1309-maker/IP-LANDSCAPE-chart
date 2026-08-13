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
from src.viz_payload import BLUES, YLGNBU, ok_result, empty_result, line_chart, bar_chart, heatmap, \
    base_layout
from src.analyses.common import diagnose_year_tech, applicant_mask


def _year_series(df, mask=None):
    sub = df if mask is None else df[mask]
    years = sub["_base_year"].dropna().astype(int)
    return year_counts(years) if len(years) else pd.Series(dtype=float)


def _applicant_lists(df, mode):
    """행별 귀속 출원인 리스트.

    mode="all"  : 공동출원인 전원 (공동출원 1건이 각 출원인에게 1건씩)
    mode="first": 대표(첫) 출원인만
    """
    if mode == "all" and "_co_applicants_display" in df.columns:
        disp = df["applicant_display"].astype(str)
        return df["_co_applicants_display"].combine(
            disp, lambda lst, d: list(lst) if lst else ([d] if d else []))
    return df["applicant_display"].astype(str).map(lambda a: [a] if a else [])


def compute_basic_stats(df, settings, company=None):
    """기본 통계 계산.

    company 지정 시 해당 출원인의 문헌만 집계 (공동출원 건 포함).
    출원인별 차트는 settings["coapplicant_mode"] 를 따른다:
      all(기본)=공동출원인 각각 1건 집계, first=대표 출원인만.
    """
    co_mode = str(settings.get("coapplicant_mode", "all"))
    if company:
        df = df[applicant_mask(df, company, scope="any")]
        if not len(df):
            return empty_result("출원인 '%s'의 문헌이 없습니다 (공동출원 포함 검색)."
                                % company)
    if not len(df):
        return empty_result()

    def _drill_scope(d):
        """company 화면·공동출원 집계 모드에 맞게 drill 조건을 보정."""
        if co_mode == "all" and d.get("applicant"):
            d["applicant_scope"] = "any"
        if company:
            d["co_applicant"] = str(company)
        return d
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
        tr["customdata"] = [{"drill": _drill_scope({"type": "year", "year": int(x)})}
                            for x in tr["x"]]

    # ② 국가별 분포
    fig_country = None
    if "country" in df.columns:
        counts = df["country"].astype(str).str.strip().str.upper() \
            .replace("", np.nan).replace("NAN", np.nan).dropna().value_counts().head(top_n)
        if len(counts):
            fig_country = bar_chart(
                [str(c) for c in counts.index], [int(v) for v in counts.values],
                title="국가별 출원 분포", x_title="국가", y_title="건수",
                customdata=[{"drill": _drill_scope({"country": str(c)})}
                            for c in counts.index])

    # ③ 출원인 순위 + ④ 출원인×연도 매트릭스
    # 공동출원 처리: co_mode="all"이면 공동출원 1건을 각 공동출원인에게 1건씩 집계
    fig_applicants, fig_app_year = None, None
    app_lists = _applicant_lists(df, co_mode)
    n_joint = int(app_lists.map(lambda lst: len(lst) > 1).sum()) if co_mode == "all" \
        else int(df["_co_applicants_display"].map(lambda lst: len(lst or []) > 1).sum()
                 if "_co_applicants_display" in df.columns else 0)

    def _amask(a):
        return app_lists.map(lambda lst: str(a) in lst)

    app_counts = pd.Series([a for lst in app_lists for a in lst]) \
        .replace("", np.nan).dropna().value_counts()
    if len(app_counts):
        top_apps = app_counts.head(top_n)
        fig_applicants = bar_chart(
            [str(a) for a in top_apps.index][::-1], [int(v) for v in top_apps.values][::-1],
            title="출원인 순위 Top %d" % len(top_apps), orientation="h", x_title="건수",
            customdata=[{"drill": _drill_scope({"type": "applicant", "applicant": str(a)})}
                        for a in top_apps.index][::-1])
        matrix_apps = app_counts.head(max_rows).index.tolist()
        year_lo, year_hi = int(years_all.min()), int(years_all.max())
        years_range = list(range(year_lo, year_hi + 1))
        z, hover = [], []
        for a in matrix_apps:
            s = _year_series(df, _amask(a))
            row = [float(s.get(y, 0.0)) for y in years_range]
            z.append(row)
            hover.append(["%s — %d년: %s건" % (a, y, fmt_num(v))
                          for y, v in zip(years_range, row)])
        fig_app_year = heatmap(z, [str(y) for y in years_range], matrix_apps,
                               title="출원인 × 연도 활동 매트릭스", colorscale=BLUES,
                               hovertext=hover, colorbar_title="건수")

    # ③-b 출원인 × 출원연도 버블 (크기=출원건수)
    fig_app_bubble = None
    if len(app_counts):
        bub_apps = app_counts.head(max_rows).index.tolist()
        year_lo, year_hi = int(years_all.min()), int(years_all.max())
        pts = {"x": [], "y": [], "size": [], "color": [], "hover": [], "custom": []}
        vmax = 1.0
        for a in bub_apps:
            s = _year_series(df, _amask(a))
            vmax = max(vmax, float(s.max()) if len(s) else 1.0)
        for a in bub_apps:
            s = _year_series(df, _amask(a))
            for y, v in s.items():
                if v <= 0:
                    continue
                pts["x"].append(int(y))
                pts["y"].append(str(a))
                pts["size"].append(float(7 + 33 * np.sqrt(float(v) / vmax)))
                pts["color"].append(float(v))
                pts["hover"].append("%s — %d년 출원 %s건" % (a, int(y), fmt_num(v)))
                pts["custom"].append({"drill": _drill_scope({"type": "applicant",
                                                             "applicant": str(a),
                                                             "year": int(y)}),
                                      "m": {"출원인": str(a), "연도": int(y),
                                            "출원건수": int(v)}})
        _bub_cut = max(float(np.median(pts["color"])) if pts["color"] else 0, 2)
        fig_app_bubble = {"data": [{
            "type": "scatter", "mode": "markers+text", "cliponaxis": False,
            "x": pts["x"], "y": pts["y"],
            "text": [(fmt_num(v) if v >= _bub_cut else "") for v in pts["color"]],
            "textposition": "middle center",
            "textfont": {"size": 9, "color": "#1f3550"},
            "hovertext": pts["hover"], "hoverinfo": "text",
            "customdata": pts["custom"],
            "marker": {"size": pts["size"], "color": pts["color"],
                       "colorscale": BLUES, "cmin": 0,
                       "colorbar": {"title": "출원건수", "thickness": 12},
                       "line": {"width": 0.6, "color": "#5b7a8a"}}}],
            "layout": base_layout(
                "출원인 × 출원연도 버블 (크기·색=출원건수)",
                xaxis={"title": "출원연도", "dtick": 1, "tickformat": "d",
                       "range": [year_lo - 0.7, year_hi + 0.7]},
                yaxis={"title": "", "type": "category", "automargin": True,
                       "categoryorder": "array",
                       "categoryarray": [str(a) for a in bub_apps[::-1]],
                       "range": [-0.9, len(bub_apps) - 0.1]},
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
            customdata=[{"drill": _drill_scope({"type": "tech", "tech": str(t)})}
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
                                title="기술분류 × 연도 동향", colorscale=YLGNBU,
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
    if n_joint:
        sentences.append(
            ("공동출원 %s건은 각 공동출원인에게 1건씩 집계되어 출원인별 합계가 전체 "
             "건수를 초과할 수 있습니다 (Settings→공동출원 집계에서 변경 가능)."
             if co_mode == "all" else
             "공동출원 %s건은 대표(첫) 출원인에게만 집계됩니다 (Settings→공동출원 "
             "집계에서 '각각 집계'로 변경 가능).") % fmt_num(n_joint))
    if kpi["grant_rate"] is not None:
        sentences.append("등록률 %s%s — 등록·유효 정보는 법적상태/등록여부 컬럼 기준입니다."
                         % (fmt_pct(kpi["grant_rate"]),
                            (", 유효율 %s" % fmt_pct(kpi["active_rate"]))
                            if kpi["active_rate"] is not None else ""))
    insight = build_insight(sentences, metrics,
                            small_sample=check_small_sample(len(df), settings))

    # 차트별 인사이트 — 각 차트 바로 아래에 분리 표시 (차트가 없으면 생략)
    chart_insights = {}
    if len(total_s):
        chart_insights["annual"] = [
            "최다 출원 연도는 %s년(%s건)이고 최근 %d년 성장률은 %s입니다."
            % (kpi["peak_year"], fmt_num(total_s.max()), recent,
               fmt_pct(kpi["growth"]) if kpi["growth"] is not None else "계산 불가"),
            "최근 1~2년 하락은 미공개 출원(공개 전) 영향일 수 있어 하락으로 단정할 수 "
            "없습니다."]
    if fig_country is not None:
        c_counts = df["country"].astype(str).str.strip().str.upper() \
            .replace("", np.nan).replace("NAN", np.nan).dropna().value_counts()
        c_top3 = float(c_counts.head(3).sum()) / float(c_counts.sum())
        chart_insights["country"] = [
            "출원 1위 국가는 %s(%s건, %s)이며 상위 3개국이 전체의 %s를 차지합니다 — "
            "권리 확보가 집중된 시장입니다."
            % (c_counts.index[0], fmt_num(c_counts.iloc[0]),
               fmt_pct(c_counts.iloc[0] / float(c_counts.sum())), fmt_pct(c_top3))]
    if len(app_counts):
        cr3 = float(app_counts.head(3).sum()) / float(len(df))
        chart_insights["applicants"] = [
            "출원인 1위는 '%s'(%s건, 점유율 %s)이고 상위 3개사 집중도(CR3)는 %s입니다%s."
            % (app_counts.index[0], fmt_num(app_counts.iloc[0]),
               fmt_pct(app_counts.iloc[0] / float(len(df))), fmt_pct(cr3),
               " — 소수 기업 주도 시장" if cr3 >= 0.5 else " — 경쟁이 분산된 시장")]
        if n_joint:
            chart_insights["applicants"].append(
                ("공동출원 %s건은 각 공동출원인에게 1건씩 집계됩니다 — 출원인별 "
                 "합계·점유율 합이 100%%를 넘을 수 있습니다."
                 if co_mode == "all" else
                 "공동출원 %s건은 대표(첫) 출원인에게만 집계됩니다.") % fmt_num(n_joint))
        recent_hi = int(years_all.max()) - recent + 1
        rec_mask = df["_base_year"] >= recent_hi
        rec_counts = pd.Series(
            [a for lst in app_lists[rec_mask] for a in lst]) \
            .replace("", np.nan).dropna().value_counts()
        bub_sents = []
        max_cell = None
        for a in app_counts.head(max_rows).index:
            s = _year_series(df, _amask(a))
            if len(s) and (max_cell is None or float(s.max()) > max_cell[2]):
                max_cell = (str(a), int(s.idxmax()), float(s.max()))
        if max_cell:
            bub_sents.append("가장 큰 버블(최대 집중)은 '%s'의 %d년(%s건)입니다."
                             % (max_cell[0], max_cell[1], fmt_num(max_cell[2])))
        if len(rec_counts):
            bub_sents.append("최근 %d년 가장 활발한 출원인은 '%s'(%s건)입니다 — 줄이 "
                             "이어지는 기업=꾸준한 투자, 최근 버블이 사라진 기업=투자 "
                             "축소 신호입니다." % (recent, rec_counts.index[0],
                                             fmt_num(rec_counts.iloc[0])))
        if bub_sents:
            chart_insights["applicant_year_bubble"] = bub_sents
            chart_insights["applicant_year"] = [bub_sents[0] +
                                                " (버블 차트와 같은 데이터의 히트맵 보기입니다.)"]
    if fig_tech is not None:
        t_counts = tech_flat.value_counts()
        chart_insights["tech"] = [
            "최다 기술분류는 '%s'(%s건, %s)로 포트폴리오가 가장 집중된 기술입니다."
            % (t_counts.index[0], fmt_num(t_counts.iloc[0]),
               fmt_pct(t_counts.iloc[0] / float(max(len(df), 1))))]
        recent_hi = int(years_all.max()) - recent + 1
        grow_best, grow_val = None, None
        for t in t_counts.head(max_rows).index:
            in_tech = df["_tech_list"].map(lambda lst: t in (lst or []))
            s = _year_series(df, in_tech)
            rec_n = float(s[s.index >= recent_hi].sum())
            old_n = float(s[s.index < recent_hi].sum())
            if old_n >= 3:
                ratio = rec_n / old_n
                if grow_val is None or ratio > grow_val:
                    grow_best, grow_val = str(t), ratio
        if grow_best is not None:
            chart_insights["tech_year"] = [
                "최근 %d년 비중이 가장 커진 분류는 '%s'(최근/이전 비율 %.2f)입니다 — "
                "오른쪽(최근)으로 갈수록 진해지는 행이 성장 기술입니다."
                % (recent, grow_best, grow_val)]

    return ok_result({
        "kpi": kpi, "annual": fig_annual, "country": fig_country,
        "applicants": fig_applicants, "applicant_year": fig_app_year,
        "applicant_year_bubble": fig_app_bubble,
        "tech": fig_tech, "tech_year": fig_tech_year,
        "chart_insights": chart_insights,
    }, insight=insight)


# ---------------------------------------------------------------------------
# 기술분류 트리맵 (대·중·소)
# ---------------------------------------------------------------------------
def _lighten(hex_color, factor):
    """#RRGGBB 를 흰색 쪽으로 factor(0~1)만큼 밝게."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    r = int(r + (255 - r) * factor)
    g = int(g + (255 - g) * factor)
    b = int(b + (255 - b) * factor)
    return "#%02x%02x%02x" % (r, g, b)


def compute_tech_tree(df, settings, company=None):
    """대·중·소 기술분류 트리맵.

    각 문헌의 레벨별 대표(첫) 분류로 경로(대>중>소)를 만들어 문헌 수를
    집계한다. 하위 레벨이 없는 문헌은 있는 레벨까지만 집계되므로 부모
    면적이 자식 합보다 클 수 있다 (남는 면적 = 하위 분류 미기재 문헌).
    company 지정 시 그 출원인(공동출원 포함) 문헌만 집계.
    """
    from src.viz_payload import PALETTE
    if company:
        from src.analyses.common import applicant_mask
        df = df[applicant_mask(df, company, scope="any")]
        if not len(df):
            return empty_result("출원인 '%s'의 문헌이 없습니다 (공동출원 포함 검색)."
                                % company)
    if not len(df):
        return empty_result()
    level_cols = [c for c in ("_tech_l1_list", "_tech_l2_list", "_tech_l3_list")
                  if c in df.columns and df[c].map(lambda v: bool(v)).any()]
    drill_keys = {"_tech_l1_list": "tech_l1", "_tech_l2_list": "tech_l2",
                  "_tech_l3_list": "tech_l3"}
    single = False
    if not level_cols:
        if df["_tech_list"].map(lambda v: bool(v)).any():
            level_cols, single = ["_tech_list"], True
        else:
            return empty_result("기술분류(대/중/소 또는 통합) 값이 없습니다 — "
                                "Settings → 컬럼 매핑에서 기술분류를 매핑하세요.")

    # 문헌별 경로 (레벨별 첫 분류, 값이 끊기면 거기까지)
    node_vals = {}
    total_docs = 0
    for vals in zip(*[df[c] for c in level_cols]):
        path = []
        for lst in vals:
            v = (lst or [None])[0]
            s = "" if v is None else str(v).strip()
            if not s or s.lower() in ("nan", "none", "-"):
                break
            path.append(s)
        if not path:
            continue
        total_docs += 1
        for i in range(1, len(path) + 1):
            node_vals[tuple(path[:i])] = node_vals.get(tuple(path[:i]), 0) + 1
    if not node_vals:
        return empty_result("기술분류 경로를 구성할 수 있는 문헌이 없습니다.")

    # 너무 작은 잎 노드는 표시에서 제외 (부모의 무라벨 여백으로 남음 — 값 왜곡 없음)
    min_leaf = max(1, int(total_docs * 0.002))
    keep = {p for p, v in node_vals.items()
            if len(p) == 1 or v >= min_leaf}
    keep |= {p[:i] for p in keep for i in range(1, len(p))}  # 조상 보존
    nodes = sorted(keep, key=lambda p: (len(p), -node_vals[p]))
    if len(nodes) > 400:
        leaves = sorted((p for p in nodes if len(p) > 1),
                        key=lambda p: -node_vals[p])[:400 - sum(1 for p in nodes
                                                                if len(p) == 1)]
        keep = set(leaves) | {p for p in nodes if len(p) == 1}
        keep |= {p[:i] for p in keep for i in range(1, len(p))}
        nodes = sorted(keep, key=lambda p: (len(p), -node_vals[p]))

    l1_order = [p[0] for p in nodes if len(p) == 1]
    l1_color = {name: PALETTE[i % len(PALETTE)] for i, name in enumerate(l1_order)}
    parent_set = {p[:-1] for p in nodes if len(p) > 1}
    ids, labels, parents, values, colors, customs = [], [], [], [], [], []
    for p in nodes:
        ids.append(" > ".join(p))
        labels.append(p[-1])
        parents.append(" > ".join(p[:-1]) if len(p) > 1 else "")
        values.append(int(node_vals[p]))
        colors.append(_lighten(l1_color.get(p[0], "#8aa0b2"),
                               (len(p) - 1) * 0.28))
        if single:
            drill = {"type": "tech", "tech": p[0]}
        else:
            drill = {drill_keys[level_cols[i]]: seg for i, seg in enumerate(p)}
        # leaf=하위 칸 없음 → 클릭 시 근거 특허 (하위가 있으면 클릭=확대만)
        customs.append({"drill": drill, "leaf": p not in parent_set,
                        "m": {"경로": " > ".join(p), "문헌 수": int(node_vals[p]),
                              "전체 대비": round(node_vals[p] / float(total_docs), 4)}})

    level_names = {"_tech_l1_list": "대", "_tech_l2_list": "중",
                   "_tech_l3_list": "소", "_tech_list": "기술분류"}
    depth_label = "·".join(level_names[c] for c in level_cols)
    title = "기술분류 트리맵 (%s)%s" % (depth_label,
                                    (" — %s" % company) if company else "")
    fig = {"data": [{
        "type": "treemap", "ids": ids, "labels": labels, "parents": parents,
        "values": values, "branchvalues": "total", "customdata": customs,
        "hovertemplate": "<b>%{id}</b><br>%{value}건 · 전체의 %{percentRoot:.1%}"
                         "<extra></extra>",
        "texttemplate": "%{label}<br>%{value}건", "textfont": {"size": 12},
        "marker": {"colors": colors, "line": {"width": 1.5, "color": "#ffffff"}},
        "pathbar": {"visible": True, "thickness": 24},
        "tiling": {"pad": 2}}],
        "layout": base_layout(title, height=640,
                              margin={"t": 70, "l": 8, "r": 8, "b": 8})}

    l1_counts = sorted(((p[0], node_vals[p]) for p in nodes if len(p) == 1),
                       key=lambda kv: -kv[1])
    sentences = []
    if l1_counts:
        top1 = l1_counts[0]
        sentences.append("%s 최대 분류는 '%s'(%s건, 전체의 %s)입니다."
                         % (("'%s' 기준" % company) if company else period_label(df),
                            top1[0], fmt_num(top1[1]),
                            fmt_pct(top1[1] / float(total_docs))))
    deep = [p for p in nodes if len(p) == len(level_cols) and len(p) > 1]
    if deep:
        best = max(deep, key=lambda p: node_vals[p])
        sentences.append("최하위 레벨에서 가장 큰 영역은 '%s'(%s건)입니다 — 하위가 "
                         "있는 칸은 클릭하면 확대되고, 최하위 칸을 클릭하면 근거 "
                         "특허가 열립니다." % (" > ".join(best), fmt_num(node_vals[best])))
    sentences.append("면적=문헌 수(각 문헌의 레벨별 대표 분류 기준). 부모 칸의 남는 "
                     "여백은 하위 분류가 기재되지 않은 문헌입니다.")
    insight = build_insight(
        sentences, {"levels": depth_label, "n_docs": total_docs,
                    "n_nodes": len(nodes)},
        small_sample=check_small_sample(total_docs, settings))
    return ok_result({"figure": fig, "levels": depth_label,
                      "n_docs": int(total_docs)}, insight=insight)


# ---------------------------------------------------------------------------
# 출원인 포커스 — 집중 기술 · 소규모 급부상 아이템
# ---------------------------------------------------------------------------
def compute_company_focus(df, settings, company=None):
    """선택한 출원인의 기술 집중도와 '작지만 최근 급부상하는 아이템' 탐지.

    - 기술분류별로 그 회사(공동출원 포함)의 누적 건수 vs 최근 N년 비중을 버블로
      배치: 좌상단(누적은 적은데 최근 비중 높음)=새로 힘을 싣기 시작한 아이템.
    - 급부상 판정(값을 지어내지 않는 규칙): 최근 N년 건수 ≥ 2, 최근 비중 ≥ 50%,
      최근 N년 건수 > 그 직전 N년 건수, 누적 건수는 회사 내 중앙값 이하.
    """
    if not company:
        return empty_result("상단에서 출원인을 선택하면 그 회사의 집중 기술과 "
                            "급부상 아이템을 분석합니다.")
    from src.analyses.common import applicant_mask
    sub = df[applicant_mask(df, company, scope="any")]
    if not len(sub):
        return empty_result("출원인 '%s'의 문헌이 없습니다 (공동출원 포함 검색)."
                            % company)
    if not sub["_base_year"].notna().any():
        return empty_result(diagnose_year_tech(sub))
    if not sub["_tech_list"].map(lambda v: bool(v)).any():
        return empty_result("출원인 '%s' 문헌에 기술분류 값이 없습니다." % company)
    recent = int(get_threshold(settings, "recent_years"))
    y_max = int(df["_base_year"].dropna().max())  # 기준 연도는 전체 데이터 최신
    recent_from = y_max - recent + 1
    prev_from = recent_from - recent

    stats = {}
    for lst, y in zip(sub["_tech_list"], sub["_base_year"]):
        yv = None if (y is None or (isinstance(y, float) and np.isnan(y))) else int(y)
        for t in set(lst or []):
            st = stats.setdefault(t, {"total": 0, "recent": 0, "prev": 0})
            st["total"] += 1
            if yv is not None and yv >= recent_from:
                st["recent"] += 1
            elif yv is not None and prev_from <= yv < recent_from:
                st["prev"] += 1
    if not stats:
        return empty_result("기술분류 값이 없습니다.")
    market = pd.Series([t for lst in df["_tech_list"] for t in (lst or [])]) \
        .value_counts()
    totals = sorted(st["total"] for st in stats.values())
    median_total = float(totals[len(totals) // 2])

    rows = []
    for t, st in stats.items():
        share_recent = st["recent"] / float(st["total"])
        rising = (st["recent"] >= 2 and share_recent >= 0.5
                  and st["recent"] > st["prev"] and st["total"] <= median_total)
        rows.append({
            "tech": str(t), "total": int(st["total"]),
            "recent": int(st["recent"]), "prev": int(st["prev"]),
            "recent_share": round(share_recent, 3),
            "market_total": int(market.get(t, 0)),
            "market_share": round(st["total"] / float(market.get(t, 1) or 1), 3),
            "rising": bool(rising),
            "drill": {"type": "tech", "tech": str(t), "applicant": str(company),
                      "applicant_scope": "any"},
        })
    rows.sort(key=lambda r: (-r["rising"], -(r["recent_share"] * r["recent"]),
                             -r["total"]))

    top_main = {r["tech"] for r in sorted(rows, key=lambda r: -r["total"])[:3]}
    xs, ys, sizes, colors, hovers, customs = [], [], [], [], [], []
    for r in rows:
        xs.append(r["total"])
        ys.append(r["recent_share"])
        sizes.append(float(max(9.0, min(44.0, 8 + 9 * np.sqrt(r["recent"])))))
        colors.append("#E15759" if r["rising"] else "#4E79A7")
        hovers.append(
            "<b>%s</b><br>누적 %d건 · 최근 %d년 %d건 (비중 %s)<br>직전 %d년 %d건 · "
            "전체 시장 %d건 중 점유 %s%s"
            % (r["tech"], r["total"], recent, r["recent"],
               fmt_pct(r["recent_share"]), recent, r["prev"], r["market_total"],
               fmt_pct(r["market_share"]),
               "<br>★ 급부상 아이템 후보" if r["rising"] else ""))
        customs.append({"drill": r["drill"],
                        "m": {"기술분류": r["tech"], "누적 건수": r["total"],
                              "최근 %d년 건수" % recent: r["recent"],
                              "직전 %d년 건수" % recent: r["prev"],
                              "최근 비중": r["recent_share"],
                              "전체 시장 건수": r["market_total"],
                              "급부상": "예" if r["rising"] else ""}})
    x_max = max(xs)
    # 로그축은 기본값으로 두면 보조 눈금(2,3,…,9)이 매 자리수마다 찍혀 축 아래가
    # 숫자로 지저분해짐 → 정수 건수 눈금만 명시 (1,2,3,5,10,20,…)
    _tick_cands = [1, 2, 3, 5, 10, 20, 30, 50, 100, 200, 300, 500,
                   1000, 2000, 3000, 5000, 10000]
    x_ticks = [v for v in _tick_cands if v <= x_max * 1.3] or [1]
    fig = {"data": [{
        "type": "scatter", "mode": "markers", "cliponaxis": False,
        "x": xs, "y": ys,
        "hovertext": hovers, "hoverinfo": "text", "customdata": customs,
        "marker": {"size": sizes, "color": colors, "opacity": 0.85,
                   "line": {"width": 0.8, "color": "#5b7a8a"}}}],
        "layout": base_layout(
            "'%s' 기술 포커스 맵 — X=누적 출원, Y=최근 %d년 비중 (빨강=급부상 후보)"
            % (company, recent),
            xaxis={"title": "누적 출원 건수 (로그축)", "type": "log",
                   "tickvals": x_ticks,
                   "ticktext": [fmt_num(v) for v in x_ticks],
                   # 로그축 range 는 log10 단위 — 좌우 여백으로 버블·축 겹침 방지
                   "range": [float(np.log10(0.72)),
                             float(np.log10(x_max * 1.45))]},
            yaxis={"title": "최근 %d년 출원 비중" % recent,
                   "range": [-0.08, 1.08], "tickformat": ".0%"},
            annotations=[
                {"x": np.log10(max(1.5, median_total * 0.35)), "y": 1.04,
                 "xref": "x", "yref": "y", "showarrow": False,
                 "text": "◀ 작지만 최근에 몰림 = 새 베팅", "xanchor": "left",
                 "font": {"size": 11, "color": "#c0392b"}},
                {"x": np.log10(max(2.0, x_max)), "y": 1.04, "xref": "x",
                 "yref": "y", "showarrow": False, "xanchor": "right",
                 "text": "주력 기술 ▶", "font": {"size": 11, "color": "#2e5f8a"}}],
            height=560)}

    # 기술명 라벨: 대부분의 버블에 표시하되, 겹치면 지시선(화살표)으로 밖에 배치.
    # 그리디 충돌 회피 — 로그축이므로 x 는 log10 정규화 좌표로 거리 계산.
    lx_min, lx_max = np.log10(max(min(xs), 1.0)), np.log10(max(x_max, 2.0))
    lx_span = max(lx_max - lx_min, 1e-6)

    def _npos(x, y, ax_px=0, ay_px=0):
        # 근사 정규화 좌표 (플롯 ~900×470px 가정, ay 는 위가 음수)
        return (float((np.log10(max(x, 1.0)) - lx_min) / lx_span + ax_px / 900.0),
                float(y - ay_px / 470.0))

    label_rows = sorted(rows, key=lambda r: (-r["rising"], -r["recent"],
                                             -r["total"]))[:35]
    placed = []  # (nx, ny) 라벨 중심들
    offsets = [(0, -30), (55, -30), (-55, -30), (70, -60), (-70, -60),
               (85, 20), (-85, 20), (0, -85), (100, -40), (-100, -40)]
    lbl_anns = []
    for r in label_rows:
        best = None
        for ax_px, ay_px in offsets:
            nx, ny = _npos(r["total"], r["recent_share"], ax_px, ay_px)
            if all(abs(nx - px) > 0.11 or abs(ny - py) > 0.05
                   for px, py in placed):
                best = (ax_px, ay_px, nx, ny)
                break
        if best is None:  # 자리가 전혀 없으면 라벨 생략 (겹쳐 쓰지 않음)
            continue
        ax_px, ay_px, nx, ny = best
        placed.append((nx, ny))
        rising = r["rising"]
        lbl_anns.append({
            "x": np.log10(max(r["total"], 1.0)), "y": r["recent_share"],
            "xref": "x", "yref": "y", "showarrow": True,
            "arrowhead": 0, "arrowwidth": 0.8,
            "arrowcolor": "#c0392b" if rising else "#9fb2c2",
            "ax": ax_px, "ay": ay_px, "standoff": 4,
            "text": ("★ " if rising else "") + str(r["tech"])[:14],
            "font": {"size": 9.5,
                     "color": "#c0392b" if rising else
                     ("#2e5f8a" if r["tech"] in top_main else "#54677a")},
            "bgcolor": "rgba(255,255,255,0.72)", "borderpad": 1})
    fig["layout"]["annotations"] = fig["layout"].get("annotations", []) + lbl_anns

    top10 = sorted(rows, key=lambda r: -r["total"])[:10]
    fig_top = bar_chart(
        [r["tech"] for r in top10][::-1], [r["total"] for r in top10][::-1],
        title="'%s' 집중 기술 Top %d (누적 건수)" % (company, len(top10)),
        orientation="h", x_title="누적 출원 건수",
        hovertext=["%s — 누적 %d건 · 최근 %d년 %d건 · 시장 점유 %s"
                   % (r["tech"], r["total"], recent, r["recent"],
                      fmt_pct(r["market_share"])) for r in top10][::-1],
        customdata=[{"drill": r["drill"]} for r in top10][::-1])

    rising_rows = [r for r in rows if r["rising"]][:15]
    sentences = []
    if top10:
        t0 = top10[0]
        sentences.append("'%s'의 최대 집중 기술은 '%s'(누적 %s건, 시장 점유 %s)입니다."
                         % (company, t0["tech"], fmt_num(t0["total"]),
                            fmt_pct(t0["market_share"])))
    if rising_rows:
        names = ", ".join("'%s'" % r["tech"] for r in rising_rows[:3])
        sentences.append("급부상 아이템 후보는 %s 등 %s개 — 누적 건수는 회사 중앙값 "
                         "이하지만 출원의 절반 이상이 최근 %d년에 몰렸고 직전 %d년보다 "
                         "늘었습니다. 규모가 작을 때 잡히는 신호이므로 초기 베팅 "
                         "관찰 대상입니다."
                         % (names, fmt_num(len(rising_rows)), recent, recent))
    else:
        sentences.append("급부상 판정 기준(최근 %d년 ≥2건, 최근 비중 ≥50%%, 직전 대비 "
                         "증가, 누적은 중앙값 이하)을 만족하는 분류가 없습니다 — 이 "
                         "회사의 신규 베팅 신호는 아직 약합니다." % recent)
    insight = build_insight(
        sentences, {"company": company, "n_techs": len(rows),
                    "n_rising": len(rising_rows), "recent_years": recent},
        small_sample=check_small_sample(len(sub), settings))
    return ok_result({"figure": fig, "fig_top": fig_top, "rising": rising_rows,
                      "company": company, "recent_years": recent,
                      "n_docs": int(len(sub))}, insight=insight)


# ---------------------------------------------------------------------------
# 기술분류 × 출원연도 버블 (출원인 선택·다사 비교)
# ---------------------------------------------------------------------------
def compute_tech_year_bubble(df, settings, companies=None, level=None):
    """X=출원연도, Y=기술분류 버블 (크기=출원건수).

    companies 미지정: 전체 데이터 1개 시리즈 (색=건수).
    companies 1~4개: 회사별 색 + 같은 셀에서 겹치지 않도록 세로 미세 오프셋 —
    두세 회사의 기술별 투자 시점·규모를 한 화면에서 비교한다.
    level: 'l1'|'l2'|'l3' → 대/중/소 분류 레벨 선택 (미지정=통합 기술분류).
    Drill: 버블 클릭 → 해당 (기술분류 × 연도 [× 출원인]) 특허.
    """
    from src.viz_payload import color_for
    level = level if level in ("l1", "l2", "l3", "path") else None
    tech_col, level_label, drill_key = "_tech_list", "통합", "tech"
    path_drills = {}
    if level == "path":
        # 계층 보기: 각 문헌의 대›중›소 대표 분류를 하나의 경로 행으로 —
        # Y축에서 어느 소분류가 어느 중·대분류에 속하는지 바로 보인다
        lv_cols = [c for c in ("_tech_l1_list", "_tech_l2_list", "_tech_l3_list")
                   if c in df.columns and df[c].map(lambda v: bool(v)).any()]
        if len(lv_cols) < 2:
            return empty_result("계층 보기는 대/중(/소) 분류가 2개 레벨 이상 매핑된 "
                                "경우에만 가능합니다 — Settings → 컬럼 매핑을 확인하세요.")
        lv_keys = {"_tech_l1_list": "tech_l1", "_tech_l2_list": "tech_l2",
                   "_tech_l3_list": "tech_l3"}
        df = df.copy()
        paths = []
        for vals in zip(*[df[c] for c in lv_cols]):
            segs = []
            for lst in vals:
                v = (lst or [None])[0]
                s = "" if v is None else str(v).strip()
                if not s or s.lower() in ("nan", "none", "-"):
                    break
                segs.append(s)
            if segs:
                path = " › ".join(segs)
                paths.append([path])
                if path not in path_drills:
                    path_drills[path] = {lv_keys[lv_cols[i]]: seg
                                         for i, seg in enumerate(segs)}
            else:
                paths.append([])
        df["_bubble_path_list"] = paths
        tech_col, level_label, drill_key = "_bubble_path_list", "대›중›소 계층", "path"
    elif level:
        cand = "_tech_%s_list" % level
        names = {"l1": "대분류", "l2": "중분류", "l3": "소분류"}
        if cand not in df.columns or not df[cand].map(lambda v: bool(v)).any():
            return empty_result("%s 컬럼이 매핑되지 않았거나 값이 없습니다 — Settings → "
                                "컬럼 매핑에서 기술분류(%s)를 매핑하세요."
                                % (names[level], names[level]))
        tech_col, level_label, drill_key = cand, names[level], "tech_%s" % level
    if not len(df) or not df["_base_year"].notna().any():
        return empty_result(diagnose_year_tech(df))
    if not df[tech_col].map(lambda v: bool(v)).any():
        return empty_result(diagnose_year_tech(df))
    comps = [str(c) for c in (companies or []) if str(c).strip()][:4]
    if comps:  # 공동출원 건 포함 매칭
        m = pd.Series(False, index=df.index)
        for c in comps:
            m |= applicant_mask(df, c, scope="any")
        scope = df[m]
    else:
        scope = df
    if comps and not len(scope):
        return empty_result("선택한 출원인(%s)의 특허가 현재 필터에 없습니다."
                            % ", ".join(comps))

    max_rows = min(int(get_limit(settings, "matrix_max_rows")),
                   20 if drill_key == "path" else 15)
    tech_counts = pd.Series([t for lst in scope[tech_col] for t in (lst or [])])
    if not len(tech_counts):
        return empty_result("기술분류(%s) 값이 없습니다." % level_label)
    top_techs = tech_counts.value_counts().head(max_rows).index.tolist()
    if drill_key == "path":
        # 계층 보기: 대분류→중분류→소분류 순으로 정렬해 같은 상위 분류끼리 묶임
        top_techs = sorted(top_techs)
    tpos = {t: i for i, t in enumerate(top_techs)}
    year_lo = int(scope["_base_year"].dropna().min())
    year_hi = int(scope["_base_year"].dropna().max())

    def _t_drill(t, y=None):
        if drill_key == "path":
            d = dict(path_drills.get(str(t), {}))
        elif drill_key == "tech":
            d = {"type": "tech", "tech": str(t)}
        else:
            d = {drill_key: str(t)}
        if y is not None:
            d["year"] = int(y)
        return d

    def cell_counts(sub):
        counts = {}
        for lst, y in zip(sub[tech_col], sub["_base_year"]):
            if y is None or (isinstance(y, float) and np.isnan(y)):
                continue
            for t in set(lst or []):
                if t in tpos:
                    counts[(t, int(y))] = counts.get((t, int(y)), 0) + 1
        return counts

    groups = comps if comps else [None]
    all_counts = [cell_counts(scope[applicant_mask(scope, g, scope="any")] if g else scope)
                  for g in groups]
    vmax = max([max(c.values()) for c in all_counts if c] or [1])
    n_g = len(groups)
    offsets = [0.0] if n_g == 1 else \
        [(-0.22 + 0.44 * i / (n_g - 1)) for i in range(n_g)]

    color_reg = {}
    traces = []
    for gi, (g, counts) in enumerate(zip(groups, all_counts)):
        if not counts:
            continue
        name = g if g else "전체"
        xs, ys, sizes, colors, hovers, customs, cell_ns = [], [], [], [], [], [], []
        for (t, y), n in counts.items():
            xs.append(int(y))
            ys.append(tpos[t] + offsets[gi])
            sizes.append(float(max(7.0, min(40.0, 6 + 30 * np.sqrt(n / vmax)))))
            colors.append(n)
            cell_ns.append(int(n))
            hovers.append("%s — %s %d년: %s건" % (name, t, y, fmt_num(n)))
            drill = _t_drill(t, y)
            if g:
                drill["applicant"] = g
                drill["applicant_scope"] = "any"  # 공동출원 건 포함
            customs.append({"drill": drill,
                            "m": {"출원인": name, "기술분류": str(t),
                                  "연도": int(y), "건수": int(n)}})
        # 건수 표시: 중간값 이상 버블에 수치 라벨 (작은 버블은 hover 로)
        label_cut = max(float(np.median(cell_ns)) if cell_ns else 0, 2)
        texts = [(fmt_num(n) if n >= label_cut else "") for n in cell_ns]
        marker = {"size": sizes, "line": {"width": 0.6, "color": "#5b7a8a"}}
        if n_g == 1:
            marker.update({"color": colors, "colorscale": BLUES, "cmin": 0,
                           "colorbar": {"title": "출원건수", "thickness": 12}})
        else:
            marker.update({"color": color_for(name, color_reg), "opacity": 0.85})
        traces.append({"type": "scatter", "mode": "markers+text", "name": name,
                       "cliponaxis": False,  # 맨 아래 행 버블이 X축 선에 잘리지 않게
                       "x": xs, "y": ys, "text": texts,
                       "textposition": "middle center",
                       "textfont": {"size": 9, "color": "#1f3550"},
                       "hovertext": hovers, "hoverinfo": "text",
                       "customdata": customs, "marker": marker})
    title = ("기술분류(%s) × 출원연도 버블 — %s 비교 (크기=출원건수)"
             % (level_label, " vs ".join(comps)) if comps else
             "기술분류(%s) × 출원연도 버블 (크기·색=출원건수, 전체)" % level_label)
    fig = {"data": traces, "layout": base_layout(
        title,
        xaxis={"title": "출원연도", "dtick": 1, "tickformat": "d",
               "range": [year_lo - 0.7, year_hi + 0.7]},
        yaxis={"title": "", "tickmode": "array",
               "tickvals": list(range(len(top_techs))),
               "ticktext": [str(t)[:44 if drill_key == "path" else 22]
                            for t in top_techs],
               "range": [-0.95, len(top_techs) - 0.05], "automargin": True},
        showlegend=bool(comps),
        height=max(440, 140 + 36 * len(top_techs)))}

    sentences = []
    if comps:
        for g, counts in zip(groups, all_counts):
            if not counts:
                sentences.append("'%s'는 현재 필터에서 상위 기술분류 출원이 없습니다." % g)
                continue
            (bt, by), bn = max(counts.items(), key=lambda kv: kv[1])
            recent_total = sum(n for (t, y), n in counts.items() if y >= year_hi - 2)
            sentences.append("'%s'의 최대 집중은 '%s' %d년(%s건)이며 최근 3년 상위 분류 "
                             "출원은 %s건입니다."
                             % (g, bt, by, fmt_num(bn), fmt_num(recent_total)))
        sentences.append("같은 행(기술)에서 색이 다른 버블의 크기·등장 시점을 비교하면 "
                         "누가 먼저·더 크게 투자했는지 보입니다.")
        joint_in_scope = int(scope["_co_applicants_display"]
                             .map(lambda lst: len(lst or []) > 1).sum()) \
            if "_co_applicants_display" in scope.columns else 0
        if joint_in_scope and len(comps) >= 2:
            sentences.append("공동출원 %s건은 관련된 각 선택 회사의 버블에 각각 "
                             "표시됩니다 — 두 공동출원사를 함께 선택하면 같은 특허가 "
                             "양쪽 시리즈에 나타날 수 있습니다 (전체 보기에서는 특허 "
                             "1건이 1번만 집계됩니다)." % fmt_num(joint_in_scope))
    else:
        counts = all_counts[0]
        (bt, by), bn = max(counts.items(), key=lambda kv: kv[1])
        sentences.append("최대 밀집 셀은 '%s' %d년(%s건)입니다. 위 출원인 선택으로 "
                         "특정 회사·최대 3개사 비교 보기가 가능합니다. 전체 보기의 "
                         "건수는 특허 1건=1번 집계이며 공동출원이어도 중복 계산되지 "
                         "않습니다 (다중 기술분류만 분류마다 1건씩)."
                         % (bt, by, fmt_num(bn)))
    insight = build_insight(
        sentences,
        {"companies": comps or "전체", "n_techs": len(top_techs),
         "period": "%d–%d" % (year_lo, year_hi)},
        small_sample=check_small_sample(len(scope), settings))
    return ok_result({"figure": fig, "techs": top_techs, "companies": comps},
                     insight=insight)
