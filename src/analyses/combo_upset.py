# -*- coding: utf-8 -*-
"""
analyses/combo_upset.py — 미점유 조합 UpSet 차트 (3개 이상 요소 교집합 분석).

핵심 질문:
  "각 기술요소는 이미 알려져 있지만, 아직 함께 청구되지 않은 조합은 무엇인가?"

분석 개념:
  2차원 히트맵으로는 보이지 않는 3개 이상 기술요소의 교집합을 UpSet 형식으로
  분석한다. 기술요소는 매핑된 기술분류(_tech_list)의 전역 상위 요소를 사용한다.

UpSet 차트 (Plotly 단일 figure, 위 막대 + 아래 도트 매트릭스):
  - 세로 막대: 특정 요소 조합(문헌의 추적 요소 집합이 정확히 일치)의 특허 수
  - 점·연결선: 조합에 포함된 요소 (아래 매트릭스)
  - 막대 색: 조합 내 유효특허 비율 (빨강=낮음→초록=높음, 회색=판정 불가)
  - 막대 테두리: 최근 3년 출원이 있는 조합 (굵은 테두리)

미점유 조합 (white space) 점수:
  상위 요소들의 2·3개 조합 후보에 대해
    기대 건수 E = N × Π(요소별 출현확률)   (요소 독립 가정)
    실제 건수 A = 요소를 모두 포함한 특허 수
  격차 점수 = E − A. E 가 크고 A≈0 이면 "개별 요소는 혼잡하지만 조합이 비어
  있는" 후보다. 제품 요구사항 적합도 점수는 요구사항 데이터가 없어 계산하지
  않고 격차 점수와 요소별 최근 활동 여부로 대체한다 (임의 값 생성 금지).

Drill-down: 막대 클릭 → 해당 조합 특허({"type":"ids"}).
예외처리: 요소 2개 미만 또는 다중 요소 문헌 없음 → empty, 기술분류 없으면
disabled (라우터의 가용성 매트릭스).
"""
from itertools import combinations

import numpy as np

from src.config import get_limit, get_threshold
from src.insights import build_insight, fmt_num, fmt_pct, check_small_sample
from src.viz_payload import ok_result, empty_result, base_layout


def compute_combo_upset(df, settings):
    """기술요소 조합 UpSet + 미점유 조합 후보."""
    max_elements = get_limit(settings, "upset_max_elements")
    max_combos = get_limit(settings, "upset_max_combos")
    recent_years = int(get_threshold(settings, "recent_years"))

    # ---- 요소 선정: 전역 상위 기술분류 ------------------------------------
    elem_counts = {}
    for lst in df["_tech_list"]:
        for t in set(lst or []):
            elem_counts[t] = elem_counts.get(t, 0) + 1
    elements = [t for t, _c in sorted(elem_counts.items(), key=lambda kv: -kv[1])
                [:max_elements]]
    if len(elements) < 2:
        return empty_result("기술요소(기술분류)가 %d개뿐이라 조합 분석을 할 수 "
                            "없습니다 (최소 2개)." % len(elements))
    elem_set = set(elements)

    years = df["_base_year"]
    max_year = int(years.max()) if years.notna().any() else None
    recent_from = (max_year - recent_years + 1) if max_year else None

    id_col = "pub_number" if "pub_number" in df.columns else \
        ("app_number" if "app_number" in df.columns else None)

    # ---- 문헌별 추적 요소 집합 → 정확 조합 집계 ---------------------------
    combos = {}
    doc_sets = []  # 미점유 후보 계산용 (포함 카운트)
    n_tracked_docs = 0
    for i in range(len(df)):
        row_techs = set(df["_tech_list"].iloc[i] or []) & elem_set
        if not row_techs:
            continue
        n_tracked_docs += 1
        doc_sets.append(frozenset(row_techs))
        key = tuple(sorted(row_techs))
        rec = combos.setdefault(key, {"n": 0, "recent": 0, "active_true": 0,
                                      "active_known": 0, "applicants": {},
                                      "ids": []})
        rec["n"] += 1
        y = years.iloc[i]
        if recent_from is not None and y is not None and not (
                isinstance(y, float) and np.isnan(y)) and int(y) >= recent_from:
            rec["recent"] += 1
        flag = df["_active_flag"].iloc[i] if "_active_flag" in df.columns else None
        if flag is not None:
            rec["active_known"] += 1
            if flag is True:
                rec["active_true"] += 1
        app = str(df["applicant_display"].iloc[i]) \
            if "applicant_display" in df.columns else ""
        if app:
            rec["applicants"][app] = rec["applicants"].get(app, 0) + 1
        if len(rec["ids"]) < 200:
            rec["ids"].append(str(df[id_col].iloc[i]) if id_col else str(df.index[i]))
    if not combos:
        return empty_result("추적 요소를 포함한 문헌이 없습니다.")
    multi = sum(1 for k in combos if len(k) >= 2)
    if multi == 0:
        return empty_result("두 개 이상의 기술요소를 함께 가진 문헌이 없어 교집합 "
                            "분석을 할 수 없습니다. 다중 기술분류 매핑을 확인하세요.")

    ranked = sorted(combos.items(), key=lambda kv: -kv[1]["n"])[:max_combos]
    # 매트릭스 행 순서: 표시 조합에 등장하는 요소만, 전역 빈도 순
    shown_elems = [e for e in elements
                   if any(e in key for key, _r in ranked)]
    elem_pos = {e: len(shown_elems) - 1 - i for i, e in enumerate(shown_elems)}

    # ---- UpSet figure ------------------------------------------------------
    xs = list(range(len(ranked)))
    bar_y, bar_colors, bar_lines, hovers, customs = [], [], [], [], []
    for key, rec in ranked:
        bar_y.append(rec["n"])
        ratio = (rec["active_true"] / rec["active_known"]) \
            if rec["active_known"] else None
        bar_colors.append(ratio)  # None=미상 → 아래에서 회색 고정
        bar_lines.append(2.5 if rec["recent"] > 0 else 0.4)
        top_apps = sorted(rec["applicants"].items(), key=lambda kv: -kv[1])[:3]
        hovers.append("<b>%s</b><br>%d건 · 유효 %s · 최근 %d년 출원 %d건<br>주요: %s"
                      % (" + ".join(key), rec["n"],
                         fmt_pct(ratio) if ratio is not None else "미상",
                         recent_years, rec["recent"],
                         ", ".join(a for a, _c in top_apps) or "-"))
        customs.append({"drill": {"type": "ids", "ids": rec["ids"]}})
    # 유효비율 미상 막대는 중간색(0.5=절반 유효처럼 오독)이 아닌 회색으로 —
    # 명시적 색상 배열로 변환 (RDYLGN: 0=빨강, 0.5=노랑, 1=초록 보간)
    def _ratio_color(r):
        if r is None:
            return "#b9c4cd"  # 미상
        stops = [(0.0, (0xE1, 0x57, 0x59)), (0.5, (0xF5, 0xC9, 0x5C)),
                 (1.0, (0x59, 0xA1, 0x4F))]
        r = max(0.0, min(1.0, float(r)))
        for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
            if r <= p1:
                f = (r - p0) / (p1 - p0) if p1 > p0 else 0.0
                return "#%02x%02x%02x" % tuple(
                    int(a + (b - a) * f) for a, b in zip(c0, c1))
        return "#59A14F"
    traces = [{
        "type": "bar", "x": xs, "y": bar_y, "name": "특허 수",
        "hovertext": hovers, "hoverinfo": "text", "customdata": customs,
        "marker": {"color": [_ratio_color(r) for r in bar_colors],
                   "line": {"width": bar_lines, "color": "#1a2733"}},
        "yaxis": "y"}]
    # 매트릭스: 회색 배경 도트 + 멤버 도트 + 조합 연결선
    grid_x, grid_y = [], []
    for x in xs:
        for e in shown_elems:
            grid_x.append(x)
            grid_y.append(elem_pos[e])
    traces.append({"type": "scatter", "mode": "markers", "x": grid_x, "y": grid_y,
                   "marker": {"size": 7, "color": "#dde5ec"}, "hoverinfo": "skip",
                   "showlegend": False, "yaxis": "y2"})
    mem_x, mem_y, mem_hover = [], [], []
    for x, (key, rec) in zip(xs, ranked):
        pos = sorted(elem_pos[e] for e in key if e in elem_pos)
        for p in pos:
            mem_x.append(x)
            mem_y.append(p)
            mem_hover.append(" + ".join(key))
        if len(pos) >= 2:
            traces.append({"type": "scatter", "mode": "lines",
                           "x": [x, x], "y": [pos[0], pos[-1]],
                           "line": {"color": "#2F4B7C", "width": 2},
                           "hoverinfo": "skip", "showlegend": False, "yaxis": "y2"})
    traces.append({"type": "scatter", "mode": "markers", "x": mem_x, "y": mem_y,
                   "marker": {"size": 9, "color": "#2F4B7C"},
                   "hovertext": mem_hover, "hoverinfo": "text",
                   "showlegend": False, "yaxis": "y2"})
    fig = {"data": traces, "layout": base_layout(
        "기술요소 조합 UpSet (상위 %d개 조합 · 요소 %d개 추적)"
        % (len(ranked), len(shown_elems)),
        height=max(520, 340 + 22 * len(shown_elems)),
        showlegend=False,
        xaxis={"visible": False, "range": [-0.7, len(ranked) - 0.3]},
        yaxis={"title": "특허 수", "domain": [0.47, 1.0]},
        yaxis2={"domain": [0.0, 0.42], "tickmode": "array",
                "tickvals": [elem_pos[e] for e in shown_elems],
                "ticktext": [str(e)[:22] for e in shown_elems],
                "range": [-0.6, len(shown_elems) - 0.4], "zeroline": False,
                "showgrid": False},
        margin={"l": 170, "r": 30, "t": 48, "b": 20})}

    # ---- 미점유 조합 후보 (기대 vs 실제) ----------------------------------
    gap_pool = elements[:min(8, len(elements))]
    p = {e: elem_counts[e] / float(n_tracked_docs) for e in gap_pool}
    recent_active_elems = set()
    if recent_from is not None:
        for lst, y in zip(df["_tech_list"], years):
            if y is None or (isinstance(y, float) and np.isnan(y)) or int(y) < recent_from:
                continue
            recent_active_elems |= (set(lst or []) & set(gap_pool))
    gaps = []
    for size in (2, 3):
        for cand in combinations(gap_pool, size):
            cset = set(cand)
            actual = sum(1 for ds in doc_sets if cset <= ds)
            expected = n_tracked_docs * float(np.prod([p[e] for e in cand]))
            if expected < 1.5 or actual > max(1, expected * 0.15):
                continue
            gaps.append({
                "elements": list(cand), "size": size,
                "actual": int(actual), "expected": round(expected, 1),
                "gap_score": round(expected - actual, 1),
                "element_counts": {e: int(elem_counts[e]) for e in cand},
                "all_recent_active": bool(cset <= recent_active_elems),
            })
    gaps.sort(key=lambda g: -g["gap_score"])
    gaps = gaps[:15]

    sentences = []
    top_key, top_rec = ranked[0]
    sentences.append("가장 많이 청구된 요소 조합은 '%s'(%s건)입니다."
                     % (" + ".join(top_key), fmt_num(top_rec["n"])))
    if gaps:
        g0 = gaps[0]
        parts = ", ".join("%s %s건" % (e, fmt_num(g0["element_counts"][e]))
                          for e in g0["elements"])
        sentences.append("가장 유력한 미점유 조합은 '%s'입니다 — 개별 요소는 각각 "
                         "활발하지만(%s) 함께 청구된 특허는 %d건으로, 독립 가정 기대치 "
                         "%s건 대비 비어 있습니다%s."
                         % (" + ".join(g0["elements"]), parts, g0["actual"],
                            fmt_num(g0["expected"]),
                            " (요소 모두 최근 %d년 활동 중)" % recent_years
                            if g0["all_recent_active"] else ""))
    else:
        sentences.append("기대 대비 비어 있는 요소 조합이 발견되지 않았습니다 — 상위 "
                         "요소들의 조합은 대부분 이미 청구되어 있습니다.")
    sentences.append("미점유 조합은 통계적 공백 신호이며, 기술적 실현 가능성과 "
                     "선행문헌 검토를 대체하지 않습니다.")

    insight = build_insight(
        sentences,
        {"n_elements": len(elements), "n_combos": len(combos),
         "n_multi_combos": multi, "n_gap_candidates": len(gaps),
         "top_combo": " + ".join(top_key), "top_combo_n": top_rec["n"]},
        drills=[{"label": "최다 조합 특허 보기",
                 "drill": {"type": "ids", "ids": top_rec["ids"]}}],
        small_sample=check_small_sample(n_tracked_docs, settings))
    return ok_result(
        {"figure": fig, "gaps": gaps,
         "elements": [{"name": e, "count": int(elem_counts[e]),
                       "recent_active": e in recent_active_elems}
                      for e in elements]},
        insight=insight,
        meta={"note": "조합 막대는 문헌의 추적 요소 집합이 '정확히 일치'하는 기준이고, "
                      "미점유 후보의 실제 건수는 '모두 포함' 기준입니다. 제품 요구사항 "
                      "적합도는 요구사항 데이터가 없어 기대-실제 격차 점수로 대체합니다."})
