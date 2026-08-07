# -*- coding: utf-8 -*-
"""
analyses/problem_solution.py — 문제–해결수단 매트릭스 (1단계).

분석 목적:
  해결과제(행) × 해결수단(열) 매트릭스로 R&D 접근 조합의 밀집/공백을 파악한다.

필수 컬럼: C축 기술분류(=해결과제), B축 기술분류(=해결수단) — 두 축이 모두
  매핑된 경우에만 매트릭스를 그린다 (임의 추출 결과 생성 금지). 의미 그룹
  모드(compute_ps_semantic)는 해결과제·해결수단 텍스트 컬럼 기반으로 별도 동작.
선택 컬럼: 날짜(성장률), 출원인(상위 출원인), 독립청구항(대표 청구항), 유효특허 여부

계산식:
  셀 값 = 특허 수 / 셀 색상 = 최근 성장률(robust_growth) / 셀 테두리 = 권리장벽
  (유효등록 비율 — hover 로 제공). 행·열은 빈도 상위 matrix_max_rows/cols 로 제한.
  Opportunity Score(셀) = 정규화(성장률) × (1 - 유효등록비율) — 경량 산식.

그래프: Plotly 히트맵 (셀 수가 heatmap_max_cells 초과 시 ECharts 옵션 반환).
Drill-down: 셀 클릭 → {"type":"cell","problem":…,"solution":…} → 패널에
  관련 특허 리스트·상위 출원인·연도별 추이·대표 청구항·유효특허 비율·Score·인사이트.
자동 인사이트: 최다 셀, 최근 고성장 셀, 공백(행·열 존재하나 셀 0) 개수.
예외처리: 두 컬럼 중 하나라도 없으면 disabled_result(필요 컬럼 안내).
"""
import numpy as np
import pandas as pd

from src.config import get_threshold, get_limit
from src.metrics import robust_growth, year_counts, normalize_series
from src.insights import build_insight, fmt_num, fmt_pct, period_label, check_small_sample
from src.viz_payload import ok_result, empty_result, disabled_result, heatmap, \
    echarts_heatmap


def _clean_text_series(s):
    out = s.astype(str).str.strip()
    return out.where(~out.str.lower().isin(["nan", "none", ""]), other=None)


_BC_DISABLED_MSG = ("문제–해결수단 매트릭스는 C축(해결과제)과 B축(해결수단) 기술분류가 "
                    "모두 매핑된 경우에만 그립니다. Settings → 컬럼 매핑에서 "
                    "'기술분류 (C축)'에 해결과제 분류를, '기술분류 (B축)'에 해결수단 "
                    "분류를 매핑하세요. (요약·청구항 텍스트에서 임의 추출하지 않습니다.)")


def _bc_frame(df):
    """C축(해결과제)×B축(해결수단) → (problem, solution) 스칼라 프레임.

    다중값은 explode 로 조합별 1행씩 계산한다 (다중분류 duplicate 방식과 동일).
    두 축 중 하나라도 없거나 값이 비면 None 반환.
    """
    if "_tech_c_list" not in df.columns or "_tech_b_list" not in df.columns:
        return None
    work = df.copy()
    work["problem"] = df["_tech_c_list"].map(lambda v: list(v or []) or None)
    work["solution"] = df["_tech_b_list"].map(lambda v: list(v or []) or None)
    work = work[work["problem"].notna() & work["solution"].notna()]
    if not len(work):
        return None
    work = work.explode("problem").explode("solution")
    work["problem"] = _clean_text_series(work["problem"])
    work["solution"] = _clean_text_series(work["solution"])
    work = work[work["problem"].notna() & work["solution"].notna()]
    return work if len(work) else None


def compute_problem_solution(df, settings):
    """문제–해결수단 매트릭스 계산 — C축(해결과제)×B축(해결수단) 분류 기반."""
    if not len(df):
        return empty_result()
    work = _bc_frame(df)
    if work is None:
        return disabled_result(["기술분류 (C축)=해결과제", "기술분류 (B축)=해결수단"],
                               message=_BC_DISABLED_MSG)

    max_rows = get_limit(settings, "matrix_max_rows")
    max_cols = get_limit(settings, "matrix_max_cols")
    top_problems = work["problem"].value_counts().head(max_rows).index.tolist()
    top_solutions = work["solution"].value_counts().head(max_cols).index.tolist()
    sub = work[work["problem"].isin(top_problems) & work["solution"].isin(top_solutions)]
    if not len(sub):
        return empty_result()

    recent = int(get_threshold(settings, "recent_years"))
    counts = sub.pivot_table(index="problem", columns="solution", values="_base_year",
                             aggfunc="size", fill_value=0)
    counts = counts.reindex(index=top_problems, columns=top_solutions, fill_value=0)

    # 셀별 성장률·유효비율·상위 출원인
    growth_z, hover, cell_meta = [], [], {}
    for p in top_problems:
        g_row, h_row = [], []
        for s in top_solutions:
            cell = sub[(sub["problem"] == p) & (sub["solution"] == s)]
            n = len(cell)
            if n == 0:
                g_row.append(None)
                h_row.append("%s × %s<br>0건 (공백)" % (p[:40], s[:40]))
                continue
            years = cell["_base_year"].dropna()
            growth, _ = (robust_growth(year_counts(years.astype(int)), recent_years=recent)
                         if len(years) >= 2 else (None, "insufficient"))
            flags = cell["_active_flag"]
            known = flags.map(lambda v: v is not None)
            active_ratio = (float(flags[known].map(lambda v: v is True).mean())
                            if known.any() else None)
            top_apps = cell["applicant_display"].replace("", np.nan).dropna() \
                .value_counts().head(3)
            g_row.append(growth if growth is not None else 0.0)
            h_row.append("<b>%s × %s</b><br>%s건 / 성장률 %s / 유효비율 %s<br>상위: %s"
                         % (p[:40], s[:40], fmt_num(n),
                            fmt_pct(growth) if growth is not None else "-",
                            fmt_pct(active_ratio) if active_ratio is not None else "미상",
                            ", ".join("%s(%d)" % (a[:14], c) for a, c in top_apps.items())))
            cell_meta["%s|||%s" % (p, s)] = {
                "count": n, "growth": growth, "active_ratio": active_ratio,
                "top_applicants": [{"name": str(a), "count": int(c)}
                                   for a, c in top_apps.items()]}
        growth_z.append(g_row)
        hover.append(h_row)

    # 축 라벨 축약: 긴 과제·수단 문구가 플롯 영역을 잠식하지 않도록 축에는 짧은
    # 라벨을 쓰고(중복 시 번호 부여), 전체 문구는 hover 와 라벨맵으로 제공한다.
    def _short_labels(values, limit=16):
        used, out = {}, []
        for v in values:
            base = str(v).strip()
            short = base if len(base) <= limit else base[:limit] + "…"
            if short in used:
                used[short] += 1
                short = "%s(%d)" % (short[:limit - 2], used[short])
            else:
                used[short] = 1
            out.append(short)
        return out

    prob_labels = _short_labels(top_problems)
    sol_labels = _short_labels(top_solutions)

    n_cells = len(top_problems) * len(top_solutions)
    use_echarts = n_cells > get_limit(settings, "heatmap_max_cells")
    z_counts = [[int(counts.loc[p, s]) for s in top_solutions] for p in top_problems]
    if use_echarts and n_cells > get_limit(settings, "echarts_threshold_cells"):
        fig = echarts_heatmap(z_counts, sol_labels, prob_labels,
                              title="문제–해결수단 매트릭스 (건수)")
    else:
        fig = heatmap(growth_z, sol_labels, prob_labels,
                      title="문제–해결수단 매트릭스 (색=최근 성장률, hover=건수·장벽)",
                      colorscale="RdYlGn", hovertext=hover, colorbar_title="성장률", zmid=0)
        fig["counts_z"] = z_counts
        # 플롯 영역 확보: 행 수 비례 높이 + 라벨 폰트·여백 제한
        fig["layout"]["height"] = max(460, 140 + 26 * len(top_problems))
        # 축 제목 명시 — 화면 판독 + Excel 다운로드 시 행/열 의미 식별용
        fig["layout"]["xaxis"].update({"tickfont": {"size": 10}, "tickangle": -35,
                                       "title": {"text": "해결수단 (B축 분류)", "standoff": 6}})
        fig["layout"]["yaxis"].update({"tickfont": {"size": 10},
                                       "title": {"text": "해결과제 (C축 분류)", "standoff": 6}})
        fig["layout"]["margin"] = {"l": 150, "r": 30, "t": 48, "b": 110}

    zeros = int(sum(1 for row in z_counts for v in row if v == 0))
    flat = [(p, s, int(counts.loc[p, s])) for p in top_problems for s in top_solutions
            if counts.loc[p, s] > 0]
    flat.sort(key=lambda t: -t[2])
    sentences, metrics = [], {"n_cells": n_cells, "empty_cells": zeros}
    if flat:
        p0, s0, c0 = flat[0]
        sentences.append("%s 기준 최다 조합은 '%s × %s'(%s건)이며, 매트릭스 %s개 셀 중 "
                         "%s개(%s)가 공백입니다."
                         % (period_label(work), p0, s0, fmt_num(c0), fmt_num(n_cells),
                            fmt_num(zeros), fmt_pct(zeros / float(n_cells))))
    growth_cells = [(p, s, g) for p, row in zip(top_problems, growth_z)
                    for s, g in zip(top_solutions, row) if g is not None and g > 0.3
                    and cell_meta.get("%s|||%s" % (p, s), {}).get("count", 0) >= 3]
    if growth_cells:
        growth_cells.sort(key=lambda t: -t[2])
        p1, s1, g1 = growth_cells[0]
        sentences.append("최근 성장률이 가장 높은 조합은 '%s × %s'(%s)로 긍정 요인이며, "
                         "동일 셀 진입 기업 증가는 위험 요인입니다."
                         % (p1, s1, fmt_pct(g1)))
    insight = build_insight(
        sentences, metrics,
        drills=[{"label": "최다 셀 근거 특허",
                 "drill": {"type": "cell", "problem": flat[0][0], "solution": flat[0][1]}}]
        if flat else [],
        small_sample=check_small_sample(len(sub), settings))
    return ok_result({"figure": fig, "problems": top_problems, "solutions": top_solutions,
                      "problem_labels": prob_labels, "solution_labels": sol_labels,
                      "cells": cell_meta, "engine": "echarts" if use_echarts else "plotly"},
                     insight=insight,
                     meta={"n_with_ps": int(len(work)), "truncated":
                           len(work["problem"].unique()) > len(top_problems)
                           or len(work["solution"].unique()) > len(top_solutions)})


def cell_detail(df, settings, problem, solution):
    """셀 클릭 패널 데이터: 연도별 추이·상위 출원인·대표 청구항·유효비율·인사이트.

    매트릭스가 C축(해결과제)×B축(해결수단) 기반이므로 셀 매칭도 축 리스트
    포함 여부로 판단한다 (축이 없으면 구버전 텍스트 컬럼으로 폴백).
    """
    p, s = str(problem).strip(), str(solution).strip()
    if "_tech_c_list" in df.columns and "_tech_b_list" in df.columns:
        cell = df[df["_tech_c_list"].map(lambda lst: p in (lst or []))
                  & df["_tech_b_list"].map(lambda lst: s in (lst or []))]
    elif "problem" in df.columns and "solution" in df.columns:
        cell = df[(df["problem"].astype(str).str.strip() == p)
                  & (df["solution"].astype(str).str.strip() == s)]
    else:
        return disabled_result(["기술분류 (C축)=해결과제", "기술분류 (B축)=해결수단"],
                               message=_BC_DISABLED_MSG)
    if not len(cell):
        return empty_result("해당 조합의 특허가 없습니다.")
    years = cell["_base_year"].dropna().astype(int)
    trend = year_counts(years) if len(years) else pd.Series(dtype=float)
    recent = int(get_threshold(settings, "recent_years"))
    growth, _ = robust_growth(trend, recent_years=recent) if len(trend) else (None, "n/a")
    flags = cell["_active_flag"]
    known = flags.map(lambda v: v is not None)
    active_ratio = float(flags[known].map(lambda v: v is True).mean()) if known.any() else None
    top_apps = cell["applicant_display"].replace("", np.nan).dropna().value_counts().head(5)
    rep_claim = None
    if "indep_claim" in cell.columns:
        claims = cell["indep_claim"].dropna().astype(str)
        claims = claims[claims.str.strip() != ""]
        if len(claims):
            rep_claim = claims.iloc[0][:600]
    norm_growth = float(normalize_series([max(growth or 0, 0)], log=False)[0]) if growth else 0.0
    opp = round(norm_growth * (1 - (active_ratio or 0)), 4)
    sentences = ["'%s × %s' 조합은 총 %s건이며 최근 성장률 %s, 유효특허 비율 %s입니다."
                 % (str(problem)[:40], str(solution)[:40], fmt_num(len(cell)),
                    fmt_pct(growth) if growth is not None else "계산 불가",
                    fmt_pct(active_ratio) if active_ratio is not None else "미상")]
    insight = build_insight(sentences, {"opportunity_score": opp},
                            small_sample=check_small_sample(len(cell), settings))
    return ok_result({
        "count": int(len(cell)), "growth": growth, "active_ratio": active_ratio,
        "opportunity_score": opp,
        "trend": {"years": [int(y) for y in trend.index], "counts": [float(v) for v in trend.values]},
        "top_applicants": [{"name": str(a), "count": int(c)} for a, c in top_apps.items()],
        "representative_claim": rep_claim,
    }, insight=insight)


# ---------------------------------------------------------------------------
# 의미 그룹 매트릭스 — 해결과제·해결수단을 각각 임베딩해 유사 그룹으로 묶은 표
# ---------------------------------------------------------------------------
def _embed_phrases(texts, settings):
    """고유 문구 목록 임베딩 (KR-SBERT adapter → TF-IDF 폴백). (vectors, method)."""
    import hashlib
    from src.embedding_adapter import get_adapter
    from src.analyses.claim_density import _tfidf_vectors
    vectors, method = None, None
    adapter = get_adapter(settings)
    if adapter is not None:
        ids = [hashlib.sha1(t.encode("utf-8")).hexdigest()[:16] for t in texts]
        emb = adapter.get_embeddings(ids, texts)
        got = [emb.get(i) for i in ids]
        dims = {len(v) for v in got if v is not None}
        if all(v is not None for v in got) and len(dims) == 1:
            vectors = np.vstack(got).astype(np.float64)
            method = "adapter:%s" % adapter.name
    if vectors is None:
        vectors = np.asarray(_tfidf_vectors(list(texts)), dtype=np.float64)
        method = "tfidf_fallback"
    # 0 벡터(어휘 미포함 희귀 문구)는 서로 직교하는 단위벡터로 대체 → 어느 그룹에도
    # 억지로 묶이지 않고 단독 그룹이 된다 (cosine 군집의 0-벡터 오류 방지).
    norms = np.linalg.norm(vectors, axis=1)
    for zi in np.where(norms == 0)[0]:
        vectors[zi, int(zi) % vectors.shape[1]] = 1.0
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / norms, method


def _semantic_groups(value_counts, settings):
    """고유 문구 → 의미 그룹 (계층 군집, 코사인 거리 임계값 방식).

    군집법: AgglomerativeClustering(cosine, average linkage,
    distance_threshold=ps_group_distance). 군집 수를 미리 정하지 않고
    "이 거리보다 가까운 문구끼리 묶는다" 단일 파라미터로 동작한다 —
    임계값은 Settings → 임계값 ps_group_distance 로 조정 가능.
    반환: (mapping{문구→gid}, groups[{gid,label,members,n}], method) 또는 (None,None,사유)
    """
    texts = [str(t) for t in value_counts.index[:300]]
    if len(texts) < 4:
        return None, None, "고유 문구가 %d개뿐 (최소 4개)" % len(texts)
    vectors, method = _embed_phrases(texts, settings)
    from sklearn.cluster import AgglomerativeClustering
    dist = float(get_threshold(settings, "ps_group_distance"))
    kwargs = {"n_clusters": None, "distance_threshold": dist, "linkage": "average"}
    try:
        model = AgglomerativeClustering(metric="cosine", **kwargs)
        labels = model.fit_predict(vectors)
    except TypeError:  # sklearn<1.2 는 metric 대신 affinity
        model = AgglomerativeClustering(affinity="cosine", **kwargs)
        labels = model.fit_predict(vectors)
    by_gid = {}
    for t, l in zip(texts, labels):
        by_gid.setdefault(int(l), []).append(t)
    groups, mapping = [], {}
    for members in by_gid.values():
        members.sort(key=lambda t: -int(value_counts.get(t, 0)))
        total = int(sum(int(value_counts.get(t, 0)) for t in members))
        rep = members[0]
        label = rep[:20] + ("…" if len(rep) > 20 else "")
        if len(members) > 1:
            label += " 외 %d" % (len(members) - 1)
        groups.append({"label": label, "rep": rep, "members": members, "n": total})
    groups.sort(key=lambda g: -g["n"])
    for gid, g in enumerate(groups):
        g["gid"] = gid
        for t in g["members"]:
            mapping[t] = gid
    return mapping, groups, method


def compute_ps_semantic(df, settings):
    """의미 그룹 매트릭스: 임베딩 유사도로 묶은 해결과제 그룹 × 해결수단 그룹."""
    missing = [label for col, label in (("problem", "해결과제"), ("solution", "해결수단"))
               if col not in df.columns]
    if missing:
        return disabled_result(missing)
    work = df.copy()
    work["problem"] = _clean_text_series(work["problem"])
    work["solution"] = _clean_text_series(work["solution"])
    work = work[work["problem"].notna() & work["solution"].notna()]
    if len(work) < 10:
        return empty_result("해결과제·해결수단 값이 있는 특허가 부족합니다 (최소 10건).")
    p_counts = work["problem"].value_counts()
    s_counts = work["solution"].value_counts()
    p_map, p_groups, p_method = _semantic_groups(p_counts, settings)
    s_map, s_groups, s_method = _semantic_groups(s_counts, settings)
    if p_map is None or s_map is None:
        return empty_result("의미 그룹을 만들 수 없습니다 — %s. 고유 문구가 적으면 "
                            "'원문 기준' 보기를 사용하세요."
                            % (p_method if p_map is None else s_method))

    max_rows = get_limit(settings, "matrix_max_rows")
    p_show = p_groups[:max_rows]
    s_show = s_groups[:max_rows]
    p_keep = {g["gid"] for g in p_show}
    s_keep = {g["gid"] for g in s_show}
    z = [[0] * len(s_show) for _ in p_show]
    p_pos = {g["gid"]: i for i, g in enumerate(p_show)}
    s_pos = {g["gid"]: i for i, g in enumerate(s_show)}
    n_used = 0
    for p, s in zip(work["problem"], work["solution"]):
        pg, sg = p_map.get(str(p)), s_map.get(str(s))
        if pg in p_keep and sg in s_keep:
            z[p_pos[pg]][s_pos[sg]] += 1
            n_used += 1
    hover = [["<b>%s</b> × <b>%s</b><br>%d건<br>과제 예: %s<br>수단 예: %s"
              % (pg_["label"], sg_["label"], z[i][j],
                 " / ".join(m[:24] for m in pg_["members"][:2]),
                 " / ".join(m[:24] for m in sg_["members"][:2]))
              for j, sg_ in enumerate(s_show)] for i, pg_ in enumerate(p_show)]
    fig = heatmap(z, [g["label"] for g in s_show], [g["label"] for g in p_show],
                  title="문제–해결수단 의미 그룹 매트릭스 (임베딩 유사 문구 통합, 셀=건수)",
                  colorscale="YlGnBu", hovertext=hover, colorbar_title="건수")
    fig["layout"]["xaxis"]["title"] = {"text": "해결수단 그룹", "standoff": 6}
    fig["layout"]["yaxis"]["title"] = {"text": "해결과제 그룹", "standoff": 6}
    fig["data"][0]["customdata"] = [
        [{"drill": {"type": "cell_group",
                    "problems": pg_["members"][:50],
                    "solutions": sg_["members"][:50]}}
         for sg_ in s_show] for pg_ in p_show]

    zeros = sum(1 for row in z for v in row if v == 0)
    n_cells = len(p_show) * len(s_show)
    best_i, best_j = max(((i, j) for i in range(len(p_show))
                          for j in range(len(s_show))), key=lambda ij: z[ij[0]][ij[1]])
    sentences = [
        "임베딩 유사도로 해결과제 %s개 문구를 %s개 그룹으로, 해결수단 %s개 문구를 "
        "%s개 그룹으로 통합했습니다 (유사 표현 중복 제거)."
        % (fmt_num(len(p_counts)), fmt_num(len(p_groups)),
           fmt_num(len(s_counts)), fmt_num(len(s_groups))),
        "최다 조합은 '%s × %s'(%s건)이며, 그룹 매트릭스 %s개 셀 중 %s개(%s)가 "
        "공백입니다 — 원문 매트릭스보다 실질 공백을 판단하기 쉽습니다."
        % (p_show[best_i]["label"], s_show[best_j]["label"],
           fmt_num(z[best_i][best_j]), fmt_num(n_cells), fmt_num(zeros),
           fmt_pct(zeros / float(n_cells))),
        "그룹 라벨은 그룹 내 최다 빈도 문구이며, 셀 클릭 시 그룹에 속한 모든 문구의 "
        "특허가 열립니다.",
    ]
    insight = build_insight(
        sentences,
        {"n_problem_phrases": int(len(p_counts)), "n_problem_groups": len(p_groups),
         "n_solution_phrases": int(len(s_counts)), "n_solution_groups": len(s_groups),
         "empty_cells": zeros, "n_cells": n_cells,
         "embedding": p_method},
        small_sample=check_small_sample(len(work), settings))
    return ok_result(
        {"figure": fig, "group_mode": "semantic",
         "problem_groups": [{k: g[k] for k in ("gid", "label", "members", "n")}
                            for g in p_show],
         "solution_groups": [{k: g[k] for k in ("gid", "label", "members", "n")}
                             for g in s_show],
         "methods": {"embedding": p_method,
                     "clustering": "agglomerative(cosine·average, "
                                   "distance<%.2f)" % float(
                                       get_threshold(settings, "ps_group_distance"))}},
        insight=insight,
        meta={"note": "그룹핑은 임베딩 코사인 거리 기반 계층 군집이며, 거리 임계값은 "
                      "Settings → 임계값 ps_group_distance 로 조정할 수 있습니다 "
                      "(낮출수록 더 엄격하게 나뉨). 상투구('본 발명은' 등)는 "
                      "전처리에서 제거됩니다."})
