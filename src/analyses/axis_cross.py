# -*- coding: utf-8 -*-
"""
analyses/axis_cross.py — 기술분류 A·B·C축 교차 해석.

배경:
  WIPS 데이터에는 서로 다른 관점의 분류 체계가 여러 개 있을 수 있다
  (예: A축=기술 관점, B축=응용처 관점, C축=재료/공정 관점).
  A축은 기존 기술 대/중/소/다중 분류이고, B·C축은 컬럼 매핑의
  "B축 대/중/소분류", "C축 대/중/소분류" 개념으로 매핑한다 (소→중→대 우선).

분석 (매핑된 축만 사용 — 없는 축은 자동 제외):
  - 축 pair 별 교차 히트맵: 셀 = 두 축 값을 동시에 가진 특허 수.
    A×B / A×C / B×C 중 데이터가 있는 조합만 생성.
  - 3축 모두 있으면 Sunburst (A → B → C 계층 분해)로 삼중 교차를 표시.
  - 셀 클릭 drill: {"type":"axis_cell","conds":[{"axis":"A","value":…},…]}.

인사이트: 최다 교차 조합, pair 별 공백 비율, 특정 A분류가 B/C축에서
집중/분산되는 정도(엔트로피).
예외처리: 축이 1개뿐이면 empty + B/C축 매핑 안내.
"""
from itertools import combinations

import math

import numpy as np

from src.config import get_limit
from src.insights import build_insight, fmt_num, fmt_pct, check_small_sample
from src.viz_payload import YLGNBU, ok_result, empty_result, heatmap, base_layout

_AXIS_COLS = (("A", "_tech_list", "A축(기술)"), ("B", "_tech_b_list", "B축"),
              ("C", "_tech_c_list", "C축"))


def compute_axis_cross(df, settings):
    """A·B·C 분류축 교차 히트맵 + 3축 Sunburst."""
    axes = {}
    for key, col, label in _AXIS_COLS:
        if col in df.columns and df[col].map(lambda v: bool(v)).any():
            axes[key] = {"col": col, "label": label}
    if len(axes) < 2:
        return empty_result(
            "교차 해석에는 분류축이 2개 이상 필요합니다 (현재 %d개: %s). "
            "Settings → 컬럼 매핑에서 'B축 대/중/소분류' 또는 'C축 대/중/소분류'를 "
            "매핑하세요 — 매핑된 축의 데이터만 사용하며 값을 추정하지 않습니다."
            % (len(axes), ", ".join(axes.keys()) or "없음"))

    max_cat = min(int(get_limit(settings, "matrix_max_rows")), 15)
    top_vals = {}
    for key in axes:
        col = axes[key]["col"]
        counts = {}
        for lst in df[col]:
            for v in set(lst or []):
                counts[v] = counts.get(v, 0) + 1
        top_vals[key] = [v for v, _c in
                         sorted(counts.items(), key=lambda kv: -kv[1])[:max_cat]]

    pairs = []
    for a_key, b_key in combinations(sorted(axes.keys()), 2):
        rows_v = top_vals[a_key]
        cols_v = top_vals[b_key]
        if not rows_v or not cols_v:
            continue
        rpos = {v: i for i, v in enumerate(rows_v)}
        cpos = {v: i for i, v in enumerate(cols_v)}
        z = [[0] * len(cols_v) for _ in rows_v]
        for la, lb in zip(df[axes[a_key]["col"]], df[axes[b_key]["col"]]):
            for va in set(la or []):
                if va not in rpos:
                    continue
                for vb in set(lb or []):
                    if vb in cpos:
                        z[rpos[va]][cpos[vb]] += 1
        n_cells = len(rows_v) * len(cols_v)
        zeros = sum(1 for row in z for v in row if v == 0)
        hover = [["%s(%s) × %s(%s): %d건"
                  % (va, a_key, vb, b_key, z[i][j])
                  for j, vb in enumerate(cols_v)] for i, va in enumerate(rows_v)]
        fig = heatmap(z, [str(v) for v in cols_v], [str(v) for v in rows_v],
                      title="%s × %s 교차 매트릭스 (셀=특허 수)"
                            % (axes[a_key]["label"], axes[b_key]["label"]),
                      colorscale=YLGNBU, hovertext=hover, colorbar_title="건수")
        fig["layout"]["xaxis"]["title"] = {"text": axes[b_key]["label"], "standoff": 6}
        fig["layout"]["yaxis"]["title"] = {"text": axes[a_key]["label"], "standoff": 6}
        fig["data"][0]["customdata"] = [
            [{"drill": {"type": "axis_cell",
                        "conds": [{"axis": a_key, "value": str(va)},
                                  {"axis": b_key, "value": str(vb)}]}}
             for vb in cols_v] for va in rows_v]
        # 최대 셀 + 행 분산도(행별 열 분포 엔트로피 평균)
        best = max(((i, j) for i in range(len(rows_v)) for j in range(len(cols_v))),
                   key=lambda ij: z[ij[0]][ij[1]])
        ents = []
        for row in z:
            tot = float(sum(row))
            if tot < 5:
                continue
            h = -sum((v / tot) * math.log(v / tot) for v in row if v > 0)
            k = sum(1 for v in row if v > 0)
            ents.append(h / math.log(len(cols_v)) if len(cols_v) > 1 else 0.0)
        pairs.append({
            "pair": "%s×%s" % (a_key, b_key),
            "a_axis": a_key, "b_axis": b_key, "figure": fig,
            "n_cells": n_cells, "zero_ratio": round(zeros / float(n_cells), 3),
            "top_cell": {"a": str(rows_v[best[0]]), "b": str(cols_v[best[1]]),
                         "n": int(z[best[0]][best[1]])},
            "avg_spread": round(float(np.mean(ents)), 3) if ents else None,
        })
    if not pairs:
        return empty_result("교차 집계 가능한 축 조합이 없습니다.")

    # 3축 Sunburst (A → B → C)
    sunburst = None
    if len(axes) == 3:
        triple = {}
        for la, lb, lc in zip(df["_tech_list"], df["_tech_b_list"], df["_tech_c_list"]):
            for va in set(la or []):
                if va not in top_vals["A"][:8]:
                    continue
                for vb in set(lb or []):
                    if vb not in top_vals["B"][:8]:
                        continue
                    for vc in set(lc or []):
                        if vc in top_vals["C"][:8]:
                            triple[(va, vb, vc)] = triple.get((va, vb, vc), 0) + 1
        if triple:
            keep = sorted(triple.items(), key=lambda kv: -kv[1])[:80]
            ids, labels, parents, values = [], [], [], []
            agg1, agg2 = {}, {}
            for (va, vb, vc), n in keep:
                agg1[va] = agg1.get(va, 0) + n
                agg2[(va, vb)] = agg2.get((va, vb), 0) + n
            for va, n in agg1.items():
                ids.append("A|%s" % va)
                labels.append(str(va))
                parents.append("")
                values.append(int(n))
            for (va, vb), n in agg2.items():
                ids.append("B|%s|%s" % (va, vb))
                labels.append(str(vb))
                parents.append("A|%s" % va)
                values.append(int(n))
            for (va, vb, vc), n in keep:
                ids.append("C|%s|%s|%s" % (va, vb, vc))
                labels.append(str(vc))
                parents.append("B|%s|%s" % (va, vb))
                values.append(int(n))
            sunburst = {"data": [{"type": "sunburst", "ids": ids, "labels": labels,
                                  "parents": parents, "values": values,
                                  "branchvalues": "total",
                                  "hovertemplate": "%{label}: %{value}건"
                                                   "<extra></extra>"}],
                        "layout": base_layout("3축 계층 분해 Sunburst — 안쪽부터 "
                                              "A축(기술) → B축 → C축", height=560)}

    sentences = []
    axis_names = ", ".join("%s(%s)" % (k, axes[k]["label"]) for k in sorted(axes))
    sentences.append("매핑된 분류축 %d개(%s)로 %d개 교차 매트릭스를 생성했습니다."
                     % (len(axes), axis_names, len(pairs)))
    biggest = max(pairs, key=lambda p: p["top_cell"]["n"])
    sentences.append("가장 밀집된 교차는 %s의 '%s × %s'(%s건)로, 두 관점이 만나는 "
                     "핵심 영역입니다."
                     % (biggest["pair"], biggest["top_cell"]["a"],
                        biggest["top_cell"]["b"], fmt_num(biggest["top_cell"]["n"])))
    emptiest = max(pairs, key=lambda p: p["zero_ratio"])
    sentences.append("%s 매트릭스는 셀의 %s가 공백입니다 — 한 축에서는 활발하지만 "
                     "다른 축과 결합되지 않은 영역이 후보 기회입니다."
                     % (emptiest["pair"], fmt_pct(emptiest["zero_ratio"])))
    for p in pairs:
        if p["avg_spread"] is not None and p["avg_spread"] <= 0.35:
            sentences.append("%s: 행별 분포 엔트로피 %.2f — %s축 값들이 특정 %s축 "
                             "값에 강하게 집중되어 두 분류가 사실상 연동됩니다."
                             % (p["pair"], p["avg_spread"], p["a_axis"], p["b_axis"]))
            break
    insight = build_insight(
        sentences,
        {"n_axes": len(axes), "pairs": [p["pair"] for p in pairs],
         "zero_ratios": {p["pair"]: p["zero_ratio"] for p in pairs},
         "top_cells": {p["pair"]: p["top_cell"] for p in pairs}},
        drills=[{"label": "최다 교차 특허 보기",
                 "drill": {"type": "axis_cell",
                           "conds": [{"axis": biggest["a_axis"],
                                      "value": biggest["top_cell"]["a"]},
                                     {"axis": biggest["b_axis"],
                                      "value": biggest["top_cell"]["b"]}]}}],
        small_sample=check_small_sample(len(df), settings))
    return ok_result(
        {"pairs": [{k: p[k] for k in ("pair", "figure", "zero_ratio", "top_cell",
                                      "avg_spread")} for p in pairs],
         "sunburst": sunburst,
         "axes": [{"key": k, "label": axes[k]["label"],
                   "n_categories": len(top_vals[k])} for k in sorted(axes)]},
        insight=insight,
        meta={"note": "매핑된 축의 실제 데이터만 사용하며(없는 축 자동 제외), 각 축은 "
                      "소분류→중분류→대분류 우선으로 가장 세밀한 매핑 레벨을 씁니다. "
                      "표시 범주는 축당 상위 %d개입니다." % max_cat})
