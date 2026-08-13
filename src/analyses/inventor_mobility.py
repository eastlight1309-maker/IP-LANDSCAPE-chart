# -*- coding: utf-8 -*-
"""
analyses/inventor_mobility.py — 4.11 발명자 이동 및 기술 전파 네트워크 (3단계).

분석 목적:
  발명자의 소속(출원인) 변화를 추적하여 기업 간 인력·기술 이동 신호를 네트워크로
  표현한다.

필수 컬럼: 발명자, 출원인(any), 날짜(any)
선택 컬럼: 기술분류(엣지 색), 국가(동명이인 식별)

동명이인 처리 (식별 신뢰도 점수):
  같은 이름의 두 기록(이동 전/후)이 동일인인지에 대한 신뢰도를
    confidence = 0.35·공동발명자 겹침(Jaccard)
               + 0.25·기술분류 겹침(Jaccard)
               + 0.20·시간 근접성(간격<=3년 → 1, 이후 연 0.1 감쇠)
               + 0.10·국가 일치
               + 0.10·이름 희소성(전체에서 해당 이름 문헌 수가 적을수록 1)
  으로 계산한다. confidence < inventor_match_confidence(기본 0.6)면 "추정 이동"으로
  표시하고 기본 그래프에서 제외한다 (include_uncertain=True 로 포함 선택 가능).

이동 정의: 발명자 이름별 문헌을 연도순 정렬 후, 연속 문헌의 표준화 출원인이
  다르면 이동 후보 1건. 같은 (from,to,inventor) 는 1회만 집계.

그래프 (Cytoscape): 노드=기업, 엣지=이동 발명자 수, 엣지 색=대표 기술분류,
  시간 슬라이더용 year 속성 포함. 발명자 클릭 시 특허 이력(drill).
Drill-down: 엣지 → 이동 발명자 목록, 발명자 → {"type":"inventor"} 특허 이력.
자동 인사이트: 최대 유출→유입 경로, 추정 이동 비율.
예외처리: 발명자·출원인 없으면 disabled, 이동 없으면 empty.
"""
import numpy as np

from src.config import get_threshold, get_limit, MESSAGES
from src.insights import build_insight, fmt_num, fmt_pct, period_label, check_small_sample
from src.viz_payload import ok_result, empty_result, disabled_result, \
    cytoscape_network, color_for


def _jaccard_sets(a, b):
    a, b = set(a or []), set(b or [])
    if not a and not b:
        return 0.0
    union = a | b
    return len(a & b) / float(len(union)) if union else 0.0


def compute_inventor_mobility(df, settings, include_uncertain=False):
    """발명자 이동 네트워크 계산."""
    if "_inventor_list" not in df.columns:
        return disabled_result(["발명자"],
                               message="발명자 컬럼이 없어 발명자 이동 분석을 사용할 수 "
                                       "없습니다. 컬럼 매핑에서 '발명자'를 매핑하세요.")
    work = df[df["_base_year"].notna()].copy()
    if not len(work):
        return empty_result("연도 정보가 없어 이동 순서를 정할 수 없습니다.")
    conf_cutoff = get_threshold(settings, "inventor_match_confidence")
    max_edges = get_limit(settings, "inventor_network_max_edges")

    # 발명자 이름별 기록 구축
    records_by_name = {}
    name_doc_counts = {}
    has_coapps = "_co_applicants_display" in work.columns
    for idx, row in work.iterrows():
        invs = row.get("_inventor_list") or []
        app = str(row.get("applicant_display") or "")
        if not app:
            continue
        # 공동출원 문헌은 출원인 '집합'으로 기록 — 발명자가 공동출원사 중
        # 어느 소속인지는 데이터로 알 수 없으므로, 집합이 겹치는 연속 문헌을
        # 이동으로 세지 않기 위한 근거로 사용한다
        apps_set = set(a for a in ((row.get("_co_applicants_display") or [])
                                   if has_coapps else []) if str(a).strip())
        if not apps_set:
            apps_set = {app}
        year = int(row["_base_year"])
        techs = set(row.get("_tech_list") or [])
        country = str(row.get("country") or "").upper() if "country" in work.columns else ""
        pid = str(row.get("pub_number", idx))
        for inv in invs:
            inv = str(inv).strip()
            if not inv:
                continue
            name_doc_counts[inv] = name_doc_counts.get(inv, 0) + 1
            records_by_name.setdefault(inv, []).append({
                "year": year, "app": app, "apps": apps_set, "techs": techs,
                "coinv": set(i for i in invs if i != inv),
                "country": country, "pid": pid})
    if not records_by_name:
        return empty_result("발명자·출원인 정보가 있는 문헌이 없습니다.")
    max_docs = max(name_doc_counts.values())

    moves = []
    for inv, recs in records_by_name.items():
        recs.sort(key=lambda r: r["year"])
        seen_pairs = set()
        for prev, cur in zip(recs, recs[1:]):
            if prev["app"] == cur["app"]:
                continue
            # 공동출원 보정: 이전·현재 문헌의 출원인 집합이 겹치면 같은 소속이
            # 이어지는 것 (예: B 단독 → A·B 공동출원은 B 소속 지속) — 대표
            # 출원인만 보면 B→A 가짜 이동이 만들어진다
            if prev["apps"] & cur["apps"]:
                continue
            pair = (prev["app"], cur["app"])
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            gap = cur["year"] - prev["year"]
            time_score = 1.0 if gap <= 3 else max(0.0, 1.0 - 0.1 * (gap - 3))
            rarity = 1.0 - (name_doc_counts[inv] - 1) / float(max(max_docs - 1, 1))
            confidence = (0.35 * _jaccard_sets(prev["coinv"], cur["coinv"])
                          + 0.25 * _jaccard_sets(prev["techs"], cur["techs"])
                          + 0.20 * time_score
                          + 0.10 * (1.0 if prev["country"] and prev["country"] == cur["country"] else 0.0)
                          + 0.10 * rarity)
            techs = sorted(prev["techs"] | cur["techs"])
            moves.append({"inventor": inv, "from": prev["app"], "to": cur["app"],
                          "year": cur["year"], "confidence": round(float(confidence), 3),
                          "uncertain": confidence < conf_cutoff,
                          "techs": techs[:5]})
    if not moves:
        return empty_result("기업 간 발명자 이동이 관측되지 않았습니다.")

    n_uncertain = sum(1 for m in moves if m["uncertain"])
    used = moves if include_uncertain else [m for m in moves if not m["uncertain"]]
    if not used:
        return empty_result("신뢰도 %.2f 이상 이동이 없습니다. '추정 이동 포함' 옵션으로 "
                            "%d건의 추정 이동을 볼 수 있습니다." % (conf_cutoff, n_uncertain))

    edge_map = {}
    for m in used:
        key = (m["from"], m["to"])
        rec = edge_map.setdefault(key, {"from": m["from"], "to": m["to"], "inventors": [],
                                        "years": [], "techs": {}, "uncertain": 0})
        rec["inventors"].append({"name": m["inventor"], "year": m["year"],
                                 "confidence": m["confidence"],
                                 "label": (MESSAGES["estimated_move"] if m["uncertain"] else "확인 이동")})
        rec["years"].append(m["year"])
        for t in m["techs"]:
            rec["techs"][t] = rec["techs"].get(t, 0) + 1
        if m["uncertain"]:
            rec["uncertain"] += 1
    edges_data = sorted(edge_map.values(), key=lambda r: -len(r["inventors"]))[:max_edges]

    companies = sorted(set([e["from"] for e in edges_data] + [e["to"] for e in edges_data]))
    counts = work["applicant_display"].value_counts()
    max_count = max((counts.get(c, 1) for c in companies), default=1)
    nodes = [{"id": c, "label": c, "count": int(counts.get(c, 0)),
              "size": float(14 + 24 * np.sqrt(counts.get(c, 1) / max_count)),
              "color": "#59A14F", "drill": {"type": "applicant", "applicant": c}}
             for c in companies]
    color_reg = {}
    max_inv = max(len(e["inventors"]) for e in edges_data)
    edges = []
    for e in edges_data:
        top_tech = max(e["techs"], key=e["techs"].get) if e["techs"] else "기타"
        edges.append({
            "source": e["from"], "target": e["to"],
            "weight": len(e["inventors"]),
            "width": float(1.5 + 6 * len(e["inventors"]) / max_inv),
            "color": color_for(top_tech, color_reg), "tech": top_tech,
            "years": sorted(set(e["years"])),
            "year_min": min(e["years"]), "year_max": max(e["years"]),
            "uncertain": e["uncertain"],
            "inventors": e["inventors"][:30], "arrow": True,
            "label": "%d명" % len(e["inventors"]),
        })

    # 진단: 발명자 값이 출원인명과 대량으로 겹치면 '발명자' 컬럼 오매핑 신호
    # (예: 발명자 자리에 출원인 계열 컬럼이 매핑된 경우 — 화면에 회사명이 발명자로 보임)
    applicant_names = set(work["applicant_display"].astype(str)) \
        | set(work.get("applicant_raw", work["applicant_display"]).astype(str))
    inv_names = set(records_by_name.keys())
    overlap = (len(inv_names & applicant_names) / float(len(inv_names))) \
        if inv_names else 0.0
    mapping_warning = None
    if overlap >= 0.3:
        mapping_warning = ("⚠ 발명자 값의 %s가 출원인명과 동일합니다 — '발명자' 컬럼 "
                           "매핑이 출원인 계열 컬럼으로 잘못 잡혔을 가능성이 큽니다. "
                           "Settings → 컬럼 매핑에서 '발명자'의 매핑 컬럼과 예시 값을 "
                           "확인하세요." % fmt_pct(overlap))

    # 이동 발명자 목록 (화면 표 — 개별 발명자를 노드가 아닌 표로 노출)
    move_rows = sorted(used, key=lambda m: (-m["year"], -m["confidence"]))[:100]
    moves_table = [{"inventor": m["inventor"], "from": m["from"], "to": m["to"],
                    "year": m["year"], "confidence": m["confidence"],
                    "label": (MESSAGES["estimated_move"] if m["uncertain"]
                              else "확인 이동"),
                    "techs": m["techs"][:3],
                    "drill": {"type": "inventor", "inventor": m["inventor"]}}
                   for m in move_rows]

    sentences = []
    if mapping_warning:
        sentences.append(mapping_warning)
    if edges:
        e0 = max(edges, key=lambda e: e["weight"])
        sentences.append("%s 기준 최대 이동 경로는 '%s → %s'(%s명, 주요 분류 %s)입니다."
                         % (period_label(work), e0["source"], e0["target"],
                            fmt_num(e0["weight"]), e0["tech"]))
    sentences.append("전체 이동 후보 %s건 중 %s(%s건)이 신뢰도 %.2f 미만의 '추정 이동'으로 "
                     "분류되었습니다%s."
                     % (fmt_num(len(moves)), fmt_pct(n_uncertain / len(moves)),
                        fmt_num(n_uncertain), conf_cutoff,
                        " (그래프에 포함됨)" if include_uncertain else " (기본 그래프에서 제외)"))
    insight = build_insight(sentences, {"n_moves": len(used), "n_uncertain": n_uncertain,
                                        "inventor_applicant_overlap": round(overlap, 3)},
                            small_sample=check_small_sample(len(used), settings))
    years_all = sorted(set(y for e in edges for y in e["years"]))
    meta = {"coapplicant_note":
                "공동출원 보정: 공동출원 문헌은 출원인 집합으로 취급하며, 이전·현재 "
                "문헌의 출원인 집합이 겹치면(예: B 단독 → A·B 공동출원) 같은 소속의 "
                "지속으로 보고 이동으로 세지 않습니다 — 대표 출원인만 보면 생기는 "
                "가짜 이동 방지.",
            "note": "네트워크의 노드=기업(출원인), 엣지=이동 발명자 수입니다. 개별 "
                    "발명자는 아래 이동 목록 표와 엣지 클릭에서 확인하세요. 동명이인 "
                    "가능성이 있어 이동은 식별 신뢰도 기반 추정입니다."}
    if mapping_warning:
        meta["warning"] = mapping_warning
    return ok_result({"network": cytoscape_network(nodes, edges),
                      "years": years_all, "include_uncertain": bool(include_uncertain),
                      "n_uncertain": n_uncertain, "moves": moves_table},
                     insight=insight, meta=meta)
