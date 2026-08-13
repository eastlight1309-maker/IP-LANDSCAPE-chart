# -*- coding: utf-8 -*-
"""
analyses/trajectory.py — 4.4 Technology Trajectory Map (기업별 전략 이동 궤적, 2단계).

분석 목적:
  기업·연도별 기술분류 구성비 벡터를 2차원에 투영하여, 기업 전략의 이동 궤적을
  화살표로 연결해 시각화한다.

필수 컬럼: 기술분류(any), 날짜(any), 출원인(any)
선택 컬럼: 유효특허 여부(점 크기), 패밀리 ID

계산식:
  1) 기업·연도별 기술분류 구성비 벡터 (company_tech_shares(by_year=True))
     - 출원량 차이 왜곡 방지: weighting='share'(구성비) 또는 'tfidf'
       (구성비 × log((기업×연도 관측 수+1)/(분류 보유 관측 수+1))+1 — IDF 유사 가중).
  2) 차원축소: method='pca'(기본) | 'umap' — UMAP 불가 시 PCA 자동 폴백 (gpu_utils).
  3) 기업별 연도 순 점 연결 화살표, 이동거리 = 연속 연도 좌표 간 유클리드 거리 합.

그래프: 점(기업×연도), 크기=해당 연도 유효 문헌 수, 색=기업,
        hover=주요 기술분류 Top3·비중, 화살표=연도 순 이동.
Drill-down: 점 클릭 {"type":"applicant","applicant":…,"year":…}.
자동 인사이트: 이동거리 상위 기업, 가장 안정적인 기업.
예외처리: 최소 관측(기업당 2개 연도, 연도당 min_class_patents 건) 미달 기업 제외.
대상 기업: companies 파라미터 또는 출원 상위 trajectory_max_companies 개.
"""
import numpy as np

from src.config import get_threshold, get_limit
from src.gpu_utils import run_pca, run_umap
from src.analyses.common import company_tech_shares
from src.insights import build_insight, fmt_num, period_label, check_small_sample
from src.viz_payload import ok_result, empty_result, base_layout, PALETTE


def compute_trajectory(df, settings, companies=None, method="pca", weighting=None):
    """Technology Trajectory Map 계산."""
    if not len(df):
        return empty_result()
    weighting = weighting or settings.get("trajectory_weighting", "share")
    shares = company_tech_shares(df, multiclass_mode=settings.get("multiclass_mode", "duplicate"),
                                 by_year=True)
    if shares.empty:
        return empty_result("기업·연도별 구성비를 만들 데이터가 없습니다.")

    min_n = get_threshold(settings, "min_class_patents")
    max_companies = get_limit(settings, "trajectory_max_companies")
    tmp = df[df["_base_year"].notna()].copy()
    tmp["_year_int"] = tmp["_base_year"].astype(int)
    counts = tmp.groupby(["applicant_display", "_year_int"]).size()

    if companies:
        wanted = [str(c) for c in companies][:max_companies]
    else:
        totals = df["applicant_display"].replace("", np.nan).dropna().value_counts()
        wanted = totals.head(max_companies).index.tolist()

    rows = []
    for (company, year) in shares.index:
        if str(company) not in wanted:
            continue
        n = counts.get((company, year), 0)
        if n < min_n:
            continue
        rows.append((str(company), int(year)))
    # 기업당 최소 2개 연도
    by_company = {}
    for c, y in rows:
        by_company.setdefault(c, []).append(y)
    by_company = {c: sorted(ys) for c, ys in by_company.items() if len(ys) >= 2}
    if not by_company:
        return empty_result("연도당 최소 %d건·2개 연도 이상 관측된 기업이 없습니다." % int(min_n))

    keys = [(c, y) for c, ys in by_company.items() for y in ys]
    X = np.vstack([shares.loc[(c, y)].values for c, y in keys])
    if weighting == "tfidf":
        presence = (shares.loc[[k for k in keys]] > 0).sum(axis=0).values.astype(float)
        idf = np.log((len(keys) + 1.0) / (presence + 1.0)) + 1.0
        X = X * idf

    if X.shape[0] < 3 or X.shape[1] < 2:
        return empty_result("차원축소에 필요한 표본이 부족합니다.")
    if method == "umap":
        emb, used_method = run_umap(X, n_components=2)
    else:
        emb, used_method = run_pca(X, n_components=2)
    if emb.shape[1] < 2:
        emb = np.hstack([emb, np.zeros((emb.shape[0], 1))])

    coords = {k: (float(emb[i, 0]), float(emb[i, 1])) for i, k in enumerate(keys)}
    act = tmp[tmp["_active_flag"].map(lambda v: v is True)]
    active_counts = act.groupby(["applicant_display", "_year_int"]).size() if len(act) else None

    traces, annotations = [], []
    company_stats = []
    for ci, (company, years) in enumerate(sorted(by_company.items())):
        color = PALETTE[ci % len(PALETTE)]
        xs, ys_, sizes, hovers, custom = [], [], [], [], []
        dist = 0.0
        for j, y in enumerate(years):
            x, yy = coords[(company, y)]
            xs.append(x)
            ys_.append(yy)
            top_shares = shares.loc[(company, y)].sort_values(ascending=False).head(3)
            share_txt = ", ".join("%s %.0f%%" % (t[:14], s * 100)
                                  for t, s in top_shares.items() if s > 0)
            n_total = int(counts.get((company, y), 0))
            n_active = int(active_counts.get((company, y), 0)) if active_counts is not None else n_total
            sizes.append(max(n_active, 1))
            hovers.append("<b>%s — %d</b><br>%s건 (유효 %s)<br>주요: %s"
                          % (company, y, fmt_num(n_total), fmt_num(n_active), share_txt))
            custom.append({"drill": {"type": "applicant", "applicant": company, "year": y}})
            if j > 0:
                px, py = coords[(company, years[j - 1])]
                dist += float(np.hypot(x - px, yy - py))
                annotations.append({"x": x, "y": yy, "ax": px, "ay": py,
                                    "xref": "x", "yref": "y", "axref": "x", "ayref": "y",
                                    "showarrow": True, "arrowhead": 3, "arrowsize": 0.9,
                                    "arrowwidth": 1.2, "arrowcolor": color, "text": "",
                                    "opacity": 0.7})
        smax = max(sizes)
        traces.append({"type": "scatter", "mode": "markers+text", "name": company,
                       "x": xs, "y": ys_, "text": [str(y) for y in years],
                       "textposition": "top center", "textfont": {"size": 9},
                       "hovertext": hovers, "hoverinfo": "text", "customdata": custom,
                       "marker": {"size": sizes, "sizemode": "area",
                                  "sizeref": 2.0 * smax / (26 ** 2), "sizemin": 6,
                                  "color": color, "opacity": 0.85,
                                  "line": {"width": 1, "color": "#333"}}})
        company_stats.append({"company": company, "distance": round(dist, 3),
                              "years": years,
                              "drill": {"type": "applicant", "applicant": company}})
    layout = base_layout("Technology Trajectory Map (%s, %s 가중)" % (used_method, weighting),
                         xaxis={"title": "주성분 1 (단위 없음 — 상대 위치)", "zeroline": False,
                                "showticklabels": False},
                         yaxis={"title": "주성분 2 (단위 없음 — 상대 위치)", "zeroline": False,
                                "showticklabels": False})
    layout["annotations"] = annotations
    fig = {"data": traces, "layout": layout}

    company_stats.sort(key=lambda r: -r["distance"])
    sentences = []
    if company_stats:
        top = company_stats[0]
        sentences.append("%s 기준 전략 이동거리가 가장 큰 기업은 '%s'(누적 이동거리 %s, "
                         "관측 %d–%d년)로 포트폴리오 재편 신호입니다."
                         % (period_label(df), top["company"], fmt_num(top["distance"], 2),
                            top["years"][0], top["years"][-1]))
        stable = company_stats[-1]
        sentences.append("가장 안정적인 기업은 '%s'(이동거리 %s)입니다."
                         % (stable["company"], fmt_num(stable["distance"], 2)))
    insight = build_insight(sentences, {"n_companies": len(company_stats)},
                            small_sample=check_small_sample(len(keys), settings))
    return ok_result({"figure": fig, "companies": company_stats, "method": used_method,
                      "weighting": weighting}, insight=insight)
