# -*- coding: utf-8 -*-
"""
analyses/advanced_stats.py — 심화 통계 (윈텔립스/WIPS Excel 서지 정보 활용).

분석 목적:
  상용 검색 DB(윈텔립스 등) Excel 이 제공하는 서지 컬럼(등록일, 만료예정일,
  청구항 수, 공동출원인, IPC/CPC)으로 4가지 인사이트를 도출한다:
  ① 등록 소요기간(심사 기간) 분석 — 출원일↔등록일 간격
  ② 권리 만료 타임라인(특허 절벽) — 만료예정일 기반 연도별 만료 물량
  ③ 청구항 수 분석 — 권리범위 폭·정교함의 프록시 (기업별 평균, 피인용과의 관계)
  ④ 공동출원 협력 네트워크 — 출원인 컬럼의 복수 출원인 관계

필수 컬럼: 출원인(any)
선택 컬럼(섹션별): ①출원일+등록일 ②만료예정일 ③청구항 수(+피인용 수)
  ④복수 출원인이 든 출원인 컬럼 / ⑤IPC/CPC 분류(메인클래스 분포)

계산식:
  ① 소요기간(월) = (등록일-출원일)/30.44, 0~240개월 범위만 유효 처리.
     연도별 평균 라인 + 기업별 평균 막대(Top10, 최소 표본 적용).
  ② 만료 연도별 유효(또는 등록)특허 건수 막대 + 피인용 상위 만료 임박 특허 목록.
  ③ 기업별 평균 청구항 수(독립항 수 병기) 막대 + 청구항 수 구간별 평균 피인용 막대.
  ④ 공동출원 pair 빈도 → Cytoscape (노드=기업, 엣지=공동출원 건수). 자동 표준화명 사용.
  ⑤ IPC 메인클래스(서브클래스 4자리, 예: H01L) 분포 막대.

각 섹션은 필요한 컬럼이 없으면 생략되고 skipped 목록에 사유가 담긴다 (graceful).
Drill-down: 연도/기업/IPC 막대 클릭, 만료 특허 목록.
"""
import re

import numpy as np
import pandas as pd

from src.analyses.common import explode_applicants
from src.config import get_threshold, get_limit
from src.preprocessing import parse_multiclass_cell, auto_standardize_name, \
    IPC_SECTION_KO, IPC_SUBCLASS_KO
from src.insights import build_insight, fmt_num, fmt_pct, period_label, check_small_sample
from src.viz_payload import ok_result, empty_result, bar_chart, line_chart, \
    cytoscape_network, base_layout

_IPC_MAIN_RE = re.compile(r"^([A-HY]\d{2}[A-Z])")  # Y = CPC 전용 섹션 포함


def _prosecution_section(df, settings):
    """① 등록 소요기간 분석."""
    if "app_date" not in df.columns or "reg_date" not in df.columns:
        return None, "출원일·등록일 컬럼 필요"
    both = df[df["app_date"].notna() & df["reg_date"].notna()].copy()
    if not len(both):
        return None, "출원일과 등록일이 모두 있는 특허 없음"
    months = (both["reg_date"] - both["app_date"]).dt.days / 30.44
    both["_months"] = months
    both = both[(months > 0) & (months <= 240)]
    if len(both) < 5:
        return None, "유효한 소요기간 표본 부족 (5건 미만)"
    both["_year"] = both["app_date"].dt.year
    by_year = both.groupby("_year")["_months"].mean().round(1)
    fig_year = line_chart(
        [{"name": "평균 소요기간", "x": [int(y) for y in by_year.index],
          "y": [float(v) for v in by_year.values]}],
        "출원연도", "평균 등록 소요기간 (개월)", title="출원연도별 평균 등록 소요기간",
        year_axis=True)
    min_n = get_threshold(settings, "min_class_patents")
    by_comp = both[both["applicant_display"].astype(str) != ""] \
        .pipe(explode_applicants, settings) \
        .groupby("applicant_display")["_months"].agg(["mean", "size"])
    # 빠른 6 + 느린 6 — 빠른 순 상위 12개만 보이면 '느린 회사'(관심 대상)가
    # 조용히 사라진다
    _eligible = by_comp[by_comp["size"] >= min_n].sort_values("mean")
    by_comp = (_eligible if len(_eligible) <= 12
               else pd.concat([_eligible.head(6), _eligible.tail(6)]))
    fig_comp = None
    if len(by_comp):
        fig_comp = bar_chart(
            [str(c) for c in by_comp.index][::-1],
            [round(float(v), 1) for v in by_comp["mean"]][::-1],
            title="기업별 평균 등록 소요기간 (짧을수록 빠른 권리화)", orientation="h",
            x_title="평균 소요기간 (개월)",
            hovertext=["%s — 평균 %.1f개월 (%d건)" % (c, m, n)
                       for c, (m, n) in by_comp.iterrows()][::-1],
            customdata=[{"drill": {"type": "applicant", "applicant": str(c)}}
                        for c in by_comp.index][::-1])
    overall = float(both["_months"].mean())
    return {"fig_year": fig_year, "fig_company": fig_comp,
            "avg_months": round(overall, 1), "n": int(len(both))}, None


def _expiry_section(df, settings):
    """② 권리 만료 타임라인."""
    if "expiry_date" not in df.columns or not df["expiry_date"].notna().any():
        return None, "만료예정일 컬럼 필요"
    active = df[df["_active_flag"].map(lambda v: v is True)]
    scope = active if len(active) else df[df["_is_granted_bool"].map(lambda v: v is True)]
    scope_label = "유효특허" if len(active) else "등록특허"
    scope = scope[scope["expiry_date"].notna()]
    now = pd.Timestamp.now()
    # '만료 예정' 차트이므로 이미 만료된 과거 건은 제외 (현재 시점부터)
    scope = scope[scope["expiry_date"] >= now]
    if not len(scope):
        return None, "만료예정일이 있는 %s 없음" % scope_label
    years = scope["expiry_date"].dt.year
    counts = years.value_counts().sort_index()
    counts = counts[counts.index <= int(now.year) + 21]
    fig = bar_chart([int(y) for y in counts.index], [int(v) for v in counts.values],
                    title="권리 만료 타임라인 (%s 기준)" % scope_label,
                    x_title="만료 연도", y_title="만료 예정 건수")
    fig["layout"]["xaxis"].update({"tickformat": "d", "hoverformat": "d"})
    # 만료 임박(3년) 피인용 상위 특허
    soon = scope[scope["expiry_date"] <= now + pd.DateOffset(years=3)]
    if "cites_forward" in soon.columns and soon["cites_forward"].notna().any():
        soon = soon.nlargest(10, "cites_forward")
    else:
        soon = soon.nsmallest(10, "expiry_date")
    id_col = "pub_number" if "pub_number" in scope.columns else None
    expiring = [{"id": str(r.get(id_col, i)) if id_col else str(i),
                 "title": str(r.get("title", ""))[:80],
                 "applicant": str(r.get("applicant_display", "")),
                 "expiry": str(r["expiry_date"].date()),
                 "cites": int(r["cites_forward"]) if "cites_forward" in scope.columns
                 and pd.notna(r.get("cites_forward")) else None,
                 "drill": {"type": "ids", "ids": [str(r.get(id_col, i)) if id_col else str(i)]}}
                for i, r in soon.iterrows()]
    peak_year = int(counts.idxmax()) if len(counts) else None
    return {"fig": fig, "expiring": expiring, "peak_year": peak_year,
            "n": int(len(scope)), "scope": scope_label}, None


def _claims_section(df, settings):
    """③ 청구항 수 분석."""
    if "claims_count" not in df.columns or not df["claims_count"].notna().any():
        return None, "청구항 수 컬럼 필요 (윈텔립스: '청구항 수')"
    sub = df[df["claims_count"].notna() & (df["claims_count"] > 0)]
    if len(sub) < 5:
        return None, "청구항 수 표본 부족"
    min_n = get_threshold(settings, "min_class_patents")
    has_indep = "indep_claims_count" in sub.columns and sub["indep_claims_count"].notna().any()
    agg = {"claims": ("claims_count", "mean"), "n": ("claims_count", "size")}
    if has_indep:
        agg["indep"] = ("indep_claims_count", "mean")
    by_comp = sub[sub["applicant_display"].astype(str) != ""] \
        .pipe(explode_applicants, settings) \
        .groupby("applicant_display").agg(**agg)
    by_comp = by_comp[by_comp["n"] >= min_n].sort_values("claims", ascending=False).head(12)
    fig_comp = None
    if len(by_comp):
        fig_comp = bar_chart(
            [str(c) for c in by_comp.index][::-1],
            [round(float(v), 1) for v in by_comp["claims"]][::-1],
            title="기업별 평균 청구항 수 (많을수록 정교·광범위한 권리 설계 경향)",
            orientation="h", x_title="평균 청구항 수",
            hovertext=["%s — 평균 %.1f항%s (%d건)"
                       % (c, r["claims"],
                          (" / 독립항 %.1f" % r["indep"]) if has_indep else "",
                          int(r["n"])) for c, r in by_comp.iterrows()][::-1],
            customdata=[{"drill": {"type": "applicant", "applicant": str(c)}}
                        for c in by_comp.index][::-1])
    # 청구항 수 구간별 평균 피인용 (품질 관계)
    fig_rel = None
    if "cites_forward" in sub.columns and sub["cites_forward"].notna().any():
        bins = [0, 5, 10, 15, 20, 30, 1000]
        labels = ["1-5", "6-10", "11-15", "16-20", "21-30", "31+"]
        grp = pd.cut(sub["claims_count"], bins=bins, labels=labels)
        rel = sub.groupby(grp, observed=True)["cites_forward"].agg(["mean", "size"])
        rel = rel[rel["size"] >= 3]
        if len(rel) >= 2:
            fig_rel = bar_chart([str(i) for i in rel.index],
                                [round(float(v), 2) for v in rel["mean"]],
                                title="청구항 수 구간별 평균 피인용 (권리 설계와 기술 영향력의 관계)",
                                x_title="청구항 수 구간", y_title="평균 피인용",
                                hovertext=["%s항: 평균 피인용 %.2f (%d건)" % (i, r["mean"], r["size"])
                                           for i, r in rel.iterrows()])
    return {"fig_company": fig_comp, "fig_relation": fig_rel,
            "avg_claims": round(float(sub["claims_count"].mean()), 1),
            "n": int(len(sub))}, None


def _coapplicant_section(df, settings):
    """④ 공동출원 협력 네트워크.

    노드 이름은 출원인 표준화 결과(_co_applicants_display: 사용자 표준화
    규칙·그룹 + 표준화 출원인 컬럼 + 자동 표준화)를 그대로 사용한다 —
    원본(_co_applicants)에 자동 표준화만 적용하면 사용자가 지정한 표준명이
    반영되지 않고 드릴다운 매칭도 어긋난다. 표준화로 같은 회사로 합쳐진
    공동출원(예: 'A' + 'A(주)')은 1개 주체가 되어 관계에서 제외된다.
    """
    if "_co_applicants_display" in df.columns:
        lists = df["_co_applicants_display"]
        pre_standardized = True
    elif "_co_applicants" in df.columns:
        lists = df["_co_applicants"]          # 구버전 프레임 폴백
        pre_standardized = False
    else:
        return None, "출원인 컬럼 필요"
    pair_counts = {}
    for names in lists:
        if not names or len(names) < 2:
            continue
        if pre_standardized:
            std = sorted({str(n).strip() for n in names if str(n).strip()})
        else:
            std = sorted({auto_standardize_name(n) for n in names if str(n).strip()})
        std = [s for s in std if s]
        for i in range(len(std)):
            for j in range(i + 1, len(std)):
                key = (std[i], std[j])
                pair_counts[key] = pair_counts.get(key, 0) + 1
    if not pair_counts:
        return None, "공동출원(출원인 2인 이상) 특허 없음"
    max_edges = int(get_limit(settings, "inventor_network_max_edges"))
    top_pairs = sorted(pair_counts.items(), key=lambda kv: -kv[1])[:max_edges]
    node_totals = {}
    for (a, b), n in top_pairs:
        node_totals[a] = node_totals.get(a, 0) + n
        node_totals[b] = node_totals.get(b, 0) + n
    nmax = max(node_totals.values())
    # 노드 클릭 = 그 회사의 공동출원 특허 목록 (공동출원인 포함 매칭 + 공동출원 건만)
    nodes = [{"id": name, "label": name, "count": total,
              "size": float(14 + 26 * np.sqrt(total / nmax)), "color": "#B07AA1",
              "drill": {"type": "applicant", "applicant": name,
                        "applicant_scope": "any", "joint_only": True}}
             for name, total in node_totals.items()]
    emax = max(n for _, n in top_pairs)
    # 선(엣지) 클릭 = 두 회사가 함께 출원한 특허 목록 (양사 모두 (공동)출원인)
    edges = [{"source": a, "target": b, "weight": n,
              "width": float(1.5 + 6 * n / emax), "label": "%d건" % n,
              "drill": {"applicant": a, "applicant_scope": "any", "co_applicant": b},
              "color": "#9C755F"} for (a, b), n in top_pairs]
    top_pair = top_pairs[0]
    return {"network": cytoscape_network(nodes, edges),
            "n_pairs": len(pair_counts),
            "top_pair": {"a": top_pair[0][0], "b": top_pair[0][1], "n": top_pair[1]}}, None


def _ipc_desc(code):
    """서브클래스 코드 → 한글 설명 (사전 없으면 섹션 설명으로 폴백)."""
    code = str(code)
    sub = IPC_SUBCLASS_KO.get(code)
    sec = IPC_SECTION_KO.get(code[:1], "")
    if sub:
        return "%s (섹션 %s: %s)" % (sub, code[:1], sec) if sec else sub
    if sec:
        return "섹션 %s(%s) — 세부 설명 사전 미수록" % (code[:1], sec)
    return "설명 미수록"


def _ipc_section(df, settings):
    """⑤ IPC/CPC 메인클래스 분포.

    - 어떤 분류 체계(IPC/CPC)인지 매핑된 원본 컬럼명으로 표시 (유실 시 값 기반 추정)
    - 문헌 단위 집계: 한 문헌에 같은 서브클래스가 여러 번 있어도 1회 —
      막대 클릭 drill(해당 코드 보유 문헌 목록)과 건수가 정확히 일치
    - 코드별 한글 설명(hover + 하단 표)
    """
    if "ipc" not in df.columns:
        return None, "IPC/CPC 분류 컬럼 필요"
    mains = []
    for v in df["ipc"]:
        row_codes = set()
        for code in parse_multiclass_cell(v):
            m = _IPC_MAIN_RE.match(str(code).strip().upper().replace(" ", ""))
            if m:
                row_codes.add(m.group(1))
        mains.extend(sorted(row_codes))
    if not mains:
        return None, "IPC 형식(예: H01L 23/28) 값 없음"
    # 분류 체계 표기: 매핑된 원본 컬럼명 우선, 없으면 값(Y섹션=CPC 전용)으로 추정
    src_col = ""
    try:
        src_col = str((df.attrs.get("concept_source_cols") or {}).get("ipc") or "")
    except Exception:
        src_col = ""
    low = src_col.lower()
    if "cpc" in low and "ipc" not in low:
        scheme = "CPC"
    elif "ipc" in low:
        scheme = "IPC"
    elif any(c.startswith("Y") for c in mains):
        scheme = "CPC(Y섹션 포함 — 컬럼명 미상)"
    else:
        scheme = "IPC/CPC(컬럼명 미상)"
    counts = pd.Series(mains).value_counts().head(15)
    codes = [str(c) for c in counts.index]
    fig = bar_chart(
        codes[::-1], [int(v) for v in counts.values][::-1],
        title="%s 서브클래스(4자리) 분포 — 문헌 단위%s"
              % (scheme, (" · 매핑 컬럼: %s" % src_col) if src_col else ""),
        orientation="h", x_title="문헌 수",
        hovertext=["%s — %s · %d건 (클릭=해당 문헌 목록)"
                   % (c, _ipc_desc(c), int(n))
                   for c, n in zip(codes, counts.values)][::-1],
        customdata=[{"drill": {"ipc_main": c}} for c in codes][::-1])
    rows = [{"code": c, "desc": _ipc_desc(c), "n": int(n),
             "drill": {"ipc_main": c}}
            for c, n in zip(codes, counts.values)]
    return {"fig": fig, "top_class": codes[0], "n_classes": int(len(set(mains))),
            "scheme": scheme, "source_col": src_col, "rows": rows,
            "desc_note": "코드 설명은 대표 서브클래스 사전 기준이며, 사전에 없는 "
                         "코드는 섹션(1자리) 설명만 표시합니다 (임의 설명을 만들지 "
                         "않음 — 정확한 정의는 WIPO/특허청 IPC·CPC 분류표 참조)."}, None


def compute_advanced_stats(df, settings):
    """심화 통계 계산 (섹션별 graceful degradation)."""
    if not len(df):
        return empty_result()
    sections, skipped = {}, []
    for key, fn in (("prosecution", _prosecution_section), ("expiry", _expiry_section),
                    ("claims", _claims_section), ("coapplicant", _coapplicant_section),
                    ("ipc", _ipc_section)):
        result, reason = fn(df, settings)
        if result is not None:
            sections[key] = result
        else:
            skipped.append({"section": key, "reason": reason})
    if not sections:
        return empty_result("심화 통계에 필요한 컬럼(등록일/만료예정일/청구항 수/IPC 등)이 "
                            "없습니다. 컬럼 매핑을 확인하세요.")

    sentences, metrics = [], {}
    period = period_label(df)
    if "prosecution" in sections:
        sentences.append("%s 기준 평균 등록 소요기간은 %s개월(%s건 기준)입니다."
                         % (period, sections["prosecution"]["avg_months"],
                            fmt_num(sections["prosecution"]["n"])))
        metrics["avg_prosecution_months"] = sections["prosecution"]["avg_months"]
    if "expiry" in sections and sections["expiry"]["peak_year"]:
        sentences.append("권리 만료가 가장 몰리는 해는 %d년으로, 해당 시점 이후 관련 영역의 "
                         "설계 자유도 확대가 예상됩니다 (탐색적 신호)."
                         % sections["expiry"]["peak_year"])
        metrics["expiry_peak_year"] = sections["expiry"]["peak_year"]
    if "claims" in sections:
        sentences.append("전체 평균 청구항 수는 %s항입니다. 평균 청구항 수가 많은 기업은 "
                         "권리를 정교하게 설계하는 경향이 있습니다."
                         % sections["claims"]["avg_claims"])
    if "coapplicant" in sections:
        tp = sections["coapplicant"]["top_pair"]
        sentences.append("최다 공동출원 관계는 '%s ↔ %s'(%s건)로 긴밀한 협력 관계를 시사합니다."
                         % (tp["a"], tp["b"], fmt_num(tp["n"])))
    insight = build_insight(sentences, metrics,
                            small_sample=check_small_sample(len(df), settings))
    return ok_result({"sections": sections, "skipped": skipped}, insight=insight)
