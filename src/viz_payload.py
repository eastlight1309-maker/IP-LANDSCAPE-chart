# -*- coding: utf-8 -*-
"""
viz_payload.py — 시각화용 JSON 생성 모듈 + 분석 결과 공통 envelope.

모든 분석 결과는 다음 envelope 로 통일한다 (프론트 렌더러 공통 처리):
  {"status": "ok" | "empty" | "disabled" | "error",
   "message": str (empty/disabled/error 시 안내문),
   "missing_columns": [필수 컬럼 라벨...] (disabled 시),
   "figure"/"figures"/"network"/... : 시각화 payload,
   "insight": {"sentences":[...], "metrics":{...}, "source":"rule|llm"},
   "meta": {"generated_at":…, "n_rows":…, "cache_hit":…, "disclaimer":…}}

Plotly payload 는 {"data":[trace...], "layout":{...}} 그대로 프론트에서
Plotly.newPlot 에 전달 가능한 형태로 생성한다.
Cytoscape payload 는 {"nodes":[{data:{...}}], "edges":[{data:{...}}]}.
ECharts payload 는 옵션 dict 자체.

숫자는 모두 python float/int 로 변환하여 JSON 직렬화 오류(np.int64 등)를 방지한다.
"""
import math

import numpy as np

from src.config import MESSAGES

# 색상 팔레트 (대분류·기업 등 범주형)
PALETTE = ["#4E79A7", "#F28E2B", "#E15759", "#76B7B2", "#59A14F", "#EDC948",
           "#B07AA1", "#FF9DA7", "#9C755F", "#BAB0AC", "#2F4B7C", "#FFA600"]


def jsonable(obj):
    """numpy/pandas 스칼라·배열을 JSON 직렬화 가능한 python 기본형으로 재귀 변환."""
    if obj is None or isinstance(obj, (str, bool, int)):
        return obj
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return [jsonable(v) for v in obj.tolist()]
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [jsonable(v) for v in obj]
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


def ok_result(payload, insight=None, meta=None, disclaimer=True):
    """정상 결과 envelope."""
    out = {"status": "ok"}
    out.update(payload or {})
    out["insight"] = insight or {"sentences": [], "metrics": {}, "source": "rule"}
    m = dict(meta or {})
    if disclaimer:
        m["disclaimer"] = MESSAGES["disclaimer"]
    out["meta"] = m
    return jsonable(out)


def empty_result(message=None, meta=None):
    """데이터 없음/계산 불가 envelope (값 임의 생성 금지 원칙)."""
    return jsonable({"status": "empty", "message": message or MESSAGES["no_data"],
                     "insight": {"sentences": [message or MESSAGES["no_data"]],
                                 "metrics": {}, "source": "rule"},
                     "meta": dict(meta or {})})


def disabled_result(missing_labels, message=None, meta=None):
    """필수 컬럼 누락으로 비활성화된 분석 envelope."""
    msg = message or MESSAGES["missing_columns"].format(cols=", ".join(missing_labels))
    return jsonable({"status": "disabled", "message": msg,
                     "missing_columns": list(missing_labels),
                     "insight": {"sentences": [msg], "metrics": {}, "source": "rule"},
                     "meta": dict(meta or {})})


def color_for(key, registry, palette=None):
    """범주 키 → 팔레트 색상 (registry dict 에 배정 상태 유지)."""
    palette = palette or PALETTE
    if key not in registry:
        registry[key] = palette[len(registry) % len(palette)]
    return registry[key]


# ---------------------------------------------------------------------------
# Plotly 빌더
# ---------------------------------------------------------------------------
def base_layout(title=None, **overrides):
    """공통 Plotly layout (여백·폰트·범례·hover 설정)."""
    layout = {
        "font": {"family": "'Pretendard','Malgun Gothic','Apple SD Gothic Neo',sans-serif",
                 "size": 12},
        "margin": {"l": 60, "r": 30, "t": 48 if title else 24, "b": 60},
        "paper_bgcolor": "rgba(0,0,0,0)", "plot_bgcolor": "rgba(0,0,0,0)",
        "hovermode": "closest",
        "legend": {"orientation": "h", "y": -0.18},
    }
    if title:
        layout["title"] = {"text": title, "font": {"size": 15}}
    layout.update(overrides)
    return layout


def bubble_chart(points, x_title, y_title, title=None, quadrants=None,
                 size_ref_max=40.0, colorbar_title=None):
    """버블 차트 payload.

    points: [{x, y, size, color(수치), label, hover, customdata, line_width?}, ...]
    quadrants: {"x_mid":…, "y_mid":…, "labels":[좌상,우상,우하,좌하]} — 4분면 주석.
    """
    if not points:
        return None
    sizes = [max(float(p.get("size") or 1.0), 0.1) for p in points]
    smax = max(sizes)
    trace = {
        "type": "scatter", "mode": "markers",
        "x": [p["x"] for p in points], "y": [p["y"] for p in points],
        "text": [p.get("label", "") for p in points],
        "hovertext": [p.get("hover", "") for p in points],
        "hoverinfo": "text",
        "customdata": [p.get("customdata") for p in points],
        "marker": {
            "size": sizes, "sizemode": "area",
            "sizeref": 2.0 * smax / (size_ref_max ** 2), "sizemin": 4,
            "color": [p.get("color", 0) for p in points],
            "colorscale": "Viridis", "showscale": True,
            "colorbar": {"title": colorbar_title or "", "thickness": 12},
            "line": {"width": [p.get("line_width", 1) for p in points],
                     "color": "#333"},
            "opacity": 0.85,
        },
    }
    layout = base_layout(title, xaxis={"title": x_title}, yaxis={"title": y_title})
    if quadrants:
        xm, ym = quadrants["x_mid"], quadrants["y_mid"]
        layout["shapes"] = [
            {"type": "line", "x0": xm, "x1": xm, "yref": "paper", "y0": 0, "y1": 1,
             "line": {"color": "#bbb", "dash": "dot", "width": 1}},
            {"type": "line", "y0": ym, "y1": ym, "xref": "paper", "x0": 0, "x1": 1,
             "line": {"color": "#bbb", "dash": "dot", "width": 1}},
        ]
        labels = quadrants.get("labels") or []
        positions = [(0.02, 0.98), (0.98, 0.98), (0.98, 0.02), (0.02, 0.02)]
        anchors = [("left", "top"), ("right", "top"), ("right", "bottom"), ("left", "bottom")]
        layout["annotations"] = [
            {"x": px, "y": py, "xref": "paper", "yref": "paper", "text": lab,
             "showarrow": False, "xanchor": ax, "yanchor": ay,
             "font": {"size": 11, "color": "#888"}}
            for lab, (px, py), (ax, ay) in zip(labels, positions, anchors)]
    return {"data": [trace], "layout": layout}


# Plotly.js 에 내장되지 않은 명명 색상표(RdYlGn/Purples/OrRd/Turbo 등)를 이름으로
# 넘기면 기본 색상표(파랑=낮음 → 빨강=높음)로 대체 렌더링되어 색 해석이 뒤집힌다.
# (예: 개시 충실도 z=+1 이 빨강으로 보이는 문제) → 명시적 색 배열로 정의해 사용.
RDYLGN = [[0.0, "#E15759"], [0.5, "#F1CE63"], [1.0, "#59A14F"]]  # 낮음=빨강, 높음=초록
PURPLES = [[0.0, "#f6f2fa"], [1.0, "#59489C"]]
ORRD = [[0.0, "#fff3e0"], [1.0, "#d7301f"]]
# Plotly.js 내장 YlOrRd/YlGnBu/Blues 는 python 쪽과 반대로 0=진함→1=연함으로
# 정의되어 있어 "값이 클수록 진하다"는 해석이 뒤집힌다 → 연함→진함 배열로 고정.
BLUES = [[0.0, "#f0f6fc"], [0.5, "#7fafd4"], [1.0, "#1b5e93"]]
YLORRD = [[0.0, "#fff8e1"], [0.5, "#fdae61"], [1.0, "#c0392b"]]
YLGNBU = [[0.0, "#f7fcf0"], [0.5, "#66c2a4"], [1.0, "#0868ac"]]
BLUE_RED = [[0.0, "#2166ac"], [0.5, "#f7f7f7"], [1.0, "#b2182c"]]  # 낮음=파랑, 높음=빨강


def heatmap(z, x_labels, y_labels, title=None, colorscale=None, hovertext=None,
            colorbar_title=None, zmid=None):
    """Plotly 히트맵 payload. 셀 수가 LIMITS 초과인 경우 호출부에서 ECharts 로 전환.

    가독성 규칙: 행(y) 수에 비례해 세로 길이를 늘리고(행당 최소 26px),
    양 축 모두 dtick=1 로 라벨 생략 없이 전부 표시한다 (라벨 많으면 글자만 축소).
    """
    if colorscale is None:
        colorscale = YLORRD
    trace = {"type": "heatmap", "z": z, "x": x_labels, "y": y_labels,
             "colorscale": colorscale, "colorbar": {"thickness": 12}}
    if colorbar_title:
        trace["colorbar"]["title"] = colorbar_title
    if hovertext is not None:
        trace["hovertext"] = hovertext
        trace["hoverinfo"] = "text"
    if zmid is not None:
        trace["zmid"] = zmid
    n_rows = len(y_labels or [])
    n_cols = len(x_labels or [])
    y_font = 10 if n_rows <= 12 else (9 if n_rows <= 20 else 8)
    x_font = 10 if n_cols <= 14 else (9 if n_cols <= 24 else 8)
    # 축을 범주형으로 고정: 라벨이 숫자처럼 보여도 수치축으로 오인 렌더링되지 않도록
    return {"data": [trace],
            "layout": base_layout(
                title,
                height=max(440, 150 + 26 * n_rows),
                xaxis={"tickangle": -40, "automargin": True, "type": "category",
                       "dtick": 1, "tickfont": {"size": x_font}},
                yaxis={"automargin": True, "type": "category", "dtick": 1,
                       "tickfont": {"size": y_font}})}


def echarts_heatmap(z, x_labels, y_labels, title=None):
    """대규모(10만+ 셀) 히트맵용 Apache ECharts 옵션."""
    data = []
    vmin, vmax = None, None
    for yi, row in enumerate(z):
        for xi, v in enumerate(row):
            if v is None:
                continue
            data.append([xi, yi, round(float(v), 4)])
            vmin = v if vmin is None else min(vmin, v)
            vmax = v if vmax is None else max(vmax, v)
    return {
        "engine": "echarts",
        "title": {"text": title or "", "textStyle": {"fontSize": 14}},
        "tooltip": {"position": "top"},
        "grid": {"left": 120, "bottom": 100, "right": 40, "top": 40},
        "xAxis": {"type": "category", "data": x_labels,
                  "axisLabel": {"rotate": 45, "fontSize": 10}},
        "yAxis": {"type": "category", "data": y_labels, "axisLabel": {"fontSize": 10}},
        "visualMap": {"min": vmin or 0, "max": vmax or 1, "calculable": True,
                      "orient": "horizontal", "left": "center", "bottom": 0},
        "series": [{"type": "heatmap", "data": data,
                    "emphasis": {"itemStyle": {"shadowBlur": 6}},
                    "progressive": 2000, "animation": False}],
    }


def sankey(nodes, links, title=None):
    """Plotly Sankey payload. nodes:[{label,color}], links:[{source,target,value,color,hover,customdata}]."""
    trace = {
        "type": "sankey",
        "node": {"label": [n["label"] for n in nodes],
                 "color": [n.get("color", "#4E79A7") for n in nodes],
                 "pad": 12, "thickness": 14,
                 "line": {"width": 0.5, "color": "#999"}},
        "link": {"source": [l["source"] for l in links],
                 "target": [l["target"] for l in links],
                 "value": [l["value"] for l in links],
                 "color": [l.get("color", "rgba(120,140,180,0.35)") for l in links],
                 "customdata": [l.get("customdata") for l in links],
                 "hovertemplate": "%{source.label} → %{target.label}<br>%{value}<extra></extra>"},
    }
    return {"data": [trace], "layout": base_layout(title, margin={"l": 10, "r": 10, "t": 40, "b": 10})}


def line_chart(series_list, x_title, y_title, title=None, year_axis=False):
    """복수 시계열 라인차트. series_list: [{name, x:[..], y:[..], color?}].

    year_axis=True 면 X축을 정수 연도로 고정 (소수점 눈금 방지).
    """
    data = []
    for i, s in enumerate(series_list):
        data.append({"type": "scatter", "mode": "lines+markers", "name": s["name"],
                     "x": s["x"], "y": s["y"],
                     "line": {"color": s.get("color", PALETTE[i % len(PALETTE)])}})
    xaxis = {"title": x_title}
    if year_axis:
        xaxis.update({"tickformat": "d", "hoverformat": "d"})
    return {"data": data, "layout": base_layout(
        title, xaxis=xaxis, yaxis={"title": y_title})}


def bar_chart(x, y, title=None, orientation="v", hovertext=None, colors=None,
              customdata=None, x_title=None, y_title=None, height=None):
    """막대차트 payload (수평/수직).

    수평(orientation="h")일 때 Y축을 명시적 category 로 고정한다 — 라벨이
    숫자형(분류코드 등)이면 Plotly 가 축을 수치축으로 해석해 막대와 라벨
    위치가 어긋나는 문제 방지. 높이도 행 수에 맞춰 자동 산정해 라벨
    솎아내기(막대-라벨 어긋나 보임)를 막는다.
    """
    trace = {"type": "bar", "orientation": orientation}
    if orientation == "h":
        labels = [str(v) for v in x]
        trace["x"], trace["y"] = y, labels
        yaxis = {"title": y_title or "", "automargin": True, "type": "category",
                 "categoryorder": "array", "categoryarray": labels}
        if height is None:
            height = max(340, min(900, 120 + 28 * len(labels)))
    else:
        trace["x"], trace["y"] = x, y
        yaxis = {"title": y_title or "", "automargin": True}
    if hovertext is not None:
        trace["hovertext"] = hovertext
        trace["hoverinfo"] = "text"
    if colors is not None:
        trace["marker"] = {"color": colors}
    if customdata is not None:
        trace["customdata"] = customdata
    layout = base_layout(title, xaxis={"title": x_title or "", "automargin": True},
                         yaxis=yaxis)
    if height:
        layout["height"] = height
    return {"data": [trace], "layout": layout}


def radar_chart(categories, series_list, title=None):
    """레이더 차트. series_list: [{name, values(카테고리 순, 0~1 표준화), raw(원값 hover)}]."""
    data = []
    for i, s in enumerate(series_list):
        vals = list(s["values"]) + [s["values"][0]]
        cats = list(categories) + [categories[0]]
        raws = list(s.get("raw", s["values"]))
        raws = raws + [raws[0]]
        data.append({
            "type": "scatterpolar", "name": s["name"], "r": vals, "theta": cats,
            "fill": "toself", "opacity": 0.55,
            "line": {"color": PALETTE[i % len(PALETTE)]},
            "hovertext": ["%s<br>%s: 표준화 %.2f / 원값 %s" % (s["name"], c, v, r)
                          for c, v, r in zip(cats, vals, raws)],
            "hoverinfo": "text",
        })
    layout = base_layout(
        title, polar={"radialaxis": {"visible": True, "range": [0, 1],
                                     "tickvals": [0, 0.25, 0.5, 0.75, 1.0]}})
    layout["annotations"] = [{
        "x": 0.5, "y": -0.22, "xref": "paper", "yref": "paper", "showarrow": False,
        "text": "축 값 = 0~1 표준화 점수 (비교 기업 집합 내 상대값, 1=최고) · Hover 에 원값 표시",
        "font": {"size": 10.5, "color": "#8aa0b2"}}]
    return {"data": data, "layout": layout}


def cytoscape_network(nodes, edges):
    """Cytoscape.js elements payload.

    nodes: [{id, label, size, color, border_color?, border_width?, meta...}]
    edges: [{source, target, weight, width, color?, label?, meta...}]
    """
    elements = {"nodes": [], "edges": []}
    for n in nodes:
        data = {str(k): jsonable(v) for k, v in n.items()}
        elements["nodes"].append({"data": data})
    for i, e in enumerate(edges):
        data = {str(k): jsonable(v) for k, v in e.items()}
        data.setdefault("id", "e%d" % i)
        elements["edges"].append({"data": data})
    return elements
