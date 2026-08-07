# -*- coding: utf-8 -*-
"""
analyses/classification_quality.py — 4.12 기술분류 품질·경계 진단 (3단계).

분석 목적:
  당사가 수행한 기술분류 결과의 품질(응집도·분리도·경계 모호성)을 진단하고
  분류 수정 후보를 제안한다.

필수 컬럼: 기술분류(any)
선택 컬럼: 임베딩(응집도·분리도·실루엣), 분류 신뢰도, 제목/요약(대표 키워드),
          날짜(드리프트)

지표:
  - cohesion(분류 내 응집도): 분류 내 문서-중심 벡터 평균 코사인 유사도
  - separation(분류 간 분리도): 분류 중심 간 평균 코사인 거리(1-유사도)
  - silhouette: sklearn silhouette (표본 상한 2000, 임베딩 필요)
  - multi_ratio: 다중분류 비율 (분류 2개 이상 문헌 비중)
  - low_conf_ratio: 분류 신뢰도 < low_confidence_class 문헌 비중
  - drift: 연도별 분류 중심 임베딩 이동 평균 거리
  - keyword_stability: 전·후반 기간 대표 키워드(TF 상위) Jaccard

탐지 규칙 → 수정 후보 제안:
  - 두 분류 중심 유사도 > 0.8 → "통합 검토"
  - cohesion < 0.3 → "분리 검토(이질 기술군 혼재)"
  - keyword_stability < 0.3 → "대표 키워드 재정의"
  - multi_ratio > 0.6 → "다중분류 기준 검토"
  - 표본 < min_class_patents → "과세분화 의심(표본 부족)"

그래프: Classification Confusion Map (히트맵, 행·열=기술분류, 셀=중심 간 의미
  유사도 또는 (임베딩 없으면) 중복 특허 비율. 빨강=모호, 파랑=분리 명확).
  보조: 분류별 응집도 막대, 저신뢰 특허 목록, 연도별 중심 이동, 키워드 변화.
Drill-down: 히트맵 셀 → 두 분류 동시 포함 특허 {"type":"combo"}.
예외처리: 임베딩 없으면 임베딩 기반 지표는 null + 중복 비율 기반으로 degrade.
"""
import re

import numpy as np
import pandas as pd

from src.config import get_threshold, get_limit
from src.gpu_utils import cosine_similarity_matrix
from src.insights import build_insight, fmt_num, fmt_pct, check_small_sample
from src.viz_payload import BLUE_RED, ok_result, empty_result, heatmap, bar_chart, echarts_heatmap

_TOKEN_RE = re.compile(r"[A-Za-z가-힣一-龥ぁ-んァ-ン0-9]{2,}")
_STOP = frozenset(["및", "또는", "위한", "있는", "하는", "the", "and", "for", "with",
                   "of", "in", "to", "method", "device", "system", "장치", "방법"])


def _top_keywords(texts, k=8):
    counts = {}
    for t in texts:
        if t is None or (isinstance(t, float) and np.isnan(t)):
            continue
        for tok in _TOKEN_RE.findall(str(t).lower()):
            if tok not in _STOP:
                counts[tok] = counts.get(tok, 0) + 1
    return [w for w, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:k]]


def compute_classification_quality(df, settings):
    """기술분류 품질·경계 진단 계산."""
    if not len(df):
        return empty_result()
    techs_all = pd.Series([t for lst in df["_tech_list"] for t in (lst or [])])
    if not len(techs_all):
        return empty_result("기술분류 데이터가 없습니다.")
    min_n = get_threshold(settings, "min_class_patents")
    low_conf_cut = get_threshold(settings, "low_confidence_class")
    tech_counts = techs_all.value_counts()
    techs = tech_counts.head(get_limit(settings, "network_max_nodes")).index.tolist()

    has_emb = "_embedding" in df.columns and df["_embedding"].map(lambda v: v is not None).any()
    emb_dim = None
    if has_emb:
        dims = {len(v) for v in df["_embedding"] if v is not None}
        emb_dim = dims.pop() if len(dims) == 1 else None
        has_emb = emb_dim is not None

    # 분류별 문서 인덱스
    idx_by_tech = {t: df.index[df["_tech_list"].map(lambda lst: t in (lst or []))].tolist()
                   for t in techs}

    centroids, cohesion = {}, {}
    if has_emb:
        for t in techs:
            vecs = [df.loc[i, "_embedding"] for i in idx_by_tech[t]
                    if df.loc[i, "_embedding"] is not None]
            if len(vecs) >= 2:
                V = np.vstack(vecs)
                c = V.mean(axis=0)
                centroids[t] = c
                sims = cosine_similarity_matrix(V, c.reshape(1, -1)).ravel()
                cohesion[t] = float(np.mean(sims))
            elif len(vecs) == 1:
                centroids[t] = np.asarray(vecs[0])
                cohesion[t] = 1.0

    # Confusion Map: 임베딩 → 중심 유사도 / 폴백 → 중복 특허 비율(Jaccard)
    z, hover = [], []
    for a in techs:
        row_z, row_h = [], []
        set_a = set(idx_by_tech[a])
        for b in techs:
            if a == b:
                row_z.append(None)
                row_h.append("%s (대각)" % a)
                continue
            if has_emb and a in centroids and b in centroids:
                v = float(cosine_similarity_matrix(
                    centroids[a].reshape(1, -1), centroids[b].reshape(1, -1))[0, 0])
                row_h.append("%s ↔ %s<br>중심 의미 유사도 %.2f" % (a, b, v))
            else:
                set_b = set(idx_by_tech[b])
                union = len(set_a | set_b) or 1
                v = len(set_a & set_b) / float(union)
                row_h.append("%s ↔ %s<br>중복 특허 비율(Jaccard) %.2f" % (a, b, v))
            row_z.append(round(v, 3))
        z.append(row_z)
        hover.append(row_h)
    n_cells = len(techs) ** 2
    if n_cells > get_limit(settings, "echarts_threshold_cells"):
        fig_confusion = echarts_heatmap(z, techs, techs, title="Classification Confusion Map")
    else:
        fig_confusion = heatmap(z, techs, techs,
                                title="Classification Confusion Map (빨강=모호, 파랑=분리 명확)",
                                colorscale=BLUE_RED, hovertext=hover,
                                colorbar_title="유사도/중복", zmid=0.5)

    # 실루엣 (단일 분류 문헌만, 표본 상한)
    silhouette = None
    if has_emb:
        try:
            from sklearn.metrics import silhouette_score
            rows = [(i, (lst or [None])[0]) for i, lst in zip(df.index, df["_tech_list"])
                    if lst and len(set(lst)) == 1 and df.loc[i, "_embedding"] is not None
                    and (lst[0] in set(techs))]
            if len(rows) > 2000:
                rows = rows[:2000]
            labels = [t for _, t in rows]
            if len(set(labels)) >= 2 and len(rows) >= 10:
                X = np.vstack([df.loc[i, "_embedding"] for i, _ in rows])
                silhouette = float(silhouette_score(X, labels, metric="cosine"))
        except Exception:
            silhouette = None

    multi_ratio = float(df["_tech_list"].map(lambda lst: len(set(lst or [])) >= 2).mean())
    low_conf_ratio = None
    low_conf_list = []
    if "class_confidence" in df.columns and df["class_confidence"].notna().any():
        conf = df["class_confidence"]
        low_mask = conf.notna() & (conf < low_conf_cut)
        low_conf_ratio = float(low_mask.mean())
        id_col = "pub_number" if "pub_number" in df.columns else None
        for i in df.index[low_mask][:50]:
            low_conf_list.append({
                "id": str(df.loc[i, id_col]) if id_col else str(i),
                "title": str(df.loc[i].get("title", ""))[:70],
                "confidence": round(float(conf.loc[i]), 3),
                "techs": list(df.loc[i, "_tech_list"] or [])[:4]})

    # 드리프트: 연도별 중심 이동 평균 거리
    drift_by_tech = {}
    if has_emb and "_base_year" in df.columns:
        for t in techs:
            pts = [(int(df.loc[i, "_base_year"]), df.loc[i, "_embedding"])
                   for i in idx_by_tech[t]
                   if df.loc[i, "_embedding"] is not None and pd.notna(df.loc[i, "_base_year"])]
            by_year = {}
            for y, v in pts:
                by_year.setdefault(y, []).append(v)
            years_sorted = sorted(by_year)
            if len(years_sorted) >= 2:
                cents = [np.vstack(by_year[y]).mean(axis=0) for y in years_sorted]
                dists = [1.0 - float(cosine_similarity_matrix(
                    cents[j].reshape(1, -1), cents[j + 1].reshape(1, -1))[0, 0])
                    for j in range(len(cents) - 1)]
                drift_by_tech[t] = round(float(np.mean(dists)), 4)

    # 대표 키워드 안정성
    keyword_info = {}
    text_col = "title" if "title" in df.columns else ("abstract" if "abstract" in df.columns else None)
    if text_col:
        years = df["_base_year"].dropna()
        mid = float(years.median()) if len(years) else None
        for t in techs:
            sub = df.loc[idx_by_tech[t]]
            kws = _top_keywords(sub[text_col], 8)
            stability = None
            if mid is not None:
                early = _top_keywords(sub.loc[sub["_base_year"] <= mid, text_col], 10)
                late = _top_keywords(sub.loc[sub["_base_year"] > mid, text_col], 10)
                if early and late:
                    inter = len(set(early) & set(late))
                    union = len(set(early) | set(late)) or 1
                    stability = round(inter / float(union), 3)
            keyword_info[t] = {"keywords": kws, "stability": stability}

    # 수정 후보 제안
    suggestions = []
    for i, a in enumerate(techs):
        for j in range(i + 1, len(techs)):
            b = techs[j]
            v = z[i][j]
            if v is not None and has_emb and v > 0.8:
                suggestions.append({"type": "통합 검토", "targets": [a, b],
                                    "reason": "중심 의미 유사도 %.2f (>0.8)" % v,
                                    "drill": {"type": "combo", "a": a, "b": b}})
            elif v is not None and not has_emb and v > 0.5:
                suggestions.append({"type": "통합 검토", "targets": [a, b],
                                    "reason": "중복 특허 비율 %.2f (>0.5)" % v,
                                    "drill": {"type": "combo", "a": a, "b": b}})
    for t in techs:
        if t in cohesion and cohesion[t] < 0.3:
            suggestions.append({"type": "분리 검토", "targets": [t],
                                "reason": "응집도 %.2f (<0.3) — 이질 기술군 혼재 의심" % cohesion[t],
                                "drill": {"type": "tech", "tech": t}})
        ki = keyword_info.get(t, {})
        if ki.get("stability") is not None and ki["stability"] < 0.3:
            suggestions.append({"type": "대표 키워드 재정의", "targets": [t],
                                "reason": "전·후반 키워드 안정성 %.2f (<0.3)" % ki["stability"],
                                "drill": {"type": "tech", "tech": t}})
        if int(tech_counts.get(t, 0)) < min_n:
            suggestions.append({"type": "과세분화 검토", "targets": [t],
                                "reason": "표본 %d건 (<%d)" % (int(tech_counts.get(t, 0)), int(min_n)),
                                "drill": {"type": "tech", "tech": t}})
    if multi_ratio > 0.6:
        suggestions.append({"type": "다중분류 기준 검토", "targets": [],
                            "reason": "다중분류 비율 %s (>60%%)" % fmt_pct(multi_ratio)})

    cohesion_fig = None
    if cohesion:
        items = sorted(cohesion.items(), key=lambda kv: kv[1])
        cohesion_fig = bar_chart([k for k, _ in items], [round(v, 3) for _, v in items],
                                 title="분류별 임베딩 응집도", orientation="h",
                                 x_title="응집도(중심 코사인 평균)")

    sentences = ["기술분류 %s개 진단: 다중분류 비율 %s%s%s."
                 % (fmt_num(len(techs)), fmt_pct(multi_ratio),
                    (", 실루엣 %.3f" % silhouette) if silhouette is not None else "",
                    (", 저신뢰(<%.1f) 비율 %s" % (low_conf_cut, fmt_pct(low_conf_ratio)))
                    if low_conf_ratio is not None else "")]
    merges = [s for s in suggestions if s["type"] == "통합 검토"]
    if merges:
        m0 = merges[0]
        sentences.append("경계가 가장 모호한 분류쌍은 '%s ↔ %s'(%s)로 통합 검토 대상입니다."
                         % (m0["targets"][0], m0["targets"][1], m0["reason"]))
    if not has_emb:
        sentences.append("임베딩 벡터가 없어 의미 기반 지표(응집도·실루엣·드리프트) 없이 "
                         "중복 특허 비율 기반으로 진단했습니다. '임베딩 벡터' 컬럼을 매핑하면 "
                         "정밀 진단이 가능합니다.")
    insight = build_insight(sentences, {"multi_ratio": multi_ratio, "silhouette": silhouette},
                            small_sample=check_small_sample(len(df), settings))
    return ok_result({
        "confusion": fig_confusion, "cohesion_figure": cohesion_fig,
        "cohesion": {k: round(v, 3) for k, v in cohesion.items()},
        "separation": None if not centroids else round(float(np.mean(
            [1.0 - z[i][j] for i in range(len(techs)) for j in range(len(techs))
             if i != j and z[i][j] is not None])), 3),
        "silhouette": silhouette, "multi_ratio": round(multi_ratio, 3),
        "low_conf_ratio": low_conf_ratio, "low_conf_list": low_conf_list,
        "drift": drift_by_tech, "keywords": keyword_info,
        "suggestions": suggestions[:40], "has_embedding": bool(has_emb),
    }, insight=insight)
