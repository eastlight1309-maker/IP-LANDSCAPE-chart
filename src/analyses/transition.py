# -*- coding: utf-8 -*-
"""
analyses/transition.py — 4.1 기술분류 전이 Sankey Diagram (2단계).

분석 목적:
  기간별로 포트폴리오의 기술 중심이 어떤 기술분류에서 다른 기술분류로 이동했는지
  Sankey 로 표현한다.

필수 컬럼: 기술분류(any), 날짜(any)
선택 컬럼: 패밀리 ID(모드1), 출원인(모드2), 출원번호/패밀리(모드3 근사)

전이 정의 4종 (mode 파라미터, 드롭다운):
  family      ① 동일 패밀리 내 기술분류 변화: 같은 family_id 문헌들을 시간순 정렬,
                 이전 기간 분류 → 다음 기간 분류 링크.
  applicant   ② 동일 출원인의 기간별 포트폴리오 변화: 출원인별 (이전 기간 분류 집합
                 × 다음 기간 분류 집합) 링크 — 규모 왜곡 방지 위해 1/(|S|·|T|) 가중.
  continuation③ 후속출원 기준: 동일 패밀리 내 출원일이 다른 문헌 쌍(선→후)의 분류
                 변화 (계속·분할출원 데이터가 별도로 없으므로 패밀리 내 시차 출원을
                 후속출원으로 간주 — 근사임을 meta 에 명시).
  cooccurrence④ 기술분류 간 공동출현 증가 기준: 이전 기간 대비 다음 기간에 공동출현이
                 증가한 조합을 전이 신호 링크로 표시 (링크값 = 증가량).

기간 분할: 사용자 지정 period_years(기본 recent_years)로 [이전 기간 | 다음 기간]
을 나눈다 (연도 필터 적용 후 최근 2개 구간).

그래프: Source=이전 기간 분류, Target=다음 기간 분류, Link=전이량, 색=대분류.
Drill-down: 링크 클릭 {"type":"transition","source":…,"target":…}.
자동 인사이트: 최대 전이 링크, 순유입 상위 분류.
예외처리: 구간 데이터 부족 시 empty. 링크 수 상한 sankey_max_links.
"""
import numpy as np

from src.config import get_threshold, get_limit
from src.preprocessing import build_l1_lookup
from src.insights import build_insight, fmt_num, check_small_sample
from src.viz_payload import ok_result, empty_result, sankey, color_for

TRANSITION_MODES = ["family", "applicant", "continuation", "cooccurrence"]


def _split_periods(df, period_years):
    years = df["_base_year"].dropna()
    if not len(years):
        return None
    y_max = int(years.max())
    cur_from = y_max - period_years + 1
    prev_from = cur_from - period_years
    prev = df[(df["_base_year"] >= prev_from) & (df["_base_year"] < cur_from)]
    cur = df[df["_base_year"] >= cur_from]
    label_prev = "%d–%d" % (prev_from, cur_from - 1)
    label_cur = "%d–%d" % (cur_from, y_max)
    return prev, cur, label_prev, label_cur


def _links_family(prev, cur):
    """모드①/③: 동일 패밀리의 이전 기간 분류 → 다음 기간 분류."""
    links = {}
    if "family_id" not in prev.columns:
        return None
    prev_map = {}
    for fid, techs in zip(prev["family_id"], prev["_tech_list"]):
        if fid is None or (isinstance(fid, float) and np.isnan(fid)):
            continue
        prev_map.setdefault(str(fid), set()).update(techs or [])
    for fid, techs in zip(cur["family_id"], cur["_tech_list"]):
        key = str(fid)
        if key not in prev_map:
            continue
        src_set, tgt_set = prev_map[key], set(techs or [])
        if not src_set or not tgt_set:
            continue
        w = 1.0 / (len(src_set) * len(tgt_set))
        for s in src_set:
            for t in tgt_set:
                links[(s, t)] = links.get((s, t), 0.0) + w
    return links


def _links_applicant(prev, cur):
    """모드②: 동일 출원인의 기간별 포트폴리오 변화 (1/(|S||T|) 가중)."""
    links = {}
    prev_map = {}
    for app, techs in zip(prev["applicant_display"], prev["_tech_list"]):
        if app:
            prev_map.setdefault(str(app), set()).update(techs or [])
    cur_map = {}
    for app, techs in zip(cur["applicant_display"], cur["_tech_list"]):
        if app:
            cur_map.setdefault(str(app), set()).update(techs or [])
    for app, tgt_set in cur_map.items():
        src_set = prev_map.get(app)
        if not src_set or not tgt_set:
            continue
        w = 1.0 / (len(src_set) * len(tgt_set))
        for s in src_set:
            for t in tgt_set:
                links[(s, t)] = links.get((s, t), 0.0) + w
    return links


def _links_cooccurrence(prev, cur):
    """모드④: 공동출현 증가 조합 (증가량을 링크값으로)."""
    def pair_counts(frame):
        from itertools import combinations
        counts = {}
        for techs in frame["_tech_list"]:
            uniq = sorted(set(techs or []))
            for a, b in combinations(uniq, 2):
                counts[(a, b)] = counts.get((a, b), 0) + 1
        return counts
    p_prev, p_cur = pair_counts(prev), pair_counts(cur)
    links = {}
    for pair, n_cur in p_cur.items():
        inc = n_cur - p_prev.get(pair, 0)
        if inc > 0:
            links[pair] = float(inc)
    return links


def compute_transition(df, settings, mode=None, period_years=None):
    """기술분류 전이 Sankey 계산."""
    if not len(df):
        return empty_result()
    mode = mode if mode in TRANSITION_MODES else settings.get("transition_mode", "cooccurrence")
    period_years = int(period_years or get_threshold(settings, "recent_years"))
    split = _split_periods(df, period_years)
    if split is None:
        return empty_result("연도 정보가 없어 기간을 나눌 수 없습니다.")
    prev, cur, label_prev, label_cur = split
    if not len(prev) or not len(cur):
        return empty_result("이전/다음 기간 중 한쪽에 데이터가 없어 전이를 계산할 수 없습니다.")

    if mode == "family":
        links = _links_family(prev, cur)
        if links is None:
            return empty_result("패밀리 ID 컬럼이 없어 '동일 패밀리' 전이를 계산할 수 없습니다. "
                                "다른 전이 정의를 선택하세요.")
    elif mode == "continuation":
        links = _links_family(prev, cur)  # 패밀리 내 시차 출원을 후속출원으로 근사
        if links is None:
            return empty_result("패밀리 ID 컬럼이 없어 후속출원 기준 전이를 계산할 수 없습니다.")
    elif mode == "applicant":
        links = _links_applicant(prev, cur)
    else:
        links = _links_cooccurrence(prev, cur)
    links = {k: v for k, v in links.items() if v > 0}
    if not links:
        return empty_result("선택한 전이 정의로 관측된 전이가 없습니다.")

    max_links = get_limit(settings, "sankey_max_links")
    top_links = sorted(links.items(), key=lambda kv: -kv[1])[:max_links]

    l1_lookup = build_l1_lookup(df)
    color_reg = {}
    node_index, nodes = {}, []

    def node_id(name, side):
        key = (name, side)
        if key not in node_index:
            node_index[key] = len(nodes)
            l1 = str(l1_lookup.get(name, "기타"))
            label = "%s (%s)" % (name, label_prev if side == "src" else label_cur)
            nodes.append({"label": label, "color": color_for(l1, color_reg),
                          "tech": name, "side": side})
        return node_index[key]

    link_payload = []
    for (s, t), v in top_links:
        si, ti = node_id(s, "src"), node_id(t, "tgt")
        l1 = str(l1_lookup.get(s, "기타"))
        base = color_for(l1, color_reg)
        link_payload.append({"source": si, "target": ti, "value": round(float(v), 3),
                             "color": base + "59",  # 알파 추가
                             "customdata": {"drill": {"type": "transition",
                                                      "source": s, "target": t}}})
    fig = sankey(nodes, link_payload,
                 title="기술분류 전이 (%s → %s, 정의: %s)" % (label_prev, label_cur, mode))

    inflow = {}
    for (s, t), v in top_links:
        if s != t:
            inflow[t] = inflow.get(t, 0.0) + v
            inflow[s] = inflow.get(s, 0.0) - v
    sentences = []
    if top_links:
        (s0, t0), v0 = top_links[0]
        sentences.append("%s → %s 구간 최대 전이 링크는 '%s → %s'(전이량 %s, 정의=%s)입니다."
                         % (label_prev, label_cur, s0, t0, fmt_num(v0, 2), mode))
    if inflow:
        top_in = max(inflow, key=inflow.get)
        if inflow[top_in] > 0:
            sentences.append("순유입이 가장 큰 분류는 '%s'(순유입 %s)로 포트폴리오 중심 이동의 "
                             "목적지로 해석됩니다 (탐색적 신호)." % (top_in, fmt_num(inflow[top_in], 2)))
    insight = build_insight(sentences, {"n_links": len(top_links)},
                            small_sample=check_small_sample(len(cur), settings))
    return ok_result({"figure": fig, "mode": mode,
                      "period_prev": label_prev, "period_cur": label_cur},
                     insight=insight,
                     meta={"note": ("후속출원 기준은 패밀리 내 시차 출원 근사입니다."
                                    if mode == "continuation" else None),
                           "truncated": len(links) > len(top_links)})
