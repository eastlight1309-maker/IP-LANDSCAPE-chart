# -*- coding: utf-8 -*-
"""
analyses/wips_deep.py — 심층 시그널: 잘 활용되지 않는 WIPS 필드 기반 분석 9종.

설계 철학:
  일반 IP Landscape 보고서가 쓰는 "출원건수·출원인·기술분류" 축을 벗어나,
  WIPS Excel 이 제공하지만 대부분 무시되는 필드(연차료 소멸, 대리인, 심사이력,
  지정국 진입 시차, 분할출원, 도면 수, 심판 이력)를 주 축으로 쓴다.
  각 섹션은 필요한 컬럼이 없으면 사유와 함께 생략된다 (graceful degradation).

섹션 (필요 컬럼):
  ① survival     연차료 생존곡선 — 기업이 연차료를 포기하는 시점은 스스로 매긴
                 특허 가치평가. Kaplan-Meier 생존곡선(기술분류별) + 기업별 중위
                 생존연수. (등록일 + 소멸일; 유효특허는 관측 중단(censored) 처리)
  ② market_entry 지정국 진입 순서 — 우선일 이후 각국 진입 시차(개월).
                 기업×국가 평균 시차 히트맵 + 1순위 진입국. (패밀리 ID + 출원일
                 + 국가 [+우선일])
  ③ agent        대리인 전환 시그널 — 신규 대리인 등장·비중 급증 감지.
                 상관 신호이지 인과가 아니므로 "관찰된 변화"로만 표현. (대리인)
  ④ examiner_eye 심사관의 눈 — OA(심사관) 인용 vs 출원인 자발 인용 밀도 산점도.
                 대각선 위쪽(심사관≫자발)은 출원인들이 선행기술을 과소평가하는
                 영역 → 무효 리스크 신호. (심사관/출원인 인용문헌 수)
  ⑤ expedited    우선심사·조기공개 — 사업화 긴급도의 자기 신고. 기술×연도 버블
                 (크기=출원, 색=우선심사 비율) + 급등 영역. (우선심사 여부)
  ⑥ divisional   분할·계속출원 타이밍 — 기업별 분할출원 타임라인과 단기 집중
                 (버스트) 구간. 산업 이벤트 데이터가 없어 이벤트 정렬은 미지원
                 임을 명시. (원출원번호)
  ⑦ anomaly      심사 소요기간 이상탐지 — 분류별 분포(바이올린)에서 크게 벗어난
                 특허. 장기 심사 끝 등록 = 심사를 견딘 강한 권리 후보. (출원일/
                 심사청구일 + 등록일 [+OA 횟수])
  ⑧ disclosure   개시 충실도 — 도면 수·명세서 분량은 실제 개발 정도의 프록시.
                 대리인 작성 스타일이 섞이므로 데이터셋 내 상대비교 전용.
                 (도면 수 [+명세서 분량, 청구항 수])
  ⑨ trial        무효심판·이의 충돌 지도 — 심판 기록은 "누가 무엇을 진짜 위협
                 으로 봤는가"의 직접 증거. 청구인→권리자 방향성 네트워크.
                 (심판 이력 [+심판 청구인])

모든 수치는 매핑된 실제 데이터에서만 계산한다 (임의 값 생성 금지).
"""
import numpy as np
import pandas as pd

from src.config import get_threshold, get_limit
from src.preprocessing import parse_numeric, parse_bool, parse_multiclass_cell, \
    auto_standardize_name
from src.insights import build_insight, fmt_num, fmt_pct, period_label, \
    check_small_sample
from src.viz_payload import YLORRD, RDYLGN, PURPLES, ORRD, ok_result, empty_result, bar_chart, base_layout, \
    heatmap, cytoscape_network, color_for, PALETTE


def _primary_tech(df):
    return df["_tech_list"].map(lambda lst: lst[0] if lst else None)


def _count_like(series):
    """숫자 또는 '문헌번호 목록' 문자열 → 건수 시리즈.

    "KR101234567B1; KR10..." 같은 번호 목록에서 첫 숫자를 건수로 오인하지 않도록,
    값 전체가 순수 숫자("3", "12건")일 때만 숫자로 해석하고 그 외에는 구분자 기준
    항목 수를 센다.
    """
    s = series.astype(str).str.strip()
    nonempty = s[(s != "") & (~s.str.lower().isin(["nan", "none"]))]
    if len(nonempty) and float(nonempty.str.fullmatch(
            r"[+-]?\d{1,6}(\.\d+)?\s*(건|회|개)?").mean()) >= 0.5:
        return parse_numeric(series)
    return series.map(lambda v: float(len(parse_multiclass_cell(v)))
                      if str(v).strip() not in ("", "nan", "None") else np.nan)


def _ids_of(df):
    col = "pub_number" if "pub_number" in df.columns else \
        ("app_number" if "app_number" in df.columns else None)
    return df[col].astype(str) if col else df.index.astype(str).to_series(index=df.index)


# ---------------------------------------------------------------------------
# ① 연차료 생존곡선
# ---------------------------------------------------------------------------
def _km_curve(durations, events, t_max=21.0):
    """Kaplan-Meier product-limit 추정. 반환 (times, surv_probs) — 계단형."""
    order = np.argsort(durations)
    d = np.asarray(durations, dtype=float)[order]
    e = np.asarray(events, dtype=int)[order]
    n = len(d)
    at_risk, surv = n, 1.0
    times, probs = [0.0], [1.0]
    i = 0
    while i < n:
        t = d[i]
        deaths = removed = 0
        while i < n and d[i] == t:
            deaths += int(e[i])
            removed += 1
            i += 1
        if deaths and at_risk:
            surv *= 1.0 - deaths / float(at_risk)
            times.append(float(min(t, t_max)))
            probs.append(round(float(surv), 4))
        at_risk -= removed
    return times, probs


def _km_at(times, probs, t):
    s = 1.0
    for ti, pi in zip(times, probs):
        if ti <= t:
            s = pi
        else:
            break
    return s


def _km_median(times, probs):
    for ti, pi in zip(times, probs):
        if pi <= 0.5:
            return round(float(ti), 1)
    return None  # 관측 기간 내 중위 도달 못함 (장수 포트폴리오)


def _survival_section(df, settings):
    if "reg_date" not in df.columns or not df["reg_date"].notna().any():
        return None, "등록일 컬럼 필요"
    now = pd.Timestamp.now()
    sub = df[df["reg_date"].notna()].copy()
    lapse_basis = None
    if "lapse_date" in sub.columns and sub["lapse_date"].notna().any():
        lapse = sub["lapse_date"]
        lapse_basis = "소멸일 컬럼"
    elif "expiry_date" in sub.columns and sub["expiry_date"].notna().any() \
            and "legal_status_norm" in sub.columns:
        # 소멸일 미매핑 폴백: 권리가 이미 종료된 특허(소멸/포기/존속기간만료)의
        # '존속기간(예상)만료일'이 과거 날짜면 그 시점을 권리 종료일로 근사한다
        # (WIPS 는 소멸 특허의 (예상)만료일에 실제 종료 시점을 기록하는 경우가 많음).
        dead = sub["legal_status_norm"].isin(
            ["Lapsed", "Abandoned", "Granted-Expired"])
        past = sub["expiry_date"].notna() & (sub["expiry_date"] <= now)
        lapse = sub["expiry_date"].where(dead & past)
        if lapse.notna().sum() < 5:
            return None, ("소멸일 컬럼 필요 — 법적상태·만료일 기반 근사도 표본 부족 "
                          "(권리 종료 특허 5건 미만)")
        lapse_basis = ("법적상태(소멸·포기·만료) × 존속기간(예상)만료일 근사 — "
                       "소멸일 컬럼이 없어 권리 종료 특허의 (예상)만료일(과거)을 "
                       "종료 시점으로 사용")
    else:
        return None, ("소멸일 컬럼 필요 (또는 법적상태 + 존속기간(예상)만료일 매핑 시 "
                      "자동 근사 계산)")
    dur = np.where(lapse.notna(),
                   (lapse - sub["reg_date"]).dt.days / 365.25,
                   (now - sub["reg_date"]).dt.days / 365.25)
    event = np.where(lapse.notna(), 1, 0)
    ok_mask = (dur > 0) & (dur <= 25)
    sub, dur, event = sub[ok_mask], dur[ok_mask], event[ok_mask]
    if int(event.sum()) < 5:
        return None, "소멸(포기) 이벤트 표본 부족 (5건 미만)"
    sub = sub.reset_index(drop=True)
    sub["_dur"], sub["_event"] = dur, event
    sub["_ptech"] = _primary_tech(sub)

    min_n = max(10, int(get_threshold(settings, "min_class_patents")) * 3)
    tech_counts = sub["_ptech"].dropna().value_counts()
    top_techs = [t for t in tech_counts.index if tech_counts[t] >= min_n][:6]
    traces, tech_rows = [], []
    color_reg = {}
    for tech in top_techs:
        g = sub[sub["_ptech"] == tech]
        times, probs = _km_curve(g["_dur"], g["_event"])
        traces.append({"type": "scatter", "mode": "lines", "name": str(tech),
                       "x": times, "y": probs, "line": {"shape": "hv",
                       "color": color_for(str(tech), color_reg)},
                       "hovertemplate": str(tech) + " · %{x:.0f}년차 생존율 %{y:.0%}"
                                        "<extra></extra>"})
        tech_rows.append({
            "tech": str(tech), "n": int(len(g)),
            "surv_5y": round(_km_at(times, probs, 5.0), 3),
            "surv_10y": round(_km_at(times, probs, 10.0), 3),
            "surv_18y": round(_km_at(times, probs, 18.0), 3),
            "median": _km_median(times, probs),
            "drill": {"type": "tech", "tech": str(tech)}})
    if not traces:
        # 분류가 부족하면 전체 곡선 하나
        times, probs = _km_curve(sub["_dur"], sub["_event"])
        traces.append({"type": "scatter", "mode": "lines", "name": "전체",
                       "x": times, "y": probs, "line": {"shape": "hv"}})
    fig = {"data": traces, "layout": base_layout(
        "연차료 생존곡선 (Kaplan-Meier) — 기업 스스로 매긴 특허 가치",
        xaxis={"title": "등록 후 경과 (년)", "range": [0, 21], "dtick": 2},
        yaxis={"title": "권리 유지 비율", "range": [0, 1.02], "tickformat": ".0%"})}

    by_comp = []
    comp_counts = sub[sub["applicant_display"].astype(str) != ""] \
        ["applicant_display"].value_counts()
    for comp in [c for c in comp_counts.index if comp_counts[c] >= min_n][:10]:
        g = sub[sub["applicant_display"] == comp]
        times, probs = _km_curve(g["_dur"], g["_event"])
        med = _km_median(times, probs)
        by_comp.append((str(comp), med, int(len(g))))
    fig_comp = None
    if by_comp:
        plot_rows = [(c, (m if m is not None else 21.0), n) for c, m, n in by_comp]
        plot_rows.sort(key=lambda r: r[1])
        fig_comp = bar_chart(
            [r[0] for r in plot_rows], [round(r[1], 1) for r in plot_rows],
            title="기업별 중위 생존연수 (21=관측 기간 내 절반 미달 — 장수 포트폴리오)",
            orientation="h", x_title="중위 생존연수 (년)",
            hovertext=["%s — %s (표본 %d건)"
                       % (c, ("중위 %.1f년" % m2) if m2 < 21 else "관측 내 중위 미도달",
                          n) for c, m2, n in plot_rows],
            customdata=[{"drill": {"type": "applicant", "applicant": c}}
                        for c, _m, _n in plot_rows])
    n_events = int(sub["_event"].sum())
    return {"fig": fig, "fig_company": fig_comp, "techs": tech_rows,
            "n": int(len(sub)), "n_events": n_events,
            "note": "권리 종료 시점 기준: %s." % lapse_basis}, None


# ---------------------------------------------------------------------------
# ② 지정국 진입 시차
# ---------------------------------------------------------------------------
def _market_entry_section(df, settings):
    if "family_id" not in df.columns:
        return None, "패밀리 ID 컬럼 필요"
    if "app_date" not in df.columns or "country" not in df.columns:
        return None, "출원일·국가 컬럼 필요"
    sub = df[df["family_id"].astype(str).str.strip().ne("") & df["app_date"].notna()
             & df["country"].astype(str).str.strip().ne("")].copy()
    if not len(sub):
        return None, "패밀리·출원일·국가가 모두 있는 문헌 없음"
    base_col = "priority_date" if "priority_date" in sub.columns and \
        sub["priority_date"].notna().any() else "app_date"
    t0 = sub.groupby("family_id")[base_col].transform("min")
    t0 = t0.fillna(sub.groupby("family_id")["app_date"].transform("min"))
    sub["_lag_m"] = (sub["app_date"] - t0).dt.days / 30.44
    sub = sub[(sub["_lag_m"] >= 0) & (sub["_lag_m"] <= 120)]
    fam_sizes = sub.groupby("family_id")["country"].nunique()
    multi_fams = set(fam_sizes[fam_sizes >= 2].index)
    sub = sub[sub["family_id"].isin(multi_fams)]
    if len(sub) < 10:
        return None, ("복수 국가 진입 패밀리 부족 (10건 미만) — 단일국 출원 위주 "
                      "데이터이거나, 분석 단위가 '패밀리 대표'라서 구성 문헌이 제거된 "
                      "경우입니다. Settings → 분석 단위를 '문헌'으로 바꾸면 국가별 "
                      "진입 문헌이 보입니다")
    sub["_ctry"] = sub["country"].astype(str).str.upper().str.strip().str[:2]

    comp_counts = sub[sub["applicant_display"].astype(str) != ""] \
        ["applicant_display"].value_counts()
    top_comps = list(comp_counts.head(8).index)
    top_ctrys = list(sub["_ctry"].value_counts().head(8).index)
    z, hover = [], []
    for comp in top_comps:
        row_z, row_h = [], []
        g = sub[sub["applicant_display"] == comp]
        for ct in top_ctrys:
            v = g[g["_ctry"] == ct]["_lag_m"]
            if len(v) >= 3:
                row_z.append(round(float(v.mean()), 1))
                row_h.append("%s → %s: 평균 %.1f개월 (%d건)"
                             % (comp, ct, float(v.mean()), len(v)))
            else:
                row_z.append(None)
                row_h.append("%s → %s: 표본 부족" % (comp, ct))
        z.append(row_z)
        hover.append(row_h)
    fig = heatmap(z, top_ctrys, top_comps,
                  title="기업×국가 평균 진입 시차 (개월, 낮을수록 우선 베팅 시장)",
                  colorscale=YLORRD, hovertext=hover, colorbar_title="개월")

    # 1순위 진입국 + 최근 변화 (패밀리별 최소 시차 행 = 첫 진입 문헌)
    first_rows = []
    fam_grp = sub.loc[sub.groupby("family_id")["_lag_m"].idxmin()]
    recent_years = int(get_threshold(settings, "recent_years"))
    max_year = sub["_base_year"].dropna().max()
    for comp in top_comps:
        g = fam_grp[fam_grp["applicant_display"] == comp]
        if len(g) < 3:
            continue
        overall = g["_ctry"].value_counts()
        row = {"company": comp, "n_families": int(len(g)),
               "first_country": str(overall.index[0]),
               "first_share": round(float(overall.iloc[0] / len(g)), 3),
               "recent_first": None, "shifted": False}
        if max_year is not None and not np.isnan(max_year):
            rec = g[g["_base_year"] >= max_year - recent_years + 1]
            if len(rec) >= 3:
                rc = rec["_ctry"].value_counts()
                row["recent_first"] = str(rc.index[0])
                row["shifted"] = bool(rc.index[0] != overall.index[0])
        first_rows.append(row)
    return {"fig": fig, "first_entries": first_rows,
            "n_families": int(len(multi_fams))}, None


# ---------------------------------------------------------------------------
# ③ 대리인 전환 시그널
# ---------------------------------------------------------------------------
def _agent_section(df, settings):
    if "agent" not in df.columns:
        return None, "대리인 컬럼 필요 (WIPS '대리인'/'특허법인')"
    sub = df[df["agent"].astype(str).str.strip().ne("")
             & df["_base_year"].notna()
             & (df["applicant_display"].astype(str) != "")].copy()
    if len(sub) < 20:
        return None, "대리인·연도·출원인이 모두 있는 문헌 부족 (20건 미만)"
    sub["_agent"] = sub["agent"].astype(str).map(
        lambda v: parse_multiclass_cell(v)[0] if parse_multiclass_cell(v) else v.strip())
    sub["_y"] = sub["_base_year"].astype(int)
    top_comps = list(sub["applicant_display"].value_counts().head(8).index)
    years = sorted(sub["_y"].unique())
    z, hover, signals = [], [], []
    for comp in top_comps:
        g = sub[sub["applicant_display"] == comp]
        seen = set()
        row_z, row_h = [], []
        prev_main = None
        for y in years:
            gy = g[g["_y"] == y]
            if not len(gy):
                row_z.append(None)
                row_h.append("%s %d년: 출원 없음" % (comp, y))
                continue
            agents_y = gy["_agent"].value_counts()
            new_agents = [a for a in agents_y.index if a not in seen]
            new_share = float(agents_y[new_agents].sum() / len(gy)) if new_agents else 0.0
            row_z.append(round(new_share, 3))
            row_h.append("%s %d년: 출원 %d건, 신규 대리인 %s (비중 %s)"
                         % (comp, y, len(gy),
                            ", ".join(new_agents[:2]) or "없음", fmt_pct(new_share)))
            main = str(agents_y.index[0])
            if seen and new_agents and agents_y[new_agents].sum() >= 3 \
                    and new_share >= 0.25:
                techs = gy[gy["_agent"].isin(new_agents)]["_tech_list"] \
                    .map(lambda lst: lst[0] if lst else None).dropna()
                signals.append({
                    "company": comp, "year": int(y),
                    "new_agent": new_agents[0],
                    "share": round(new_share, 3),
                    "prior_main": prev_main or "-",
                    "tech": str(techs.value_counts().index[0]) if len(techs) else "-",
                    "n": int(agents_y[new_agents].sum())})
            seen |= set(agents_y.index)
            prev_main = main
        z.append(row_z)
        hover.append(row_h)
    fig = heatmap(z, [str(y) for y in years], top_comps,
                  title="기업×연도 신규 대리인 비중 (그 해 처음 쓰는 대리인의 출원 비중)",
                  colorscale=PURPLES, hovertext=hover, colorbar_title="신규 비중")
    signals.sort(key=lambda s: (-s["year"], -s["share"]))
    return {"fig": fig, "signals": signals[:15],
            "n_agents": int(sub["_agent"].nunique())}, None


# ---------------------------------------------------------------------------
# ④ 심사관의 눈 (OA 인용 vs 자발 인용)
# ---------------------------------------------------------------------------
def _examiner_eye_section(df, settings):
    if "examiner_citations" not in df.columns:
        return None, "심사관 인용문헌 컬럼 필요 (OA 인용)"
    ex = _count_like(df["examiner_citations"])
    if not ex.notna().any():
        return None, "심사관 인용문헌 값 해석 불가"
    has_apl = "applicant_citations" in df.columns
    apl = _count_like(df["applicant_citations"]) if has_apl else None
    sub = df.copy()
    sub["_ex"], sub["_ptech"] = ex, _primary_tech(df)
    if has_apl:
        sub["_apl"] = apl
    min_n = int(get_threshold(settings, "min_class_patents")) + 2
    rows = []
    for tech, g in sub[sub["_ptech"].notna() & sub["_ex"].notna()].groupby("_ptech"):
        if len(g) < min_n:
            continue
        rows.append({"tech": str(tech), "n": int(len(g)),
                     "examiner_avg": round(float(g["_ex"].mean()), 2),
                     "applicant_avg": round(float(g["_apl"].mean()), 2)
                     if has_apl and g.get("_apl") is not None
                     and g["_apl"].notna().any() else None,
                     "drill": {"type": "tech", "tech": str(tech)}})
    if not rows:
        return None, "기술분류별 표본 부족"
    if has_apl and any(r["applicant_avg"] is not None for r in rows):
        xs = [r["applicant_avg"] or 0 for r in rows]
        ys = [r["examiner_avg"] for r in rows]
        lim = max(max(xs), max(ys)) * 1.15 + 0.5
        risky = [r for r in rows if (r["applicant_avg"] or 0) * 1.8 < r["examiner_avg"]
                 and r["examiner_avg"] >= 2]
        fig = {"data": [
            {"type": "scatter", "mode": "lines", "x": [0, lim], "y": [0, lim],
             "line": {"dash": "dot", "color": "#8899aa"}, "hoverinfo": "skip",
             "showlegend": False},
            {"type": "scatter", "mode": "markers+text", "x": xs, "y": ys,
             "text": [r["tech"][:14] for r in rows], "textposition": "top center",
             "textfont": {"size": 9},
             "hovertext": ["%s — 심사관 평균 %.2f vs 자발 평균 %.2f (%d건)"
                           % (r["tech"], r["examiner_avg"], r["applicant_avg"] or 0,
                              r["n"]) for r in rows],
             "hoverinfo": "text",
             "customdata": [{"drill": r["drill"]} for r in rows],
             "marker": {"size": [max(10, min(40, 8 + np.sqrt(r["n"]) * 2))
                                 for r in rows],
                        "color": ["#E15759" if r in risky else "#4E79A7"
                                  for r in rows]}}],
            "layout": base_layout(
                "심사관의 눈 — OA 인용 vs 출원인 자발 인용 (대각선 위=선행기술 과소평가 영역)",
                xaxis={"title": "출원인 자발 인용 평균 (건)", "range": [0, lim]},
                yaxis={"title": "심사관(OA) 인용 평균 (건)", "range": [0, lim]})}
        return {"fig": fig, "rows": rows,
                "risky": [r["tech"] for r in risky]}, None
    rows.sort(key=lambda r: -r["examiner_avg"])
    fig = bar_chart([r["tech"] for r in rows][::-1],
                    [r["examiner_avg"] for r in rows][::-1],
                    title="기술분류별 심사관(OA) 인용 평균 — 높을수록 선행기술 밀집",
                    orientation="h", x_title="심사관 인용 평균 (건)",
                    customdata=[{"drill": r["drill"]} for r in rows][::-1])
    return {"fig": fig, "rows": rows, "risky": []}, None


# ---------------------------------------------------------------------------
# ⑤ 우선심사·조기공개 긴급도
# ---------------------------------------------------------------------------
def _expedited_section(df, settings):
    if "expedited_exam" not in df.columns:
        return None, "우선심사 여부 컬럼 필요"
    flag = df["expedited_exam"].map(parse_bool)
    if not any(v is True for v in flag):
        return None, "우선심사 값(Y) 없음"
    sub = df.copy()
    sub["_exp"] = [bool(v) if isinstance(v, (bool, np.bool_)) else None for v in flag]
    sub["_ptech"] = _primary_tech(sub)
    sub = sub[sub["_ptech"].notna() & sub["_base_year"].notna()
              & sub["_exp"].notna()]
    if len(sub) < 15:
        return None, "우선심사·연도·분류 표본 부족"
    sub["_y"] = sub["_base_year"].astype(int)
    top_techs = list(sub["_ptech"].value_counts().head(10).index)
    pts = {"x": [], "y": [], "size": [], "color": [], "hover": [], "custom": []}
    for (tech, y), g in sub[sub["_ptech"].isin(top_techs)].groupby(["_ptech", "_y"]):
        n = len(g)
        if n < 2:
            continue
        ratio = float(pd.Series([v is True for v in g["_exp"]]).mean())
        pts["x"].append(int(y))
        pts["y"].append(str(tech))
        pts["size"].append(float(max(8, min(42, 6 + 3 * np.sqrt(n)))))
        pts["color"].append(round(ratio, 3))
        pts["hover"].append("%s %d년: 출원 %d건, 우선심사 %s"
                            % (tech, y, n, fmt_pct(ratio)))
        pts["custom"].append({"drill": {"type": "tech", "tech": str(tech),
                                        "year": int(y)}})
    fig = {"data": [{"type": "scatter", "mode": "markers",
                     "x": pts["x"], "y": pts["y"],
                     "hovertext": pts["hover"], "hoverinfo": "text",
                     "customdata": pts["custom"],
                     "marker": {"size": pts["size"], "color": pts["color"],
                                "colorscale": ORRD, "cmin": 0, "cmax": 1,
                                "colorbar": {"title": "우선심사 비율",
                                             "thickness": 12},
                                "line": {"width": 0.5, "color": "#666"}}}],
            "layout": base_layout(
                "우선심사·조기공개로 본 사업화 긴급도 (크기=출원 수, 색=우선심사 비율)",
                xaxis={"title": "출원연도", "dtick": 1, "tickformat": "d"},
                yaxis={"title": "", "type": "category", "automargin": True},
                height=max(420, 120 + 34 * len(top_techs)))}
    # 급등 랭킹: 최근 vs 이전 비율 차
    recent_n = int(get_threshold(settings, "recent_years"))
    max_year = int(sub["_y"].max())
    surge = []
    for tech in top_techs:
        g = sub[sub["_ptech"] == tech]
        rec = g[g["_y"] >= max_year - recent_n + 1]
        old = g[g["_y"] < max_year - recent_n + 1]
        if len(rec) < 5:
            continue
        r_rec = float(pd.Series([v is True for v in rec["_exp"]]).mean())
        r_old = float(pd.Series([v is True for v in old["_exp"]]).mean()) \
            if len(old) >= 5 else 0.0
        surge.append({"tech": str(tech), "recent_ratio": round(r_rec, 3),
                      "prior_ratio": round(r_old, 3),
                      "delta": round(r_rec - r_old, 3),
                      "n_recent": int(len(rec)),
                      "drill": {"type": "tech", "tech": str(tech)}})
    surge.sort(key=lambda s: -s["delta"])
    return {"fig": fig, "surge": surge[:10],
            "overall_ratio": round(float(pd.Series(
                [v is True for v in sub["_exp"]]).mean()), 3)}, None


# ---------------------------------------------------------------------------
# ⑥ 분할·계속출원 타이밍
# ---------------------------------------------------------------------------
def _divisional_section(df, settings):
    if "parent_app_number" not in df.columns:
        return None, "원출원번호 컬럼 필요 (분할·계속출원 식별)"
    isdiv = df["parent_app_number"].astype(str).str.strip() \
        .map(lambda v: v not in ("", "nan", "None"))
    sub = df[isdiv & df["app_date"].notna()
             & (df["applicant_display"].astype(str) != "")].copy()
    if len(sub) < 5:
        return None, "분할·계속출원(원출원번호 보유) 문헌 부족 (5건 미만)"
    ids = _ids_of(sub)
    comp_counts = sub["applicant_display"].value_counts()
    top_comps = [c for c in comp_counts.index if comp_counts[c] >= 2][:8]
    if not top_comps:
        return None, "분할출원 2건 이상 기업 없음"
    color_reg = {}
    traces = []
    bursts = []
    for lane, comp in enumerate(top_comps):
        g = sub[sub["applicant_display"] == comp].sort_values("app_date")
        xs = [d.strftime("%Y-%m-%d") for d in g["app_date"]]
        traces.append({
            "type": "scatter", "mode": "markers", "name": str(comp),
            "x": xs, "y": [lane] * len(g),
            "hovertext": ["%s %s 분할출원 (원출원 %s)"
                          % (comp, x, str(p)[:20])
                          for x, p in zip(xs, g["parent_app_number"])],
            "hoverinfo": "text",
            "customdata": [{"drill": {"type": "ids", "ids": [str(i)]}}
                           for i in _ids_of(g)],
            "marker": {"size": 11, "symbol": "diamond",
                       "color": color_for(str(comp), color_reg)}})
        # 버스트: 180일 창에 3건 이상
        dates = list(g["app_date"])
        gids = list(_ids_of(g))
        i = 0
        while i < len(dates):
            j = i
            while j + 1 < len(dates) and (dates[j + 1] - dates[i]).days <= 180:
                j += 1
            if j - i + 1 >= 3:
                bursts.append({
                    "company": str(comp),
                    "start": dates[i].strftime("%Y-%m"),
                    "end": dates[j].strftime("%Y-%m"),
                    "n": j - i + 1,
                    "drill": {"type": "ids", "ids": [str(x) for x in gids[i:j + 1]]}})
                i = j + 1
            else:
                i += 1
    fig = {"data": traces, "layout": base_layout(
        "분할·계속출원 타임라인 (기업별 레인, ◇=분할출원)",
        xaxis={"title": "분할출원일"},
        yaxis={"tickmode": "array", "tickvals": list(range(len(top_comps))),
               "ticktext": [str(c) for c in top_comps], "automargin": True,
               "range": [-0.6, len(top_comps) - 0.4]},
        height=max(360, 120 + 40 * len(top_comps)), showlegend=False)}
    bursts.sort(key=lambda b: -b["n"])
    return {"fig": fig, "bursts": bursts[:10], "n_divisionals": int(len(sub)),
            "note": ("산업 이벤트(경쟁사 발표·소송) 데이터가 없어 이벤트 정렬은 "
                     "제공하지 않습니다 — 단기 집중(버스트) 구간은 방어적 청구항 "
                     "조정 가능성이 있는 '관찰된 군집'입니다.")}, None


# ---------------------------------------------------------------------------
# ⑦ 심사 소요기간 이상탐지
# ---------------------------------------------------------------------------
def _anomaly_section(df, settings):
    if "reg_date" not in df.columns or not df["reg_date"].notna().any():
        return None, "등록일 컬럼 필요"
    start_col = "exam_request_date" if "exam_request_date" in df.columns and \
        df["exam_request_date"].notna().any() else "app_date"
    if start_col not in df.columns:
        return None, "출원일(또는 심사청구일) 컬럼 필요"
    sub = df[df[start_col].notna() & df["reg_date"].notna()].copy()
    months = (sub["reg_date"] - sub[start_col]).dt.days / 30.44
    sub["_m"] = months
    sub = sub[(months > 0) & (months <= 240)]
    sub["_ptech"] = _primary_tech(sub)
    sub = sub[sub["_ptech"].notna()]
    if len(sub) < 15:
        return None, "소요기간 계산 가능 표본 부족 (15건 미만)"
    sub["_oa"] = parse_numeric(sub["oa_count"]) if "oa_count" in sub.columns else np.nan
    min_n = 8
    tech_counts = sub["_ptech"].value_counts()
    top_techs = [t for t in tech_counts.index if tech_counts[t] >= min_n][:6]
    if not top_techs:
        return None, "분류별 표본 %d건 이상인 기술분류 없음" % min_n
    ids = _ids_of(sub)
    traces, outliers = [], []
    for tech in top_techs:
        g = sub[sub["_ptech"] == tech]
        med = float(g["_m"].median())
        mad = float((g["_m"] - med).abs().median()) or 1.0
        z = 0.6745 * (g["_m"] - med) / mad
        traces.append({"type": "violin", "name": str(tech)[:16],
                       "y": [round(float(v), 1) for v in g["_m"]],
                       "box": {"visible": True}, "meanline": {"visible": True},
                       "points": False, "hoverinfo": "name"})
        for idx in g.index[(z.abs() > 2.5)]:
            r = sub.loc[idx]
            granted_strong = bool(z.loc[idx] > 2.5)
            outliers.append({
                "id": str(ids.loc[idx]), "tech": str(tech),
                "months": round(float(r["_m"]), 1),
                "z": round(float(z.loc[idx]), 2),
                "kind": "장기 심사 (심사 저항 큼 → 견딘 청구항은 강한 권리 후보)"
                        if granted_strong else "초단기 심사 (명확한 신기술 또는 우선심사)",
                "oa": (int(r["_oa"]) if pd.notna(r.get("_oa")) else None),
                "applicant": str(r.get("applicant_display", "")),
                "drill": {"type": "ids", "ids": [str(ids.loc[idx])]}})
    outliers.sort(key=lambda o: -abs(o["z"]))
    fig = {"data": traces, "layout": base_layout(
        "심사 소요기간 분포 (바이올린, %s→등록) — 이상치는 하단 목록"
        % ("심사청구일" if start_col == "exam_request_date" else "출원일"),
        yaxis={"title": "소요기간 (개월)"}, showlegend=False)}
    return {"fig": fig, "outliers": outliers[:15],
            "start_basis": "심사청구일" if start_col == "exam_request_date" else "출원일",
            "n": int(len(sub))}, None


# ---------------------------------------------------------------------------
# ⑧ 개시 충실도 (도면·명세서 분량)
# ---------------------------------------------------------------------------
def _disclosure_section(df, settings):
    if "drawings_count" not in df.columns:
        return None, "도면 수 컬럼 필요"
    dr = parse_numeric(df["drawings_count"])
    if not dr.notna().any():
        return None, "도면 수 값 해석 불가"
    sub = df.copy()
    sub["_dr"] = dr
    sub["_ptech"] = _primary_tech(sub)
    sub = sub[sub["_dr"].notna() & sub["_ptech"].notna()
              & (sub["applicant_display"].astype(str) != "")]
    if len(sub) < 15:
        return None, "도면 수·분류·출원인 표본 부족"
    top_comps = list(sub["applicant_display"].value_counts().head(8).index)
    top_techs = list(sub["_ptech"].value_counts().head(8).index)
    # 기술분류 내 z-score 로 정규화 → 분류 난이도·스타일 차이를 통제한 상대비교
    z_rows, hover = [], []
    tech_stats = {t: (float(sub[sub["_ptech"] == t]["_dr"].mean()),
                      float(sub[sub["_ptech"] == t]["_dr"].std()) or 1.0)
                  for t in top_techs}
    for comp in top_comps:
        row_z, row_h = [], []
        g = sub[sub["applicant_display"] == comp]
        for t in top_techs:
            v = g[g["_ptech"] == t]["_dr"]
            if len(v) >= 3:
                mu, sd = tech_stats[t]
                zval = round(float((v.mean() - mu) / sd), 2)
                row_z.append(zval)
                row_h.append("%s × %s: 평균 도면 %.1f장 (분류 평균 %.1f, z=%+.2f, %d건)"
                             % (comp, t, float(v.mean()), mu, zval, len(v)))
            else:
                row_z.append(None)
                row_h.append("%s × %s: 표본 부족" % (comp, t))
        z_rows.append(row_z)
        hover.append(row_h)
    fig = heatmap(z_rows, [str(t)[:18] for t in top_techs], top_comps,
                  title="개시 충실도 — 기업×기술분류 평균 도면 수 (분류 내 z-score)",
                  colorscale=RDYLGN, hovertext=hover, colorbar_title="z", zmid=0)
    fig_scatter = None
    if "claims_count" in sub.columns and sub["claims_count"].notna().any():
        s2 = sub[sub["claims_count"].notna()]
        fig_scatter = {"data": [{
            "type": "scatter", "mode": "markers",
            "x": [float(v) for v in s2["claims_count"]],
            "y": [float(v) for v in s2["_dr"]],
            "hovertext": ["%s · 청구항 %d항 / 도면 %d장"
                          % (a, int(c), int(d))
                          for a, c, d in zip(s2["applicant_display"],
                                             s2["claims_count"], s2["_dr"])],
            "hoverinfo": "text",
            "marker": {"size": 6, "opacity": 0.5, "color": "#59A14F"}}],
            "layout": base_layout(
                "도면 수 vs 청구항 수 — 우하단(청구 많고 도면 적음)=서면 위주 출원 신호",
                xaxis={"title": "청구항 수"}, yaxis={"title": "도면 수"})}
    comp_avg = sub.groupby("applicant_display")["_dr"].agg(["mean", "size"])
    comp_avg = comp_avg[comp_avg["size"] >= 5].sort_values("mean")
    lowest = str(comp_avg.index[0]) if len(comp_avg) else None
    highest = str(comp_avg.index[-1]) if len(comp_avg) else None
    return {"fig": fig, "fig_scatter": fig_scatter,
            "lowest": lowest, "highest": highest,
            "note": ("도면 수·명세서 분량은 대리인 작성 스타일 차이가 섞이므로 "
                     "데이터셋 내 상대비교로만 해석하세요 (절대 지표 아님).")}, None


# ---------------------------------------------------------------------------
# ⑨ 무효심판·이의 충돌 지도
# ---------------------------------------------------------------------------
def _trial_section(df, settings):
    tr_cnt = parse_numeric(df["trial_count"]) if "trial_count" in df.columns else None
    ls_cnt = parse_numeric(df["lawsuit_count"]) if "lawsuit_count" in df.columns \
        else None
    has_info = df["trial_info"].astype(str).str.strip() \
        .map(lambda v: v not in ("", "nan", "None")) if "trial_info" in df.columns \
        else pd.Series(False, index=df.index)
    has = has_info.copy()
    if tr_cnt is not None:
        has |= tr_cnt.fillna(0) > 0
    if ls_cnt is not None:
        has |= ls_cnt.fillna(0) > 0
    if not has.any():
        return None, "심판 이력/심판 전체 횟수/소송 전체 횟수 컬럼 필요"
    sub = df[has].copy()
    if len(sub) < 3:
        return None, "심판·소송 이력 보유 문헌 부족 (3건 미만)"
    if tr_cnt is not None:
        sub["_tr_cnt"] = tr_cnt[has]
    if ls_cnt is not None:
        sub["_ls_cnt"] = ls_cnt[has]
    sub["_ptech"] = _primary_tech(sub)
    by_tech = sub["_ptech"].dropna().value_counts().head(10)
    fig_bar = None
    if len(by_tech):
        totals = _primary_tech(df).value_counts()
        hover = ["%s: 심판 %d건 / 전체 %d건 (%s)"
                 % (t, c, int(totals.get(t, c)),
                    fmt_pct(c / float(totals.get(t, c))))
                 for t, c in by_tech.items()]
        fig_bar = bar_chart([str(t) for t in by_tech.index][::-1],
                            [int(v) for v in by_tech.values][::-1],
                            title="기술분류별 심판 건수 — 심판이 몰린 분류가 상업적 격전지",
                            orientation="h", x_title="심판 건수",
                            hovertext=hover[::-1],
                            customdata=[{"drill": {"type": "tech", "tech": str(t)}}
                                        for t in by_tech.index][::-1])
    network = None
    top_target = None
    if "trial_claimant" in sub.columns:
        pairs = {}
        for _i, r in sub.iterrows():
            claimant = auto_standardize_name(str(r.get("trial_claimant", "")))
            owner = str(r.get("applicant_display", "")).strip()
            if not claimant or claimant.lower() in ("nan", "none") or not owner \
                    or claimant == owner:
                continue
            techs = r.get("_tech_list") or []
            key = (claimant, owner)
            rec = pairs.setdefault(key, {"n": 0, "techs": {}})
            rec["n"] += 1
            for t in techs[:1]:
                rec["techs"][t] = rec["techs"].get(t, 0) + 1
        if pairs:
            in_deg = {}
            for (c, o), rec in pairs.items():
                in_deg[o] = in_deg.get(o, 0) + rec["n"]
            nmax = max(in_deg.values())
            names = sorted({n for k in pairs for n in k})
            color_reg = {}
            nodes = [{"id": name, "label": name,
                      "size": float(16 + 24 * np.sqrt(in_deg.get(name, 1) / nmax)),
                      "color": "#E15759" if in_deg.get(name, 0) == nmax else "#4E79A7",
                      "in_trials": int(in_deg.get(name, 0)),
                      "drill": {"type": "applicant", "applicant": name}}
                     for name in names]
            emax = max(rec["n"] for rec in pairs.values())
            edges = [{"source": c, "target": o, "weight": rec["n"], "arrow": True,
                      "width": float(1.5 + 5 * rec["n"] / emax),
                      "label": "%d건" % rec["n"],
                      "color": color_for(
                          max(rec["techs"], key=rec["techs"].get)
                          if rec["techs"] else "-", color_reg),
                      "techs": sorted(rec["techs"], key=rec["techs"].get,
                                      reverse=True)[:3]}
                     for (c, o), rec in pairs.items()]
            network = cytoscape_network(nodes, edges)
            top_target = max(in_deg, key=in_deg.get)
    trial_types = sub["trial_info"].astype(str).str.strip().value_counts().head(6) \
        if "trial_info" in sub.columns else pd.Series(dtype=int)
    trial_types = trial_types[trial_types.index.map(
        lambda v: v not in ("", "nan", "None"))]

    # 다분쟁 특허 목록 (심판+소송 횟수 상위 = 상업적으로 가장 뜨거운 특허)
    hot_patents = []
    if "_tr_cnt" in sub.columns or "_ls_cnt" in sub.columns:
        sub["_disputes"] = sub.get("_tr_cnt", pd.Series(0, index=sub.index)) \
            .fillna(0) + sub.get("_ls_cnt", pd.Series(0, index=sub.index)).fillna(0)
        ids = _ids_of(sub)
        for idx, r in sub.nlargest(10, "_disputes").iterrows():
            if r["_disputes"] <= 0:
                continue
            hot_patents.append({
                "id": str(ids.loc[idx]),
                "title": str(r.get("title", ""))[:60],
                "applicant": str(r.get("applicant_display", "")),
                "trials": int(r.get("_tr_cnt", 0) or 0),
                "lawsuits": int(r.get("_ls_cnt", 0) or 0),
                "court": (str(r.get("court_type", "")).strip()
                          if "court_type" in sub.columns else ""),
                "cites": (int(r["cites_forward"])
                          if "cites_forward" in sub.columns
                          and pd.notna(r.get("cites_forward")) else None),
                "drill": {"type": "ids", "ids": [str(ids.loc[idx])]}})

    # 관할 법원 분포 (분쟁 무대 — 법원별 특성 파악)
    fig_court = None
    if "court_type" in sub.columns:
        courts = sub["court_type"].astype(str).str.strip()
        courts = courts[~courts.str.lower().isin(["", "nan", "none"])] \
            .value_counts().head(10)
        if len(courts):
            fig_court = bar_chart([str(c) for c in courts.index][::-1],
                                  [int(v) for v in courts.values][::-1],
                                  title="관할 법원 분포 — 분쟁이 진행되는 무대",
                                  orientation="h", x_title="건수")

    # 분쟁 특허 vs 일반 특허 품질 비교 (분쟁은 가치의 방증)
    dispute_quality = None
    if "cites_forward" in df.columns and df["cites_forward"].notna().any():
        d_c = sub["cites_forward"].dropna()
        n_c = df[~has]["cites_forward"].dropna()
        if len(d_c) >= 3 and len(n_c) >= 10:
            dispute_quality = {"disputed_avg": round(float(d_c.mean()), 2),
                               "normal_avg": round(float(n_c.mean()), 2)}

    return {"fig": fig_bar, "network": network,
            "trial_types": [{"type": str(t), "n": int(v)}
                            for t, v in trial_types.items()],
            "hot_patents": hot_patents, "fig_court": fig_court,
            "dispute_quality": dispute_quality,
            "top_target": top_target, "n_trials": int(len(sub))}, None


# ---------------------------------------------------------------------------
# ⑩ 국가연구 과제 연계 분석
# ---------------------------------------------------------------------------
def _gov_program_section(df, settings):
    if "gov_program" not in df.columns:
        return None, "국가연구 과제명 컬럼 필요"
    prog = df["gov_program"].astype(str).str.strip()
    linked = ~prog.str.lower().isin(["", "nan", "none", "-"])
    if linked.sum() < 3:
        return None, "국가연구 과제 연계 문헌 부족 (3건 미만)"
    sub = df[linked].copy()
    ratio = float(linked.mean())

    # 과제 프로그램별 특허 산출 순위
    top_progs = sub["gov_program"].astype(str).str.strip().value_counts().head(12)
    fig_prog = bar_chart(
        [str(p)[:34] for p in top_progs.index][::-1],
        [int(v) for v in top_progs.values][::-1],
        title="국가연구 과제별 특허 산출 — 어떤 국책과제가 특허를 만들고 있나 "
              "(막대 클릭 → 해당 과제 특허 목록·Excel 다운로드)",
        orientation="h", x_title="특허 수",
        hovertext=["%s — %d건 (클릭 시 특허 목록)" % (p, v)
                   for p, v in top_progs.items()][::-1],
        customdata=[{"drill": {"gov_program": str(p)}}
                    for p in top_progs.index][::-1])

    # 기업별 정부과제 연계율
    fig_comp = None
    comp_rows = []
    apps = df["applicant_display"].replace("", np.nan).dropna()
    if len(apps):
        min_n = int(get_threshold(settings, "min_class_patents")) + 2
        for comp, total in apps.value_counts().head(12).items():
            if total < min_n:
                continue
            n_link = int(linked[df["applicant_display"] == comp].sum())
            comp_rows.append((str(comp), n_link, int(total),
                              n_link / float(total)))
        if comp_rows:
            comp_rows.sort(key=lambda r: r[3])
            fig_comp = bar_chart(
                [r[0] for r in comp_rows], [round(r[3], 3) for r in comp_rows],
                title="기업별 국가연구 과제 연계율 — 높을수록 국책과제 의존 R&D",
                orientation="h", x_title="연계율",
                hovertext=["%s — 정부과제 연계 %d건 / 전체 %d건 (%s)"
                           % (r[0], r[1], r[2], fmt_pct(r[3])) for r in comp_rows],
                customdata=[{"drill": {"type": "applicant", "applicant": r[0]}}
                            for r in comp_rows])

    # 기술분류별 연계율 (국가 지원이 집중되는 기술)
    fig_tech = None
    if df["_tech_list"].map(lambda v: bool(v)).any():
        link_tech = pd.Series([t for lst in sub["_tech_list"]
                               for t in (lst or [])]).value_counts()
        all_tech = pd.Series([t for lst in df["_tech_list"]
                              for t in (lst or [])]).value_counts()
        rows = [(str(t), int(c), int(all_tech.get(t, c)),
                 c / float(all_tech.get(t, c)))
                for t, c in link_tech.head(10).items() if all_tech.get(t, 0) >= 5]
        if rows:
            rows.sort(key=lambda r: r[3])
            fig_tech = bar_chart(
                [r[0] for r in rows], [round(r[3], 3) for r in rows],
                title="기술분류별 국가과제 연계율 — 국가 지원이 집중되는 기술",
                orientation="h", x_title="연계율",
                hovertext=["%s — 연계 %d건 / 전체 %d건 (%s)"
                           % (r[0], r[1], r[2], fmt_pct(r[3])) for r in rows],
                customdata=[{"drill": {"type": "tech", "tech": r[0]}}
                            for r in rows])

    # 정부과제 특허 vs 자체 특허 품질
    quality = None
    if "cites_forward" in df.columns and df["cites_forward"].notna().any():
        g_c = sub["cites_forward"].dropna()
        s_c = df[~linked]["cites_forward"].dropna()
        if len(g_c) >= 5 and len(s_c) >= 5:
            quality = {"gov_avg": round(float(g_c.mean()), 2),
                       "own_avg": round(float(s_c.mean()), 2)}

    return {"fig_prog": fig_prog, "fig_company": fig_comp, "fig_tech": fig_tech,
            "linked_ratio": round(ratio, 4), "n_linked": int(linked.sum()),
            "top_program": str(top_progs.index[0]), "quality": quality,
            "note": "국가연구 과제명이 기재된 특허 기준입니다. 과제 연계율이 높은 "
                    "기업·기술은 정부 R&D 의존도가 높아 과제 종료·정책 변화가 출원 "
                    "흐름에 영향을 줄 수 있습니다."}, None


# ---------------------------------------------------------------------------
# 통합
# ---------------------------------------------------------------------------
_SECTIONS = (("survival", _survival_section), ("market_entry", _market_entry_section),
             ("agent", _agent_section), ("examiner_eye", _examiner_eye_section),
             ("expedited", _expedited_section), ("divisional", _divisional_section),
             ("anomaly", _anomaly_section), ("disclosure", _disclosure_section),
             ("trial", _trial_section), ("gov_program", _gov_program_section))


def compute_wips_deep(df, settings, only_sections=None):
    """심층 시그널 계산 (섹션별 graceful degradation).

    only_sections: 계산할 섹션 키 목록 — 지정 시 해당 섹션만 계산하고
    인사이트 문장도 그 범위로 한정된다 (탭 분할 렌더링용). None=전체.
    """
    if not len(df):
        return empty_result()
    wanted = set(only_sections) if only_sections else None
    sections, skipped = {}, []
    for key, fn in _SECTIONS:
        if wanted is not None and key not in wanted:
            continue
        try:
            result, reason = fn(df, settings)
        except Exception as e:  # 개별 섹션 오류가 전체를 막지 않도록
            result, reason = None, "계산 오류: %s" % e
        if result is not None:
            sections[key] = result
        else:
            skipped.append({"section": key, "reason": reason})
    if not sections:
        labels = {"survival": "연차료 생존곡선", "market_entry": "지정국 진입 시차",
                  "agent": "대리인 전환", "examiner_eye": "심사관의 눈",
                  "expedited": "우선심사", "divisional": "분할출원",
                  "anomaly": "심사기간 이상탐지", "disclosure": "개시 충실도",
                  "trial": "심판·소송", "gov_program": "국가연구 과제"}
        details = " · ".join("%s: %s" % (labels.get(s["section"], s["section"]),
                                         s["reason"]) for s in skipped)
        return empty_result("이 화면의 섹션이 계산되지 못했습니다 — %s. Settings → "
                            "컬럼 매핑에서 위 컬럼을 매핑하면 활성화됩니다 (자동 매핑을 "
                            "다시 실행하면 '등록일[KR,JP…]'처럼 국가목록이 붙은 WIPS "
                            "헤더도 인식됩니다)." % details)

    sentences, metrics = [], {}
    period = period_label(df)
    if "survival" in sections and sections["survival"]["techs"]:
        worst = min(sections["survival"]["techs"], key=lambda t: t["surv_5y"])
        best = max(sections["survival"]["techs"], key=lambda t: t["surv_18y"])
        sentences.append("%s 기준 5년 생존율이 가장 낮은 분류는 '%s'(%s — 출원 실적용 "
                         "가능성)이고, 18년 완주율이 가장 높은 분류는 '%s'(%s — 사업 "
                         "핵심)입니다." % (period, worst["tech"], fmt_pct(worst["surv_5y"]),
                                       best["tech"], fmt_pct(best["surv_18y"])))
        metrics["survival_worst_5y"] = {worst["tech"]: worst["surv_5y"]}
    if "market_entry" in sections:
        shifted = [r for r in sections["market_entry"]["first_entries"] if r["shifted"]]
        if shifted:
            s0 = shifted[0]
            sentences.append("'%s'의 최근 1순위 진입국이 %s→%s 로 바뀌었습니다 — 시장 "
                             "베팅 전환 신호입니다." % (s0["company"], s0["first_country"],
                                                s0["recent_first"]))
    if "agent" in sections and sections["agent"]["signals"]:
        s0 = sections["agent"]["signals"][0]
        sentences.append("'%s'가 %d년 신규 대리인 '%s'를 %s 비중으로 기용하는 변화가 "
                         "관찰됩니다 (상관 신호이며 인과 판단이 아닙니다)."
                         % (s0["company"], s0["year"], s0["new_agent"],
                            fmt_pct(s0["share"])))
    if "examiner_eye" in sections and sections["examiner_eye"]["risky"]:
        sentences.append("심사관 인용이 자발 인용보다 훨씬 많은 분류(%s)는 출원인들이 "
                         "선행기술을 과소평가하는 영역으로, 무효 리스크 검토 후보입니다."
                         % ", ".join(sections["examiner_eye"]["risky"][:3]))
    if "expedited" in sections and sections["expedited"]["surge"]:
        s0 = sections["expedited"]["surge"][0]
        if s0["delta"] > 0.05:
            sentences.append("우선심사 비율이 가장 급등한 분류는 '%s'(%s→%s)로, 향후 "
                             "1~2년 내 제품화 가능성이 높은 영역입니다."
                             % (s0["tech"], fmt_pct(s0["prior_ratio"]),
                                fmt_pct(s0["recent_ratio"])))
    if "trial" in sections and sections["trial"]["top_target"]:
        sentences.append("심판 청구가 '%s'로 수렴합니다 — 병목(핵심) 특허 보유자일 "
                         "가능성이 있습니다." % sections["trial"]["top_target"])
    if "trial" in sections and sections["trial"].get("hot_patents"):
        hp = sections["trial"]["hot_patents"][0]
        sentences.append("분쟁이 가장 많은 특허는 %s(심판 %d·소송 %d회)로, 반복 분쟁은 "
                         "그 권리가 상업적으로 중요하다는 방증입니다."
                         % (hp["id"], hp["trials"], hp["lawsuits"]))
    if "trial" in sections and sections["trial"].get("dispute_quality"):
        dq = sections["trial"]["dispute_quality"]
        sentences.append("분쟁 특허의 평균 피인용은 %s로 일반 특허(%s) 대비 %s배 — "
                         "분쟁 대상이 곧 핵심 기술임을 보여줍니다."
                         % (dq["disputed_avg"], dq["normal_avg"],
                            round(dq["disputed_avg"] / max(dq["normal_avg"], 0.1), 1)))
    if "gov_program" in sections:
        gp = sections["gov_program"]
        sentences.append("전체의 %s(%s건)가 국가연구 과제 연계 특허이며, 최다 산출 "
                         "과제는 '%s'입니다."
                         % (fmt_pct(gp["linked_ratio"]), fmt_num(gp["n_linked"]),
                            gp["top_program"][:40]))
    if not sentences:
        sentences.append("%s 기준 심층 시그널 %d개 섹션이 계산되었습니다."
                         % (period, len(sections)))
    insight = build_insight(sentences, metrics,
                            small_sample=check_small_sample(len(df), settings))
    return ok_result(
        {"sections": sections, "skipped": skipped},
        insight=insight,
        meta={"note": "이 화면은 출원건수·출원인·기술분류 축이 아니라 연차료 소멸, "
                      "지정국 진입 시차, 대리인, 심사이력, 분할출원, 개시 분량, 심판 "
                      "기록 등 잘 활용되지 않는 WIPS 필드를 주 축으로 사용합니다. "
                      "모든 신호는 상관 관찰이며 인과·법률 판단이 아닙니다."})
