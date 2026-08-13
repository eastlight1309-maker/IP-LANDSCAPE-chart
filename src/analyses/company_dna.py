# -*- coding: utf-8 -*-
"""
analyses/company_dna.py — 4.5 경쟁사 기술 DNA Fingerprint (+전략 유사도·포트폴리오
중첩도, 2단계).

분석 목적:
  기업별 12개 전략 지표로 기술 DNA 를 정량화하고, 규칙 기반으로 기업 유형을
  자동 분류한다.

필수 컬럼: 기술분류(any), 날짜(any), 출원인(any)
선택 컬럼: 패밀리 수, 패밀리 국가 수, 피인용 수, 법적상태, 발명자, 패밀리 ID

12개 지표 (기업별):
   1 tech_concentration  기술 집중도 (분류 분포 HHI)
   2 tech_diversity      기술 다양성 (Shannon entropy, 정규화)
   3 new_class_entry     신규분류 진입률 (최근 구간 신규 분류 수 / 활동 분류 수)
   4 combo_diversity     기술조합 다양성 (고유 조합 수 / 문헌 수)
   5 family_size         평균 패밀리 규모
   6 intl_scope          해외 출원 범위 (평균 패밀리 국가 수)
   7 grant_keep_ratio    등록 유지율 (유효등록 / 등록)
   8 avg_citations       평균 피인용도
   9 continuation_ratio  후속출원 비율 (패밀리 내 2건 이상 보유 패밀리 비율 근사)
  10 co_apply_ratio      공동출원 비율 (출원인 2인 이상)
  11 inventor_concentration 발명자 집중도 (발명자 HHI)
  12 recent_growth       최근 3년 성장률 (robust_growth)

지표별 원값(raw)과 표준화값(0~1, normalize_series)을 함께 제공 (Hover/토글).

그래프: 기업 수 <= max_companies_compare → 레이더, 초과 → 히트맵.
        세부 비교용 평행좌표(parcoords) payload 도 항상 포함.

규칙 기반 기업 유형 (기준값 dna_type_cutoff, Settings 조정 가능):
  선도 개척형: 신규분류 진입률·최근 성장률 높음 + 피인용 높음
  권리 장벽형: 등록 유지율·패밀리 규모·해외 범위 높음
  집중 방어형: 기술 집중도 높음 + 다양성 낮음
  융합 확장형: 조합 다양성·다양성 높음
  추격 확장형: 최근 성장률 높음 + 피인용 낮음
  양적 출원형: 출원량 상위 + 피인용·유지율 낮음
  (우선순위 순서로 첫 매칭. 매칭 없으면 '균형형')

전략 유사도: 기업 간 기술 구성비 벡터 코사인 유사도 행렬.
포트폴리오 중첩도: 기업 간 분류 집합 Jaccard 중첩 행렬.
Drill-down: {"type":"applicant"}.
예외처리: 표본<min_class_patents 기업 제외.
"""
import numpy as np
import pandas as pd

from src.config import get_threshold, get_limit
from src.metrics import hhi, shannon_entropy, robust_growth, year_counts, \
    normalize_series, cosine_sim_vec
from src.analyses.common import company_tech_shares
from src.insights import build_insight, fmt_num, fmt_pct, period_label, check_small_sample
from src.viz_payload import BLUES, PURPLES, ok_result, empty_result, radar_chart, heatmap

DNA_METRICS = [
    ("tech_concentration", "기술 집중도(HHI)"), ("tech_diversity", "기술 다양성"),
    ("new_class_entry", "신규분류 진입률"), ("combo_diversity", "조합 다양성"),
    ("family_size", "패밀리 규모"), ("intl_scope", "해외 범위"),
    ("grant_keep_ratio", "등록 유지율"), ("avg_citations", "평균 피인용"),
    ("continuation_ratio", "후속출원 비율"), ("co_apply_ratio", "공동출원 비율"),
    ("inventor_concentration", "발명자 집중도"), ("recent_growth", "최근 성장률"),
]

# 화면 지표 정의표 — 각 지표의 계산식을 그대로 공개한다 (숨은 가정 없음).
DNA_DEFINITIONS = [
    {"code": "기술 집중도", "name": "tech_concentration",
     "definition": "포트폴리오가 소수 기술분류에 몰려 있는 정도 (허핀달-허쉬만 지수)",
     "formula": "HHI = Σ(분류별 건수 비중)² — 다중분류는 각 분류에 1건씩",
     "basis": "기술분류 컬럼", "reading": "1에 가까울수록 한두 분류 집중, 1/분류수≈분산"},
    {"code": "기술 다양성", "name": "tech_diversity",
     "definition": "분류 분포의 고른 정도 (정규화 샤논 엔트로피)",
     "formula": "(−Σ p·log₂p) ÷ log₂(활동 분류 수), p=분류별 건수 비중",
     "basis": "기술분류 컬럼", "reading": "0~1 · 1=모든 분류에 균등, 0=단일 분류"},
    {"code": "신규분류 진입률", "name": "new_class_entry",
     "definition": "최근 N년(기본 3)에 처음 등장한 분류의 비중",
     "formula": "|최근에만 있는 분류| ÷ |전체 활동 분류(최근∪과거)|",
     "basis": "기술분류 × 출원연도", "reading": "높음=새 영역으로 확장 중"},
    {"code": "조합 다양성", "name": "combo_diversity",
     "definition": "한 문헌 안에서 서로 다른 분류를 함께 쓰는 정도",
     "formula": "고유 기술분류 2-조합 수 ÷ 문헌 수",
     "basis": "기술분류 컬럼(다중분류)", "reading": "높음=융합형 출원 (1 초과 가능)"},
    {"code": "패밀리 규모", "name": "family_size",
     "definition": "특허 1건이 몇 개 문헌(국가·후속 포함)으로 확장되는가",
     "formula": "패밀리 수 컬럼의 평균", "basis": "패밀리 수 컬럼",
     "reading": "높음=권리를 넓게 강화하는 투자"},
    {"code": "해외 범위", "name": "intl_scope",
     "definition": "평균 몇 개 국가에 권리를 확보하는가",
     "formula": "패밀리 국가 수 컬럼의 평균", "basis": "패밀리 국가 수(목록) 컬럼",
     "reading": "높음=글로벌 시장 지향"},
    {"code": "등록 유지율", "name": "grant_keep_ratio",
     "definition": "등록받은 권리를 계속 유지하는 비율",
     "formula": "유효(존속) 등록 건수 ÷ 등록 건수",
     "basis": "법적상태/등록·존속 여부", "reading": "높음=등록 권리를 끝까지 지킴"},
    {"code": "평균 피인용", "name": "avg_citations",
     "definition": "후행 특허가 얼마나 인용하는가 (기술 영향력 프록시)",
     "formula": "피인용 수 컬럼의 평균", "basis": "피인용 수(F1 등) 컬럼",
     "reading": "높음=기술 영향력 큼 (연차 미보정 주의)"},
    {"code": "후속출원 비율", "name": "continuation_ratio",
     "definition": "한 발명을 2건 이상으로 이어가는 패밀리의 비율 (근사)",
     "formula": "패밀리 내 문헌 2건 이상 패밀리 ÷ 전체 패밀리 — 문헌 단위에서는 "
                "패밀리 ID 중복으로, 패밀리 대표 단위에서는 '패밀리 수 ≥ 2'로 계산",
     "basis": "패밀리 ID 또는 패밀리 수 컬럼", "reading": "높음=핵심 발명을 계속 보강"},
    {"code": "공동출원 비율", "name": "co_apply_ratio",
     "definition": "다른 주체와 함께 출원하는 비율 (개방형 협력 성향)",
     "formula": "출원인 2인 이상 문헌 ÷ 전체 문헌 — 원본 출원인 리스트 기준 "
                "(공동출원 집계 설정과 무관)",
     "basis": "출원인 컬럼", "reading": "높음=산학·기업 간 협력형"},
    {"code": "발명자 집중도", "name": "inventor_concentration",
     "definition": "발명이 소수 발명자에게 몰려 있는 정도 (키맨 의존)",
     "formula": "HHI = Σ(발명자별 건수 비중)²", "basis": "발명자 컬럼",
     "reading": "높음=키맨 리스크 (이탈 시 타격 큼)"},
    {"code": "최근 성장률", "name": "recent_growth",
     "definition": "최근 N년(기본 3) 출원 증가 속도",
     "formula": "연도별 건수(데이터 최신 연도까지 0 채움)의 robust growth — "
                "① 최근 N년 CAGR → ② 회귀 기울기÷평균 → ③ 직전 N년 대비 증가율 "
                "사다리에서 계산 가능한 첫 방법",
     "basis": "출원일(없으면 우선일/공개일)",
     "reading": "양수=확대, 음수=축소 · 출원을 멈춘 기업은 0 채움으로 음수가 됨"},
]


def _company_metrics(sub, recent_from, recent):
    techs_flat = [t for lst in sub["_tech_list"] for t in (lst or [])]
    tech_counts = pd.Series(techs_flat).value_counts() if techs_flat else pd.Series(dtype=int)
    combos = set()
    for lst in sub["_tech_list"]:
        uniq = sorted(set(lst or []))
        from itertools import combinations
        combos.update(combinations(uniq, 2))
    recent_techs = set(t for lst, y in zip(sub["_tech_list"], sub["_base_year"])
                       for t in (lst or []) if y is not None and not
                       (isinstance(y, float) and np.isnan(y)) and y >= recent_from)
    old_techs = set(t for lst, y in zip(sub["_tech_list"], sub["_base_year"])
                    for t in (lst or []) if y is not None and not
                    (isinstance(y, float) and np.isnan(y)) and y < recent_from)
    granted = sub["_is_granted_bool"].map(lambda v: v is True)
    active_granted = granted & sub["_active_flag"].map(lambda v: v is True)
    inventors = [i for lst in (sub["_inventor_list"] if "_inventor_list" in sub.columns else [])
                 for i in (lst or [])]
    inv_counts = pd.Series(inventors).value_counts() if inventors else None
    co_apply = sub["_co_applicants"].map(lambda lst: len(lst or []) >= 2) \
        if "_co_applicants" in sub.columns else pd.Series(dtype=bool)
    # 후속출원 비율: 패밀리 내 문헌 2건 이상 패밀리 비율.
    # 문헌 단위에서는 family_id 중복으로 직접 계산하지만, 분석 단위가 '패밀리
    # 대표'(기본)이면 dedup 후 family_id 가 전부 유일해져 0 으로 붕괴하므로
    # 그 경우 '패밀리 수(구성 문헌 수) ≥ 2' 근사로 폴백한다.
    fam_multi = None
    if "family_id" in sub.columns and sub["family_id"].notna().any():
        fam_sizes = sub["family_id"].astype(str).value_counts()
        if (fam_sizes >= 2).any():
            fam_multi = float((fam_sizes >= 2).mean())
    if fam_multi is None and "family_size" in sub.columns \
            and sub["family_size"].notna().any():
        fam_multi = float((sub["family_size"].dropna() >= 2).mean())
    years = sub["_base_year"].dropna().astype(int)
    # 최근 성장률: 데이터 전체의 최신 연도까지 0 을 채워 계산 — 일찍 출원을
    # 멈춘 기업이 '자기 마지막 3년' 기준의 낡은 성장률을 받지 않도록.
    growth, _ = (robust_growth(year_counts(years,
                                           year_max=recent_from + recent - 1),
                               recent_years=recent)
                 if len(years) else (None, "n/a"))
    return {
        "n": len(sub),
        "tech_concentration": hhi(tech_counts.values) if len(tech_counts) else None,
        "tech_diversity": shannon_entropy(tech_counts.values, normalize=True)
        if len(tech_counts) else None,
        "new_class_entry": (len(recent_techs - old_techs) / max(len(recent_techs | old_techs), 1))
        if (recent_techs or old_techs) else None,
        "combo_diversity": len(combos) / max(len(sub), 1),
        "family_size": float(sub["family_size"].dropna().mean())
        if "family_size" in sub.columns and sub["family_size"].notna().any() else None,
        "intl_scope": float(sub["family_country_count"].dropna().mean())
        if "family_country_count" in sub.columns and sub["family_country_count"].notna().any() else None,
        "grant_keep_ratio": (float(active_granted.sum()) / float(granted.sum()))
        if granted.sum() else None,
        "avg_citations": float(sub["cites_forward"].dropna().mean())
        if "cites_forward" in sub.columns and sub["cites_forward"].notna().any() else None,
        "continuation_ratio": fam_multi,
        "co_apply_ratio": float(co_apply.mean()) if len(co_apply) else None,
        "inventor_concentration": hhi(inv_counts.values) if inv_counts is not None else None,
        "recent_growth": growth,
    }


def _classify(std, n_rank, cutoff):
    """규칙 기반 기업 유형 (표준화 점수 std: {metric: 0~1}, n_rank: 출원량 백분위)."""
    hi = lambda k: (std.get(k) or 0) >= cutoff
    lo = lambda k: (std.get(k) or 0) <= (1 - cutoff)
    if hi("new_class_entry") and hi("recent_growth") and (std.get("avg_citations") or 0) >= 0.5:
        return "선도 개척형"
    if hi("grant_keep_ratio") and ((std.get("family_size") or 0) >= 0.5
                                   or (std.get("intl_scope") or 0) >= 0.5):
        return "권리 장벽형"
    if hi("tech_concentration") and lo("tech_diversity"):
        return "집중 방어형"
    if hi("combo_diversity") and (std.get("tech_diversity") or 0) >= 0.5:
        return "융합 확장형"
    if hi("recent_growth") and lo("avg_citations"):
        return "추격 확장형"
    if n_rank >= 0.7 and lo("avg_citations") and lo("grant_keep_ratio"):
        return "양적 출원형"
    return "균형형"


def compute_company_dna(df, settings, companies=None):
    """경쟁사 기술 DNA Fingerprint 계산."""
    if not len(df):
        return empty_result()
    recent = int(get_threshold(settings, "recent_years"))
    years = df["_base_year"].dropna()
    recent_from = (int(years.max()) - recent + 1) if len(years) else 0
    min_n = get_threshold(settings, "min_class_patents")
    max_cmp = get_limit(settings, "max_companies_compare")

    totals = df["applicant_display"].replace("", np.nan).dropna().value_counts()
    if companies:
        wanted = [c for c in map(str, companies) if totals.get(c, 0) >= min_n][:30]
    else:
        wanted = [c for c in totals.index if totals[c] >= min_n][:30]
    if not wanted:
        return empty_result("최소 표본(%d건) 이상의 기업이 없습니다." % int(min_n))

    raw_by_company = {}
    for c in wanted:
        sub = df[df["applicant_display"].astype(str) == c]
        raw_by_company[c] = _company_metrics(sub, recent_from, recent)

    keys = [k for k, _ in DNA_METRICS]
    std_by_metric = {}
    for k in keys:
        vals = [raw_by_company[c][k] if raw_by_company[c][k] is not None else 0.0
                for c in wanted]
        std_by_metric[k] = normalize_series(vals, log=(k in ("family_size", "avg_citations", "intl_scope")))
    n_ranks = normalize_series([raw_by_company[c]["n"] for c in wanted], log=True)
    from src.config import WEIGHTS
    try:
        cutoff = float((settings or {}).get("dna_type_cutoffs", {}).get("default")
                       or WEIGHTS["dna_type_cutoff"])
    except (TypeError, ValueError):
        cutoff = WEIGHTS["dna_type_cutoff"]

    companies_payload = []
    for i, c in enumerate(wanted):
        raw = raw_by_company[c]
        std = {k: round(float(std_by_metric[k][i]), 4) for k in keys}
        ctype = _classify(std, float(n_ranks[i]), cutoff)
        companies_payload.append({
            "company": c, "n": raw["n"], "type": ctype,
            "raw": {k: (round(raw[k], 4) if isinstance(raw[k], float) else raw[k]) for k in keys},
            "std": std, "drill": {"type": "applicant", "applicant": c},
        })

    labels = [label for _, label in DNA_METRICS]
    if len(companies_payload) <= max_cmp:
        fig = radar_chart(labels, [
            {"name": p["company"], "values": [p["std"][k] for k in keys],
             "raw": [p["raw"][k] if p["raw"][k] is not None else "-" for k in keys]}
            for p in companies_payload], title="경쟁사 기술 DNA Fingerprint")
        chart_kind = "radar"
    else:
        z = [[p["std"][k] for k in keys] for p in companies_payload]
        hover = [["%s<br>%s: 표준화 %.2f / 원값 %s"
                  % (p["company"], label, p["std"][k],
                     p["raw"][k] if p["raw"][k] is not None else "-")
                  for k, label in DNA_METRICS] for p in companies_payload]
        fig = heatmap(z, labels, [p["company"] for p in companies_payload],
                      title="기술 DNA 히트맵 (표준화)", colorscale=BLUES, hovertext=hover)
        chart_kind = "heatmap"

    parcoords = {"data": [{
        "type": "parcoords",
        "line": {"color": list(range(len(companies_payload))), "colorscale": "Portland"},
        "dimensions": [{"label": label, "values": [p["std"][k] for p in companies_payload],
                        "range": [0, 1]} for k, label in DNA_METRICS],
    }], "layout": {"margin": {"l": 80, "r": 60, "t": 40, "b": 30},
                   "title": {"text": "지표별 평행좌표 비교 (표준화)", "font": {"size": 14}}}}

    # 전략 유사도·포트폴리오 중첩도
    shares = company_tech_shares(df, multiclass_mode=settings.get("multiclass_mode", "duplicate"))
    sim_matrix, overlap_matrix = None, None
    names = [p["company"] for p in companies_payload]
    if not shares.empty:
        available = [c for c in names if c in shares.index]
        vecs = {c: shares.loc[c].values for c in available}
        sets = {c: set(shares.columns[shares.loc[c].values > 0]) for c in available}
        sim_z, ov_z = [], []
        for a in available:
            sim_row, ov_row = [], []
            for b in available:
                sim_row.append(round(cosine_sim_vec(vecs[a], vecs[b]), 3))
                inter = len(sets[a] & sets[b])
                union = len(sets[a] | sets[b]) or 1
                ov_row.append(round(inter / union, 3))
            sim_z.append(sim_row)
            ov_z.append(ov_row)
        sim_matrix = heatmap(sim_z, available, available,
                             title="전략 유사도 (기술 구성비 코사인, 0~1 · 1=구성 동일)",
                             colorscale=BLUES, colorbar_title="유사도")
        overlap_matrix = heatmap(ov_z, available, available,
                                 title="포트폴리오 중첩도 (활동 분류 Jaccard, 0~1 · 1=완전 중첩)",
                                 colorscale=PURPLES, colorbar_title="중첩도")
        for fig_ in (sim_matrix, overlap_matrix):
            fig_["layout"]["xaxis"]["title"] = "기업"
            fig_["layout"]["yaxis"]["title"] = "기업"

    type_counts = {}
    for p in companies_payload:
        type_counts[p["type"]] = type_counts.get(p["type"], 0) + 1
    sentences = ["%s 기준 %s개 기업의 유형 분포: %s."
                 % (period_label(df), fmt_num(len(companies_payload)),
                    ", ".join("%s %d" % (t, c) for t, c in type_counts.items()))]
    pioneers = [p["company"] for p in companies_payload if p["type"] == "선도 개척형"]
    if pioneers:
        sentences.append("선도 개척형(%s)은 신규분류 진입률과 성장률·피인용이 동시에 높아 "
                         "핵심 경쟁 위험 요인입니다." % ", ".join(pioneers[:4]))
    grow = sorted(companies_payload, key=lambda p: -(p["raw"]["recent_growth"] or -9))[:1]
    if grow and grow[0]["raw"]["recent_growth"] is not None:
        sentences.append("최근 성장률 1위는 '%s'(%s)입니다."
                         % (grow[0]["company"], fmt_pct(grow[0]["raw"]["recent_growth"])))
    insight = build_insight(sentences, {"type_counts": type_counts},
                            small_sample=check_small_sample(len(companies_payload), settings))
    return ok_result({"figure": fig, "chart_kind": chart_kind, "parcoords": parcoords,
                      "companies": companies_payload, "metric_labels": dict(DNA_METRICS),
                      "definitions": DNA_DEFINITIONS,
                      "normalization_note":
                          "레이더/히트맵/평행좌표의 축 값은 기업 간 비교를 위한 "
                          "0~1 표준화 점수(log1p 일부 → 윈저라이즈 2% → IQR robust "
                          "정규화)이며, 원값은 hover 와 기업 표에 함께 표시됩니다. "
                          "유형 분류는 표준화 점수 ≥ cutoff(Settings 조정 가능) 규칙의 "
                          "첫 매칭입니다.",
                      "similarity": sim_matrix, "overlap": overlap_matrix},
                     insight=insight)
