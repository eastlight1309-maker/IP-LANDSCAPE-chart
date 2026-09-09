# -*- coding: utf-8 -*-
"""
analyses/citation_influence.py — 4.10 핵심특허 영향력 전파 (3단계).

분석 목적:
  피인용·패밀리·권리 지표를 결합한 Influence Score 로 핵심특허를 선별하고,
  Citation Diffusion Sankey 로 영향력 전파 경로를 표현한다.

필수 컬럼: 피인용 수, 기술분류(any)
선택 컬럼: 인용 수, 패밀리 수, 패밀리 국가 수, 법적상태, 만료예정일, 출원인, 제품

계산식:
  Influence Score = Σ( 표준화된 지표 × 가중치 ) / Σ가중치   (가중치 Settings 조정 가능)
  지표:
    direct_citations   직접 피인용 수
    indirect_citations 간접 피인용 근사 = 피인용 수 × log1p(인용 수)  (2-hop 데이터가
                       없는 WIPS 다운로드 환경에서의 명시적 근사 — meta 에 표기)
    cross_class        타 기술분류 확산 = 문헌의 다중분류 수 (자신이 걸친 분류 수)
    cross_company      타 기업 확산 근사 = 동일 분류 내 타 출원인 비율 × 피인용
    family_expansion   후속 패밀리 확장 = 패밀리 수
    legal_strength     유지·권리범위 = 유효여부(0/1) × 패밀리 국가 수(log1p) + 잔존기간
  개별 인용 문헌 간 링크 데이터(인용쌍)가 없으므로 Sankey 는
  「핵심특허 → 기술분류 → 상위 출원인(→ 제품)」 집계 흐름으로 구성한다.

인용 데이터 없으면: disabled + 필요 컬럼 안내 (임의 생성 금지).
그래프: Influence Top-N 막대 + Citation Diffusion Sankey.
Drill-down: {"type":"ids"}.
자동 인사이트: 최고 영향력 특허·만료 임박 핵심특허 경고.

확장 섹션 (해당 컬럼 매핑 시에만 계산 — graceful degradation):
  self_other     자기 vs 타인 피인용 분리 — WIPS '자기/타인 피인용 문헌번호(F1)'
                 로 자기인용을 제외한 "타인이 인정한 영향력"을 기업별로 비교.
                 자기인용 비율이 높은 기업=기술 내재화형, 타인 피인용이 높은
                 기업=산업 파급형.
  inset_network  세트 내 인용 네트워크 — '인용 문헌번호(B1)' 목록을 분석 대상
                 문헌번호(공개/출원/등록, 하이픈·공백 제거 정규화)와 매칭해
                 "누가 누구를 인용하는가" 기업 간 기술 흐름을 실제 인용쌍으로
                 구성. 세트 밖 인용은 집계에서 제외되며 매칭 커버리지를 함께
                 표시한다 (근사 아님 — 매칭된 쌍만 사용).
"""
import re

import numpy as np
import pandas as pd

from src.config import get_threshold, get_limit, get_weights
from src.metrics import normalize_series
from src.insights import build_insight, fmt_num, fmt_pct, check_small_sample
from src.viz_payload import ok_result, empty_result, disabled_result, bar_chart, \
    sankey, color_for, base_layout, cytoscape_network


def _ids_series(df):
    col = "pub_number" if "pub_number" in df.columns else \
        ("app_number" if "app_number" in df.columns else None)
    return df[col].astype(str) if col else df.index.astype(str).to_series(index=df.index)


def _self_other_section(df, settings):
    """자기 vs 타인 피인용 분리 — 자기인용을 뺀 '타인이 인정한 영향력'."""
    from src.analyses.wips_deep import _count_like
    from src.analyses.common import explode_applicants
    has_self = "cites_forward_self" in df.columns
    has_other = "cites_forward_other" in df.columns
    if not (has_self or has_other):
        return None, ("자기/타인 피인용 컬럼 필요 — 컬럼 매핑에서 '자기 피인용 "
                      "문헌번호'와 '타인 피인용 문헌번호'(WIPS F1)를 매핑하세요.")
    zero = pd.Series(0.0, index=df.index)
    self_c = _count_like(df["cites_forward_self"]).fillna(0) if has_self else zero
    other_c = _count_like(df["cites_forward_other"]).fillna(0) if has_other else zero
    if not ((self_c + other_c) > 0).any():
        return None, "자기/타인 피인용 값이 해석되지 않습니다 (건수 또는 문헌번호 목록 지원)."
    work = df.copy()
    work["_cf_self"] = self_c
    work["_cf_other"] = other_c
    # 기업별 합산 — 공동출원은 설정(coapplicant_mode)에 따라 각 출원인에게 계상
    wx = explode_applicants(work, settings)
    grp = wx[wx["applicant_display"].astype(str) != ""] \
        .groupby("applicant_display")[["_cf_self", "_cf_other"]].sum()
    grp = grp[grp.sum(axis=1) > 0]
    if not len(grp):
        return None, "자기/타인 피인용 보유 출원인이 없습니다."
    top = grp.assign(_tot=grp["_cf_self"] + grp["_cf_other"]) \
        .sort_values("_tot", ascending=False).head(12)
    comps = [str(c) for c in top.index][::-1]
    selfs = [float(v) for v in top["_cf_self"]][::-1]
    others = [float(v) for v in top["_cf_other"]][::-1]
    custom = [{"drill": {"type": "applicant", "applicant": c,
                         "applicant_scope": "any"}} for c in comps]
    hover_o = ["%s — 타인 피인용 %s건 (자기인용 제외 순수 영향력)"
               % (c, fmt_num(v)) for c, v in zip(comps, others)]
    hover_s = ["%s — 자기 피인용 %s건 / 전체 %s건 (자기인용률 %s)"
               % (c, fmt_num(s), fmt_num(s + o),
                  fmt_pct(s / (s + o) if (s + o) else 0.0))
               for c, s, o in zip(comps, selfs, others)]
    fig = {"data": [
        {"type": "bar", "orientation": "h", "name": "타인 피인용",
         "y": comps, "x": others, "marker": {"color": "#4E79A7"},
         "hovertext": hover_o, "hoverinfo": "text", "customdata": custom},
        {"type": "bar", "orientation": "h", "name": "자기 피인용",
         "y": comps, "x": selfs, "marker": {"color": "#F28E2B"},
         "hovertext": hover_s, "hoverinfo": "text", "customdata": custom}],
        "layout": base_layout(
            "기업별 자기 vs 타인 피인용 — 타인 피인용이 '진짜 영향력'",
            barmode="stack", xaxis={"title": "피인용 건수"},
            height=max(360, 90 + 34 * len(comps)))}
    rows = [{"company": str(c),
             "n_self": int(top.loc[c, "_cf_self"]),
             "n_other": int(top.loc[c, "_cf_other"]),
             "self_rate": round(float(top.loc[c, "_cf_self"] / top.loc[c, "_tot"]), 4),
             "drill": {"type": "applicant", "applicant": str(c),
                       "applicant_scope": "any"}}
            for c in top.index]
    # 타인 피인용 상위 특허 (자기인용 부풀림 없는 핵심특허 후보)
    ids = _ids_series(work)
    top_pat = []
    for idx, r in work.nlargest(10, "_cf_other").iterrows():
        if r["_cf_other"] <= 0:
            break
        top_pat.append({"id": str(ids.loc[idx]),
                        "title": str(r.get("title", ""))[:70],
                        "applicant": str(r.get("applicant_display", "")),
                        "n_other": int(r["_cf_other"]),
                        "n_self": int(r["_cf_self"]),
                        "drill": {"type": "ids", "ids": [str(ids.loc[idx])]}})
    tot_s, tot_o = float(self_c.sum()), float(other_c.sum())
    overall = {"n_self": int(tot_s), "n_other": int(tot_o),
               "self_rate": round(tot_s / (tot_s + tot_o), 4) if (tot_s + tot_o) else None}
    return {"fig": fig, "rows": rows, "top_patents": top_pat, "overall": overall,
            "note": ("자기 피인용=출원인(계열 포함, WIPS 기준)이 후속 출원에서 스스로 "
                     "인용한 건, 타인 피인용=타사가 인용한 건. 자기인용률이 높은 기업은 "
                     "기술 내재화·연속 개발형, 타인 피인용이 큰 기업은 산업 전체에 "
                     "영향을 주는 원천 기술형으로 해석합니다.")}, None


_NUM_NORM_RE = re.compile(r"[^A-Z0-9]")
_KIND_CODE_RE = re.compile(r"[A-Z]\d?$")


def _norm_doc_no(v):
    """문헌번호 정규화: 대문자화 + 특수문자 제거 (KR10-2020-0001234A → KR1020200001234A)."""
    return _NUM_NORM_RE.sub("", str(v).upper())


def _inset_network_section(df, settings):
    """세트 내 인용 네트워크 — 인용 문헌번호를 세트 문헌과 매칭한 실제 인용쌍."""
    from src.preprocessing import parse_multiclass_cell
    if "cites_backward_nums" not in df.columns:
        return None, ("인용 문헌번호 목록 컬럼 필요 — 컬럼 매핑에서 '인용 문헌번호 "
                      "목록'(WIPS '인용 문헌번호(B1)')을 매핑하세요.")
    # 세트 문헌번호 색인 (공개/출원/등록번호, 원형 + 말미 종별코드 제거형)
    key_to_idx = {}
    for id_col in ("pub_number", "app_number", "reg_number"):
        if id_col not in df.columns:
            continue
        for idx, v in df[id_col].items():
            k = _norm_doc_no(v)
            if len(k) >= 6:
                key_to_idx.setdefault(k, idx)
                key_to_idx.setdefault(_KIND_CODE_RE.sub("", k), idx)
    if not key_to_idx:
        return None, "문헌번호(공개/출원/등록번호) 컬럼이 없어 매칭할 수 없습니다."
    ids = _ids_series(df)
    apps = df["applicant_display"].astype(str)
    total_refs, matched = 0, 0
    pair_docs = {}       # (citing_idx, cited_idx)
    for idx, cell in df["cites_backward_nums"].items():
        for num in parse_multiclass_cell(cell):
            total_refs += 1
            k = _norm_doc_no(num)
            j = key_to_idx.get(k)
            if j is None:
                j = key_to_idx.get(_KIND_CODE_RE.sub("", k))
            if j is None or j == idx:
                continue
            matched += 1
            pair_docs[(idx, j)] = True
    if not pair_docs:
        return None, ("인용 문헌번호 %s건 중 분석 대상 세트 내 문헌과 매칭된 인용쌍이 "
                      "없습니다 — 세트 밖(외부) 문헌만 인용하고 있습니다."
                      % fmt_num(total_refs))
    # 기업 간 집계 (citing 기업 → cited 기업)
    comp_edges = {}
    self_company = 0
    inset_cited = {}     # cited_idx → citing idx 목록
    for (ci, cj) in pair_docs:
        inset_cited.setdefault(cj, []).append(ci)
        a, b = apps.loc[ci].strip(), apps.loc[cj].strip()
        if not a or not b:
            continue
        if a == b:
            self_company += 1
            continue
        rec = comp_edges.setdefault((a, b), {"n": 0, "citing_ids": []})
        rec["n"] += 1
        rec["citing_ids"].append(str(ids.loc[ci]))
    network = None
    top_pairs = []
    if comp_edges:
        deg = {}
        for (a, b), rec in comp_edges.items():
            deg[a] = deg.get(a, 0) + rec["n"]
            deg[b] = deg.get(b, 0) + rec["n"]
        keep = set(sorted(deg, key=deg.get, reverse=True)[:20])
        edges_kept = {k: v for k, v in comp_edges.items()
                      if k[0] in keep and k[1] in keep}
        in_deg = {}
        for (a, b), rec in edges_kept.items():
            in_deg[b] = in_deg.get(b, 0) + rec["n"]
        nmax = max(in_deg.values()) if in_deg else 1
        names = sorted({n for k in edges_kept for n in k})
        nodes = [{"id": n, "label": n,
                  "size": float(16 + 24 * np.sqrt(in_deg.get(n, 0) / float(nmax))
                                if nmax else 16),
                  "color": "#E15759" if in_deg.get(n, 0) == nmax and nmax > 0
                  else "#4E79A7",
                  "cited_in_set": int(in_deg.get(n, 0)),
                  "drill": {"type": "applicant", "applicant": n,
                            "applicant_scope": "any"}}
                 for n in names]
        emax = max(rec["n"] for rec in edges_kept.values())
        max_links = int(get_limit(settings, "sankey_max_links"))
        edge_items = sorted(edges_kept.items(), key=lambda kv: -kv[1]["n"])[:max_links]
        edges = [{"source": a, "target": b, "weight": rec["n"], "arrow": True,
                  "width": float(1.5 + 5 * rec["n"] / emax),
                  "label": "%d건" % rec["n"],
                  "drill": {"type": "ids", "ids": rec["citing_ids"][:200]}}
                 for (a, b), rec in edge_items]
        network = cytoscape_network(nodes, edges)
        top_pairs = [{"citing": a, "cited": b, "n": rec["n"],
                      "drill": {"type": "ids", "ids": rec["citing_ids"][:200]}}
                     for (a, b), rec in edge_items[:10]]
    # 세트 내에서 가장 많이 인용받은 특허 (실측 인용쌍 기준)
    top_cited = []
    for cj, citing in sorted(inset_cited.items(), key=lambda kv: -len(kv[1]))[:10]:
        top_cited.append({
            "id": str(ids.loc[cj]),
            "title": str(df.loc[cj].get("title", ""))[:70],
            "applicant": str(apps.loc[cj]),
            "n_inset": len(citing),
            "drill": {"type": "ids",
                      "ids": [str(ids.loc[ci]) for ci in citing][:200]}})
    return {"network": network, "top_pairs": top_pairs, "top_cited": top_cited,
            "n_pairs": int(len(pair_docs)), "n_refs": int(total_refs),
            "matched_ratio": round(matched / float(total_refs), 4) if total_refs else 0.0,
            "n_self_company": int(self_company),
            "note": ("매칭 기준: 인용 문헌번호와 세트 내 공개/출원/등록번호를 "
                     "정규화(하이픈·공백 제거, 말미 종별코드 허용)해 일치시킨 실제 "
                     "인용쌍만 사용합니다. 세트 밖 문헌 인용은 제외되므로 전체 인용 "
                     "관계의 부분집합입니다.")}, None


def compute_citation_influence(df, settings, top_n=None, company=None):
    """핵심특허 영향력 전파 계산.

    company 지정 시: 점수는 전체 데이터 기준으로 계산하되(타 기업 확산 등 상대
    지표가 전체 지형 기준을 유지하도록), 순위·Sankey 는 그 출원인의 특허
    (공동출원 포함)만 표시한다.
    """
    if "cites_forward" not in df.columns:
        return disabled_result(
            ["피인용 수"],
            message="피인용 수 컬럼이 없어 영향력 분석을 사용할 수 없습니다. 컬럼 매핑에서 "
                    "'피인용 수'(정수)를 매핑하세요. 인용쌍(citing-cited) 데이터가 있으면 "
                    "더 정밀한 전파 분석이 가능합니다.")
    if not df["cites_forward"].notna().any():
        return disabled_result(
            ["피인용 수"],
            message="피인용 수 컬럼은 매핑되어 있으나 숫자로 해석되는 값이 없습니다. "
                    "컬럼 매핑 화면의 '예시 값'으로 매핑된 실제 컬럼의 값 형식을 확인하세요 "
                    "(지원 형식: 3, 1,234, 3건 등).")
    work = df[df["cites_forward"].notna()].copy()
    if not len(work):
        return empty_result()
    top_n = int(top_n or get_limit(settings, "top_n_default"))
    now = pd.Timestamp.now()

    direct = work["cites_forward"].astype(float)
    backward = work["cites_backward"].fillna(0).astype(float) \
        if "cites_backward" in work.columns else pd.Series(0.0, index=work.index)
    indirect = direct * np.log1p(backward)
    cross_class = work["_tech_list"].map(lambda lst: len(set(lst or [])))
    # 동일 분류 내 타 출원인 비율 (분류별 사전 계산)
    other_ratio_by_tech = {}
    all_apps = work["applicant_display"]
    for tech in set(t for lst in work["_tech_list"] for t in (lst or [])):
        in_tech = work["_tech_list"].map(lambda lst: tech in (lst or []))
        apps = all_apps[in_tech]
        counts = apps.value_counts()
        total = float(len(apps)) or 1.0
        other_ratio_by_tech[tech] = {a: 1.0 - c / total for a, c in counts.items()}
    cross_company = [
        (np.mean([other_ratio_by_tech.get(t, {}).get(a, 0.0) for t in (lst or [])])
         if lst else 0.0) * d
        for lst, a, d in zip(work["_tech_list"], all_apps, direct)]
    family_exp = work["family_size"].fillna(0).astype(float) \
        if "family_size" in work.columns else pd.Series(0.0, index=work.index)
    active = work["_active_flag"].map(lambda v: 1.0 if v is True else 0.0)
    fam_countries = work["family_country_count"].fillna(0).astype(float) \
        if "family_country_count" in work.columns else pd.Series(0.0, index=work.index)
    if "expiry_date" in work.columns and work["expiry_date"].notna().any():
        remain = ((work["expiry_date"] - now).dt.days / 365.25).clip(lower=0).fillna(0)
    else:
        remain = pd.Series(0.0, index=work.index)
    legal_strength = active * np.log1p(fam_countries) + remain / 20.0

    parts = {
        "direct_citations": normalize_series(direct.values),
        "indirect_citations": normalize_series(np.asarray(indirect.values, dtype=float)),
        "cross_class": normalize_series(np.asarray(cross_class.values, dtype=float), log=False),
        "cross_company": normalize_series(np.asarray(cross_company, dtype=float)),
        "family_expansion": normalize_series(family_exp.values),
        "legal_strength": normalize_series(np.asarray(legal_strength.values, dtype=float),
                                           log=False),
    }
    weights = get_weights(settings, "influence")
    total_w = sum(max(w, 0) for w in weights.values()) or 1.0
    scores = np.zeros(len(work))
    for k, arr in parts.items():
        scores += max(weights.get(k, 0.0), 0.0) * arr
    scores /= total_w
    work["_influence"] = scores
    work["_influence_parts"] = [
        {k: round(float(parts[k][i]), 3) for k in parts} for i in range(len(work))]

    pool = work
    if company:
        from src.analyses.common import applicant_mask
        pool = work[applicant_mask(work, company, scope="any")]
        if not len(pool):
            return empty_result("출원인 '%s'의 피인용 수 보유 문헌이 없습니다 "
                                "(공동출원 포함 검색)." % company)
    top = pool.nlargest(top_n, "_influence")
    id_col = "pub_number" if "pub_number" in work.columns else \
        ("app_number" if "app_number" in work.columns else None)

    def _pid(row, idx):
        return str(row[id_col]) if id_col else str(idx)

    bars_labels, bars_vals, hover, custom = [], [], [], []
    top_records = []
    for idx, row in top.iterrows():
        pid = _pid(row, idx)
        label = "%s %s" % (pid[:18], str(row.get("title", ""))[:24])
        bars_labels.append(label)
        bars_vals.append(round(float(row["_influence"]), 4))
        pd_parts = row["_influence_parts"]
        hover.append("<b>%s</b><br>%s<br>Influence %.3f<br>%s"
                     % (pid, str(row.get("title", ""))[:70], row["_influence"],
                        " / ".join("%s %.2f" % (k, v) for k, v in pd_parts.items())))
        custom.append({"drill": {"type": "ids", "ids": [pid]}})
        top_records.append({"id": pid, "title": str(row.get("title", ""))[:90],
                            "applicant": str(row.get("applicant_display", "")),
                            "score": round(float(row["_influence"]), 4),
                            "cites": int(row["cites_forward"]),
                            "parts": pd_parts,
                            "expiry": str(row["expiry_date"].date())
                            if "expiry_date" in work.columns and pd.notna(row.get("expiry_date")) else None,
                            "drill": {"type": "ids", "ids": [pid]}})
    bar_title = ("핵심특허 Influence Top %d — %s (점수는 전체 데이터 기준)"
                 % (top_n, company)) if company else "핵심특허 Influence Top %d" % top_n
    fig_bar = bar_chart(bars_labels[::-1], bars_vals[::-1], title=bar_title,
                        orientation="h", hovertext=hover[::-1], customdata=custom[::-1],
                        x_title="Influence Score")

    # Citation Diffusion Sankey: 핵심특허 → 기술분류 → 상위 출원인(피인용 가중)
    color_reg = {}
    nodes, node_idx = [], {}

    def nid(label, kind):
        key = (label, kind)
        if key not in node_idx:
            node_idx[key] = len(nodes)
            nodes.append({"label": label, "color": color_for(kind, color_reg)})
        return node_idx[key]

    links = {}
    max_links = get_limit(settings, "sankey_max_links")
    for idx, row in top.iterrows():
        pid = _pid(row, idx)
        src = nid(pid[:20], "patent")
        w_total = float(row["cites_forward"]) or 1.0
        techs = list(set(row["_tech_list"] or []))[:4] or ["미분류"]
        for t in techs:
            t_node = nid(str(t)[:24], "tech")
            links[(src, t_node)] = links.get((src, t_node), 0) + w_total / len(techs)
            in_tech = work["_tech_list"].map(lambda lst: t in (lst or []))
            apps = work.loc[in_tech & (work.index != idx), "applicant_display"] \
                .replace("", np.nan).dropna().value_counts().head(3)
            a_total = float(apps.sum()) or 1.0
            for a, c in apps.items():
                a_node = nid(str(a)[:20], "applicant")
                links[(t_node, a_node)] = links.get((t_node, a_node), 0) + \
                    (w_total / len(techs)) * (c / a_total)
    link_list = sorted(links.items(), key=lambda kv: -kv[1])[:max_links]
    fig_sankey = sankey(nodes, [{"source": s, "target": t, "value": round(v, 2)}
                                for (s, t), v in link_list],
                        title="Citation Diffusion (핵심특허 → 기술분류 → 주요 출원인)")

    # 확장 섹션: 자기/타인 피인용 분리 · 세트 내 인용 네트워크 (컬럼 매핑 시에만)
    extras, extras_skipped = {}, []
    for ex_key, ex_fn in (("self_other", _self_other_section),
                          ("inset_network", _inset_network_section)):
        try:
            ex_res, ex_reason = ex_fn(df, settings)
        except Exception as e:  # 확장 섹션 오류가 본 분석을 막지 않도록
            ex_res, ex_reason = None, "계산 오류: %s" % e
        if ex_res is not None:
            extras[ex_key] = ex_res
        else:
            extras_skipped.append({"section": ex_key, "reason": ex_reason})

    sentences = []
    if top_records:
        t0 = top_records[0]
        sentences.append("영향력 1위 특허는 %s('%s', %s, Influence %s, 피인용 %s건)입니다."
                         % (t0["id"], t0["title"][:40], t0["applicant"], t0["score"],
                            fmt_num(t0["cites"])))
    if "self_other" in extras and extras["self_other"]["overall"]["self_rate"] is not None:
        so = extras["self_other"]
        r0 = max(so["rows"], key=lambda r: r["n_other"])
        sentences.append("전체 피인용 중 자기인용 비율은 %s이며, 자기인용을 제외한 "
                         "타인 피인용 1위 기업은 '%s'(%s건)입니다 — 타인 피인용이 "
                         "자기인용 부풀림 없는 실제 영향력입니다."
                         % (fmt_pct(so["overall"]["self_rate"]), r0["company"],
                            fmt_num(r0["n_other"])))
    if "inset_network" in extras:
        net = extras["inset_network"]
        if net["top_cited"]:
            c0 = net["top_cited"][0]
            sentences.append("세트 내 실제 인용쌍 %s건이 매칭되었고(전체 인용의 %s), "
                             "세트 안에서 가장 많이 인용받은 특허는 %s('%s', %s건)"
                             "입니다 — 이 세트의 기술 흐름이 수렴하는 문헌입니다."
                             % (fmt_num(net["n_pairs"]), fmt_pct(net["matched_ratio"]),
                                c0["id"], c0["applicant"], fmt_num(c0["n_inset"])))
        if net["top_pairs"]:
            p0 = net["top_pairs"][0]
            sentences.append("기업 간 인용 흐름 최대 경로는 '%s' → '%s'(%s건 인용)로, "
                             "'%s'가 '%s'의 기술을 토대로 후속 개발 중임을 시사합니다."
                             % (p0["citing"], p0["cited"], fmt_num(p0["n"]),
                                p0["citing"], p0["cited"]))
        expiring = [r for r in top_records if r["expiry"] and
                    pd.Timestamp(r["expiry"]) <= now + pd.DateOffset(years=3)]
        if expiring:
            sentences.append("핵심특허 중 %s건이 3년 내 만료 예정으로, 만료 후 해당 영역의 "
                             "설계 자유도가 확대될 수 있습니다 (탐색적 신호)."
                             % fmt_num(len(expiring)))
    if company:
        sentences.append("표시 범위: 출원인 '%s'의 특허(공동출원 포함)만 순위에 "
                         "표시되며, Influence 점수 자체는 전체 데이터 기준으로 "
                         "계산되어 다른 회사와 비교 가능합니다." % company)
    insight = build_insight(sentences, {"weights": weights},
                            small_sample=check_small_sample(len(work), settings))
    return ok_result({"figure": fig_bar, "sankey": fig_sankey, "top_patents": top_records,
                      "self_other": extras.get("self_other"),
                      "inset_network": extras.get("inset_network"),
                      "extras_skipped": extras_skipped},
                     insight=insight,
                     meta={"note": ("간접 피인용·타 기업 확산은 피인용 수 기반 근사값"
                                    "입니다. '세트 내 인용 네트워크' 섹션은 인용 "
                                    "문헌번호가 매핑된 경우 실제 인용쌍으로 계산됩니다.")})
