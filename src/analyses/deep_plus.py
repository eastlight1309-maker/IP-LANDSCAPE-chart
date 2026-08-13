# -*- coding: utf-8 -*-
"""
analyses/deep_plus.py — WIPS 특수 필드 신호 6종 (Deep Plus).

섹션 (필요 컬럼 — 없으면 사유와 함께 생략, graceful degradation):
  ① license    실시권(라이선스) 신호 — 실시권 설정은 상업화의 직접 증거.
               기술별 라이선스율, 기업별 실시권 특허, 실시권 특허 질 비교.
               (실시권 설정 유무[KR] [+실시권자 수])
  ② sep        표준특허(SEP) 현황 — 표준화기구별 선언 건수, 선언 기업 순위,
               연도별 선언 추이. (표준화기구 [+표준번호, 선언일])
  ③ rejection  거절 사유 인텔리전스 — 거절사유 유형 분포(키워드 분류),
               기업별 거절결정률, 재심사청구율. (거절 사유/거절결정 여부/
               재심사청구 여부 중 1개 이상)
  ④ science    과학 연계성(Science Linkage) — 논문 등 비특허문헌(NPL) 인용이
               많은 기술 = 기초연구 기반. 기술·기업별 평균 NPL 인용.
               (비 특허 참고문헌 수(B1))
  ⑤ assignment 권리변동 타임라인 — 연도×양도유형 거래 추이, 최근 양수인/
               양도인 순위, 최근 거래 목록. 담보설정은 자금 사정 신호로
               읽힐 수 있음(관찰 신호). (최근 양도일 [+양수인/양도인/유형])
  ⑥ examiner   심사관 인텔리전스 — 심사관별 처리 건수·등록률·평균 OA.
               개인 실명 데이터이므로 내부 참고용으로만 (화면에 명시).
               (심사관 [+등록 여부, OA 횟수])

모든 수치는 매핑된 실제 데이터로만 계산하며 인과·법률 판단이 아니다.
"""
import numpy as np
import pandas as pd

from src.config import get_threshold, get_limit
from src.preprocessing import parse_bool, parse_numeric
from src.insights import build_insight, fmt_num, fmt_pct, period_label, \
    check_small_sample
from src.viz_payload import ok_result, empty_result, bar_chart, base_layout, \
    color_for

_DP_MIN_N = 3


def _dp_ids_of(sub, cap=200):
    col = "pub_number" if "pub_number" in sub.columns else \
        ("app_number" if "app_number" in sub.columns else None)
    return [str(v) for v in (sub[col] if col else sub.index)][:cap]


def _dp_primary_tech(df):
    return df["_tech_list"].map(lambda lst: lst[0] if lst else None) \
        if "_tech_list" in df.columns else pd.Series([None] * len(df),
                                                     index=df.index)


def _dp_nonempty(series):
    s = series.astype(str).str.strip()
    return ~s.str.lower().isin(["", "nan", "none", "-"])


# ---------------------------------------------------------------------------
# ① 실시권(라이선스) 신호
# ---------------------------------------------------------------------------
def _license_section(df, settings):
    if "license_flag" not in df.columns:
        return None, "실시권 설정 유무 컬럼 필요"
    flag = df["license_flag"].map(parse_bool)
    if not flag.notna().any():
        return None, "실시권 설정 유무 값 해석 불가 (유/무·Y/N 형식 필요)"
    lic = df[flag == True]  # noqa: E712
    n_lic = int(len(lic))
    if n_lic < _DP_MIN_N:
        return None, "실시권 설정 특허 부족 (%d건 — 최소 %d건)" % (n_lic, _DP_MIN_N)

    ratio = n_lic / float(flag.notna().sum())
    # 기술별 라이선스율
    fig_tech = None
    ptech_all = _dp_primary_tech(df[flag.notna()])
    ptech_lic = _dp_primary_tech(lic)
    if ptech_all.notna().any():
        tot = ptech_all.value_counts()
        licc = ptech_lic.value_counts()
        rows = [(str(t), int(licc.get(t, 0)), int(n), licc.get(t, 0) / float(n))
                for t, n in tot.items() if n >= 5 and licc.get(t, 0) > 0]
        rows.sort(key=lambda r: r[3])
        if rows:
            fig_tech = bar_chart(
                [r[0] for r in rows[-10:]], [round(r[3], 4) for r in rows[-10:]],
                title="기술분류별 라이선스율 — 실시권 설정은 상업화의 직접 증거 "
                      "(막대 클릭 → 실시권 특허)",
                orientation="h", x_title="라이선스율",
                hovertext=["%s — 실시권 %d건 / 전체 %d건 (%s)"
                           % (r[0], r[1], r[2], fmt_pct(r[3])) for r in rows[-10:]],
                customdata=[{"drill": {"type": "tech", "tech": r[0],
                                       "licensed": True}} for r in rows[-10:]])
            fig_tech["layout"]["xaxis"]["tickformat"] = ".0%"
    # 기업별 실시권 특허 수
    fig_comp = None
    comp = lic["applicant_display"].replace("", np.nan).dropna().value_counts().head(10)
    if len(comp):
        fig_comp = bar_chart(
            [str(c) for c in comp.index][::-1], [int(v) for v in comp.values][::-1],
            title="기업별 실시권 설정 특허 수 — 기술료 수익화가 확인된 포트폴리오",
            orientation="h", x_title="실시권 특허 수",
            customdata=[{"drill": {"applicant": str(c), "licensed": True}}
                        for c in comp.index][::-1])
    # 실시권 특허 질 비교
    quality = None
    if "cites_forward" in df.columns and df["cites_forward"].notna().any():
        lic_c = lic["cites_forward"].dropna()
        oth_c = df[flag == False]["cites_forward"].dropna()  # noqa: E712
        if len(lic_c) >= _DP_MIN_N and len(oth_c) >= _DP_MIN_N:
            quality = {"licensed_avg": round(float(lic_c.mean()), 2),
                       "other_avg": round(float(oth_c.mean()), 2)}
    # 실시권자 수 상위 특허
    top_rows = []
    sub = lic.copy()
    if "licensee_count" in sub.columns:
        sub["_lc"] = parse_numeric(sub["licensee_count"])
        sub = sub.sort_values("_lc", ascending=False)
    for _i, r in sub.head(15).iterrows():
        ids = _dp_ids_of(sub.loc[[_i]])
        top_rows.append({"id": ids[0] if ids else "-",
                         "title": str(r.get("title", ""))[:60],
                         "applicant": str(r.get("applicant_display", "")),
                         "tech": (r.get("_tech_list") or ["-"])[0],
                         "licensees": (int(r["_lc"]) if "_lc" in sub.columns
                                       and pd.notna(r.get("_lc")) else None),
                         "drill": {"type": "ids", "ids": ids}})
    return {"fig_tech": fig_tech, "fig_comp": fig_comp, "quality": quality,
            "rows": top_rows, "n_licensed": n_lic, "ratio": round(ratio, 4),
            "note": "실시권 설정 유무는 KR 등재 기준이며, 미설정이 '수요 없음'을 "
                    "뜻하지는 않습니다 (등재하지 않는 라이선스도 존재)."}, None


# ---------------------------------------------------------------------------
# ② 표준특허(SEP) 현황
# ---------------------------------------------------------------------------
def _sep_section(df, settings):
    if "sep_org" not in df.columns:
        return None, "표준화기구 컬럼 필요"
    has = _dp_nonempty(df["sep_org"])
    sep = df[has]
    if len(sep) < _DP_MIN_N:
        return None, "표준특허 선언 문헌 부족 (%d건 — 최소 %d건)" % (len(sep), _DP_MIN_N)
    org_counts = sep["sep_org"].astype(str).str.strip().value_counts().head(10)
    fig_org = bar_chart(
        [str(o) for o in org_counts.index][::-1],
        [int(v) for v in org_counts.values][::-1],
        title="표준화기구별 선언 특허 수 (SEP)", orientation="h", x_title="선언 특허 수")
    comp = sep["applicant_display"].replace("", np.nan).dropna().value_counts().head(10)
    fig_comp = None
    if len(comp):
        fig_comp = bar_chart(
            [str(c) for c in comp.index][::-1], [int(v) for v in comp.values][::-1],
            title="기업별 표준특허 선언 수 — 표준 협상력의 근거",
            orientation="h", x_title="선언 특허 수",
            customdata=[{"drill": {"applicant": str(c), "sep": True}}
                        for c in comp.index][::-1])
    fig_year = None
    if "sep_date" in sep.columns and sep["sep_date"].notna().any():
        yrs = sep["sep_date"].dt.year.dropna().astype(int)
        cnt = yrs.value_counts().sort_index()
        fig_year = bar_chart([int(y) for y in cnt.index],
                             [int(v) for v in cnt.values],
                             title="연도별 표준 선언 추이", x_title="선언 연도",
                             y_title="선언 수")
        fig_year["layout"]["xaxis"] = {"dtick": 1, "tickformat": "d",
                                       "title": "선언 연도"}
    rows = []
    for _i, r in sep.head(20).iterrows():
        ids = _dp_ids_of(sep.loc[[_i]])
        rows.append({"id": ids[0] if ids else "-",
                     "applicant": str(r.get("applicant_display", "")),
                     "org": str(r.get("sep_org", "")).strip(),
                     "std_no": str(r.get("sep_number", "") or "-").strip()[:30],
                     "declared": (str(r["sep_date"].date())
                                  if "sep_date" in sep.columns
                                  and pd.notna(r.get("sep_date")) else "-"),
                     "drill": {"type": "ids", "ids": ids}})
    return {"fig_org": fig_org, "fig_comp": fig_comp, "fig_year": fig_year,
            "rows": rows, "n_sep": int(len(sep)),
            "top_org": str(org_counts.index[0]),
            "note": "표준특허 '선언'은 자기 신고이며 필수성(essentiality)이 검증된 "
                    "것은 아닙니다."}, None


# ---------------------------------------------------------------------------
# ③ 거절 사유 인텔리전스
# ---------------------------------------------------------------------------
_REJECT_CATEGORIES = [
    ("진보성", ["진보성", "inventive step", "obvious"]),
    ("신규성", ["신규성", "novelty"]),
    ("기재불비", ["기재불비", "기재 불비", "명세서 기재", "clarity", "112"]),
    ("산업상 이용가능성", ["산업상", "industrial applicability"]),
    ("발명의 성립성", ["성립성", "eligible", "101"]),
    ("선출원/중복", ["선출원", "확대된 선원", "double patenting"]),
]


def _rejection_section(df, settings):
    has_reason = "rejection_reason" in df.columns and \
        _dp_nonempty(df["rejection_reason"]).any()
    has_flag = "rejection_flag" in df.columns and \
        df["rejection_flag"].map(parse_bool).notna().any()
    has_reexam = "reexam_flag" in df.columns and \
        df["reexam_flag"].map(parse_bool).notna().any()
    if not (has_reason or has_flag or has_reexam):
        return None, "거절 사유/거절결정 여부/재심사청구 여부 컬럼 중 1개 이상 필요"
    fig_reason, reason_counts = None, {}
    if has_reason:
        reasons = df.loc[_dp_nonempty(df["rejection_reason"]),
                         "rejection_reason"].astype(str)
        for cat, kws in _REJECT_CATEGORIES:
            n = int(reasons.str.lower().map(
                lambda t: any(k.lower() in t for k in kws)).sum())
            if n:
                reason_counts[cat] = n
        n_other = int(len(reasons)) - int(sum(reason_counts.values()))
        if n_other > 0:
            reason_counts["기타/미분류"] = n_other
        if reason_counts:
            items = sorted(reason_counts.items(), key=lambda kv: kv[1])
            fig_reason = bar_chart(
                [k for k, _v in items], [v for _k, v in items],
                title="거절 사유 유형 분포 — 어떤 벽에 부딪히고 있나 (키워드 분류)",
                orientation="h", x_title="건수")
    fig_comp = None
    comp_rows = []
    if has_flag:
        flag = df["rejection_flag"].map(parse_bool)
        base = df[flag.notna()]
        for comp, grp in base.groupby("applicant_display"):
            comp = str(comp).strip()
            if not comp or len(grp) < 5:
                continue
            rej = grp["rejection_flag"].map(parse_bool)
            comp_rows.append((comp, int((rej == True).sum()),  # noqa: E712
                              int(len(grp)),
                              float((rej == True).mean())))  # noqa: E712
        comp_rows.sort(key=lambda r: -r[3])
        comp_rows = comp_rows[:10]
        if comp_rows:
            fig_comp = bar_chart(
                [r[0] for r in comp_rows][::-1],
                [round(r[3], 4) for r in comp_rows][::-1],
                title="기업별 거절결정률 — 높으면 청구항 전략 재점검 신호",
                orientation="h", x_title="거절결정률",
                hovertext=["%s — 거절결정 %d건 / %d건 (%s)"
                           % (r[0], r[1], r[2], fmt_pct(r[3]))
                           for r in comp_rows][::-1],
                customdata=[{"drill": {"applicant": r[0]}}
                            for r in comp_rows][::-1])
            fig_comp["layout"]["xaxis"]["tickformat"] = ".0%"
    reexam_rate = None
    if has_reexam:
        rx = df["reexam_flag"].map(parse_bool)
        if rx.notna().any():
            reexam_rate = round(float((rx == True).mean()), 4)  # noqa: E712
    return {"fig_reason": fig_reason, "fig_comp": fig_comp,
            "reason_counts": reason_counts, "reexam_rate": reexam_rate,
            "note": "거절 사유 유형은 텍스트 키워드 기반 자동 분류이며, 하나의 "
                    "거절에 복수 사유가 있으면 중복 집계될 수 있습니다."}, None


# ---------------------------------------------------------------------------
# ④ 과학 연계성 (Science Linkage)
# ---------------------------------------------------------------------------
def _science_section(df, settings):
    if "npl_count" not in df.columns:
        return None, "비특허 참고문헌 수 컬럼 필요"
    npl = parse_numeric(df["npl_count"])
    if not npl.notna().any():
        return None, "비특허 참고문헌 수 값 해석 불가"
    work = df[npl.notna()].copy()
    work["_npl"] = npl[npl.notna()]
    avg_all = float(work["_npl"].mean())
    fig_tech = None
    ptech = _dp_primary_tech(work)
    if ptech.notna().any():
        by_tech = work.groupby(ptech)["_npl"].agg(["mean", "size"])
        by_tech = by_tech[by_tech["size"] >= 5].sort_values("mean")
        if len(by_tech):
            fig_tech = bar_chart(
                [str(t) for t in by_tech.index],
                [round(float(v), 2) for v in by_tech["mean"]],
                title="기술분류별 평균 NPL(논문 등) 인용 — 높을수록 기초연구 기반 신기술",
                orientation="h", x_title="평균 비특허문헌 인용 수",
                hovertext=["%s — 평균 %.1f건 (표본 %d)" % (t, m, n)
                           for t, m, n in zip(by_tech.index, by_tech["mean"],
                                              by_tech["size"])],
                # drill: 해당 분류에서 실제 NPL 을 인용한 특허만
                customdata=[{"drill": {"type": "tech", "tech": str(t), "tech_primary": True,
                                       "npl_cited": True}}
                            for t in by_tech.index])
    fig_comp = None
    comp_rows = []
    grp = work[work["applicant_display"].astype(str) != ""] \
        .groupby("applicant_display")["_npl"]
    by_comp = grp.agg(["mean", "size"])
    by_comp["cited"] = grp.apply(lambda s: int((s > 0).sum()))
    by_comp = by_comp[by_comp["size"] >= 5].sort_values("mean").tail(10)
    if len(by_comp):
        fig_comp = bar_chart(
            [str(c) for c in by_comp.index],
            [round(float(v), 2) for v in by_comp["mean"]],
            title="기업별 과학 근접도 — 평균 NPL 인용 (원천 연구형 vs 응용형)",
            orientation="h", x_title="평균 비특허문헌 인용 수",
            hovertext=["%s — 평균 %.1f건 (표본 %d건 중 NPL 인용 %d건)"
                       % (c, m, n, cn)
                       for c, m, n, cn in zip(by_comp.index, by_comp["mean"],
                                              by_comp["size"], by_comp["cited"])],
            # drill: 그 회사(공동출원 포함)의 NPL 인용 특허만
            customdata=[{"drill": {"applicant": str(c), "applicant_scope": "any",
                                   "npl_cited": True}} for c in by_comp.index])
        comp_rows = [{"company": str(c), "mean_npl": round(float(m), 2),
                      "n": int(n), "n_cited": int(cn)}
                     for c, m, n, cn in zip(by_comp.index, by_comp["mean"],
                                            by_comp["size"], by_comp["cited"])]
    top = work.sort_values("_npl", ascending=False).head(15)
    rows = []
    for _i, r in top.iterrows():
        ids = _dp_ids_of(top.loc[[_i]])
        rows.append({"id": ids[0] if ids else "-",
                     "title": str(r.get("title", ""))[:60],
                     "applicant": str(r.get("applicant_display", "")),
                     "tech": (r.get("_tech_list") or ["-"])[0],
                     "npl": int(r["_npl"]),
                     "drill": {"type": "ids", "ids": ids}})
    return {"fig_tech": fig_tech, "fig_comp": fig_comp, "rows": rows,
            "by_comp": comp_rows,
            "avg_all": round(avg_all, 2),
            "note": "NPL 인용 수는 과학 연계성(science linkage)의 프록시입니다 — "
                    "높다고 반드시 가치가 큰 것은 아니며 분야별 관행 차이가 "
                    "있습니다."}, None


# ---------------------------------------------------------------------------
# ⑤ 권리변동 타임라인
# ---------------------------------------------------------------------------
def _assignment_section(df, settings):
    if "assign_date" not in df.columns or not df["assign_date"].notna().any():
        return None, "최근 양도일 컬럼 필요"
    sub = df[df["assign_date"].notna()].copy()
    if len(sub) < _DP_MIN_N:
        return None, "양도 기록 부족 (%d건 — 최소 %d건)" % (len(sub), _DP_MIN_N)
    sub["_ay"] = sub["assign_date"].dt.year.astype(int)
    years = sorted(sub["_ay"].unique())
    has_type = "assign_type" in sub.columns and _dp_nonempty(sub["assign_type"]).any()
    traces = []
    color_reg = {}
    if has_type:
        types = sub["assign_type"].astype(str).str.strip().replace("", "미상")
        for tname in types.value_counts().head(6).index:
            g = sub[types == tname]
            cnt = g.groupby("_ay").size()
            traces.append({"type": "bar", "name": str(tname)[:16],
                           "x": years,
                           "y": [int(cnt.get(y, 0)) for y in years],
                           "marker": {"color": color_for(str(tname), color_reg)}})
    else:
        cnt = sub.groupby("_ay").size()
        traces.append({"type": "bar", "name": "권리변동",
                       "x": years, "y": [int(cnt.get(y, 0)) for y in years]})
    fig_year = {"data": traces, "layout": base_layout(
        "연도별 권리변동(양도) 추이" + (" — 유형별 적층" if has_type else ""),
        barmode="stack",
        xaxis={"title": "양도 연도", "dtick": 1, "tickformat": "d"},
        yaxis={"title": "건수"})}
    fig_buyers = None
    if "recent_assignee" in sub.columns and _dp_nonempty(sub["recent_assignee"]).any():
        buyers = sub.loc[_dp_nonempty(sub["recent_assignee"]), "recent_assignee"] \
            .astype(str).str.strip().value_counts().head(10)
        fig_buyers = bar_chart(
            [str(b) for b in buyers.index][::-1],
            [int(v) for v in buyers.values][::-1],
            title="최근 양수인 Top — 누가 특허를 사들이고 있나",
            orientation="h", x_title="양수 건수")
    rows = []
    for _i, r in sub.sort_values("assign_date", ascending=False).head(20).iterrows():
        ids = _dp_ids_of(sub.loc[[_i]])
        rows.append({"id": ids[0] if ids else "-",
                     "date": str(r["assign_date"].date()),
                     "assignor": str(r.get("recent_assignor", "") or "-").strip()[:24],
                     "assignee": str(r.get("recent_assignee", "") or "-").strip()[:24],
                     "type": str(r.get("assign_type", "") or "-").strip()[:16],
                     "tech": (r.get("_tech_list") or ["-"])[0],
                     "drill": {"type": "ids", "ids": ids}})
    type_note = ""
    if has_type:
        tv = sub["assign_type"].astype(str)
        n_sec = int(tv.str.contains("담보|security", case=False).sum())
        if n_sec:
            type_note = " 담보설정 %d건이 포함되어 있습니다 — 자금 조달 활동의 관찰 신호입니다." % n_sec
    return {"fig_year": fig_year, "fig_buyers": fig_buyers, "rows": rows,
            "n_assign": int(len(sub)),
            "note": "'최근' 양도 정보만 제공되는 WIPS 필드 특성상 과거 전체 거래 "
                    "이력은 아닙니다.%s" % type_note}, None


# ---------------------------------------------------------------------------
# ⑥ 심사관 인텔리전스
# ---------------------------------------------------------------------------
def _examiner_section(df, settings):
    if "examiner" not in df.columns or not _dp_nonempty(df["examiner"]).any():
        return None, "심사관 컬럼 필요"
    sub = df[_dp_nonempty(df["examiner"])].copy()
    sub["_ex"] = sub["examiner"].astype(str).str.strip()
    counts = sub["_ex"].value_counts()
    top = counts[counts >= 5].head(12)
    if not len(top):
        return None, "심사관별 표본 부족 (5건 이상 담당 심사관 없음)"
    rows = []
    for ex in top.index:
        g = sub[sub["_ex"] == ex]
        grant = None
        if "_is_granted_bool" in g.columns:
            known = g["_is_granted_bool"].map(lambda v: v is not None)
            if known.any():
                grant = float(g.loc[known, "_is_granted_bool"]
                              .map(lambda v: v is True).mean())
        oa = None
        if "oa_count" in g.columns:
            oav = parse_numeric(g["oa_count"]).dropna()
            if len(oav):
                oa = float(oav.mean())
        rows.append({"examiner": str(ex), "n": int(top[ex]),
                     "grant_rate": (round(grant, 3) if grant is not None else None),
                     "avg_oa": (round(oa, 2) if oa is not None else None)})
    fig = bar_chart(
        [r["examiner"] for r in rows][::-1], [r["n"] for r in rows][::-1],
        title="심사관별 담당 건수 (본 데이터셋 내, 5건 이상)",
        orientation="h", x_title="담당 건수",
        hovertext=["%s — %d건%s%s"
                   % (r["examiner"], r["n"],
                      (" · 등록률 %s" % fmt_pct(r["grant_rate"]))
                      if r["grant_rate"] is not None else "",
                      (" · 평균 OA %.1f회" % r["avg_oa"])
                      if r["avg_oa"] is not None else "") for r in rows][::-1])
    return {"fig": fig, "rows": rows, "n_examiners": int(len(counts)),
            "note": "⚠ 심사관은 개인 실명 정보입니다 — 내부 참고용으로만 사용하고 "
                    "외부 공유·평가 목적 사용은 삼가세요. 등록률·OA 는 이 데이터셋 "
                    "표본 기준이라 심사관의 전체 성향과 다를 수 있습니다."}, None


# ---------------------------------------------------------------------------
# 통합
# ---------------------------------------------------------------------------
_DP_SECTIONS = (("license", _license_section), ("sep", _sep_section),
                ("rejection", _rejection_section), ("science", _science_section),
                ("assignment", _assignment_section),
                ("examiner", _examiner_section))

_DP_LABELS = {"license": "실시권(라이선스)", "sep": "표준특허",
              "rejection": "거절 사유", "science": "과학 연계성",
              "assignment": "권리변동", "examiner": "심사관"}


def compute_deep_plus(df, settings, only_sections=None, company=None):
    """특수 필드 신호 6종 계산 (섹션별 graceful degradation).

    company 지정 시 해당 출원인 문헌(공동출원 포함)만으로 계산한다.
    """
    if company:
        from src.analyses.common import applicant_mask
        df = df[applicant_mask(df, company, scope="any")]
        if not len(df):
            return empty_result("출원인 '%s'의 문헌이 없습니다 (공동출원 포함 검색)."
                                % company)
    if not len(df):
        return empty_result()
    wanted = set(only_sections) if only_sections else None
    sections, skipped = {}, []
    for key, fn in _DP_SECTIONS:
        if wanted is not None and key not in wanted:
            continue
        try:
            result, reason = fn(df, settings)
        except Exception as e:   # 개별 섹션 오류가 전체를 막지 않도록
            result, reason = None, "계산 오류: %s" % e
        if result is not None:
            sections[key] = result
        else:
            skipped.append({"section": key, "reason": reason})
    if not sections:
        details = " · ".join("%s: %s" % (_DP_LABELS.get(s["section"], s["section"]),
                                         s["reason"]) for s in skipped)
        return empty_result("이 화면의 섹션이 계산되지 못했습니다 — %s. Settings → "
                            "컬럼 매핑에서 위 컬럼을 매핑하면 활성화됩니다." % details)

    sentences, metrics = [], {}
    period = period_label(df)
    if "license" in sections:
        lc = sections["license"]
        q = lc.get("quality")
        sentences.append("%s 기준 %s(%s건)에 실시권이 설정되어 있습니다%s — 실시권 "
                         "설정은 기술료 수익화가 실제로 일어났다는 직접 증거입니다."
                         % (period, fmt_pct(lc["ratio"]), fmt_num(lc["n_licensed"]),
                            (", 실시권 특허의 평균 피인용(%s)은 일반 특허(%s) 대비 "
                             "차이를 보입니다" % (q["licensed_avg"], q["other_avg"]))
                            if q else ""))
        metrics["license_ratio"] = lc["ratio"]
    if "sep" in sections:
        sp = sections["sep"]
        sentences.append("표준특허 선언 %s건이 확인되며 최다 선언 기구는 '%s'입니다 "
                         "(선언은 자기 신고 — 필수성 검증 아님)."
                         % (fmt_num(sp["n_sep"]), sp["top_org"]))
    if "rejection" in sections:
        rj = sections["rejection"]
        if rj["reason_counts"]:
            top_reason = max(rj["reason_counts"], key=rj["reason_counts"].get)
            sentences.append("거절 사유 1위는 '%s'(%s건)입니다 — 출원 전 선행기술 "
                             "조사·청구항 설계에서 집중 보완할 지점입니다."
                             % (top_reason, fmt_num(rj["reason_counts"][top_reason])))
        if rj["reexam_rate"] is not None:
            sentences.append("재심사청구율은 %s입니다." % fmt_pct(rj["reexam_rate"]))
    if "science" in sections:
        sc = sections["science"]
        sentences.append("평균 비특허문헌(논문 등) 인용은 %s건입니다 — NPL 인용이 "
                         "많은 기술은 기초연구에 가까운 신기술 신호입니다."
                         % sc["avg_all"])
    if "assignment" in sections:
        am = sections["assignment"]
        sentences.append("권리변동(양도) 기록 %s건이 확인됩니다 — 거래가 몰린 "
                         "기술·시기가 시장에서 가치가 확인된 지점입니다."
                         % fmt_num(am["n_assign"]))
    if "examiner" in sections:
        ex = sections["examiner"]
        sentences.append("심사관 %s명이 확인됩니다 (개인 실명 정보 — 내부 참고용)."
                         % fmt_num(ex["n_examiners"]))
    if not sentences:
        sentences.append("%s 기준 특수 신호 %d개 섹션이 계산되었습니다."
                         % (period, len(sections)))
    insight = build_insight(sentences, metrics,
                            small_sample=check_small_sample(len(df), settings))
    return ok_result(
        {"sections": sections, "skipped": skipped},
        insight=insight,
        meta={"note": "실시권·표준선언·거절·NPL·양도·심사관 등 잘 활용되지 않는 "
                      "WIPS 특수 필드 기반 신호입니다. 모든 수치는 상관 관찰이며 "
                      "인과·법률 판단이 아닙니다."})
