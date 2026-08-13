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
import re as _re_mc

import numpy as np
import pandas as pd

from src.config import get_threshold, get_limit
from src.metrics import robust_growth, year_counts, safe_div
from src.preprocessing import parse_multiclass_cell
from src.insights import build_insight, fmt_num, fmt_pct, period_label, check_small_sample
from src.viz_payload import BLUES, RDYLGN, ok_result, empty_result, disabled_result, bar_chart, \
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


# 한글 국가명/특수 표기 → ISO 코드 (WIPS 국가 목록이 한글로 오는 경우)
_KO_COUNTRY = {
    "한국": "KR", "대한민국": "KR", "미국": "US", "일본": "JP", "중국": "CN",
    "유럽": "EP", "독일": "DE", "프랑스": "FR", "영국": "GB", "대만": "TW",
    "인도": "IN", "캐나다": "CA", "호주": "AU", "러시아": "RU", "브라질": "BR",
    "스페인": "ES", "이탈리아": "IT", "네덜란드": "NL", "스위스": "CH",
    "스웨덴": "SE", "멕시코": "MX", "인도네시아": "ID", "터키": "TR",
    "싱가포르": "SG", "홍콩": "HK", "이스라엘": "IL", "베트남": "VN", "태국": "TH",
    "PCT": "WO", "국제": "WO", "기타": "XX",   # XX: 미상국 — 기본 GNI 적용
}
_CODE_RE = _re_mc.compile(r"\b([A-Za-z]{2})\b")
# 토큰 끝의 건수 표기: '한국-1', '미국 - 0', 'US(2)', 'JP: 3', 'KR 3'
_COUNT_SUFFIX_RE = _re_mc.compile(r"[\s\-–—:(]+(\d+)\s*\)?\s*$")


def _country_codes_of(value):
    """국가 목록 셀 → 문헌을 실제 보유한 국가의 ISO 코드 집합.

    처리 형식 (WIPS '패밀리 개별국 문헌 수' 등):
      '한국-1 | 미국-0 | 일본-1 | EP-0 | PCT-1 | 기타-1'  ← 건수 0 국가는 제외
      'KR 3 | US 2', 'US(2); JP(1)', 'KR;US;JP', '한국(3), 미국(2)'
    건수 표기가 없으면 나열 자체를 보유로 간주. 숫자만 있는 토큰은 무시."""
    codes = set()
    for token in parse_multiclass_cell(value):
        t = str(token).strip()
        if not t:
            continue
        m_cnt = _COUNT_SUFFIX_RE.search(t)
        if m_cnt:
            if int(m_cnt.group(1)) <= 0:   # '미국-0' = 해당국 문헌 없음 → 제외
                continue
            t = t[:m_cnt.start()].strip()
        if not t:
            continue
        base = t.upper()
        matched = None
        for name, code in _KO_COUNTRY.items():
            if name.upper() in base:
                matched = code
                break
        if matched is None:
            m = _CODE_RE.search(t)
            if m:
                matched = m.group(1).upper()
        if matched:
            codes.add(matched)
    return codes


def _mc_from_country_list(series):
    """패밀리 국가 목록 → GNI 가중 Market Coverage (US=1). 목록 없으면 NaN.

    공개 방법론(Ernst & Omland 2011): MC_i = Σ_j GNI(보호국 j) / GNI(US)."""
    us = _GNI_TRILLION["US"]

    def one(value):
        codes = _country_codes_of(value)
        if not codes:
            return np.nan
        return sum(_GNI_TRILLION.get(code, _GNI_DEFAULT) for code in codes) / us

    return series.map(one)


def compute_portfolio_index(df, settings, companies=None):
    """Patent Asset Index 방법론(Ernst & Omland 2011) 기반 포트폴리오 지표 계산.

    companies 지정 시 순위·버블·추이·CI 상위 특허를 그 회사들만으로 표시한다.
    지표 값 자체(TR 코호트·MC)는 전체 데이터 기준으로 계산되어 비교 가능하다.
    """
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

    # --- TR: 공식 방법론 코호트 = 최초 공개연도 × IPC 4자리 ---
    # TR_i = NFC_i / mean(NFC of 동일 공개연도·동일 IPC4 코호트).
    # 특허청별 인용 보정가중치(w_o)는 비공개라 모든 인용을 동일 가중(1)으로 집계.
    if "pub_date" in work.columns and work["pub_date"].notna().any():
        years = work["pub_date"].dt.year.fillna(work["_base_year"])
        tr_year_src = "최초 공개연도"
    else:
        years = work["_base_year"]
        tr_year_src = "출원연도 (공개일 미매핑)"
    field = pd.Series([None] * len(work), index=work.index)
    tr_field_src = "기술분야 정보 없음"
    if "ipc" in work.columns and work["ipc"].notna().any():
        # 공식과 동일하게 IPC 4자리(서브클래스, 예: H01L) 기준
        field = work["ipc"].map(
            lambda v: (parse_multiclass_cell(v) or [None])[0]).map(
            lambda c: str(c).replace(" ", "")[:4].upper() if c else None)
        if field.notna().any():
            tr_field_src = "IPC 4자리 (공식 기준)"
    if not field.notna().any() and "_tech_list" in work.columns:
        field = work["_tech_list"].map(lambda lst: lst[0] if lst else None)
        if field.notna().any():
            tr_field_src = "내부 기술분류 (IPC 미매핑 — 대체)"
    global_mean = float(cites.mean()) or 0.0
    cohort_mean = pd.Series(global_mean, index=work.index)
    tr_source = "전체 평균 정규화"
    if years.notna().any():
        by_year = cites.groupby(years).transform("mean")
        cohort_mean = by_year.where(by_year > 0).fillna(cohort_mean)
        tr_source = "%s 코호트" % tr_year_src
        if field.notna().any():
            grp = [years, field]
            by_yf = cites.groupby(grp).transform("mean")
            size_yf = cites.groupby(grp).transform("size")
            fine = by_yf.where((by_yf > 0) & (size_yf >= 5))
            cohort_mean = fine.fillna(cohort_mean)
            tr_source = "%s × %s 코호트 (표본<5 셀은 연도 코호트)" \
                % (tr_year_src, tr_field_src)
    tr = (cites / cohort_mean.replace(0, np.nan)).fillna(0.0)

    # --- MC: GNI 가중 (공개 방법론) → 국가 수 → 패밀리 수 → 1.0 폴백 ---
    mc, mc_source, mc_exact = None, None, False
    if "family_countries" in work.columns:
        mc_gni = _mc_from_country_list(work["family_countries"])
        # 파싱 성공률이 낮으면(30% 미만) 형식이 국가 목록이 아닌 것 — 폴백 사용
        if float(mc_gni.notna().mean()) >= 0.3:
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
    # 공식 상태 가중 s_c: 등록·존속=1.0 / 계류 출원=0.7 / 활성 권리 없음=0.
    # WIPS 국가 목록에는 국가별 법적상태가 없어, 패밀리(문헌)의 법적상태를
    # 전체 국가에 일괄 적용하는 근사를 사용한다.
    status_note = ""
    if "legal_status_norm" in work.columns and \
            (work["legal_status_norm"] != "Unknown").any():
        status_w = work["legal_status_norm"].map(
            {"Granted-Active": 1.0, "Pending": 0.7}).fillna(0.0)
        status_w = status_w.where(work["legal_status_norm"] != "Unknown", 1.0)
        mc = mc * status_w
        status_note = " × 상태 가중(등록·존속 1.0 / 계류 0.7 / 소멸 0)"
    mc_source += status_note
    # 값이 사실상 하나뿐이면(예: 전 문헌이 KR 단일국 패밀리) 그 사실을 명시 —
    # "모든 기업 MC 동일" 이 계산 오류가 아니라 데이터 특성임을 알 수 있게
    if float(pd.Series(mc).std() or 0.0) < 1e-9:
        mc_source += (" — 모든 문헌의 보호국 구성이 동일해 기업 간 MC 차이가 "
                      "없습니다 (예: 전부 단일국 패밀리)")
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
    comps_sel = [str(c) for c in (companies or []) if str(c).strip()]
    if comps_sel:
        wanted_set = set(comps_sel)
        shown = [r for r in rows if r["company"] in wanted_set]
        if not shown:
            return empty_result("선택한 출원인(%s) 중 최소 표본(%d건) 이상인 회사가 "
                                "없습니다." % (", ".join(comps_sel[:5]), int(min_n)))
        scoped = scoped[scoped["applicant_display"].astype(str).isin(wanted_set)]
    else:
        shown = rows[:30]

    # ① PI 순위 막대
    top_bar = shown[:top_n]
    fig_rank = bar_chart(
        [r["company"] for r in top_bar][::-1],
        [r["portfolio_index"] for r in top_bar][::-1],
        title="Patent Asset Index 순위 — %s 기준%s"
              % (scope_label, " · 선택 %d개사" % len(shown) if comps_sel else ""),
        orientation="h", x_title="Patent Asset Index (Σ Competitive Impact)",
        hovertext=["%s — PI %s / %s건 / 평균 CI %s (TR %s × MC %s)"
                   % (r["company"], fmt_num(r["portfolio_index"]), fmt_num(r["n"]),
                      r["avg_ci"], r["avg_tr"], r["avg_mc"]) for r in top_bar][::-1],
        customdata=[{"drill": r["drill"]} for r in top_bar][::-1])

    # ② 규모 vs 질 버블
    sizes = [max(r["portfolio_index"], 0.1) for r in shown]
    smax = max(sizes)
    bubble = {"data": [{
        "type": "scatter", "mode": "markers", "cliponaxis": False,
        "x": [r["n"] for r in shown], "y": [r["avg_ci"] for r in shown],
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
    # 회사명 라벨: 지시선 주석 (PI 상위 순, 겹침 회피)
    from src.viz_payload import leader_labels
    bubble["layout"].setdefault("annotations", [])
    bubble["layout"]["annotations"] += leader_labels(
        [{"x": r["n"], "y": r["avg_ci"], "text": r["company"][:12]}
         for r in shown[:14]], plot_h=460.0, box_w=0.15)

    # ②-b 요청 사양 버블: X=특허 패밀리 건수, Y=평균 Competitive Impact,
    #      크기=패밀리 건수(화면 최적화 스케일), 라벨=출원인, 색=평균 MC
    fam_sizes = [max(r["families"], 1) for r in shown]
    fmax = max(fam_sizes)
    family_bubble = {"data": [{
        "type": "scatter", "mode": "markers", "cliponaxis": False,
        "x": [r["families"] for r in shown], "y": [r["avg_ci"] for r in shown],
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
                   "colorscale": BLUES, "showscale": True,
                   "colorbar": {"title": "평균 MC", "thickness": 12},
                   "line": {"width": 1, "color": "#33506a"}, "opacity": 0.88},
    }], "layout": base_layout(
        "기업별 패밀리 규모 × Competitive Impact (크기=패밀리 건수)",
        xaxis={"title": "특허 패밀리 건수"},
        yaxis={"title": "평균 Competitive Impact (CI)"})}
    family_bubble["layout"].setdefault("annotations", [])
    family_bubble["layout"]["annotations"] += leader_labels(
        [{"x": r["families"], "y": r["avg_ci"], "text": r["company"][:12]}
         for r in shown[:14]], plot_h=460.0, box_w=0.15)

    # ②-c Market Coverage 차트: 기업별 평균 MC 막대
    mc_sorted = sorted(shown, key=lambda r: -r["avg_mc"])[:top_n]
    fig_mc = bar_chart(
        [r["company"] for r in mc_sorted][::-1],
        [r["avg_mc"] for r in mc_sorted][::-1],
        title="Market Coverage (평균 MC — %s 표준화)" % mc_source, orientation="h",
        x_title=("평균 Market Coverage (1.0 = 미국 단독 보호 수준)"
                 if "GNI" in str(mc_source) else
                 "평균 Market Coverage (1.0 = 전체 평균)"),
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

    # 지표 정의표 (프론트가 차트 옆에 체계적으로 표시) — 공식 수식 기준
    definitions = [
        {"code": "TR", "name": "Technology Relevance (기술 영향력)",
         "definition": "특허 패밀리가 받은 후속 인용(forward citation) 기반의 상대 "
                       "영향력 — 인용 관행·연령·기술분야를 보정한 지수",
         "formula": "TR_i = NFC_i ÷ 평균 NFC(동일 공개연도 × 동일 IPC4 코호트)  "
                    "(공식: NFC 는 특허청별 보정가중 합)",
         "basis": "이번 계산: " + tr_source,
         "reading": "1.0 = 같은 시기·같은 분야 특허의 평균 수준. 2.0 이면 평균의 2배로 "
                    "인용되는 영향력 큰 특허. 연령·분야를 보정하므로 오래된 특허와 최신 "
                    "특허를 공정하게 비교할 수 있습니다."},
        {"code": "MC", "name": "Market Coverage (시장 커버리지)",
         "definition": "특허 패밀리가 권리(등록·존속) 또는 출원(계류)으로 활성 상태인 "
                       "국가들의 시장 규모 합 (GNI 기준, 미국=1)",
         "formula": "MC_i = Σ_c [ GNI_c ÷ GNI_US × s_c ],  s_c: 등록·존속=1.0 / "
                    "계류 출원=0.7 / 활성 권리 없음=0",
         "basis": "이번 계산: " + mc_source,
         "reading": "1.0 = 미국에 등록·존속 특허만 있는 수준, 0.7 = 미국에 계류 출원만 "
                    "있는 수준. 미국+중국+유럽 등록이면 약 2~3. 값이 클수록 넓은 "
                    "시장에서 권리를 확보한 특허입니다."},
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
    # 공식 PatentSight 지수와 본 계산의 차이 (화면 하단 명시용)
    official_diff = [
        "특허청별 인용 보정가중치(w_o)는 비공개 계수라 적용하지 못했습니다 — 모든 "
        "인용을 동일 가중(1)으로 집계합니다. (공식: 인용 특허청별 가중 합)",
        "패밀리 간 중복 인용 제거(family-to-family dedup)는 재현 불가 — WIPS 의 "
        "피인용 문헌 수(F1)를 그대로 사용하며, '분석 단위=패밀리 대표' 선택 시 "
        "패밀리 대표 문헌 기준으로 근사됩니다.",
        "TR 코호트 — 공식: 최초 공개연도 × IPC 4자리 / 본 계산: %s." % tr_source,
        "MC 상태 가중 — 공식: '국가별' 등록·존속(1.0)/계류(0.7) 구분 / 본 계산: "
        "WIPS 국가 목록에 국가별 법적상태가 없어 문헌의 법적상태를 전체 국가에 "
        "일괄 적용합니다.",
        "계류 PCT/EP 의 잠재시장 가중(체약국 GNI 합 × 0.7)은 국별단계 진입 여부를 "
        "알 수 없어 미적용 (PCT 가중 0) — 공식 대비 보수적으로 낮게 나올 수 "
        "있습니다.",
        "GNI 는 World Bank 2023 근사표(고정)를 사용합니다 — 공식은 현재가격 GNI 를 "
        "연도별 갱신. 이런 차이로 절대값은 공식 지수와 다를 수 있으며, 기업 간 "
        "상대 비교 용도로 사용하세요.",
    ]
    return ok_result({"rank": fig_rank, "bubble": bubble, "trend": fig_trend,
                      "family_bubble": family_bubble, "mc_bar": fig_mc,
                      "companies": shown, "top_patents": top_patents,
                      "scope": scope_label, "mc_source": mc_source,
                      "tr_source": tr_source, "definitions": definitions,
                      "official_diff": official_diff},
                     insight=insight,
                     meta={"note": ("공개 방법론(Ernst & Omland 2011)의 구조·정규화를 따라 "
                                    "계산했습니다 (TR: %s / MC: %s / 대상: %s). 상용 "
                                    "PatentSight 제품의 비공개 데이터 보정은 재현할 수 없어 "
                                    "절대값은 다를 수 있으며, 기업 간 상대 비교 용도로 "
                                    "사용하세요." % (tr_source, mc_source, scope_label))})
