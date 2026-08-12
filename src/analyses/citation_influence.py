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
"""
import numpy as np
import pandas as pd

from src.config import get_threshold, get_limit, get_weights
from src.metrics import normalize_series
from src.insights import build_insight, fmt_num, check_small_sample
from src.viz_payload import ok_result, empty_result, disabled_result, bar_chart, \
    sankey, color_for


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

    sentences = []
    if top_records:
        t0 = top_records[0]
        sentences.append("영향력 1위 특허는 %s('%s', %s, Influence %s, 피인용 %s건)입니다."
                         % (t0["id"], t0["title"][:40], t0["applicant"], t0["score"],
                            fmt_num(t0["cites"])))
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
    return ok_result({"figure": fig_bar, "sankey": fig_sankey, "top_patents": top_records},
                     insight=insight,
                     meta={"note": ("간접 피인용·타 기업 확산은 인용쌍 데이터가 없어 "
                                    "피인용 수 기반 근사값입니다.")})
