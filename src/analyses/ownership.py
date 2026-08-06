# -*- coding: utf-8 -*-
"""
analyses/ownership.py — 출원인 ↔ 현재 권리자(소유자) 관계 분석.

분석 목적:
  최초 출원인과 현재 권리자가 다른 특허는 양도·매각·사업부 이전·M&A 를 거친
  특허다. 이 관계에서 다음 인사이트를 도출한다:
  ① 이전(양도) 규모 — 전체/기업별 이전 비율
  ② 이전 흐름 네트워크 — 누가 누구의 특허를 확보했는가 (화살표=출원인→권리자)
  ③ 순매수자 vs 순매도자 — 기업별 확보(+)·유출(−) 건수와 순증
  ④ 거래 활발 기술분류 — 이전 특허가 몰린 기술 = 시장에서 거래 가치가 확인된 영역
  ⑤ 이전 특허 품질 — 이전/보유 특허의 평균 피인용 비교 (선별 매각/매입 여부)

주의 (meta·인사이트에 명시):
  - 사명 변경·계열사 재편이 양도처럼 보일 수 있다 — 출원인 표준화 규칙으로 병합해
    제거 가능하며, 동일 표준화 규칙을 권리자에도 적용한다.
  - 법적 권리 이전 판단은 등록원부 기준이며 본 분석은 통계 신호다.

필수 컬럼: 출원인(any), 현재 권리자. 선택: 기술분류, 날짜, 피인용, 유효 여부.
Drill: {"owner":…}, {"transferred":true|false}, {"type":"ids"} 조합.
"""
import numpy as np
import pandas as pd

from src.config import get_limit, get_threshold
from src.insights import build_insight, fmt_num, fmt_pct, period_label, \
    check_small_sample
from src.viz_payload import ok_result, empty_result, disabled_result, bar_chart, \
    cytoscape_network, base_layout, color_for


def compute_ownership(df, settings):
    """출원인 ↔ 현재 권리자 관계 분석."""
    if "owner_display" not in df.columns or \
            not (df["owner_display"].astype(str) != "").any():
        return disabled_result(
            ["현재 권리자(소유자)"],
            message="현재 권리자 컬럼이 없어 출원인·소유자 관계 분석을 사용할 수 "
                    "없습니다. Settings → 컬럼 매핑에서 '현재 권리자(소유자)'"
                    "(WIPS: 현재권리자/최종권리자)를 매핑하세요.")
    work = df[(df["applicant_display"].astype(str) != "")
              & (df["owner_display"].astype(str) != "")].copy()
    if len(work) < 10:
        return empty_result("출원인과 현재 권리자가 모두 있는 문헌이 부족합니다 "
                            "(최소 10건).")
    same = work["applicant_display"].astype(str) == work["owner_display"].astype(str)
    transferred = work[~same]
    n_all, n_tr = len(work), len(transferred)
    rate = n_tr / float(n_all)

    id_col = "pub_number" if "pub_number" in work.columns else \
        ("app_number" if "app_number" in work.columns else None)

    def ids_of(sub, cap=200):
        return [str(v) for v in (sub[id_col] if id_col else sub.index)][:cap]

    # ---- ② 이전 흐름 네트워크 (출원인 → 현재 권리자) -----------------------
    network, top_pairs = None, []
    if n_tr:
        pair_rows = {}
        for _i, r in transferred.iterrows():
            key = (str(r["applicant_display"]), str(r["owner_display"]))
            rec = pair_rows.setdefault(key, {"n": 0, "techs": {}, "years": [],
                                             "ids": []})
            rec["n"] += 1
            for t in (r.get("_tech_list") or [])[:1]:
                rec["techs"][t] = rec["techs"].get(t, 0) + 1
            y = r.get("_base_year")
            if y is not None and not (isinstance(y, float) and np.isnan(y)):
                rec["years"].append(int(y))
            if len(rec["ids"]) < 200 and id_col:
                rec["ids"].append(str(r[id_col]))
        max_edges = int(get_limit(settings, "inventor_network_max_edges"))
        pairs_sorted = sorted(pair_rows.items(), key=lambda kv: -kv[1]["n"])[:max_edges]
        in_deg, out_deg = {}, {}
        for (a, o), rec in pairs_sorted:
            out_deg[a] = out_deg.get(a, 0) + rec["n"]
            in_deg[o] = in_deg.get(o, 0) + rec["n"]
        names = sorted({n for k, _ in pairs_sorted for n in k})
        nmax = max(list(in_deg.values()) + list(out_deg.values()) + [1])
        nodes = [{"id": name, "label": name,
                  "size": float(16 + 24 * np.sqrt(
                      (in_deg.get(name, 0) + out_deg.get(name, 0)) / nmax)),
                  "color": "#59A14F" if in_deg.get(name, 0) > out_deg.get(name, 0)
                  else ("#E15759" if out_deg.get(name, 0) > in_deg.get(name, 0)
                        else "#4E79A7"),
                  "acquired": int(in_deg.get(name, 0)),
                  "divested": int(out_deg.get(name, 0)),
                  "drill": {"owner": name, "transferred": True}}
                 for name in names]
        emax = max(rec["n"] for _k, rec in pairs_sorted)
        color_reg = {}
        edges = [{"source": a, "target": o, "weight": rec["n"], "arrow": True,
                  "width": float(1.5 + 5 * rec["n"] / emax),
                  "label": "%d건" % rec["n"],
                  "color": color_for(max(rec["techs"], key=rec["techs"].get)
                                     if rec["techs"] else "-", color_reg),
                  "drill": {"type": "ids", "ids": rec["ids"]}}
                 for (a, o), rec in pairs_sorted]
        network = cytoscape_network(nodes, edges)
        for (a, o), rec in pairs_sorted[:12]:
            years = rec["years"]
            top_pairs.append({
                "from": a, "to": o, "n": int(rec["n"]),
                "tech": (max(rec["techs"], key=rec["techs"].get)
                         if rec["techs"] else "-"),
                "period": ("%d–%d" % (min(years), max(years))) if years else "-",
                "drill": {"type": "ids", "ids": rec["ids"]}})

    # ---- ③ 순매수자 vs 순매도자 -------------------------------------------
    fig_net = None
    net_rows = []
    if n_tr:
        acq = transferred["owner_display"].value_counts()
        div = transferred["applicant_display"].value_counts()
        comps = sorted(set(acq.index) | set(div.index),
                       key=lambda c: -(acq.get(c, 0) + div.get(c, 0)))[:12]
        net_rows = [{"company": c, "acquired": int(acq.get(c, 0)),
                     "divested": int(div.get(c, 0)),
                     "net": int(acq.get(c, 0) - div.get(c, 0))} for c in comps]
        net_rows.sort(key=lambda r: -r["net"])
        fig_net = {"data": [
            {"type": "bar", "name": "확보(+)", "orientation": "h",
             "y": [r["company"] for r in net_rows][::-1],
             "x": [r["acquired"] for r in net_rows][::-1],
             "marker": {"color": "#59A14F"},
             "customdata": [{"drill": {"owner": r["company"], "transferred": True}}
                            for r in net_rows][::-1],
             "hovertext": ["%s — 타사 출원 특허 %d건 보유 (확보)"
                           % (r["company"], r["acquired"])
                           for r in net_rows][::-1], "hoverinfo": "text"},
            {"type": "bar", "name": "유출(−)", "orientation": "h",
             "y": [r["company"] for r in net_rows][::-1],
             "x": [-r["divested"] for r in net_rows][::-1],
             "marker": {"color": "#E15759"},
             "customdata": [{"drill": {"applicant": r["company"],
                                       "transferred": True}}
                            for r in net_rows][::-1],
             "hovertext": ["%s — 출원했지만 권리가 이전된 특허 %d건 (유출)"
                           % (r["company"], r["divested"])
                           for r in net_rows][::-1], "hoverinfo": "text"}],
            "layout": base_layout(
                "기업별 특허 확보 vs 유출 (막대 오른쪽=확보, 왼쪽=유출)",
                barmode="relative", xaxis={"title": "건수 (좌:유출 / 우:확보)"},
                yaxis={"automargin": True},
                height=max(420, 140 + 30 * len(net_rows)))}

    # ---- ④ 거래 활발 기술분류 ---------------------------------------------
    fig_tech = None
    if n_tr and transferred["_tech_list"].map(lambda v: bool(v)).any():
        tr_tech = pd.Series([t for lst in transferred["_tech_list"]
                             for t in (lst or [])]).value_counts().head(12)
        all_tech = pd.Series([t for lst in work["_tech_list"]
                              for t in (lst or [])]).value_counts()
        hover = ["%s: 이전 %d건 / 전체 %d건 (이전율 %s)"
                 % (t, c, int(all_tech.get(t, c)),
                    fmt_pct(c / float(all_tech.get(t, c))))
                 for t, c in tr_tech.items()]
        fig_tech = bar_chart(
            [str(t) for t in tr_tech.index][::-1],
            [int(v) for v in tr_tech.values][::-1],
            title="권리 이전이 활발한 기술분류 — 시장에서 거래 가치가 확인된 영역",
            orientation="h", x_title="이전 특허 수", hovertext=hover[::-1],
            customdata=[{"drill": {"type": "tech", "tech": str(t),
                                   "transferred": True}}
                        for t in tr_tech.index][::-1])

    # ---- ⑤ 이전 특허 품질 비교 --------------------------------------------
    quality = None
    if n_tr and "cites_forward" in work.columns \
            and work["cites_forward"].notna().any():
        tr_c = transferred["cites_forward"].dropna()
        kept_c = work[same]["cites_forward"].dropna()
        if len(tr_c) >= 5 and len(kept_c) >= 5:
            quality = {"transferred_avg": round(float(tr_c.mean()), 2),
                       "kept_avg": round(float(kept_c.mean()), 2)}

    kpi = {"n_docs": n_all, "n_transferred": n_tr,
           "transfer_rate": round(rate, 4),
           "n_acquirers": len({r["company"] for r in net_rows if r["acquired"]}),
           "quality": quality}

    sentences = []
    period = period_label(work)
    sentences.append("%s 기준 출원인·권리자 정보가 모두 있는 %s건 중 %s건(%s)의 "
                     "권리가 최초 출원인이 아닌 곳에 있습니다."
                     % (period, fmt_num(n_all), fmt_num(n_tr), fmt_pct(rate)))
    if net_rows:
        buyer = max(net_rows, key=lambda r: r["net"])
        seller = min(net_rows, key=lambda r: r["net"])
        if buyer["net"] > 0:
            sentences.append("최대 순매수자는 '%s'(확보 %s건 − 유출 %s건 = +%s)로, "
                             "외부 기술 확보 전략이 관찰됩니다."
                             % (buyer["company"], fmt_num(buyer["acquired"]),
                                fmt_num(buyer["divested"]), fmt_num(buyer["net"])))
        if seller["net"] < 0:
            sentences.append("최대 순매도자는 '%s'(%s건 순유출)로, 사업 재편·수익화 "
                             "가능성이 있습니다." % (seller["company"],
                                             fmt_num(-seller["net"])))
    if quality:
        cmp_txt = ("이전 특허의 평균 피인용(%s)이 보유 특허(%s)보다 높아 가치 있는 "
                   "특허가 선별 거래된 신호" if quality["transferred_avg"]
                   > quality["kept_avg"] else
                   "이전 특허의 평균 피인용(%s)이 보유 특허(%s)보다 낮아 비핵심 "
                   "자산 정리 성격의 이전 신호")
        sentences.append((cmp_txt + "입니다.") % (quality["transferred_avg"],
                                              quality["kept_avg"]))
    sentences.append("사명 변경·계열사 재편이 양도처럼 보일 수 있습니다 — Settings → "
                     "출원인 표준화에서 같은 회사로 병합하면 제거됩니다. 법적 권리 "
                     "이전 판단은 등록원부 기준입니다.")

    insight = build_insight(
        sentences, kpi,
        drills=[{"label": "이전 특허 전체 보기",
                 "drill": {"transferred": True}}] if n_tr else None,
        small_sample=check_small_sample(n_all, settings))
    return ok_result(
        {"kpi": kpi, "network": network, "fig_net": fig_net, "fig_tech": fig_tech,
         "top_pairs": top_pairs, "net_rows": net_rows},
        insight=insight,
        meta={"note": "이전(양도) = 표준화된 출원인명과 현재 권리자명이 다른 경우의 "
                      "통계 신호입니다. 사명 변경·계열사 이동이 포함될 수 있으며 "
                      "(표준화 규칙으로 병합 가능), 법적 판단은 등록원부 기준입니다."})
