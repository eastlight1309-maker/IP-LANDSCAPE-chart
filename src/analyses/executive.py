# -*- coding: utf-8 -*-
"""
analyses/executive.py — 경영진 전략 대시보드 (Executive Strategy Dashboard).

분석 목적:
  경영진이 가장 먼저 묻는 질문에 한 화면으로 답한다:
  "우리는 시장 몇 위인가, 어디에 더/덜 투자해야 하나, 위협은 무엇인가."

구성:
  ① KPI — 자사 시장 순위(누적·최근), 점유율, 자사 vs 시장 성장률 격차,
     포트폴리오 품질(평균 피인용) 시장 대비, 유효특허 비율, 5년 내 만료 비중.
  ② 성장-점유 매트릭스 (BCG 스타일) — 기술분류별
     X=상대 시장점유율(자사 건수 ÷ 최대 경쟁사 건수, 로그축),
     Y=시장 성장률(최근 3년), 크기=시장 규모(전체 건수).
     4분면: Star(고성장·우위) / Question(고성장·열위 — 투자 판단 필요) /
            Cash Cow(저성장·우위) / Dog(저성장·열위 — 정리 후보).
  ③ 경쟁 포지션 버블 — 기업별 X=최근 성장률, Y=품질(평균 피인용, 없으면
     유효특허 비율), 크기=출원량. 자사는 ◇ 강조. 우상단=공격적 리더.
  ④ 경영 alert — 자사 핵심특허(피인용 상위)의 5년 내 만료, 최근 최고 성장
     경쟁사, 자사 부재의 고성장 분류.

자사(focal) 결정 우선순위: 요청 파라미터 company → Settings own_company_names
  → '자사 특허 여부' 컬럼 → 최다 출원인 (기준을 응답에 명시).

주의: 특허 출원량·피인용은 R&D 활동의 프록시이며 매출·수익성 지표가 아니다.
BCG 분면은 특허 데이터 기준의 전략 신호로, 사업 판단을 대체하지 않는다 (meta 명시).
"""
import numpy as np
import pandas as pd

from src.config import get_threshold, get_limit
from src.metrics import robust_growth, year_counts
from src.insights import build_insight, fmt_num, fmt_pct, period_label, \
    check_small_sample
from src.viz_payload import ok_result, empty_result, base_layout, color_for


def _pick_focal(df, settings, company=None):
    """자사(focal) 출원인 결정. 반환 (name, basis)."""
    apps = df["applicant_display"].replace("", np.nan).dropna()
    if not len(apps):
        return None, None
    counts = apps.value_counts()
    if company and str(company) in counts.index:
        return str(company), "화면에서 선택"
    if company:
        # 공동출원으로만 등장하는 회사도 선택 존중 — 조용히 다른 회사로
        # 바꿔 분석하면 사용자가 알아채지 못한 채 엉뚱한 결과를 보게 됨
        from src.analyses.common import applicant_mask
        if applicant_mask(df, str(company), scope="any").any():
            return str(company), "화면에서 선택 (공동출원 포함)"
    for own in (settings or {}).get("own_company_names") or []:
        if str(own) in counts.index:
            return str(own), "Settings 자사명"
    if "_is_own_bool" in df.columns:
        own_rows = df[df["_is_own_bool"].map(lambda v: v is True)]
        own_apps = own_rows["applicant_display"].replace("", np.nan).dropna()
        if len(own_apps):
            return str(own_apps.value_counts().index[0]), "자사 특허 여부 컬럼"
    return str(counts.index[0]), "최다 출원인 (자사 미설정 — Settings 에서 지정 가능)"


def _growth_of(df, mask, recent):
    years = df.loc[mask, "_base_year"].dropna().astype(int)
    if len(years) < 3:
        return None
    # '최근 N년' 창은 전체 데이터셋 최신 연도에 고정 — 출원이 끊긴 대상이
    # 자기 마지막 연도 기준으로 고성장으로 표시되는 왜곡 방지
    all_years = df["_base_year"].dropna()
    y_max = int(all_years.max()) if len(all_years) else int(years.max())
    g, _m = robust_growth(year_counts(years, year_max=y_max),
                          recent_years=recent)
    return g


def compute_executive_summary(df, settings, company=None):
    """경영진 전략 대시보드 계산."""
    if not len(df):
        return empty_result()
    if not df["_base_year"].notna().any():
        return empty_result("연도를 해석할 수 있는 문헌이 없습니다 — 출원일 매핑을 "
                            "확인하세요.")
    focal, focal_basis = _pick_focal(df, settings, company)
    if focal is None:
        return empty_result("출원인 정보가 없어 자사 기준 대시보드를 만들 수 없습니다.")
    recent = int(get_threshold(settings, "recent_years"))
    max_year = int(df["_base_year"].dropna().max())
    recent_from = max_year - recent + 1
    apps = df["applicant_display"]
    # 출원인 순위·점유율은 공동출원 설정을 따름 (기본 '각각 집계')
    from src.analyses.common import applicant_mask, applicant_counts as _acounts
    counts = _acounts(df, settings)
    # 공동출원 포함 membership 기준 — 공동출원으로만 등장하는 자사도 집계
    focal_mask = applicant_mask(df, focal, scope="any")

    # ---- ① KPI ------------------------------------------------------------
    rank_all = (int(list(counts.index).index(focal)) + 1
                if focal in counts.index else None)
    rec_df = df[df["_base_year"] >= recent_from]
    rec_counts = _acounts(rec_df, settings)
    rank_recent = (int(list(rec_counts.index).index(focal)) + 1
                   if focal in rec_counts.index else None)
    share = float(focal_mask.sum()) / float(len(df))
    g_focal = _growth_of(df, focal_mask, recent)
    g_market = _growth_of(df, pd.Series(True, index=df.index), recent)
    has_cites = "cites_forward" in df.columns and df["cites_forward"].notna().any()
    q_focal = q_market = None
    if has_cites:
        q_focal = float(df.loc[focal_mask, "cites_forward"].dropna().mean()) \
            if df.loc[focal_mask, "cites_forward"].notna().any() else None
        q_market = float(df["cites_forward"].dropna().mean())
    active_known = df.loc[focal_mask, "_active_flag"].map(lambda v: v is not None)
    active_rate = float(df.loc[focal_mask][active_known]["_active_flag"]
                        .map(lambda v: v is True).mean()) if active_known.any() else None
    expiring_share = None
    if "expiry_date" in df.columns:
        own_active = df[focal_mask & df["_active_flag"].map(lambda v: v is True)
                        & df["expiry_date"].notna()]
        if len(own_active) >= 5:
            soon = own_active["expiry_date"] <= pd.Timestamp.now() + pd.DateOffset(years=5)
            expiring_share = float(soon.mean())
    kpi = {"focal": focal, "focal_basis": focal_basis,
           "rank_all": rank_all, "rank_recent": rank_recent,
           "n_focal": int(focal_mask.sum()), "share": round(share, 4),
           "growth_focal": round(g_focal, 4) if g_focal is not None else None,
           "growth_market": round(g_market, 4) if g_market is not None else None,
           "quality_focal": round(q_focal, 2) if q_focal is not None else None,
           "quality_market": round(q_market, 2) if q_market is not None else None,
           "active_rate": round(active_rate, 3) if active_rate is not None else None,
           "expiring_5y_share": round(expiring_share, 3)
           if expiring_share is not None else None}

    # ---- ② 성장-점유 매트릭스 (BCG 스타일) --------------------------------
    tech_flat = {}
    _use_co = (str((settings or {}).get("coapplicant_mode") or "all") == "all"
               and "_co_applicants_display" in df.columns)
    _row_apps = (df["_co_applicants_display"] if _use_co
                 else apps.map(lambda a: [a] if str(a).strip() else []))
    for lst, row_apps in zip(df["_tech_list"], _row_apps):
        row_apps = [str(a).strip() for a in (row_apps or []) if str(a).strip()]
        for t in set(lst or []):
            rec = tech_flat.setdefault(t, {"total": 0, "by_app": {}})
            rec["total"] += 1
            for app in row_apps:
                rec["by_app"][app] = rec["by_app"].get(app, 0) + 1
    top_techs = sorted(tech_flat, key=lambda t: -tech_flat[t]["total"])[:12]
    bcg_rows = []
    for t in top_techs:
        rec = tech_flat[t]
        in_tech = df["_tech_list"].map(lambda lst: t in (lst or []))
        g = _growth_of(df, in_tech, recent)
        if g is None:
            continue
        focal_n = rec["by_app"].get(focal, 0)
        rival_max = max([n for a, n in rec["by_app"].items() if a != focal] or [0])
        rel_share = (focal_n / float(rival_max)) if rival_max else \
            (2.0 if focal_n else 0.0)
        rel_share = max(rel_share, 0.02)
        bcg_rows.append({"tech": str(t), "market_n": int(rec["total"]),
                         "focal_n": int(focal_n),
                         "rel_share": round(float(rel_share), 3),
                         "growth": round(float(g), 4),
                         "drill": {"type": "tech", "tech": str(t)}})
    fig_bcg = None
    if len(bcg_rows) >= 3:
        g_mid = float(np.median([r["growth"] for r in bcg_rows]))
        nmax = max(r["market_n"] for r in bcg_rows)

        def quad(r):
            hi_g = r["growth"] >= g_mid
            hi_s = r["rel_share"] >= 1.0
            return ("Star (수성·확대)" if hi_g and hi_s else
                    "Question (투자 판단)" if hi_g else
                    "Cash Cow (효율 유지)" if hi_s else "Dog (정리 검토)")
        quad_colors = {"Star (수성·확대)": "#59A14F", "Question (투자 판단)": "#F28E2B",
                       "Cash Cow (효율 유지)": "#4E79A7", "Dog (정리 검토)": "#BAB0AC"}
        for r in bcg_rows:
            r["quadrant"] = quad(r)
        xs = [r["rel_share"] for r in bcg_rows]
        fig_bcg = {"data": [{
            "type": "scatter", "mode": "markers", "cliponaxis": False,
            "x": xs, "y": [r["growth"] for r in bcg_rows],
            "hovertext": ["<b>%s</b> — %s<br>시장 %s건 · 자사 %s건 · 상대점유 %.2f · "
                          "시장 성장률 %s"
                          % (r["tech"], r["quadrant"], fmt_num(r["market_n"]),
                             fmt_num(r["focal_n"]), r["rel_share"],
                             fmt_pct(r["growth"])) for r in bcg_rows],
            "hoverinfo": "text",
            "customdata": [{"drill": r["drill"],
                            "m": {"기술분류": r["tech"], "시장규모": r["market_n"],
                                  "자사건수": r["focal_n"],
                                  "상대점유율": r["rel_share"],
                                  "시장성장률": r["growth"],
                                  "분면": r["quadrant"]}} for r in bcg_rows],
            "marker": {"size": [max(16.0, min(58.0, 12 + 3.0 * np.sqrt(
                          46.0 * r["market_n"] / nmax))) for r in bcg_rows],
                       "color": [quad_colors[r["quadrant"]] for r in bcg_rows],
                       "opacity": 0.85, "line": {"width": 1, "color": "#455"}}}],
            "layout": base_layout(
                "성장-점유 매트릭스 (BCG 스타일) — '%s' 기준" % focal,
                xaxis={"title": "상대 시장점유율 (자사 ÷ 최대 경쟁사, 로그축)",
                       "type": "log"},
                yaxis={"title": "시장 성장률 (최근 %d년)" % recent,
                       "tickformat": ".0%"},
                height=520,
                shapes=[{"type": "line", "x0": 1, "x1": 1, "yref": "paper",
                         "y0": 0, "y1": 1, "line": {"dash": "dot",
                                                    "color": "#8899aa"}},
                        {"type": "line", "xref": "paper", "x0": 0, "x1": 1,
                         "y0": g_mid, "y1": g_mid,
                         "line": {"dash": "dot", "color": "#8899aa"}}],
                annotations=[
                    {"xref": "paper", "yref": "paper", "x": 0.99, "y": 0.99,
                     "text": "⭐ Star", "showarrow": False,
                     "font": {"color": "#59A14F", "size": 11}},
                    {"xref": "paper", "yref": "paper", "x": 0.01, "y": 0.99,
                     "text": "❓ Question", "showarrow": False,
                     "font": {"color": "#F28E2B", "size": 11}},
                    {"xref": "paper", "yref": "paper", "x": 0.99, "y": 0.03,
                     "text": "🐄 Cash Cow", "showarrow": False,
                     "font": {"color": "#4E79A7", "size": 11}},
                    {"xref": "paper", "yref": "paper", "x": 0.01, "y": 0.03,
                     "text": "🐕 Dog", "showarrow": False,
                     "font": {"color": "#93a5b4", "size": 11}}])}
        # 기술명 라벨: 지시선 주석 (시장 규모 순, 로그 X축 좌표 보정, 겹침 회피)
        from src.viz_payload import leader_labels
        lbl_bcg = sorted(bcg_rows, key=lambda r: -r["market_n"])
        fig_bcg["layout"]["annotations"] += leader_labels(
            [{"x": r["rel_share"], "y": r["growth"], "text": r["tech"][:14],
              "color": quad_colors[r["quadrant"]],
              "line_color": quad_colors[r["quadrant"]]}
             for r in lbl_bcg[:20]], log_x=True, plot_h=480.0)

    # ---- ③ 경쟁 포지션 버블 -----------------------------------------------
    top_comps = list(counts.head(10).index)
    if focal not in top_comps:
        top_comps.append(focal)
    pos_rows = []
    for compny in top_comps:
        m = applicant_mask(df, compny, scope="any")
        g = _growth_of(df, m, recent)
        if g is None:
            continue
        if has_cites and df.loc[m, "cites_forward"].notna().any():
            qual = float(df.loc[m, "cites_forward"].dropna().mean())
        else:
            known = df.loc[m, "_active_flag"].map(lambda v: v is not None)
            qual = float(df.loc[m][known]["_active_flag"]
                         .map(lambda v: v is True).mean()) if known.any() else None
        if qual is None:
            continue
        pos_rows.append({"company": str(compny), "n": int(counts[compny]),
                         "growth": round(float(g), 4), "quality": round(qual, 2),
                         "is_focal": compny == focal,
                         "drill": {"type": "applicant", "applicant": str(compny)}})
    fig_pos = None
    quality_label = "평균 피인용 (기술 영향력)" if has_cites else "유효특허 비율"
    if len(pos_rows) >= 3:
        nmax = max(r["n"] for r in pos_rows)
        color_reg = {}
        fig_pos = {"data": [{
            "type": "scatter", "mode": "markers", "cliponaxis": False,
            "x": [r["growth"] for r in pos_rows],
            "y": [r["quality"] for r in pos_rows],
            "hovertext": ["%s%s — 출원 %s건 · 성장률 %s · %s %.2f"
                          % (r["company"], " (자사)" if r["is_focal"] else "",
                             fmt_num(r["n"]), fmt_pct(r["growth"]),
                             quality_label.split(" ")[0], r["quality"])
                          for r in pos_rows],
            "hoverinfo": "text",
            "customdata": [{"drill": r["drill"],
                            "m": {"기업": r["company"], "출원": r["n"],
                                  "성장률": r["growth"], "품질": r["quality"]}}
                           for r in pos_rows],
            "marker": {"size": [max(16.0, min(56.0, 12 + 3.0 * np.sqrt(
                          44.0 * r["n"] / nmax))) for r in pos_rows],
                       "symbol": ["diamond" if r["is_focal"] else "circle"
                                  for r in pos_rows],
                       "color": [color_for(r["company"], color_reg)
                                 for r in pos_rows],
                       "opacity": 0.85,
                       "line": {"width": [3 if r["is_focal"] else 0.8
                                          for r in pos_rows],
                                "color": "#E15759"}}}],
            "layout": base_layout(
                "경쟁 포지션 맵 — 우상단=공격적 리더, ◇=자사",
                xaxis={"title": "최근 %d년 출원 성장률" % recent,
                       "tickformat": ".0%"},
                yaxis={"title": quality_label}, height=500)}
        # 회사명 라벨: 지시선 주석 (자사 우선·굵게, 규모 순, 겹침 회피)
        from src.viz_payload import leader_labels
        lbl_pos = sorted(pos_rows, key=lambda r: (not r["is_focal"], -r["n"]))
        fig_pos["layout"].setdefault("annotations", [])
        fig_pos["layout"]["annotations"] += leader_labels(
            [{"x": r["growth"], "y": r["quality"], "text": r["company"][:12],
              "bold": r["is_focal"],
              "color": "#c0392b" if r["is_focal"] else "#38506b",
              "line_color": "#c0392b" if r["is_focal"] else "#9fb2c2"}
             for r in lbl_pos], plot_h=440.0, box_w=0.15)

    # ---- ④ 경영 alert ------------------------------------------------------
    alerts = []
    if "expiry_date" in df.columns and has_cites:
        own_core = df[focal_mask & df["expiry_date"].notna()
                      & df["cites_forward"].notna()]
        own_core = own_core[own_core["expiry_date"] <= pd.Timestamp.now()
                            + pd.DateOffset(years=5)]
        own_core = own_core.nlargest(5, "cites_forward")
        id_col = "pub_number" if "pub_number" in df.columns else None
        for _i, r in own_core.iterrows():
            pid = str(r.get(id_col, _i)) if id_col else str(_i)
            alerts.append({"icon": "⏳", "text": "자사 핵심특허 %s (피인용 %d) 이 %s 만료 "
                          "예정 — 후속 출원·연장 전략 검토"
                          % (pid, int(r["cites_forward"]),
                             str(r["expiry_date"].date())),
                          "drill": {"type": "ids", "ids": [pid]}})
    rivals = [r for r in pos_rows if not r["is_focal"]]
    if rivals:
        fastest = max(rivals, key=lambda r: r["growth"])
        if fastest["growth"] is not None and (g_focal is None
                                              or fastest["growth"] > (g_focal + 0.05)):
            alerts.append({"icon": "🚨", "text": "최고 성장 경쟁사는 '%s'(성장률 %s%s) — "
                          "투자 영역 비교 필요"
                          % (fastest["company"], fmt_pct(fastest["growth"]),
                             (", 자사 %s" % fmt_pct(g_focal))
                             if g_focal is not None else ""),
                          "drill": fastest["drill"]})
    absent_hot = [r for r in bcg_rows
                  if r["focal_n"] == 0 and r["growth"] >= 0.1]
    for r in absent_hot[:3]:
        alerts.append({"icon": "🔭", "text": "고성장 분류 '%s'(시장 성장률 %s, %s건)에 "
                      "자사 출원이 없습니다 — 진입/제휴 검토 후보"
                      % (r["tech"], fmt_pct(r["growth"]), fmt_num(r["market_n"])),
                      "drill": r["drill"]})

    sentences = []
    period = period_label(df)
    sentences.append("%s 기준 '%s'는 출원량 시장 %s(점유율 %s)%s입니다."
                     % (period, focal,
                        ("%d위" % rank_all) if rank_all else
                        "순위 미산정 (공동출원 전용 출원인)",
                        fmt_pct(share),
                        (", 최근 %d년 %d위" % (recent, rank_recent))
                        if rank_recent else ""))
    if g_focal is not None and g_market is not None:
        gap = g_focal - g_market
        sentences.append("자사 성장률 %s vs 시장 %s (%s%s) — %s."
                         % (fmt_pct(g_focal), fmt_pct(g_market),
                            "+" if gap >= 0 else "", fmt_pct(gap),
                            "시장보다 빠르게 확장 중" if gap > 0.02 else
                            ("시장 수준 유지" if gap > -0.02 else
                             "시장 대비 투자 축소 국면 — 원인 점검 필요")))
    stars = [r["tech"] for r in bcg_rows if r.get("quadrant", "").startswith("Star")]
    questions = [r["tech"] for r in bcg_rows
                 if r.get("quadrant", "").startswith("Question")]
    if stars or questions:
        sentences.append("Star 영역: %s / Question(투자 판단 필요) 영역: %s."
                         % (", ".join(stars[:4]) or "없음",
                            ", ".join(questions[:4]) or "없음"))
    sentences.append("특허 출원량·피인용은 R&D 활동의 프록시이며 매출·수익성 지표가 "
                     "아닙니다. 분면 판정은 특허 데이터 기준의 전략 신호입니다.")

    insight = build_insight(
        sentences, dict(kpi, n_alerts=len(alerts)),
        drills=[{"label": "자사 특허 전체 보기",
                 "drill": {"type": "applicant", "applicant": focal}}],
        small_sample=check_small_sample(len(df), settings))
    return ok_result(
        {"kpi": kpi, "bcg": fig_bcg, "bcg_rows": bcg_rows, "position": fig_pos,
         "alerts": alerts, "quality_label": quality_label},
        insight=insight,
        meta={"note": "자사 기준: %s ('%s'). BCG 분면은 특허 활동 기준의 전략 신호로 "
                      "사업·재무 판단을 대체하지 않습니다." % (focal_basis, focal)})
