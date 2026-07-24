# -*- coding: utf-8 -*-
"""
analyses/lead_lag.py — 4.6 기업 간 기술 선도–추종 분석 (2단계).

분석 목적:
  기업별·기술분류별 연도 시계열의 시차 상관으로 「시계열상 선행 관계」를 탐지한다.
  (표현 주의: 인과관계·Granger causality 로 단정하지 않고 "시계열상 선행 신호",
  "전략적 선행 신호" 로만 표기한다.)

필수 컬럼: 기술분류(any), 날짜(any), 출원인(any)

계산식:
  1) 기업×기술분류×연도 건수 시계열 (연속 연도, 결측 0).
  2) 각 기술분류에서 기업쌍 (A,B) 에 대해 metrics.cross_correlation_lag:
     corr(A[t], B[t+lag]) 를 lag ∈ [-max_lag, +max_lag] 에서 탐색.
     lag>0 & corr>=leadlag_min_corr → "A 가 B 를 lag 년 선행" 관측 1건.
  3) 필터: 관측연도 >= min_years_leadlag, 기술분류 내 기업별 특허 수 >= min_patents_leadlag.
  4) 여러 기술분류에서 반복되는 선도 관계 집계: 같은 방향 관측 횟수(n_obs),
     평균 시차(avg_lag), 평균 상관(avg_corr). n_obs>=2 만 네트워크에 표시(옵션).

그래프 (Cytoscape Lead-Lag Network):
  노드=기업(크기=특허 수), 화살표=선도→추종, 두께=관계 강도(평균 상관×관측 수),
  엣지 색=대표 기술분류, 라벨=평균 시차.
Drill-down: 엣지 클릭 → 관련 기술분류 목록 + 양사 특허.
자동 인사이트: 최다 선도 기업, 반복 관측 관계.
예외처리: 조건 충족 시계열이 없으면 empty.
"""
import numpy as np

from src.config import get_threshold, get_limit
from src.metrics import cross_correlation_lag
from src.preprocessing import explode_tech
from src.insights import build_insight, fmt_num, period_label, check_small_sample
from src.viz_payload import ok_result, empty_result, cytoscape_network, color_for


def compute_lead_lag(df, settings, min_repeat=1):
    """선도–추종 분석 계산."""
    if not len(df):
        return empty_result()
    min_years = int(get_threshold(settings, "min_years_leadlag"))
    min_patents = int(get_threshold(settings, "min_patents_leadlag"))
    max_lag = int(get_threshold(settings, "max_lag_years"))
    min_corr = get_threshold(settings, "leadlag_min_corr")
    max_companies = get_limit(settings, "leadlag_max_companies")

    ex = explode_tech(df, mode=settings.get("multiclass_mode", "duplicate"))
    ex = ex[ex["_base_year"].notna() & (ex["applicant_display"].astype(str) != "")]
    if not len(ex):
        return empty_result("기업·기술분류·연도 시계열을 만들 데이터가 없습니다.")
    ex["_year_int"] = ex["_base_year"].astype(int)

    top_companies = set(ex["applicant_display"].value_counts().head(max_companies).index)
    ex = ex[ex["applicant_display"].isin(top_companies)]

    observations = []
    for tech, tech_group in ex.groupby("tech"):
        pivot = tech_group.pivot_table(index="_year_int", columns="applicant_display",
                                       values="weight", aggfunc="sum", fill_value=0.0)
        if len(pivot) < min_years:
            continue
        full_years = range(int(pivot.index.min()), int(pivot.index.max()) + 1)
        pivot = pivot.reindex(full_years, fill_value=0.0)
        eligible = [c for c in pivot.columns if pivot[c].sum() >= min_patents]
        for i, a in enumerate(eligible):
            for b in eligible[i + 1:]:
                lag, corr = cross_correlation_lag(pivot[a], pivot[b], max_lag=max_lag,
                                                  min_overlap=min_years)
                if lag is None or corr is None or abs(corr) < min_corr or lag == 0:
                    continue
                leader, follower = (a, b) if lag > 0 else (b, a)
                observations.append({"leader": str(leader), "follower": str(follower),
                                     "tech": str(tech), "lag": abs(int(lag)),
                                     "corr": round(float(corr), 3)})
    if not observations:
        return empty_result("조건(최소 %d년 관측·%d건 이상·상관 %.2f 이상)을 충족하는 "
                            "시계열상 선행 관계가 없습니다."
                            % (min_years, min_patents, min_corr))

    # 기업쌍 방향별 집계 (여러 기술분류 반복 관측)
    agg = {}
    for o in observations:
        key = (o["leader"], o["follower"])
        rec = agg.setdefault(key, {"leader": o["leader"], "follower": o["follower"],
                                   "techs": [], "lags": [], "corrs": []})
        rec["techs"].append(o["tech"])
        rec["lags"].append(o["lag"])
        rec["corrs"].append(abs(o["corr"]))
    relations = []
    for rec in agg.values():
        n_obs = len(rec["techs"])
        if n_obs < min_repeat:
            continue
        relations.append({
            "leader": rec["leader"], "follower": rec["follower"], "n_obs": n_obs,
            "avg_lag": round(float(np.mean(rec["lags"])), 2),
            "avg_corr": round(float(np.mean(rec["corrs"])), 3),
            "strength": round(float(np.mean(rec["corrs"]) * n_obs), 3),
            "techs": sorted(set(rec["techs"]))[:8],
        })
    if not relations:
        return empty_result("반복 관측된 선행 관계가 없습니다.")
    relations.sort(key=lambda r: -r["strength"])

    counts = df["applicant_display"].value_counts()
    node_names = sorted(set([r["leader"] for r in relations] + [r["follower"] for r in relations]))
    max_count = max((counts.get(n, 1) for n in node_names), default=1)
    nodes = [{"id": n, "label": n, "count": int(counts.get(n, 0)),
              "size": float(14 + 26 * np.sqrt(counts.get(n, 1) / max_count)),
              "color": "#4E79A7",
              "drill": {"type": "applicant", "applicant": n}} for n in node_names]
    color_reg = {}
    max_strength = max(r["strength"] for r in relations) or 1
    edges = [{"source": r["leader"], "target": r["follower"], "weight": r["strength"],
              "width": float(1.5 + 6 * r["strength"] / max_strength),
              "label": "평균 %s년 선행" % r["avg_lag"],
              "color": color_for(r["techs"][0] if r["techs"] else "기타", color_reg),
              "avg_lag": r["avg_lag"], "avg_corr": r["avg_corr"], "n_obs": r["n_obs"],
              "techs": r["techs"], "arrow": True} for r in relations]

    lead_counts = {}
    for r in relations:
        lead_counts[r["leader"]] = lead_counts.get(r["leader"], 0) + r["n_obs"]
    sentences = []
    if lead_counts:
        top_leader = max(lead_counts, key=lead_counts.get)
        sentences.append("%s 기준 시계열상 선행 신호가 가장 많이 관측된 기업은 '%s'"
                         "(%s개 관계)입니다. 이는 통계적 선행 관계이며 인과관계를 "
                         "의미하지 않습니다."
                         % (period_label(df), top_leader, fmt_num(lead_counts[top_leader])))
    repeated = [r for r in relations if r["n_obs"] >= 2]
    if repeated:
        r0 = repeated[0]
        sentences.append("'%s → %s' 관계는 %s개 기술분류에서 반복 관측(평균 시차 %s년, "
                         "평균 상관 %s)되어 전략적 선행 신호로 주목할 만합니다."
                         % (r0["leader"], r0["follower"], fmt_num(r0["n_obs"]),
                            r0["avg_lag"], r0["avg_corr"]))
    insight = build_insight(sentences, {"n_relations": len(relations)},
                            small_sample=check_small_sample(len(observations), settings))
    return ok_result({"network": cytoscape_network(nodes, edges),
                      "relations": relations[:50]},
                     insight=insight,
                     meta={"note": "시계열상 선행 관계이며 인과관계가 아닙니다."})
