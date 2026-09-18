# -*- coding: utf-8 -*-
"""
analyses/custom_chart.py — 사용자 정의 차트 빌더.

목적:
  정해진 분석 화면이 아니라, 사용자가 직접 "어떤 차트를 / X축에 무엇을 /
  Y축에 무엇을 / (버블이면) 크기에 무엇을" 골라 그리는 기능.

구성:
  DIMENSIONS : 분류 항목 (연도·출원인·기술분류·국가·법적상태·IPC 등)
               한 문헌이 여러 값을 가질 수 있는 항목(출원인·기술분류·IPC·
               발명자)은 다중값으로 전개한다 (공동출원 각각 집계 원칙과 동일).
  MEASURES   : 값 항목 (문헌 수·평균 피인용·패밀리 규모·등록률 등)

차트 종류별 축 의미 (프론트가 이 규칙대로 선택 UI를 구성한다):
  bar / line / pie   : X축=분류, Y축=값
  bubble_matrix      : X축=분류, Y축=분류, 버블 크기=값
  bubble / scatter   : 점 단위=분류, X축=값, Y축=값, (버블) 크기=값
  heatmap            : X축=분류, Y축=분류, 색=값

모든 수치는 매핑된 실제 데이터에서만 계산한다 (임의 값 생성 금지).
값이 없는 축·표본 부족은 사유와 함께 empty_result 로 반환한다.
Drill-down: 분류 항목이 select_patents 가 아는 조건이면 클릭 시 근거 특허가
열리도록 customdata.drill 을 붙인다.
"""
import numpy as np
import pandas as pd

from src.config import get_limit
from src.insights import build_insight, fmt_num, check_small_sample
from src.preprocessing import parse_multiclass_cell
from src.viz_payload import (BLUES, PALETTE, ok_result, empty_result, base_layout,
                             bar_chart, line_chart, heatmap, color_for)

# ---------------------------------------------------------------------------
# 분류 항목 (dimension)
# ---------------------------------------------------------------------------
# key: (라벨, 필요 컬럼 판정 함수, 값 추출 함수(df)->Series(list), drill 생성기)
_IPC_SUB_LEN = 4


def _has(df, col):
    return col in df.columns and df[col].astype(str).str.strip().ne("").any()


def _list_col(df, col):
    return df[col].map(lambda v: [str(x) for x in (v or []) if str(x).strip()])


def _scalar_col(df, col, upper=False):
    s = df[col].astype(str).str.strip()
    if upper:
        s = s.str.upper()
    return s.map(lambda v: [v] if v and v.lower() not in ("nan", "none") else [])


def _dim_year(df):
    return df["_base_year"].map(
        lambda v: [] if v is None or (isinstance(v, float) and np.isnan(v))
        else [str(int(v))])


def _dim_applicant(df):
    if "_co_applicants_display" in df.columns and \
            df["_co_applicants_display"].map(lambda v: bool(v)).any():
        return _list_col(df, "_co_applicants_display")
    return _scalar_col(df, "applicant_display")


def _dim_ipc(df):
    return df["ipc"].map(lambda v: sorted({
        str(x).strip().upper().replace(" ", "")[:_IPC_SUB_LEN]
        for x in parse_multiclass_cell(v)
        if len(str(x).strip().replace(" ", "")) >= _IPC_SUB_LEN}))


def _dim_bool(col, yes="Y", no="N"):
    def fn(df):
        return df[col].map(lambda v: [yes] if v is True else ([no] if v is False else []))
    return fn


DIMENSIONS = [
    {"key": "year", "label": "출원연도", "get": _dim_year,
     "need": lambda df: df["_base_year"].notna().any(),
     "drill": lambda v: {"type": "year", "year": int(v)}, "order": "num"},
    {"key": "applicant", "label": "출원인", "get": _dim_applicant,
     "need": lambda df: _has(df, "applicant_display"),
     "drill": lambda v: {"type": "applicant", "applicant": v,
                         "applicant_scope": "any"}},
    {"key": "tech", "label": "기술분류(전체)",
     "get": lambda df: _list_col(df, "_tech_list"),
     "need": lambda df: df["_tech_list"].map(len).any(),
     "drill": lambda v: {"type": "tech", "tech": v}},
    {"key": "tech_l1", "label": "기술 대분류",
     "get": lambda df: _list_col(df, "_tech_l1_list"),
     "need": lambda df: "_tech_l1_list" in df.columns
     and df["_tech_l1_list"].map(len).any(),
     "drill": lambda v: {"tech_l1": v}},
    {"key": "tech_l2", "label": "기술 중분류",
     "get": lambda df: _list_col(df, "_tech_l2_list"),
     "need": lambda df: "_tech_l2_list" in df.columns
     and df["_tech_l2_list"].map(len).any(),
     "drill": lambda v: {"tech_l2": v}},
    {"key": "tech_l3", "label": "기술 소분류",
     "get": lambda df: _list_col(df, "_tech_l3_list"),
     "need": lambda df: "_tech_l3_list" in df.columns
     and df["_tech_l3_list"].map(len).any(),
     "drill": lambda v: {"tech_l3": v}},
    {"key": "ipc_main", "label": "IPC/CPC 서브클래스", "get": _dim_ipc,
     "need": lambda df: _has(df, "ipc"),
     "drill": lambda v: {"ipc_main": v}},
    {"key": "country", "label": "국가",
     "get": lambda df: _scalar_col(df, "country", upper=True),
     "need": lambda df: _has(df, "country"),
     "drill": lambda v: {"country": v}},
    {"key": "legal_status", "label": "법적상태",
     "get": lambda df: _scalar_col(df, "legal_status_norm"),
     "need": lambda df: _has(df, "legal_status_norm"),
     "drill": lambda v: {"legal_status": v}},
    {"key": "owner", "label": "현재 권리자",
     "get": lambda df: _scalar_col(df, "owner_display"),
     "need": lambda df: _has(df, "owner_display"),
     "drill": lambda v: {"owner": v}},
    {"key": "gov_program", "label": "국가연구 과제",
     "get": lambda df: _scalar_col(df, "gov_program"),
     "need": lambda df: _has(df, "gov_program"),
     "drill": lambda v: {"gov_program": v}},
    {"key": "inventor", "label": "발명자",
     "get": lambda df: _list_col(df, "_inventor_list"),
     "need": lambda df: "_inventor_list" in df.columns
     and df["_inventor_list"].map(len).any(),
     "drill": lambda v: {"inventor": v}},
    {"key": "agent", "label": "대리인",
     "get": lambda df: _scalar_col(df, "agent"),
     "need": lambda df: _has(df, "agent"), "drill": None},
    {"key": "examiner", "label": "심사관",
     "get": lambda df: _scalar_col(df, "examiner"),
     "need": lambda df: _has(df, "examiner"), "drill": None},
    {"key": "assign_type", "label": "최근 양도유형",
     "get": lambda df: _scalar_col(df, "assign_type"),
     "need": lambda df: _has(df, "assign_type"), "drill": None},
    {"key": "first_country", "label": "최우선출원국",
     "get": lambda df: _scalar_col(df, "first_filing_country", upper=True),
     "need": lambda df: _has(df, "first_filing_country"),
     "drill": lambda v: {"first_country": v}},
    {"key": "is_granted", "label": "등록 여부",
     "get": _dim_bool("_is_granted_bool", "등록", "미등록"),
     "need": lambda df: df["_is_granted_bool"].map(lambda v: v is not None).any(),
     "drill": None},
    {"key": "is_active", "label": "유효 여부",
     "get": _dim_bool("_active_flag", "유효", "소멸"),
     "need": lambda df: df["_active_flag"].map(lambda v: v is not None).any(),
     "drill": None},
]
DIM_BY_KEY = {d["key"]: d for d in DIMENSIONS}


# ---------------------------------------------------------------------------
# 값 항목 (measure)
# ---------------------------------------------------------------------------
def _m_count(sub):
    return float(len(sub))


def _num_mean(col):
    def fn(sub):
        if col not in sub.columns:
            return None
        v = pd.to_numeric(sub[col], errors="coerce").dropna()
        return float(v.mean()) if len(v) else None
    return fn


def _num_sum(col):
    def fn(sub):
        if col not in sub.columns:
            return None
        v = pd.to_numeric(sub[col], errors="coerce").dropna()
        return float(v.sum()) if len(v) else None
    return fn


def _rate(flag_col, want=True):
    def fn(sub):
        if flag_col not in sub.columns:
            return None
        known = sub[flag_col].map(lambda v: v is not None)
        if not known.any():
            return None
        vals = sub.loc[known, flag_col].map(lambda v: v is want)
        return float(vals.mean())
    return fn


def _nunique_list(col):
    def fn(sub):
        if col not in sub.columns:
            return None
        names = {str(x) for lst in sub[col] for x in (lst or []) if str(x).strip()}
        return float(len(names))
    return fn


MEASURES = [
    {"key": "count", "label": "문헌 수", "get": _m_count,
     "need": lambda df: True, "fmt": "int"},
    {"key": "cites_forward_avg", "label": "평균 피인용 수",
     "get": _num_mean("cites_forward"),
     "need": lambda df: "cites_forward" in df.columns
     and df["cites_forward"].notna().any()},
    {"key": "cites_forward_sum", "label": "피인용 수 합계",
     "get": _num_sum("cites_forward"),
     "need": lambda df: "cites_forward" in df.columns
     and df["cites_forward"].notna().any(), "fmt": "int"},
    {"key": "cites_backward_avg", "label": "평균 인용 수",
     "get": _num_mean("cites_backward"),
     "need": lambda df: "cites_backward" in df.columns
     and df["cites_backward"].notna().any()},
    {"key": "family_size_avg", "label": "평균 패밀리 규모",
     "get": _num_mean("family_size"),
     "need": lambda df: "family_size" in df.columns
     and df["family_size"].notna().any()},
    {"key": "family_country_avg", "label": "평균 패밀리 국가 수",
     "get": _num_mean("family_country_count"),
     "need": lambda df: "family_country_count" in df.columns
     and df["family_country_count"].notna().any()},
    {"key": "claims_avg", "label": "평균 청구항 수",
     "get": _num_mean("claims_count"),
     "need": lambda df: "claims_count" in df.columns
     and df["claims_count"].notna().any()},
    {"key": "indep_claims_avg", "label": "평균 독립항 수",
     "get": _num_mean("indep_claims_count"),
     "need": lambda df: "indep_claims_count" in df.columns
     and df["indep_claims_count"].notna().any()},
    {"key": "drawings_avg", "label": "평균 도면 수",
     "get": _num_mean("drawings_count"),
     "need": lambda df: "drawings_count" in df.columns
     and df["drawings_count"].notna().any()},
    {"key": "npl_avg", "label": "평균 비특허문헌(NPL) 인용",
     "get": _num_mean("npl_count"),
     "need": lambda df: "npl_count" in df.columns and df["npl_count"].notna().any()},
    {"key": "grant_rate", "label": "등록률", "get": _rate("_is_granted_bool"),
     "need": lambda df: df["_is_granted_bool"].map(lambda v: v is not None).any(),
     "fmt": "pct"},
    {"key": "active_rate", "label": "유효율", "get": _rate("_active_flag"),
     "need": lambda df: df["_active_flag"].map(lambda v: v is not None).any(),
     "fmt": "pct"},
    {"key": "applicants_nunique", "label": "참여 출원인 수(고유)",
     "get": _nunique_list("_co_applicants_display"),
     "need": lambda df: "_co_applicants_display" in df.columns
     and df["_co_applicants_display"].map(lambda v: bool(v)).any(), "fmt": "int"},
    {"key": "inventors_nunique", "label": "발명자 수(고유)",
     "get": _nunique_list("_inventor_list"),
     "need": lambda df: "_inventor_list" in df.columns
     and df["_inventor_list"].map(len).any(), "fmt": "int"},
]
MEASURE_BY_KEY = {m["key"]: m for m in MEASURES}

CHART_TYPES = [
    {"key": "bar", "label": "막대 차트", "axes": ["x_dim", "y_measure"],
     "desc": "분류별 값 비교 — 순위·점유 파악에 가장 기본"},
    {"key": "line", "label": "선 차트 (추이)", "axes": ["x_dim", "y_measure"],
     "desc": "시간(연도) 등 순서가 있는 분류의 변화 추이"},
    {"key": "pie", "label": "파이 차트 (구성비)", "axes": ["x_dim", "y_measure"],
     "desc": "전체 대비 각 분류의 비중"},
    {"key": "bubble_matrix", "label": "버블 매트릭스 (분류 × 분류)",
     "axes": ["x_dim", "y_dim", "size_measure"],
     "desc": "두 분류의 교차점마다 버블 — 크기로 값을 표현 (예: 기술 × 연도)"},
    {"key": "bubble", "label": "버블 차트 (값 × 값 + 크기)",
     "axes": ["group_dim", "x_measure", "y_measure", "size_measure"],
     "desc": "점 하나가 한 분류(예: 출원인) — 두 값으로 위치, 세 번째 값으로 크기"},
    {"key": "scatter", "label": "산점도 (값 × 값)",
     "axes": ["group_dim", "x_measure", "y_measure"],
     "desc": "점 하나가 한 분류 — 두 지표의 관계·포지셔닝"},
    {"key": "heatmap", "label": "히트맵 (분류 × 분류)",
     "axes": ["x_dim", "y_dim", "color_measure"],
     "desc": "두 분류의 교차 값을 색 농도로 — 밀집 영역 파악"},
]
CHART_BY_KEY = {c["key"]: c for c in CHART_TYPES}


def chart_fields(df):
    """현재 데이터에서 사용 가능한 차트 종류·분류 항목·값 항목 카탈로그."""
    dims, measures = [], []
    for d in DIMENSIONS:
        try:
            ok = bool(d["need"](df))
        except Exception:
            ok = False
        if ok:
            dims.append({"key": d["key"], "label": d["label"],
                         "drillable": d.get("drill") is not None})
    for m in MEASURES:
        try:
            ok = bool(m["need"](df))
        except Exception:
            ok = False
        if ok:
            measures.append({"key": m["key"], "label": m["label"],
                             "fmt": m.get("fmt", "num")})
    return {"chart_types": CHART_TYPES, "dimensions": dims, "measures": measures}


def _explode(df, dim_key):
    """분류 항목 기준 전개 프레임 (index=원 문헌 index, 값=분류값)."""
    dim = DIM_BY_KEY[dim_key]
    lists = dim["get"](df)
    idx, vals = [], []
    for i, lst in lists.items():
        for v in (lst or []):
            idx.append(i)
            vals.append(str(v))
    return pd.Series(vals, index=idx, dtype=object)


def _measure_value(df, rows_index, measure_key):
    m = MEASURE_BY_KEY[measure_key]
    sub = df.loc[list(dict.fromkeys(rows_index))]
    try:
        return m["get"](sub)
    except Exception:
        return None


def _fmt_val(measure_key, v):
    if v is None:
        return "-"
    m = MEASURE_BY_KEY.get(measure_key, {})
    if m.get("fmt") == "pct":
        return "%.1f%%" % (float(v) * 100)
    if m.get("fmt") == "int":
        return fmt_num(int(round(float(v))))
    return "%.2f" % float(v)


def _sorted_categories(dim_key, groups, values, top_n):
    """분류값 정렬: 연도 등 숫자형은 값 순, 그 외는 측정값 내림차순 Top-N."""
    dim = DIM_BY_KEY[dim_key]
    keys = list(groups.keys())
    if dim.get("order") == "num":
        try:
            return sorted(keys, key=lambda k: float(k))
        except (TypeError, ValueError):
            return sorted(keys)
    keys.sort(key=lambda k: -(values.get(k) if values.get(k) is not None else -1e18))
    return keys[:top_n]


def compute_custom_chart(df, settings, spec=None):
    """사용자 정의 차트 계산.

    spec: {"chart_type", "x", "y", "size", "group", "top_n"}
      - 축 의미는 CHART_TYPES[*]["axes"] 규칙을 따른다.
    """
    spec = spec or {}
    ctype = str(spec.get("chart_type") or "bar")
    if ctype not in CHART_BY_KEY:
        return empty_result("알 수 없는 차트 종류입니다: %s" % ctype)
    if not len(df):
        return empty_result()
    top_n = int(spec.get("top_n") or get_limit(settings, "top_n_default") or 10)
    top_n = max(2, min(top_n, 40))
    axes = CHART_BY_KEY[ctype]["axes"]

    def _need_dim(name, key):
        if not key or key not in DIM_BY_KEY:
            return "'%s' 에 사용할 분류 항목을 선택하세요." % name
        try:
            if not DIM_BY_KEY[key]["need"](df):
                return "'%s'(%s) 은 현재 데이터에 값이 없습니다." % (
                    DIM_BY_KEY[key]["label"], name)
        except Exception:
            return "'%s' 항목을 계산할 수 없습니다." % name
        return None

    def _need_measure(name, key):
        if not key or key not in MEASURE_BY_KEY:
            return "'%s' 에 사용할 값 항목을 선택하세요." % name
        return None

    # ---- 유형별 계산 -------------------------------------------------------
    if ctype in ("bar", "line", "pie"):
        err = _need_dim("X축", spec.get("x")) or _need_measure("Y축", spec.get("y"))
        if err:
            return empty_result(err)
        return _build_single_dim(df, settings, ctype, spec["x"], spec["y"], top_n)

    if ctype in ("bubble_matrix", "heatmap"):
        mkey = spec.get("size") or spec.get("y_measure") or spec.get("color") or "count"
        err = (_need_dim("X축", spec.get("x")) or _need_dim("Y축", spec.get("y"))
               or _need_measure("값", mkey))
        if err:
            return empty_result(err)
        if spec["x"] == spec["y"]:
            return empty_result("X축과 Y축에 서로 다른 분류 항목을 선택하세요.")
        return _build_matrix(df, settings, ctype, spec["x"], spec["y"], mkey, top_n)

    # bubble / scatter : 점 단위=분류, 축=값
    gkey = spec.get("group") or spec.get("x_dim")
    err = (_need_dim("점 단위", gkey) or _need_measure("X축", spec.get("x"))
           or _need_measure("Y축", spec.get("y")))
    if err:
        return empty_result(err)
    size_key = spec.get("size") if ctype == "bubble" else None
    if ctype == "bubble" and not size_key:
        size_key = "count"
    return _build_points(df, settings, ctype, gkey, spec["x"], spec["y"],
                         size_key, top_n)


def _group_rows(df, dim_key):
    ser = _explode(df, dim_key)
    groups = {}
    for i, v in zip(ser.index, ser.values):
        groups.setdefault(v, []).append(i)
    return groups


def _build_single_dim(df, settings, ctype, dim_key, measure_key, top_n):
    dim, meas = DIM_BY_KEY[dim_key], MEASURE_BY_KEY[measure_key]
    groups = _group_rows(df, dim_key)
    if not groups:
        return empty_result("'%s' 값이 있는 문헌이 없습니다." % dim["label"])
    values = {k: _measure_value(df, idx, measure_key) for k, idx in groups.items()}
    cats = _sorted_categories(dim_key, groups, values, top_n)
    cats = [c for c in cats if values.get(c) is not None]
    if not cats:
        return empty_result("'%s' 을(를) 계산할 수 있는 값이 없습니다." % meas["label"])
    ys = [float(values[c]) for c in cats]
    hover = ["%s · %s: %s (문헌 %s건)"
             % (c, meas["label"], _fmt_val(measure_key, values[c]),
                fmt_num(len(groups[c]))) for c in cats]
    custom = [{"drill": dim["drill"](c), "m": {dim["label"]: c,
                                               meas["label"]: values[c]}}
              if dim.get("drill") else {"m": {dim["label"]: c,
                                              meas["label"]: values[c]}}
              for c in cats]
    title = "%s별 %s" % (dim["label"], meas["label"])
    if ctype == "bar":
        horizontal = len(cats) > 8 or max(len(str(c)) for c in cats) > 8
        if horizontal:
            fig = bar_chart(cats[::-1], [round(v, 4) for v in ys][::-1], title=title,
                            orientation="h", x_title=meas["label"],
                            hovertext=hover[::-1], customdata=custom[::-1])
        else:
            fig = bar_chart(cats, [round(v, 4) for v in ys], title=title,
                            x_title=dim["label"], y_title=meas["label"],
                            hovertext=hover, customdata=custom)
    elif ctype == "line":
        fig = line_chart([{"name": meas["label"], "x": cats, "y": [round(v, 4) for v in ys]}],
                         dim["label"], meas["label"], title=title,
                         year_axis=(dim_key == "year"))
        fig["data"][0]["customdata"] = custom
        fig["data"][0]["hovertext"] = hover
        fig["data"][0]["hoverinfo"] = "text"
    else:  # pie
        fig = {"data": [{"type": "pie", "labels": cats,
                         "values": [round(v, 4) for v in ys],
                         "customdata": custom, "hovertext": hover,
                         "hoverinfo": "text",
                         "textinfo": "label+percent",
                         "marker": {"colors": [PALETTE[i % len(PALETTE)]
                                               for i in range(len(cats))]}}],
               "layout": base_layout(title)}
    if meas.get("fmt") == "pct" and ctype != "pie":
        axis = "xaxis" if (ctype == "bar" and len(cats) > 8) else "yaxis"
        fig["layout"].setdefault(axis, {})["tickformat"] = ".0%"
    top = cats[0] if ctype != "line" else max(cats, key=lambda c: values[c])
    sentences = ["'%s' 기준 %s가 가장 높은 항목은 '%s'(%s)입니다."
                 % (dim["label"], meas["label"], top, _fmt_val(measure_key, values[top])),
                 "표시 항목 %s개 — 사용자가 직접 선택한 축 구성이며, 값은 필터가 적용된 "
                 "현재 데이터에서 계산됩니다." % fmt_num(len(cats))]
    return ok_result({"figure": fig, "rows": [
        {"label": c, "value": values[c], "value_text": _fmt_val(measure_key, values[c]),
         "n": len(groups[c]),
         "drill": dim["drill"](c) if dim.get("drill") else None} for c in cats],
        "axis_info": {"x": dim["label"], "y": meas["label"]}},
        insight=build_insight(sentences, {"n_categories": len(cats)},
                              small_sample=check_small_sample(len(df), settings)))


def _build_matrix(df, settings, ctype, x_key, y_key, measure_key, top_n):
    xd, yd = DIM_BY_KEY[x_key], DIM_BY_KEY[y_key]
    meas = MEASURE_BY_KEY[measure_key]
    xs_all = _group_rows(df, x_key)
    ys_all = _group_rows(df, y_key)
    if not xs_all or not ys_all:
        return empty_result("선택한 두 분류 항목의 값이 함께 있는 문헌이 없습니다.")
    x_cnt = {k: len(v) for k, v in xs_all.items()}
    y_cnt = {k: len(v) for k, v in ys_all.items()}
    x_cats = _sorted_categories(x_key, xs_all, x_cnt, min(top_n, 20))
    y_cats = _sorted_categories(y_key, ys_all, y_cnt, min(top_n, 20))
    x_ser, y_ser = _explode(df, x_key), _explode(df, y_key)
    x_map, y_map = {}, {}
    for i, v in zip(x_ser.index, x_ser.values):
        x_map.setdefault(i, []).append(v)
    for i, v in zip(y_ser.index, y_ser.values):
        y_map.setdefault(i, []).append(v)
    cell_rows = {}
    for i in set(x_map) & set(y_map):
        for xv in x_map[i]:
            if xv not in x_cats:
                continue
            for yv in y_map[i]:
                if yv not in y_cats:
                    continue
                cell_rows.setdefault((xv, yv), []).append(i)
    if not cell_rows:
        return empty_result("두 분류가 함께 나타나는 문헌이 없어 교차 차트를 그릴 수 없습니다.")

    def _cell_drill(xv, yv):
        d = {}
        if xd.get("drill"):
            d.update(xd["drill"](xv))
        if yd.get("drill"):
            dy = yd["drill"](yv)
            # type 키 충돌 방지 — 조건 키만 병합 (select_patents 는 and 결합)
            dy.pop("type", None)
            d.update(dy)
        return d or None

    if ctype == "heatmap":
        z, hover, custom = [], [], []
        for yv in y_cats:
            row_z, row_h, row_c = [], [], []
            for xv in x_cats:
                rows = cell_rows.get((xv, yv), [])
                val = _measure_value(df, rows, measure_key) if rows else None
                row_z.append(round(float(val), 4) if val is not None else None)
                row_h.append("%s × %s · %s: %s (문헌 %s건)"
                             % (xv, yv, meas["label"], _fmt_val(measure_key, val),
                                fmt_num(len(rows))))
                row_c.append({"drill": _cell_drill(xv, yv),
                              "m": {xd["label"]: xv, yd["label"]: yv,
                                    meas["label"]: val}})
            z.append(row_z)
            hover.append(row_h)
            custom.append(row_c)
        fig = heatmap(z, x_cats, y_cats,
                      title="%s × %s — %s" % (xd["label"], yd["label"], meas["label"]),
                      colorscale=BLUES, hovertext=hover, colorbar_title=meas["label"])
        for tr in fig["data"]:
            tr["customdata"] = custom
        fig["layout"]["xaxis"]["title"] = xd["label"]
        fig["layout"]["yaxis"]["title"] = yd["label"]
    else:  # bubble_matrix
        pts = {"x": [], "y": [], "size": [], "hover": [], "custom": [], "val": []}
        for (xv, yv), rows in cell_rows.items():
            val = _measure_value(df, rows, measure_key)
            if val is None or float(val) <= 0:
                continue
            pts["x"].append(xv)
            pts["y"].append(yv)
            pts["val"].append(float(val))
            pts["hover"].append("%s × %s · %s: %s (문헌 %s건)"
                                % (xv, yv, meas["label"],
                                   _fmt_val(measure_key, val), fmt_num(len(rows))))
            pts["custom"].append({"drill": _cell_drill(xv, yv),
                                  "m": {xd["label"]: xv, yd["label"]: yv,
                                        meas["label"]: val}})
        if not pts["x"]:
            return empty_result("버블로 표시할 값(0 초과)이 없습니다.")
        vmax = max(pts["val"])
        sizes = [float(max(9, min(46, 9 + 37 * np.sqrt(v / vmax)))) for v in pts["val"]]
        fig = {"data": [{"type": "scatter", "mode": "markers", "cliponaxis": False,
                         "x": pts["x"], "y": pts["y"],
                         "hovertext": pts["hover"], "hoverinfo": "text",
                         "customdata": pts["custom"],
                         "marker": {"size": sizes, "color": pts["val"],
                                    "colorscale": BLUES,
                                    "colorbar": {"title": meas["label"],
                                                 "thickness": 12},
                                    "line": {"width": 0.5, "color": "#7f97ab"}}}],
               "layout": base_layout(
                   "%s × %s — 버블 크기=%s" % (xd["label"], yd["label"], meas["label"]),
                   xaxis={"title": xd["label"], "type": "category",
                          "categoryarray": x_cats, "automargin": True},
                   yaxis={"title": yd["label"], "type": "category",
                          "categoryarray": y_cats[::-1], "automargin": True},
                   height=max(420, 120 + 30 * len(y_cats)))}
    best = max(cell_rows.items(), key=lambda kv: len(kv[1]))
    sentences = ["'%s × %s' 교차에서 문헌이 가장 많은 조합은 %s × %s(%s건)입니다."
                 % (xd["label"], yd["label"], best[0][0], best[0][1],
                    fmt_num(len(best[1]))),
                 "표시 범위: %s %s개 × %s %s개 (각 축은 문헌 수 상위 기준)."
                 % (xd["label"], fmt_num(len(x_cats)), yd["label"], fmt_num(len(y_cats)))]
    return ok_result({"figure": fig,
                      "axis_info": {"x": xd["label"], "y": yd["label"],
                                    "value": meas["label"]}},
                     insight=build_insight(sentences, {},
                                           small_sample=check_small_sample(len(df), settings)))


def _build_points(df, settings, ctype, group_key, x_key, y_key, size_key, top_n):
    gd = DIM_BY_KEY[group_key]
    mx, my = MEASURE_BY_KEY[x_key], MEASURE_BY_KEY[y_key]
    ms = MEASURE_BY_KEY.get(size_key) if size_key else None
    groups = _group_rows(df, group_key)
    if not groups:
        return empty_result("'%s' 값이 있는 문헌이 없습니다." % gd["label"])
    counts = {k: len(v) for k, v in groups.items()}
    cats = _sorted_categories(group_key, groups, counts, top_n)
    pts = []
    for c in cats:
        rows = groups[c]
        xv = _measure_value(df, rows, x_key)
        yv = _measure_value(df, rows, y_key)
        if xv is None or yv is None:
            continue
        sv = _measure_value(df, rows, size_key) if ms else None
        pts.append({"label": c, "x": float(xv), "y": float(yv),
                    "size": (float(sv) if sv is not None else None),
                    "n": len(rows),
                    "drill": gd["drill"](c) if gd.get("drill") else None})
    if len(pts) < 2:
        return empty_result("두 값을 모두 계산할 수 있는 항목이 2개 미만입니다 "
                            "(다른 값 항목을 선택하거나 필터를 넓혀보세요).")
    if ms:
        smax = max([p["size"] for p in pts if p["size"] is not None] or [0]) or 1.0
        for p in pts:
            p["_r"] = float(max(10, min(52, 10 + 42 * np.sqrt(max(p["size"], 0) / smax)))) \
                if p["size"] is not None else 12.0
    else:
        for p in pts:
            p["_r"] = 13.0
    reg = {}
    hover = ["%s<br>%s: %s<br>%s: %s%s<br>문헌 %s건"
             % (p["label"], mx["label"], _fmt_val(x_key, p["x"]),
                my["label"], _fmt_val(y_key, p["y"]),
                ("<br>%s: %s" % (ms["label"], _fmt_val(size_key, p["size"])))
                if ms else "", fmt_num(p["n"])) for p in pts]
    title = "%s별 %s × %s" % (gd["label"], mx["label"], my["label"])
    if ms:
        title += " (버블 크기=%s)" % ms["label"]
    fig = {"data": [{"type": "scatter", "mode": "markers+text",
                     "x": [round(p["x"], 4) for p in pts],
                     "y": [round(p["y"], 4) for p in pts],
                     "text": [p["label"] for p in pts],
                     "textposition": "top center",
                     "textfont": {"size": 10},
                     "hovertext": hover, "hoverinfo": "text",
                     "customdata": [{"drill": p["drill"],
                                     "m": {gd["label"]: p["label"],
                                           mx["label"]: p["x"], my["label"]: p["y"]}}
                                    for p in pts],
                     "marker": {"size": [p["_r"] for p in pts],
                                "color": [color_for(p["label"], reg) for p in pts],
                                "opacity": 0.78,
                                "line": {"width": 1, "color": "#ffffff"}}}],
           "layout": base_layout(title,
                                 xaxis={"title": mx["label"], "automargin": True},
                                 yaxis={"title": my["label"], "automargin": True},
                                 height=520, showlegend=False)}
    if mx.get("fmt") == "pct":
        fig["layout"]["xaxis"]["tickformat"] = ".0%"
    if my.get("fmt") == "pct":
        fig["layout"]["yaxis"]["tickformat"] = ".0%"
    top_x = max(pts, key=lambda p: p["x"])
    top_y = max(pts, key=lambda p: p["y"])
    sentences = ["%s가 가장 높은 항목은 '%s'(%s), %s가 가장 높은 항목은 '%s'(%s)입니다."
                 % (mx["label"], top_x["label"], _fmt_val(x_key, top_x["x"]),
                    my["label"], top_y["label"], _fmt_val(y_key, top_y["y"])),
                 "두 지표가 모두 높은 우상단 항목이 종합 우위, 좌하단은 열위 영역입니다 "
                 "(축은 사용자가 선택한 값 항목)."]
    if ms:
        big = max(pts, key=lambda p: (p["size"] if p["size"] is not None else -1))
        sentences.append("버블이 가장 큰 항목은 '%s'(%s %s)입니다."
                         % (big["label"], ms["label"], _fmt_val(size_key, big["size"])))
    return ok_result({"figure": fig,
                      "rows": [{"label": p["label"], "x": p["x"], "y": p["y"],
                                "size": p["size"], "n": p["n"], "drill": p["drill"]}
                               for p in pts],
                      "axis_info": {"x": mx["label"], "y": my["label"],
                                    "size": ms["label"] if ms else None}},
                     insight=build_insight(sentences, {"n_points": len(pts)},
                                           small_sample=check_small_sample(len(df), settings)))
