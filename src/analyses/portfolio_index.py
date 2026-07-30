# -*- coding: utf-8 -*-
"""
analyses/portfolio_index.py — 포트폴리오 가치 지표 (LexisNexis PatentSight 스타일).

분석 목적:
  PatentSight 의 Patent Asset Index(PAI)/Competitive Impact(CI)/
  Technology Relevance(TR)/Market Coverage(MC) 에서 착안한 「유사 지표」로
  기업 포트폴리오의 질적 가치를 비교한다.
  ⚠ 산식이 공개 지표와 동일하지 않은 근사 지표임을 화면에 명시한다.

필수 컬럼: 출원인(any), 피인용 수
선택 컬럼: 패밀리 국가 수(없으면 패밀리 수 → 1.0 폴백), 존속 여부/법적상태,
          날짜(연도 코호트 보정·추이)

계산식 (특허 i):
  TR_i (기술 영향력) = 피인용_i / mean(피인용, 동일 출원연도 코호트)
    — 연도 코호트 평균으로 인용 축적 기간 차이를 보정 (코호트 평균 0 이면 전체 평균,
      그것도 0 이면 TR=0). 연도 없으면 전체 평균 보정.
  MC_i (시장 커버리지) = 패밀리 국가 수_i / mean(패밀리 국가 수)
    — 컬럼 없으면 패밀리 수로 대체, 둘 다 없으면 1.0 (meta 에 명시).
  CI_i (경쟁 임팩트) = TR_i × MC_i
  Portfolio Index(기업) = Σ CI_i  (유효특허만; 유효 판정 불가 시 등록만,
    그것도 없으면 전체 — 사용한 기준을 meta 에 명시)
  평균 CI(기업) = Portfolio Index / 대상 특허 수

그래프:
  ① 기업별 Portfolio Index 순위 막대
  ② 버블: X=대상 특허 수(규모), Y=평균 CI(질), 크기=Portfolio Index, 색=최근 성장률
     (축 선택 지원: customdata.m)
  ③ 기업별 연도 추이: 출원연도 기준 CI 합 라인 (상위 5개사)
  ④ CI 상위 특허 목록
Drill-down: 기업 {"type":"applicant"}, 특허 {"type":"ids"}.
자동 인사이트: PI 1위 기업(규모 vs 질 분해), 평균 CI 1위, 소규모·고품질 기업.
예외처리: 피인용 없으면 disabled(안내), 표본 미달 기업 제외.
"""
import numpy as np
import pandas as pd

from src.config import get_threshold, get_limit
from src.metrics import robust_growth, year_counts, safe_div
from src.insights import build_insight, fmt_num, fmt_pct, period_label, check_small_sample
from src.viz_payload import ok_result, empty_result, disabled_result, bar_chart, \
    line_chart, base_layout


def compute_portfolio_index(df, settings):
    """PatentSight 스타일 포트폴리오 지표 계산."""
    if not len(df):
        return empty_result()
    if "cites_forward" not in df.columns:
        return disabled_result(["피인용 수"],
                               message="피인용 수 컬럼이 없어 포트폴리오 가치 지표를 계산할 수 "
                                       "없습니다. 컬럼 매핑에서 '피인용 수'를 매핑하세요.")
    if not df["cites_forward"].notna().any():
        return disabled_result(["피인용 수"],
                               message="피인용 수 컬럼은 매핑되어 있으나 숫자로 해석되는 값이 "
                                       "없습니다. 컬럼 매핑 화면의 '예시 값'을 확인하세요.")
    work = df.copy()
    cites = work["cites_forward"].fillna(0).astype(float)

    # TR: 출원연도 코호트 보정
    years = work["_base_year"]
    global_mean = float(cites.mean()) or 0.0
    cohort_mean = pd.Series(global_mean, index=work.index)
    if years.notna().any():
        by_year = cites.groupby(years).transform("mean")
        cohort_mean = by_year.where(by_year > 0, other=global_mean).fillna(global_mean)
    tr = cites / cohort_mean.replace(0, np.nan)
    tr = tr.fillna(0.0)

    # MC: 패밀리 국가 수 → 패밀리 수 → 1.0
    mc_source = None
    if "family_country_count" in work.columns and work["family_country_count"].notna().any():
        fam = work["family_country_count"].fillna(0).astype(float)
        mc_source = "패밀리 국가 수"
    elif "family_size" in work.columns and work["family_size"].notna().any():
        fam = work["family_size"].fillna(0).astype(float)
        mc_source = "패밀리 수 (국가 수 부재 대체)"
    else:
        fam = pd.Series(1.0, index=work.index)
        mc_source = "미가용 (MC=1 고정)"
    fam_mean = float(fam.mean()) or 1.0
    mc = fam / fam_mean if fam_mean > 0 else pd.Series(1.0, index=work.index)
    ci = tr * mc
    work["_tr"], work["_mc"], work["_ci"] = tr, mc, ci

    # 대상 포트폴리오: 유효 → 등록 → 전체
    active_mask = work["_active_flag"].map(lambda v: v is True)
    granted_mask = work["_is_granted_bool"].map(lambda v: v is True)
    if active_mask.any():
        scope_mask, scope_label = active_mask, "유효특허"
    elif granted_mask.any():
        scope_mask, scope_label = granted_mask, "등록특허 (유효 판정 불가)"
    else:
        scope_mask, scope_label = pd.Series(True, index=work.index), "전체 (권리상태 정보 없음)"
    scoped = work[scope_mask & (work["applicant_display"].astype(str) != "")]
    if not len(scoped):
        return empty_result("대상 포트폴리오(%s)에 출원인 정보가 있는 특허가 없습니다." % scope_label)

    min_n = get_threshold(settings, "min_class_patents")
    recent = int(get_threshold(settings, "recent_years"))
    top_n = int(get_limit(settings, "top_n_default")) + 5

    rows = []
    for company, grp in scoped.groupby("applicant_display"):
        n = len(grp)
        if n < min_n:
            continue
        pai = float(grp["_ci"].sum())
        all_grp = work[work["applicant_display"] == company]
        yrs = all_grp["_base_year"].dropna().astype(int)
        growth, _ = (robust_growth(year_counts(yrs), recent_years=recent)
                     if len(yrs) else (None, "n/a"))
        rows.append({"company": str(company), "n": n,
                     "portfolio_index": round(pai, 2),
                     "avg_ci": round(safe_div(pai, n, 0.0), 3),
                     "avg_tr": round(float(grp["_tr"].mean()), 3),
                     "avg_mc": round(float(grp["_mc"].mean()), 3),
                     "growth": round(growth, 4) if growth is not None else None,
                     "drill": {"type": "applicant", "applicant": str(company)}})
    if not rows:
        return empty_result("최소 표본(%d건) 이상의 기업이 없습니다." % int(min_n))
    rows.sort(key=lambda r: -r["portfolio_index"])
    shown = rows[:30]

    # ① PI 순위 막대
    top_bar = shown[:top_n]
    fig_rank = bar_chart(
        [r["company"] for r in top_bar][::-1],
        [r["portfolio_index"] for r in top_bar][::-1],
        title="Portfolio Index 순위 (%s 기준)" % scope_label, orientation="h",
        x_title="Portfolio Index (Σ CI)",
        hovertext=["%s — PI %s / %s건 / 평균 CI %s (TR %s × MC %s)"
                   % (r["company"], fmt_num(r["portfolio_index"]), fmt_num(r["n"]),
                      r["avg_ci"], r["avg_tr"], r["avg_mc"]) for r in top_bar][::-1],
        customdata=[{"drill": r["drill"]} for r in top_bar][::-1])

    # ② 규모 vs 질 버블
    sizes = [max(r["portfolio_index"], 0.1) for r in shown]
    smax = max(sizes)
    bubble = {"data": [{
        "type": "scatter", "mode": "markers+text",
        "x": [r["n"] for r in shown], "y": [r["avg_ci"] for r in shown],
        "text": [r["company"][:10] for r in shown], "textposition": "top center",
        "textfont": {"size": 9},
        "hovertext": ["<b>%s</b><br>PI %s / %s건 / 평균 CI %s<br>TR %s / MC %s / 성장률 %s"
                      % (r["company"], fmt_num(r["portfolio_index"]), fmt_num(r["n"]),
                         r["avg_ci"], r["avg_tr"], r["avg_mc"],
                         fmt_pct(r["growth"]) if r["growth"] is not None else "-")
                      for r in shown],
        "hoverinfo": "text",
        "customdata": [{"drill": r["drill"],
                        "m": {"n": r["n"], "avg_ci": r["avg_ci"],
                              "portfolio_index": r["portfolio_index"],
                              "avg_tr": r["avg_tr"], "avg_mc": r["avg_mc"],
                              "growth": r["growth"]}} for r in shown],
        "marker": {"size": sizes, "sizemode": "area",
                   "sizeref": 2.0 * smax / (42 ** 2), "sizemin": 6,
                   "color": [r["growth"] if r["growth"] is not None else 0 for r in shown],
                   "colorscale": "RdYlGn", "showscale": True,
                   "colorbar": {"title": "최근 성장률", "thickness": 12},
                   "line": {"width": 1, "color": "#333"}, "opacity": 0.85},
    }], "layout": base_layout(
        "포트폴리오 규모 vs 질 (크기=Portfolio Index)",
        xaxis={"title": "%s 수 (규모)" % scope_label},
        yaxis={"title": "평균 Competitive Impact (질)"})}

    # ③ 상위 5개사 연도별 CI 합 추이
    fig_trend = None
    if scoped["_base_year"].notna().any():
        series_list = []
        for r in shown[:5]:
            grp = scoped[(scoped["applicant_display"] == r["company"])
                         & scoped["_base_year"].notna()]
            if not len(grp):
                continue
            ci_by_year = grp.groupby(grp["_base_year"].astype(int))["_ci"].sum()
            if len(ci_by_year):
                full = range(int(ci_by_year.index.min()), int(ci_by_year.index.max()) + 1)
                ci_by_year = ci_by_year.reindex(full, fill_value=0.0)
                series_list.append({"name": r["company"],
                                    "x": [int(y) for y in ci_by_year.index],
                                    "y": [round(float(v), 2) for v in ci_by_year.values]})
        if series_list:
            fig_trend = line_chart(series_list, "출원연도", "CI 합",
                                   title="기업별 연도 CI 추이 (상위 5개사)")

    # ④ CI 상위 특허
    id_col = "pub_number" if "pub_number" in scoped.columns else \
        ("app_number" if "app_number" in scoped.columns else None)
    top_patents = []
    for idx, row in scoped.nlargest(int(get_limit(settings, "top_n_default")), "_ci").iterrows():
        pid = str(row[id_col]) if id_col else str(idx)
        top_patents.append({"id": pid, "title": str(row.get("title", ""))[:90],
                            "applicant": str(row.get("applicant_display", "")),
                            "ci": round(float(row["_ci"]), 3),
                            "tr": round(float(row["_tr"]), 3),
                            "mc": round(float(row["_mc"]), 3),
                            "cites": int(row["cites_forward"]) if pd.notna(row["cites_forward"]) else 0,
                            "drill": {"type": "ids", "ids": [pid]}})

    sentences, metrics = [], {"scope": scope_label, "mc_source": mc_source}
    top = shown[0]
    sentences.append("%s 기준 Portfolio Index 1위는 '%s'(PI %s = %s건 × 평균 CI %s)입니다."
                     % (period_label(df), top["company"], fmt_num(top["portfolio_index"]),
                        fmt_num(top["n"]), top["avg_ci"]))
    best_quality = max(shown, key=lambda r: r["avg_ci"])
    if best_quality["company"] != top["company"]:
        sentences.append("평균 CI(질) 1위는 '%s'(평균 CI %s, %s건)로, 규모 대비 질적 "
                         "가치가 높은 포트폴리오입니다 (긍정 요인)."
                         % (best_quality["company"], best_quality["avg_ci"],
                            fmt_num(best_quality["n"])))
    small_strong = [r for r in shown if r["n"] < top["n"] * 0.3
                    and r["avg_ci"] > top["avg_ci"] * 1.2]
    if small_strong:
        sentences.append("소규모·고품질 기업(%s)은 기술 확보·협력 후보로 검토할 만합니다."
                         % ", ".join(r["company"] for r in small_strong[:3]))
    metrics.update({"top_company": top["company"], "top_pi": top["portfolio_index"]})
    insight = build_insight(sentences, metrics,
                            drills=[{"label": "1위 기업 특허", "drill": top["drill"]}],
                            small_sample=check_small_sample(len(scoped), settings))
    return ok_result({"rank": fig_rank, "bubble": bubble, "trend": fig_trend,
                      "companies": shown, "top_patents": top_patents,
                      "scope": scope_label, "mc_source": mc_source},
                     insight=insight,
                     meta={"note": ("PatentSight 의 PAI/CI/TR/MC 에서 착안한 유사 지표이며 "
                                    "공식 산식과 동일하지 않습니다. MC 산출: %s, 대상: %s."
                                    % (mc_source, scope_label))})
