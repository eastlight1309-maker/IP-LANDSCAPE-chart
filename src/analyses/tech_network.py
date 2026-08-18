# -*- coding: utf-8 -*-
"""
analyses/tech_network.py — 4.2 기술분류 조합 네트워크.

분석 목적:
  기술분류 간 동시분류(co-classification) 구조를 네트워크로 표현하여 기술융합의
  중심축·커뮤니티·최근 성장 조합을 파악한다.

필수 컬럼: 기술분류(any)
선택 컬럼: 날짜(성장률·최근 조합), 출원인(신규 출원인)

그래프 구성 (Cytoscape.js):
- 노드: 기술분류 / 크기: 문헌 수 / 색상: 대분류 또는 Louvain 커뮤니티
- 테두리 색: 최근 성장률 (양수=초록, 음수=빨강, 불명=회색)
- 엣지: 동시분류 / 두께: 동시분류 강도(Jaccard) / hover: 지표 전체

계산 지표(엣지): 동시출현 건수, Jaccard, Lift, PMI/NPMI, 최근 recent_years 조합
성장률(robust_growth), 신규 출원인 수.

노드·엣지 수 상한: Top-N by weight (config.LIMITS, 설정 가능).
기업 비교: scope 파라미터 (all | company | market_excl) — 탭 3종.
Drill-down: 노드 클릭 {"type":"tech"}, 엣지 클릭 {"type":"combo"}.
자동 인사이트: 최대 연결 노드, Lift 상위 조합, 신규출원인 다수 조합.
예외처리: 조합이 없으면(단일 분류만) empty. 표본<min_combo_patents 조합 제외.
"""
import numpy as np

from src.config import get_threshold, get_limit
from src.metrics import lift as lift_fn, pmi as pmi_fn, npmi as npmi_fn, \
    jaccard as jaccard_fn, robust_growth, year_counts
from src.preprocessing import build_l1_lookup
from src.analyses.common import combo_counts
from src.insights import build_insight, fmt_num, period_label, check_small_sample
from src.viz_payload import ok_result, empty_result, cytoscape_network, color_for

try:
    import networkx as nx
except ImportError:
    nx = None


def _louvain_communities(nodes, edges):
    """Louvain(가능 시) 또는 greedy modularity 커뮤니티. 실패 시 모두 0."""
    if nx is None:
        return {n: 0 for n in nodes}
    try:
        g = nx.Graph()
        g.add_nodes_from(nodes)
        for e in edges:
            g.add_edge(e["a"], e["b"], weight=e["n_ab"])
        try:
            comms = nx.community.louvain_communities(g, weight="weight", seed=42)
        except (AttributeError, Exception):
            comms = nx.community.greedy_modularity_communities(g, weight="weight")
        out = {}
        for i, c in enumerate(comms):
            for n in c:
                out[n] = i
        return out
    except Exception:
        return {n: 0 for n in nodes}


def _scope_frame(df, scope, company):
    """scope: all | company | market_excl → 대상 DataFrame."""
    if scope == "company" and company:
        return df[df["applicant_display"].astype(str) == str(company)]
    if scope == "market_excl" and company:
        return df[df["applicant_display"].astype(str) != str(company)]
    return df


def compute_tech_network(df, settings, scope="all", company=None, color_by="l1"):
    """기술분류 조합 네트워크 계산. color_by: 'l1'(대분류) | 'community'."""
    sub = _scope_frame(df, scope, company)
    if not len(sub):
        return empty_result()
    recent = int(get_threshold(settings, "recent_years"))
    years = sub["_base_year"].dropna()
    recent_from = (int(years.max()) - recent + 1) if len(years) else None
    pairs, tech_counts, n_docs = combo_counts(sub, recent_year_from=recent_from, settings=settings)
    if not len(pairs) or n_docs == 0:
        return empty_result("동시분류(2개 이상 기술분류) 데이터가 없어 네트워크를 만들 수 없습니다.")

    min_combo = get_threshold(settings, "min_combo_patents")
    pairs = pairs[pairs["n_ab"] >= min_combo]
    if not len(pairs):
        return empty_result("최소 표본(%d건) 이상의 기술조합이 없습니다." % int(min_combo))

    max_edges = get_limit(settings, "network_max_edges")
    max_nodes = get_limit(settings, "network_max_nodes")
    n_pairs_all = len(pairs)
    pairs = pairs.sort_values("n_ab", ascending=False).head(max_edges)

    # 엣지 지표 계산
    edge_rows = []
    for _, r in pairs.iterrows():
        a, b, n_ab = r["a"], r["b"], int(r["n_ab"])
        n_a, n_b = tech_counts.get(a, 0), tech_counts.get(b, 0)
        combo_series = year_counts(r["years"]) if r["years"] else None
        growth, g_method = (robust_growth(combo_series, recent_years=recent)
                            if combo_series is not None and len(combo_series) else (None, "none"))
        edge_rows.append({
            "a": a, "b": b, "n_ab": n_ab,
            "jaccard": round(jaccard_fn(n_ab, n_a, n_b), 4),
            "lift": round(lift_fn(n_ab, n_a, n_b, n_docs), 3),
            "pmi": round(pmi_fn(n_ab, n_a, n_b, n_docs), 3) if pmi_fn(n_ab, n_a, n_b, n_docs) is not None else None,
            "npmi": round(npmi_fn(n_ab, n_a, n_b, n_docs), 3) if npmi_fn(n_ab, n_a, n_b, n_docs) is not None else None,
            "growth": round(growth, 4) if growth is not None else None,
            "growth_method": g_method,
            "new_applicants": len(r["new_applicants"]),
        })

    # 노드 상한: 엣지에 등장하는 기술 중 건수 상위 max_nodes
    node_names = {}
    for e in edge_rows:
        for t in (e["a"], e["b"]):
            node_names[t] = tech_counts.get(t, 0)
    keep_nodes = set(sorted(node_names, key=lambda t: -node_names[t])[:max_nodes])
    edge_rows = [e for e in edge_rows if e["a"] in keep_nodes and e["b"] in keep_nodes]

    # 노드 성장률·색상
    l1_lookup = build_l1_lookup(sub)
    comm = _louvain_communities(keep_nodes, edge_rows) if color_by == "community" else {}
    color_registry = {}
    nodes_payload = []
    tech_growth = {}
    year_lists = {}
    for techs, y in zip(sub["_tech_list"], sub["_base_year"]):
        if y is None or (isinstance(y, float) and np.isnan(y)):
            continue
        for t in set(techs or []):
            if t in keep_nodes:
                year_lists.setdefault(t, []).append(int(y))
    for t in keep_nodes:
        series = year_counts(year_lists.get(t, []))
        g, _ = robust_growth(series, recent_years=recent) if len(series) else (None, "none")
        tech_growth[t] = g
        group = ("커뮤니티 %d" % comm.get(t, 0)) if color_by == "community" \
            else str(l1_lookup.get(t, "기타"))
        border = "#2e9e4f" if (g is not None and g > 0.05) else \
            ("#d64545" if (g is not None and g < -0.05) else "#999999")
        nodes_payload.append({
            "id": t, "label": t, "count": int(node_names.get(t, 0)),
            "size": float(12 + 28 * np.sqrt(node_names.get(t, 0) / max(max(node_names.values()), 1))),
            "color": color_for(group, color_registry), "group": group,
            "growth": round(g, 4) if g is not None else None,
            "border_color": border,
            "drill": {"type": "tech", "tech": t},
        })

    max_j = max((e["jaccard"] for e in edge_rows), default=1) or 1
    edges_payload = [{
        "source": e["a"], "target": e["b"], "weight": e["n_ab"],
        "width": float(1 + 7 * (e["jaccard"] / max_j)),
        "jaccard": e["jaccard"], "lift": e["lift"], "pmi": e["pmi"], "npmi": e["npmi"],
        "growth": e["growth"], "new_applicants": e["new_applicants"],
        "drill": {"type": "combo", "a": e["a"], "b": e["b"]},
    } for e in edge_rows]

    # 인사이트
    sentences, metrics = [], {}
    period = period_label(sub)
    if nodes_payload:
        hub = max(nodes_payload, key=lambda n: n["count"])
        degree = {}
        for e in edges_payload:
            degree[e["source"]] = degree.get(e["source"], 0) + 1
            degree[e["target"]] = degree.get(e["target"], 0) + 1
        hub_deg = max(degree, key=degree.get) if degree else hub["id"]
        sentences.append("%s 기준 네트워크에서 연결이 가장 많은 기술은 '%s'(연결 %s개)이며, "
                         "최대 규모 노드는 '%s'(%s건)입니다."
                         % (period, hub_deg, fmt_num(degree.get(hub_deg, 0)),
                            hub["id"], fmt_num(hub["count"])))
        metrics["hub_tech"] = hub_deg
    top_lift = sorted([e for e in edges_payload if e["lift"]], key=lambda e: -e["lift"])[:1]
    if top_lift:
        e = top_lift[0]
        sentences.append("독립 대비 동시출현 강도(Lift)가 가장 높은 조합은 '%s × %s'(Lift %s, %s건)입니다."
                         % (e["source"], e["target"], fmt_num(e["lift"], 2), fmt_num(e["weight"])))
        metrics["top_lift"] = e["lift"]
    top_new = sorted(edges_payload, key=lambda e: -e["new_applicants"])[:1]
    if top_new and top_new[0]["new_applicants"] > 0:
        e = top_new[0]
        sentences.append("최근 %d년 신규 출원인이 가장 많이 진입한 조합은 '%s × %s'(신규 %s개사)로 "
                         "경쟁 심화 위험 요인입니다."
                         % (recent, e["source"], e["target"], fmt_num(e["new_applicants"])))
    insight = build_insight(sentences, metrics,
                            small_sample=check_small_sample(len(sub), settings))
    return ok_result({
        "network": cytoscape_network(nodes_payload, edges_payload),
        "scope": scope, "company": company,
        "n_nodes": len(nodes_payload), "n_edges": len(edges_payload),
    }, insight=insight, meta={"truncated": n_pairs_all > len(pairs)})
