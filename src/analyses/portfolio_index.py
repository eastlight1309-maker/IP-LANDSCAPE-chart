# -*- coding: utf-8 -*-
"""
analyses/portfolio_index.py — 포트폴리오 가치 지표 (Patent Asset Index 방법론).

분석 목적:
  공개 문헌 Ernst & Omland(2011), "The Patent Asset Index — A new approach to
  benchmark patent portfolios" (World Patent Information 33) 의 방법론에 따라
  Patent Asset Index(PAI)/Competitive Impact(CI)/Technology Relevance(TR)/
  Market Coverage(MC) 를 계산해 기업 포트폴리오의 질적 가치를 비교한다.

  공개 방법론과의 일치·차이 (화면에도 명시):
  - 구조(PAI=Σ CI, CI=TR×MC), TR 의 연령·기술분야 코호트 정규화,
    MC 의 국가별 시장규모(GNI, US=1) 가중은 공개 방법론과 동일하게 구현.
  - 상용 PatentSight 제품의 비공개 보정(인용 출처별 가중, 자체 패밀리 정의,
    데이터 정비)은 재현 불가 — 절대값은 다를 수 있으며 상대 비교 용도로 사용.

필수 컬럼: 출원인(any), 피인용 수
선택 컬럼: 패밀리 국가 목록(GNI 가중 MC — 권장), 패밀리 국가 수/패밀리 수(폴백),
          기술분류(TR 분야 보정), 존속 여부/법적상태, 날짜(연령 보정·추이)

계산식 (특허 i):
  TR_i (Technology Relevance) = 피인용_i / mean(피인용 | 동일 출원연도 × 동일 기술분야)
    — 연령(인용 축적 기간)과 기술분야(인용 관행 차이)를 동시에 보정.
      분야 코호트 표본<5 또는 분야 없음 → 연도 코호트 → 전체 평균 순 폴백.
  MC_i (Market Coverage) = Σ GNI(보호국) / GNI(US)
    — 패밀리 국가 목록이 매핑된 경우. 미국에서만 보호되면 1.0.
      EP 는 대표 검증국(DE·FR·GB) 근사(0.45), WO(PCT 출원 단계)는 0.
      목록이 없으면 국가 수/전체 평균 근사 → 패밀리 수 → 1.0 폴백 (근사임을 표시).
  CI_i (Competitive Impact) = TR_i × MC_i
  PAI(기업) = Σ CI_i  (유효특허만; 유효 판정 불가 시 등록만 → 전체 — meta 에 표시)

그래프: PAI 순위 막대 / 규모vs질 버블 / 패밀리×CI 버블 / MC 막대 / 연도 CI 추이 /
       CI 상위 특허. 각 차트에 개별 해석 캡션 + 지표 정의표(definitions) 제공.
Drill-down: 기업 {"type":"applicant"}, 특허 {"type":"ids"}.
예외처리: 피인용 없으면 disabled(안내), 표본 미달 기업 제외.
"""
import numpy as np
import pandas as pd

from src.config import get_threshold, get_limit
from src.metrics import robust_growth, year_counts, safe_div
from src.preprocessing import parse_multiclass_cell
from src.insights import build_insight, fmt_num, fmt_pct, period_label, check_small_sample
from src.viz_payload import RDYLGN, ok_result, empty_result, disabled_result, bar_chart, \
    line_chart, base_layout

# 국가별 GNI (조 USD, World Bank 2023 근사) — MC 가중치. 사용 시 US 로 정규화.
# EP: 대표 검증국(DE+FR+GB) 근사, WO: PCT 출원 단계로 보호 아님(0).
_GNI_TRILLION = {
    "US": 27.5, "CN": 19.0, "DE": 4.6, "JP": 4.3, "IN": 3.6, "GB": 3.5, "FR": 3.2,
    "IT": 2.3, "CA": 2.2, "BR": 2.2, "RU": 2.0, "KR": 1.8, "AU": 1.7, "MX": 1.6,
    "ES": 1.6, "ID": 1.4, "NL": 1.1, "SA": 1.1, "TR": 1.1, "CH": 1.0, "PL": 0.85,
    "TW": 0.8, "SE": 0.66, "BE": 0.63, "AR": 0.6, "IE": 0.55, "TH": 0.53, "IL": 0.52,
    "AT": 0.52, "NO": 0.5, "SG": 0.5, "PH": 0.47, "BD": 0.46, "VN": 0.44, "MY": 0.43,
    "DK": 0.43, "AE": 0.5, "ZA": 0.4, "EG": 0.4, "HK": 0.4, "PK": 0.37, "RO": 0.35,
    "CZ": 0.33, "CL": 0.3, "FI": 0.3, "PT": 0.29, "NZ": 0.26, "GR": 0.24, "HU": 0.2,
    "SK": 0.13, "LU": 0.06,
    "EP": 11.3,  # DE+FR+GB 근사
    "WO": 0.0,
}
_GNI_DEFAULT = 0.1  # 목록에 없는 국가의 기본 GNI (조 USD)


def _mc_from_country_list(series):
    """패밀리 국가 목록 → GNI 가중 Market Coverage (US=1). 목록 없으면 NaN."""
    us = _GNI_TRILLION["US"]

    def one(value):
        countries = parse_multiclass_cell(value)
        codes = set()
        for c in countries:
            code = str(c).strip().upper()[:2]
            if code.isalpha():
                codes.add(code)
        if not codes:
            return np.nan
        return sum(_GNI_TRILLION.get(code, _GNI_DEFAULT) for code in codes) / us

    return series.map(one)


def compute_portfolio_index(df, settings):
    """Patent Asset Index 방법론(Ernst & Omland 2011) 기반 포트폴리오 지표 계산."""
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

    # --- TR: 출원연도 × 기술분야 코호트 정규화 (공개 방법론과 동일 구조) ---
    years = work["_base_year"]
    field = work["_tech_list"].map(lambda lst: lst[0] if lst else None) \
        if "_tech_list" in work.columns else pd.Series([None] * len(work), index=work.index)
    global_mean = float(cites.mean()) or 0.0
    cohort_mean = pd.Series(global_mean, index=work.index)
    tr_source = "전체 평균 정규화"
    if years.notna().any():
        by_year = cites.groupby(years).transform("mean")
        cohort_mean = by_year.where(by_year > 0).fillna(cohort_mean)
        tr_source = "출원연도 코호트 정규화"
        if field.notna().any():
            grp = [years, field]
            by_yf = cites.groupby(grp).transform("mean")
            size_yf = cites.groupby(grp).transform("size")
            fine = by_yf.where((by_yf > 0) & (size_yf >= 5))
            cohort_mean = fine.fillna(cohort_mean)
            tr_source = "출원연도 × 기술분야 코호트 정규화 (표본<5 셀은 연도 코호트)"
    tr = (cites / cohort_mean.replace(0, np.nan)).fillna(0.0)

    # --- MC: GNI 가중 (공개 방법론) → 국가 수 → 패밀리 수 → 1.0 폴백 ---
    mc, mc_source, mc_exact = None, None, False
    if "family_countries" in work.columns:
        mc_gni = _mc_from_country_list(work["family_countries"])
        if mc_gni.notna().any():
            fill = float(mc_gni.median())
            mc = mc_gni.fillna(fill)
            mc_source = "패밀리 국가 목록 × GNI 가중 (US=1, 공개 방법론)"
            mc_exact = True
    if mc is None and "family_country_count" in work.columns \
            and work["family_country_count"].notna().any():
        fam = work["family_country_count"].fillna(0).astype(float)
        fam_mean = float(fam.mean()) or 1.0
        mc = fam / fam_mean
        mc_source = "패밀리 국가 수 / 전체 평균 (GNI 가중 불가 — 국가 목록 미매핑 근사)"
    if mc is None and "family_size" in work.columns and work["family_size"].notna().any():
        fam = work["family_size"].fillna(0).astype(float)
        fam_mean = float(fam.mean()) or 1.0
        mc = fam / fam_mean
        mc_source = "패밀리 수 / 전체 평균 (국가 정보 부재 근사)"
    if mc is None:
        mc = pd.Series(1.0, index=work.index)
        mc_source = "미가용 (MC=1 고정)"
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

    has_family = "family_id" in scoped.columns and scoped["family_id"].notna().any()
    rows = []
    for company, grp in scoped.groupby("applicant_display"):
        n = len(grp)
        if n < min_n:
            continue
        pai = float(grp["_ci"].sum())
        families = int(grp["family_id"].astype(str).nunique()) if has_family else n
        all_grp = work[work["applicant_display"] == company]
        yrs = all_grp["_base_year"].dropna().astype(int)
        growth, _ = (robust_growth(year_counts(yrs), recent_years=recent)
                     if len(yrs) else (None, "n/a"))
        rows.append({"company": str(company), "n": n, "families": families,
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
        title="Patent Asset Index (PAI 유사) 순위 — %s 기준" % scope_label,
        orientation="h", x_title="Patent Asset Index (Σ Competitive Impact)",
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
                        "m": {"n": r["n"], "families": r["families"],
                              "avg_ci": r["avg_ci"],
                              "portfolio_index": r["portfolio_index"],
                              "avg_tr": r["avg_tr"], "avg_mc": r["avg_mc"],
                              "growth": r["growth"]}} for r in shown],
        "marker": {"size": sizes, "sizemode": "area",
                   "sizeref": 2.0 * smax / (42 ** 2), "sizemin": 6,
                   "color": [r["growth"] if r["growth"] is not None else 0 for r in shown],
                   "colorscale": RDYLGN, "showscale": True,
                   "colorbar": {"title": "최근 성장률", "thickness": 12},
                   "line": {"width": 1, "color": "#333"}, "opacity": 0.85},
    }], "layout": base_layout(
        "포트폴리오 규모 vs 질 (크기=Portfolio Index)",
        xaxis={"title": "%s 수 (규모)" % scope_label},
        yaxis={"title": "평균 Competitive Impact (질)"})}

    # ②-b 요청 사양 버블: X=특허 패밀리 건수, Y=평균 Competitive Impact,
    #      크기=패밀리 건수(화면 최적화 스케일), 라벨=출원인, 색=평균 MC
    fam_sizes = [max(r["families"], 1) for r in shown]
    fmax = max(fam_sizes)
    family_bubble = {"data": [{
        "type": "scatter", "mode": "markers+text",
        "x": [r["families"] for r in shown], "y": [r["avg_ci"] for r in shown],
        "text": [r["company"][:12] for r in shown], "textposition": "top center",
        "textfont": {"size": 10, "color": "#2b445c"},
        "hovertext": ["<b>%s</b><br>패밀리 %s건 / 평균 CI %s<br>PAI %s / TR %s / MC %s"
                      % (r["company"], fmt_num(r["families"]), r["avg_ci"],
                         fmt_num(r["portfolio_index"]), r["avg_tr"], r["avg_mc"])
                      for r in shown],
        "hoverinfo": "text",
        "customdata": [{"drill": r["drill"],
                        "m": {"families": r["families"], "n": r["n"],
                              "avg_ci": r["avg_ci"],
                              "portfolio_index": r["portfolio_index"],
                              "avg_tr": r["avg_tr"], "avg_mc": r["avg_mc"],
                              "growth": r["growth"]}} for r in shown],
        "marker": {"size": fam_sizes, "sizemode": "area",
                   "sizeref": 2.0 * fmax / (46 ** 2), "sizemin": 9,
                   "color": [r["avg_mc"] for r in shown],
                   "colorscale": "Blues", "showscale": True,
                   "colorbar": {"title": "평균 MC", "thickness": 12},
                   "line": {"width": 1, "color": "#33506a"}, "opacity": 0.88},
    }], "layout": base_layout(
        "기업별 패밀리 규모 × Competitive Impact (크기=패밀리 건수)",
        xaxis={"title": "특허 패밀리 건수"},
        yaxis={"title": "평균 Competitive Impact (CI)"})}

    # ②-c Market Coverage 차트: 기업별 평균 MC 막대
    mc_sorted = sorted(shown, key=lambda r: -r["avg_mc"])[:top_n]
    fig_mc = bar_chart(
        [r["company"] for r in mc_sorted][::-1],
        [r["avg_mc"] for r in mc_sorted][::-1],
        title="Market Coverage (평균 MC — %s 표준화)" % mc_source, orientation="h",
        x_title="평균 Market Coverage (1.0 = 전체 평균)",
        hovertext=["%s — 평균 MC %s / 패밀리 %s건 / PAI %s"
                   % (r["company"], r["avg_mc"], fmt_num(r["families"]),
                      fmt_num(r["portfolio_index"])) for r in mc_sorted][::-1],
        customdata=[{"drill": r["drill"]} for r in mc_sorted][::-1])

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
                                   title="기업별 연도 CI 추이 (상위 5개사)",
                                   year_axis=True)

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

    # 지표 정의표 (프론트가 차트 옆에 체계적으로 표시)
    definitions = [
        {"code": "TR", "name": "Technology Relevance (기술 영향력)",
         "definition": "특허가 후속 기술 개발에 미친 영향력 — 전 세계 피인용 수 기반",
         "formula": "TR = 피인용 수 ÷ 평균 피인용(동일 출원연도 × 동일 기술분야 코호트)",
         "basis": "이번 계산: " + tr_source,
         "reading": "1.0 = 같은 시기·같은 분야 특허의 평균 수준. 2.0 이면 평균의 2배로 "
                    "인용되는 영향력 큰 특허. 연령·분야를 보정하므로 오래된 특허와 최신 "
                    "특허를 공정하게 비교할 수 있습니다."},
        {"code": "MC", "name": "Market Coverage (시장 커버리지)",
         "definition": "특허 패밀리가 권리를 확보한 국가들의 시장 규모 합",
         "formula": "MC = Σ GNI(보호국) ÷ GNI(미국)  — 미국에서만 보호 시 1.0",
         "basis": "이번 계산: " + mc_source,
         "reading": "1.0 = 미국 시장 규모와 같은 보호 범위. 미국+중국+유럽에서 보호되면 "
                    "약 2~3 수준. 값이 클수록 넓은 시장에서 권리를 확보한 특허입니다."},
        {"code": "CI", "name": "Competitive Impact (경쟁 임팩트)",
         "definition": "특허 1건의 질적 가치 — 기술 영향력과 시장 커버리지의 결합",
         "formula": "CI = TR × MC",
         "basis": "특허 단위로 계산 후 기업별 평균/합계로 집계",
         "reading": "1.0 = 평균적인 특허. 기술적으로 많이 인용되면서(TR↑) 넓은 시장에서 "
                    "보호되는(MC↑) 특허일수록 큽니다."},
        {"code": "PAI", "name": "Patent Asset Index (특허 자산 지수)",
         "definition": "포트폴리오 전체의 총 가치 — 유효특허 CI 의 합계",
         "formula": "PAI = Σ CI  (대상: %s)" % scope_label,
         "basis": "Ernst & Omland (2011, World Patent Information) 공개 방법론 구조",
         "reading": "양(특허 수)과 질(CI)을 동시에 반영한 총량 지표. 특허가 많아도 CI 가 "
                    "낮으면 PAI 는 크지 않습니다. 기업 간 상대 비교 용도로 사용하세요."},
    ]
    return ok_result({"rank": fig_rank, "bubble": bubble, "trend": fig_trend,
                      "family_bubble": family_bubble, "mc_bar": fig_mc,
                      "companies": shown, "top_patents": top_patents,
                      "scope": scope_label, "mc_source": mc_source,
                      "tr_source": tr_source, "definitions": definitions},
                     insight=insight,
                     meta={"note": ("공개 방법론(Ernst & Omland 2011)의 구조·정규화를 따라 "
                                    "계산했습니다 (TR: %s / MC: %s / 대상: %s). 상용 "
                                    "PatentSight 제품의 비공개 데이터 보정은 재현할 수 없어 "
                                    "절대값은 다를 수 있으며, 기업 간 상대 비교 용도로 "
                                    "사용하세요." % (tr_source, mc_source, scope_label))})
