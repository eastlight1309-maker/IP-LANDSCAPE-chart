# -*- coding: utf-8 -*-
"""
analyses/lifecycle.py — 4.7 기술 생애주기 Phase Map.

분석 목적:
  기술분류별 성숙도·모멘텀 지표로 생애주기 단계(Emerging/Growing/Competitive/
  Mature/Declining/Re-emerging)를 판정하고 버블맵으로 표현한다.

필수 컬럼: 기술분류(any), 날짜(any)
선택 컬럼: 출원인(집중도·신규출원인), 유효특허 여부, 피인용 수, 후속출원 정보

지표(기술분류별):
  - growth: 최근 출원 성장률 (robust_growth)
  - new_entrant_growth: 신규 출원인 증가율 (최근 구간 신규 출원인 / 전체 출원인)
  - age: 최초 진입 후 경과연수
  - concentration: 출원인 HHI
  - active_ratio: 유효특허 비율
  - combo_growth: 해당 분류가 참여한 신규 조합 수 증가율
  - avg_citations: 등록특허 평균 피인용도 (있을 때)
  - maturity(X축) = 정규화( age ) 와 정규화( 누적건수 ) 의 평균
  - momentum(Y축) = 정규화( growth ) 와 정규화( new_entrant_growth ) 의 평균

단계 판정 규칙 (임계값은 Settings thresholds 로 조정 가능):
  Re-emerging: 과거 reemerging_decline_years 간 감소·정체(합계 기울기<=0) AND
               최근 3년 연속 증가 AND 신규 출원인 존재 AND 신규 기술조합 동반 증가
  Emerging   : age<=5 AND growth>=emerging_min_growth
  Growing    : growth>=emerging_min_growth
  Declining  : growth<-0.1
  Competitive: 성장 정체(-0.1<=growth<emerging_min_growth) AND 집중도 낮음(HHI<0.15)
               AND 신규 출원인 유입 지속
  Mature     : 그 외

그래프: X=성숙도, Y=모멘텀, 크기=유효 패밀리 수, 색상=경쟁 강도(출원인 수),
        화살표=전년 대비 (성숙도, 모멘텀) 이동 방향.
Drill-down: 버블 클릭 {"type":"tech"}.
자동 인사이트: 단계별 분포, Re-emerging 탐지 결과.
예외처리: 표본<min_class_patents 분류 제외, 연도 없으면 empty.
"""
import numpy as np
import pandas as pd

from src.config import get_threshold, get_limit, LIFECYCLE_PHASES
from src.metrics import robust_growth, hhi, linreg_slope, normalize_series
from src.analyses.common import tech_year_matrix, combo_counts, diagnose_year_tech
from src.insights import build_insight, fmt_num, fmt_pct, period_label, check_small_sample
from src.viz_payload import ok_result, empty_result, bubble_chart


def detect_reemerging(series, new_entrants_recent, combo_growth,
                      decline_years=3, recent_increase_years=3):
    """Re-emerging 탐지 규칙 (별도 함수).

    조건(모두 충족):
      ① 과거 구간(최근 recent_increase_years 이전의 decline_years)이 감소·정체
         (선형회귀 기울기 <= 0)
      ② 최근 recent_increase_years 년 연속 증가
      ③ 신규 출원인 증가 (recent 신규 출원인 >= 1)
      ④ 신규 기술조합 동반 증가 (combo_growth > 0)
    """
    s = pd.Series(series).dropna().astype(float)
    need = decline_years + recent_increase_years
    if len(s) < need:
        return False
    recent_part = s.iloc[-recent_increase_years:]
    past_part = s.iloc[-(need):-recent_increase_years]
    past_slope = linreg_slope(past_part)
    if past_slope is None or past_slope > 0:
        return False
    diffs = np.diff(recent_part.values)
    if not (len(diffs) > 0 and all(d > 0 for d in diffs)):
        return False
    if not new_entrants_recent or new_entrants_recent < 1:
        return False
    return combo_growth is not None and combo_growth > 0


def _phase_of(row, settings):
    """단계 판정 (Re-emerging 우선)."""
    g_min = get_threshold(settings, "emerging_min_growth")
    if row["reemerging"]:
        return "Re-emerging"
    growth = row["growth"] if row["growth"] is not None else 0.0
    if row["age"] is not None and row["age"] <= 5 and growth >= g_min:
        return "Emerging"
    if growth >= g_min:
        return "Growing"
    if growth < -0.1:
        return "Declining"
    if (row["concentration"] is not None and row["concentration"] < 0.15
            and row["new_entrants"] >= 1):
        return "Competitive"
    return "Mature"


def compute_lifecycle(df, settings):
    """기술 생애주기 Phase Map 계산."""
    if not len(df):
        return empty_result()
    mode = settings.get("multiclass_mode", "duplicate")
    mat = tech_year_matrix(df, multiclass_mode=mode)
    if mat.empty:
        return empty_result(diagnose_year_tech(df))
    recent = int(get_threshold(settings, "recent_years"))
    min_n = get_threshold(settings, "min_class_patents")
    decline_years = int(get_threshold(settings, "reemerging_decline_years"))
    y_max = int(mat.columns.max())
    recent_from = y_max - recent + 1

    # 조합 성장률 (기술별): 최근 구간 첫 출현 조합 수
    pairs, _, _ = combo_counts(df, recent_year_from=recent_from)
    combo_new_by_tech, combo_old_by_tech = {}, {}
    for _, r in (pairs.iterrows() if len(pairs) else []):
        first = min(r["years"]) if r["years"] else None
        bucket = combo_new_by_tech if (first is not None and first >= recent_from) \
            else combo_old_by_tech
        for t in (r["a"], r["b"]):
            bucket[t] = bucket.get(t, 0) + 1

    rows = []
    for tech, series in mat.iterrows():
        total = float(series.sum())
        if total < min_n:
            continue
        in_tech = df["_tech_list"].map(lambda lst: tech in (lst or []))
        sub = df[in_tech]
        growth, g_method = robust_growth(series, recent_years=recent)
        first_year = int(series[series > 0].index.min()) if (series > 0).any() else None
        age = (y_max - first_year) if first_year is not None else None
        applicants_all = sub["applicant_display"].replace("", np.nan).dropna()
        counts = applicants_all.value_counts()
        conc = hhi(counts.values)
        recent_apps = set(sub.loc[sub["_base_year"] >= recent_from, "applicant_display"]
                          .replace("", np.nan).dropna())
        old_apps = set(sub.loc[sub["_base_year"] < recent_from, "applicant_display"]
                       .replace("", np.nan).dropna())
        new_entrants = len(recent_apps - old_apps)
        flags = sub["_active_flag"]
        known = flags.map(lambda v: v is not None)
        active_ratio = float(flags[known].map(lambda v: v is True).mean()) if known.any() else None
        n_active = int(flags.map(lambda v: v is True).sum())
        combo_new = combo_new_by_tech.get(tech, 0)
        combo_old = combo_old_by_tech.get(tech, 0)
        combo_growth = ((combo_new - combo_old) / combo_old) if combo_old else \
            (1.0 if combo_new else 0.0)
        avg_cites = (float(sub["cites_forward"].dropna().mean())
                     if "cites_forward" in sub.columns and sub["cites_forward"].notna().any()
                     else None)
        reemerging = detect_reemerging(series, new_entrants, combo_growth,
                                       decline_years=decline_years,
                                       recent_increase_years=recent)
        rows.append({"tech": str(tech), "total": round(total, 1),
                     "growth": round(growth, 4) if growth is not None else None,
                     "growth_method": g_method, "age": age,
                     "concentration": round(conc, 3) if conc is not None else None,
                     "new_entrants": new_entrants,
                     "n_applicants": int(len(counts)),
                     "active_ratio": round(active_ratio, 3) if active_ratio is not None else None,
                     "n_active": n_active, "combo_growth": round(combo_growth, 3),
                     "avg_citations": round(avg_cites, 2) if avg_cites is not None else None,
                     "reemerging": bool(reemerging)})
    if not rows:
        return empty_result("최소 표본(%d건) 이상의 기술분류가 없습니다." % int(min_n))

    ages = normalize_series([r["age"] if r["age"] is not None else 0 for r in rows], log=False)
    totals = normalize_series([r["total"] for r in rows], log=True)
    growths = normalize_series([r["growth"] if r["growth"] is not None else 0 for r in rows],
                               log=False)
    entrants = normalize_series([r["new_entrants"] for r in rows], log=True)
    for i, r in enumerate(rows):
        r["maturity"] = round(float((ages[i] + totals[i]) / 2), 4)
        r["momentum"] = round(float((growths[i] + entrants[i]) / 2), 4)
        r["phase"] = _phase_of(r, settings)

    # 전년 대비 이동 방향 (직전 연도 제외 데이터로 재계산한 성숙도·모멘텀 근사)
    arrows = []
    if mat.shape[1] > 2:
        mat_prev = mat.iloc[:, :-1]
        prev_metrics = {}
        for tech, series in mat_prev.iterrows():
            if float(series.sum()) < min_n:
                continue
            g, _ = robust_growth(series, recent_years=recent)
            first_year = int(series[series > 0].index.min()) if (series > 0).any() else None
            prev_metrics[str(tech)] = {
                "age": (int(mat_prev.columns.max()) - first_year) if first_year else 0,
                "total": float(series.sum()), "growth": g if g is not None else 0.0}
        if prev_metrics:
            p_ages = normalize_series([m["age"] for m in prev_metrics.values()], log=False)
            p_totals = normalize_series([m["total"] for m in prev_metrics.values()], log=True)
            p_growth = normalize_series([m["growth"] for m in prev_metrics.values()], log=False)
            for i, (tech, m) in enumerate(prev_metrics.items()):
                m["maturity"] = float((p_ages[i] + p_totals[i]) / 2)
                m["momentum"] = float(p_growth[i])
            for r in rows:
                pm = prev_metrics.get(r["tech"])
                if pm:
                    arrows.append({"tech": r["tech"], "x0": pm["maturity"], "y0": pm["momentum"],
                                   "x1": r["maturity"], "y1": r["momentum"]})

    max_points = get_limit(settings, "bubble_max_points")
    shown = sorted(rows, key=lambda r: -r["total"])[:max_points]
    points = []
    for r in shown:
        hover = ("<b>%s</b> — %s<br>누적 %s건 / 성장률 %s (%s)<br>경과 %s년 / HHI %s / "
                 "신규 출원인 %s<br>유효비율 %s / 조합증가율 %s / 평균 피인용 %s"
                 % (r["tech"], r["phase"], fmt_num(r["total"]),
                    fmt_pct(r["growth"]) if r["growth"] is not None else "계산 불가",
                    r["growth_method"], fmt_num(r["age"]), r["concentration"],
                    fmt_num(r["new_entrants"]), fmt_pct(r["active_ratio"]) if r["active_ratio"] is not None else "미상",
                    fmt_pct(r["combo_growth"]), r["avg_citations"] if r["avg_citations"] is not None else "-"))
        points.append({"x": r["maturity"], "y": r["momentum"],
                       "size": (r["n_active"] or r["total"]),
                       "color": r["n_applicants"], "label": r["tech"], "hover": hover,
                       "customdata": {"drill": {"type": "tech", "tech": r["tech"]},
                                      "phase": r["phase"],
                                      # 축 선택 기능용 포인트별 지표
                                      "m": {"maturity": r["maturity"],
                                            "momentum": r["momentum"],
                                            "total": r["total"], "growth": r["growth"],
                                            "age": r["age"],
                                            "concentration": r["concentration"],
                                            "new_entrants": r["new_entrants"],
                                            "n_applicants": r["n_applicants"],
                                            "active_ratio": r["active_ratio"],
                                            "combo_growth": r["combo_growth"],
                                            "avg_citations": r["avg_citations"]}}})
    fig = bubble_chart(points, "기술 성숙도 (정규화) — 오른쪽=오래되고 축적 큼",
                       "최근 성장 모멘텀 (정규화) — 위=최근 출원 급증",
                       title="기술 생애주기 Phase Map — 어떤 기술이 뜨고(좌상) "
                             "주도하고(우상) 저무는지(우하 아래)",
                       quadrants={"x_mid": 0.5, "y_mid": 0.5,
                                  "labels": [
                                      "🌱 신생·급성장 (Emerging) — 초기 선점 검토",
                                      "🚀 성장 주도 (Growing) — 투자 확대 구간",
                                      "🏛 성숙·안정 (Mature) — 유지·효율 관리",
                                      "❄ 초기·정체 — 관망 (신호 약함)"]},
                       colorbar_title="경쟁 강도(출원인 수)")
    if fig:
        fig["layout"].setdefault("annotations", [])
        # 상위 버블에 기술명 라벨 — 차트만 봐도 어떤 기술이 어느 국면인지 읽히도록
        tr0 = fig["data"][0]
        tr0["mode"] = "markers+text"
        top_lbl = {r["tech"] for r in shown[:8]}
        tr0["text"] = [(p["label"][:12] if p["label"] in top_lbl else "")
                       for p in points]
        tr0["textposition"] = "top center"
        tr0["textfont"] = {"size": 9.5, "color": "#38506b"}
        fig["layout"]["annotations"].append({
            "x": 0.5, "y": -0.14, "xref": "paper", "yref": "paper",
            "showarrow": False,
            "text": "버블 크기=유효 특허 수 · 색=경쟁 강도(출원인 수, 진할수록 붐빔) · "
                    "회색 화살표=직전 기간 → 현재 위치 이동 (위로 향하면 재부상)",
            "font": {"size": 10.5, "color": "#8aa0b2"}})
    if fig and arrows:
        for a in arrows[:60]:
            fig["layout"]["annotations"].append({
                "x": a["x1"], "y": a["y1"], "ax": a["x0"], "ay": a["y0"],
                "xref": "x", "yref": "y", "axref": "x", "ayref": "y",
                "showarrow": True, "arrowhead": 3, "arrowsize": 0.8,
                "arrowwidth": 1, "arrowcolor": "rgba(100,100,100,0.45)", "text": ""})

    phase_counts = {p: sum(1 for r in rows if r["phase"] == p) for p in LIFECYCLE_PHASES}
    sentences = ["%s 기준 %s개 기술분류 중 단계 분포는 %s 입니다."
                 % (period_label(df), fmt_num(len(rows)),
                    ", ".join("%s %d" % (p, c) for p, c in phase_counts.items() if c))]
    reems = [r["tech"] for r in rows if r["phase"] == "Re-emerging"]
    if reems:
        sentences.append("재부상(Re-emerging) 신호가 탐지된 기술: %s — 과거 정체 후 최근 %d년 "
                         "연속 증가와 신규 출원인·신규 조합 증가가 동반되었습니다 (긍정 요인)."
                         % (", ".join(reems[:5]), recent))
    decl = [r["tech"] for r in sorted(rows, key=lambda x: (x["growth"] or 0))
            if r["phase"] == "Declining"][:3]
    if decl:
        sentences.append("쇠퇴 단계 기술(%s)은 신규 투자 시 위험 요인입니다." % ", ".join(decl))
    insight = build_insight(sentences, {"phase_counts": phase_counts},
                            small_sample=check_small_sample(len(rows), settings))
    return ok_result({"figure": fig, "phases": rows, "phase_counts": phase_counts},
                     insight=insight)
