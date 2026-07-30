# -*- coding: utf-8 -*-
"""
analyses/problem_solution.py — 문제–해결수단 매트릭스 (1단계).

분석 목적:
  해결과제(행) × 해결수단(열) 매트릭스로 R&D 접근 조합의 밀집/공백을 파악한다.

필수 컬럼: 해결과제, 해결수단 — 없으면 분석 비활성화 + 텍스트 추출 모듈 연결
  인터페이스 안내만 제공 (임의 추출 결과 생성 금지).
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


def compute_problem_solution(df, settings):
    """문제–해결수단 매트릭스 계산."""
    missing = [label for col, label in (("problem", "해결과제"), ("solution", "해결수단"))
               if col not in df.columns]
    if missing:
        return disabled_result(
            missing,
            message=("필수 컬럼(%s)이 없어 문제–해결수단 매트릭스를 사용할 수 없습니다. "
                     "사전 추출 결과 컬럼을 매핑하거나, 텍스트 추출 모듈(요약/청구항 → "
                     "해결과제·해결수단)을 연결한 뒤 결과 컬럼을 매핑하세요. "
                     "임의 추출은 수행하지 않습니다." % ", ".join(missing)))
    if not len(df):
        return empty_result()
    work = df.copy()
    work["problem"] = _clean_text_series(work["problem"])
    work["solution"] = _clean_text_series(work["solution"])
    work = work[work["problem"].notna() & work["solution"].notna()]
    if not len(work):
        return empty_result("해결과제·해결수단 값이 있는 특허가 없습니다.")

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
                                       "title": {"text": "해결수단", "standoff": 6}})
        fig["layout"]["yaxis"].update({"tickfont": {"size": 10},
                                       "title": {"text": "해결과제", "standoff": 6}})
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
    """셀 클릭 패널 데이터: 연도별 추이·상위 출원인·대표 청구항·유효비율·인사이트."""
    if "problem" not in df.columns or "solution" not in df.columns:
        return disabled_result(["해결과제", "해결수단"])
    cell = df[(df["problem"].astype(str).str.strip() == str(problem))
              & (df["solution"].astype(str).str.strip() == str(solution))]
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
