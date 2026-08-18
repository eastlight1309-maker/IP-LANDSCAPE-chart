# -*- coding: utf-8 -*-
"""
analyses/emerging.py — 4.3 Emerging Combination Radar (기술융합 선행지표).

분석 목적:
  개별 기술 A·B 가 오래되었어도 A+B 조합이 최근 처음 증가하기 시작하면 신기술 방향
  후보로 포착한다.

필수 컬럼: 기술분류(any), 날짜(any)
선택 컬럼: 출원인(신규 진입), 유효특허 여부(테두리)

계산식:
  Emerging Combination Score
    = 가중 기하평균( 최근 3년 조합 성장률, 조합 Lift, 최근 신규 출원인 수, 기술분류 다양성 )
  - 각 성분은 log1p → Winsorization(2%) → Robust/MinMax scaling 으로 [0,1] 정규화
    (특정 변수의 점수 지배 방지). 가중치는 Settings(weights.emerging)에서 변경 가능.
  - 다양성 = 조합 A,B 가 서로 다른 대분류에 속하면 1, 같으면 0.5 (대분류 없으면 0.5).
  - 성장률은 metrics.robust_growth 사다리(CAGR→회귀기울기→기간증가율→Poisson→log1p).
  - 최소 표본: n_ab < min_combo_patents 조합 제외. 분모 0 은 safe_div/에психlon 처리.

그래프 구성 (Plotly 버블):
  X=조합 누적 특허 수(log축), Y=최근 3년 성장률, 크기=신규 진입 출원인 수+1,
  색상=Lift, 테두리 두께=유효특허 비율. 4분면 주석(좌상:초기 고성장/우상:핵심/
  우하:성숙·정체/좌하:미성숙).

Drill-down: 버블 클릭 → {"type":"combo","a":…,"b":…}.
자동 인사이트: Score 상위 조합, 신규 출원인·Lift 근거 문장. 표본 부족 문구 처리.
예외처리: 조합 없음/전부 표본 미달 시 empty.
"""
import numpy as np

from src.config import get_threshold, get_limit, get_weights
from src.metrics import lift as _emerging_lift, robust_growth, year_counts, \
    normalize_series, weighted_geometric_mean
from src.preprocessing import build_l1_lookup
from src.analyses.common import combo_counts, diagnose_year_tech
from src.insights import build_insight, fmt_num, fmt_pct, period_label, check_small_sample
from src.viz_payload import ok_result, empty_result, bubble_chart


def compute_emerging(df, settings):
    """Emerging Combination Radar 계산."""
    if not len(df):
        return empty_result()
    years = df["_base_year"].dropna()
    if not len(years):
        return empty_result(diagnose_year_tech(df))
    recent = int(get_threshold(settings, "recent_years"))
    recent_from = int(years.max()) - recent + 1
    pairs, tech_counts, n_docs = combo_counts(df, recent_year_from=recent_from, settings=settings)
    min_combo = get_threshold(settings, "min_combo_patents")
    pairs = pairs[pairs["n_ab"] >= min_combo] if len(pairs) else pairs
    if not len(pairs):
        return empty_result("최소 표본(%d건) 이상의 기술조합이 없어 계산 불가입니다." % int(min_combo))

    l1_lookup = build_l1_lookup(df)
    rows = []
    for _, r in pairs.iterrows():
        a, b = r["a"], r["b"]
        # year_max 고정: 마지막 출원이 오래된 조합이 자기 마지막 연도 기준으로
        # '최근 성장'을 얻는 왜곡 방지 — 최근 N년 창은 데이터셋 최신 연도 기준
        series = (year_counts(r["years"], year_max=int(years.max()))
                  if r["years"] else None)
        growth, g_method = (robust_growth(series, recent_years=recent)
                            if series is not None and len(series) else (None, "insufficient"))
        lift_v = _emerging_lift(int(r["n_ab"]), tech_counts.get(a, 0),
                                tech_counts.get(b, 0), n_docs)
        n_new = len(r["new_applicants"])
        l1a, l1b = l1_lookup.get(a), l1_lookup.get(b)
        diversity = 1.0 if (l1a and l1b and l1a != l1b) else 0.5
        # 유효특허 비율 (해당 조합 문헌 기준)
        in_combo = df["_tech_list"].map(lambda lst: a in (lst or []) and b in (lst or []))
        flags = df.loc[in_combo, "_active_flag"]
        known = flags.map(lambda v: v is not None)
        active_ratio = (float(flags[known].map(lambda v: v is True).mean())
                        if known.any() else None)
        rows.append({"a": a, "b": b, "n_ab": int(r["n_ab"]),
                     "growth": growth if growth is not None else 0.0,
                     "growth_available": growth is not None, "growth_method": g_method,
                     "lift": float(lift_v), "new_applicants": n_new,
                     "diversity": diversity, "active_ratio": active_ratio})
    if not rows:
        return empty_result()

    winsor = get_threshold(settings, "winsor_pct")
    norm_growth = normalize_series([max(r["growth"], 0.0) for r in rows], log=False,
                                   winsor_pct=winsor)
    norm_lift = normalize_series([r["lift"] for r in rows], log=True, winsor_pct=winsor)
    norm_new = normalize_series([r["new_applicants"] for r in rows], log=True,
                                winsor_pct=winsor)
    weights = get_weights(settings, "emerging")
    for i, r in enumerate(rows):
        r["score"] = weighted_geometric_mean(
            {"growth": float(norm_growth[i]), "lift": float(norm_lift[i]),
             "new_entrants": float(norm_new[i]), "diversity": r["diversity"]},
            weights)
        r["score"] = round(r["score"], 4) if r["score"] is not None else None
    rows.sort(key=lambda r: -(r["score"] or 0))
    max_points = get_limit(settings, "bubble_max_points")
    shown = rows[:max_points]

    points = []
    for r in shown:
        hover = ("<b>%s × %s</b><br>누적 %s건 / 최근성장률 %s (%s)<br>"
                 "Lift %s / 신규 출원인 %s / Score %s<br>유효특허 비율 %s"
                 % (r["a"], r["b"], fmt_num(r["n_ab"]),
                    fmt_pct(r["growth"]) if r["growth_available"] else "계산 불가",
                    r["growth_method"], fmt_num(r["lift"], 2), fmt_num(r["new_applicants"]),
                    r["score"], fmt_pct(r["active_ratio"]) if r["active_ratio"] is not None else "미상"))
        points.append({
            "x": max(r["n_ab"], 1), "y": r["growth"],
            "size": r["new_applicants"] + 1, "color": r["lift"],
            "label": "%s×%s" % (r["a"][:8], r["b"][:8]), "hover": hover,
            "line_width": 1 + 3 * (r["active_ratio"] or 0),
            "customdata": {"drill": {"type": "combo", "a": r["a"], "b": r["b"]},
                           "score": r["score"],
                           # 축 선택 기능용 포인트별 지표 (프론트에서 X/Y 재배치)
                           "m": {"n_ab": r["n_ab"], "growth": r["growth"],
                                 "lift": round(r["lift"], 3),
                                 "new_applicants": r["new_applicants"],
                                 "active_ratio": r["active_ratio"],
                                 "score": r["score"]}},
        })
    x_vals = [p["x"] for p in points]
    y_vals = [p["y"] for p in points]
    fig = bubble_chart(
        points, "조합 누적 특허 수 (log)", "최근 %d년 성장률" % recent,
        title="Emerging Combination Radar",
        quadrants={"x_mid": float(np.median(x_vals)), "y_mid": max(float(np.median(y_vals)), 0.0),
                   "labels": ["초기 고성장", "핵심", "성숙·정체", "미성숙"]},
        colorbar_title="Lift")
    if fig:
        fig["layout"]["xaxis"]["type"] = "log"
        # 로그축 range 는 log10 단위 — bubble_chart 가 넣은 선형 range 를 재계산
        x_lo = max(min(x_vals), 1.0)
        fig["layout"]["xaxis"]["range"] = [
            float(np.log10(x_lo)) - 0.1, float(np.log10(max(x_vals))) + 0.1]
        # 상위 조합 라벨: 지시선 주석 (Score 순, 로그 X 좌표 보정, 겹침 회피)
        from src.viz_payload import leader_labels
        fig["layout"].setdefault("annotations", [])
        fig["layout"]["annotations"] += leader_labels(
            [{"x": max(r["n_ab"], 1), "y": r["growth"],
              "text": "%s×%s" % (r["a"][:8], r["b"][:8]),
              "bold": i == 0}
             for i, r in enumerate(shown[:12])], log_x=True, plot_h=460.0,
            box_w=0.15)

    sentences, metrics = [], {}
    top = shown[0] if shown else None
    if top and top["score"]:
        sentences.append(
            "%s 기준 Emerging Score 1위 조합은 '%s × %s'(Score %s, 상위 %.0f%%)로, "
            "최근 %d년 성장률 %s·Lift %s·신규 출원인 %s개사가 근거입니다."
            % (period_label(df), top["a"], top["b"], top["score"],
               100.0 / max(len(rows), 1), recent,
               fmt_pct(top["growth"]) if top["growth_available"] else "계산 불가",
               fmt_num(top["lift"], 2), fmt_num(top["new_applicants"])))
        metrics.update({"top_combo": "%s × %s" % (top["a"], top["b"]),
                        "top_score": top["score"], "n_combos": len(rows)})
    high_new = [r for r in shown if r["new_applicants"] >= 3]
    if high_new:
        sentences.append("신규 출원인이 3개사 이상 진입한 조합이 %s개로, 융합 경쟁이 시작된 "
                         "신호입니다 (위험 요인: 선점 경쟁)." % fmt_num(len(high_new)))
    insight = build_insight(sentences, metrics,
                            drills=[{"label": "상위 조합 근거 특허",
                                     "drill": {"type": "combo", "a": top["a"], "b": top["b"]}}]
                            if top else [],
                            small_sample=check_small_sample(len(rows), settings))
    return ok_result({"figure": fig, "combos": shown[:50]}, insight=insight,
                     meta={"weights": get_weights(settings, "emerging"),
                           "truncated": len(rows) > len(shown)})
