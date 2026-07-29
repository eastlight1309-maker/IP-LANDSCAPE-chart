# -*- coding: utf-8 -*-
"""
insights.py — 자동 인사이트 문장 생성 (규칙 기반 + LLM 기반).

규칙 기반 (1단계):
- 계산된 수치·임계값에 근거한 문장만 생성한다 (데이터 근거 없는 서술 금지).
- 문장 필수 요소: 분석 기간, 비교 기준, 핵심 수치, 상위/하위 백분위, 긍정 요인,
  위험 요인. 근거 특허 링크는 insight["drill"] 로 전달되어 프론트가 버튼을 렌더링한다.
- 표본 부족(임계값 미만) 시 MESSAGES["small_sample"] 문장으로 대체한다.

LLM 기반 (3단계):
- Dataiku LLM Mesh 사용. 원문 데이터가 아닌 요약 통계(JSON 문자열)만 전달.
- llm_client.sanitize_for_llm 으로 입력 정화, 실패 시 규칙 기반 문장으로 자동 폴백.
- 생성 문장과 함께 근거 지표(metrics)를 항상 함께 반환한다.
"""
import json

from src.config import MESSAGES, get_threshold
from src.llm_client import call_llm, sanitize_for_llm, llm_available


def fmt_num(v, digits=1):
    """수치 포맷 (천 단위 구분, None 안전)."""
    if v is None:
        return "-"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if abs(f - round(f)) < 1e-9 and abs(f) < 1e15:
        return format(int(round(f)), ",")
    return format(round(f, digits), ",")


def fmt_pct(v, digits=1):
    """비율(0.15) → 퍼센트 문자열('15.0%')."""
    if v is None:
        return "-"
    try:
        return "%s%%" % round(float(v) * 100.0, digits)
    except (TypeError, ValueError):
        return "-"


def period_label(df):
    """분석 기간 라벨 (예: '2015–2024년')."""
    years = df["_base_year"].dropna() if "_base_year" in df.columns else []
    if len(years):
        return "%d–%d년" % (int(min(years)), int(max(years)))
    return "기간 미상"


def build_insight(sentences, metrics=None, drills=None, source="rule",
                  small_sample=False):
    """인사이트 dict 조립. drills: [{"label":버튼명,"drill":{...}}] — 근거 특허 이동 버튼."""
    sents = list(sentences or [])
    if small_sample:
        sents.append(MESSAGES["small_sample"])
    return {"sentences": sents, "metrics": dict(metrics or {}),
            "drills": list(drills or []), "source": source}


def check_small_sample(n, settings):
    """표본 수가 임계값 미만인지."""
    return n < get_threshold(settings, "insight_small_sample")


def llm_chat(analysis_name, metrics, sentences, question, history, settings,
             description=None):
    """그래프별 LLM 챗 인사이트 (요약 통계만 전달, 실패 시 규칙 기반 폴백).

    question: 사용자 추가 질문 (없으면 '이 그래프의 인사이트를 도출' 기본 요청).
    history: [{"role":"user|assistant","content":…}] 최근 대화 (최대 6턴만 사용).
    반환: {"answer": str, "source": "llm|rule"} — 원문 특허 데이터는 전달하지 않는다.
    """
    rule_summary = " / ".join(str(s) for s in (sentences or [])[:6])
    try:
        stats_json = json.dumps(metrics or {}, ensure_ascii=False, default=str)[:2500]
    except (TypeError, ValueError):
        stats_json = str(metrics)[:2500]
    parts = [
        "다음은 특허 IP Landscape 분석 화면 '%s' 의 요약 정보입니다."
        % sanitize_for_llm(analysis_name, 80)]
    if description:
        parts.append("그래프 설명: %s" % sanitize_for_llm(description, 500))
    if rule_summary:
        parts.append("규칙 기반 요약: %s" % sanitize_for_llm(rule_summary, 1200))
    parts.append("요약 지표(JSON): %s" % sanitize_for_llm(stats_json))
    for turn in (history or [])[-6:]:
        role = "질문" if str(turn.get("role")) == "user" else "이전 답변"
        parts.append("%s: %s" % (role, sanitize_for_llm(str(turn.get("content", "")), 500)))
    q = sanitize_for_llm(str(question or ""), 500).strip()
    if q:
        parts.append("사용자 질문: %s" % q)
        parts.append("위 요약 정보만 근거로 사용자 질문에 한국어로 답하세요.")
    else:
        parts.append("위 요약 정보만 근거로 이 그래프에서 도출할 수 있는 핵심 인사이트를 "
                     "3~5문장의 한국어로 작성하세요. 긍정 요인과 위험 요인을 구분하세요.")
    parts.append("규칙: 통계에 없는 수치를 만들지 말 것. 법률적 판단(FTO/유효성)이나 "
                 "인과관계 단정을 하지 말 것. 표본이 적으면 그 한계를 언급할 것.")
    text = call_llm("\n".join(parts), llm_id=(settings or {}).get("llm_id"),
                    max_tokens=700)
    if text:
        return {"answer": text.strip(), "source": "llm"}
    fallback = rule_summary or MESSAGES["no_data"]
    return {"answer": "%s (근거: 규칙 기반 요약) %s"
            % (MESSAGES["llm_fallback"], fallback), "source": "rule"}


def llm_augment_insight(analysis_name, rule_insight, summary_stats, settings):
    """LLM 인사이트 생성 시도. 실패 시 규칙 기반 그대로 반환 (+폴백 안내).

    summary_stats: 요약 통계 dict (원문 데이터 금지 — 호출부 책임).
    """
    if not (settings or {}).get("llm_insights_enabled"):
        return rule_insight
    if not llm_available():
        out = dict(rule_insight)
        out["llm_note"] = MESSAGES["llm_fallback"]
        return out
    try:
        stats_json = json.dumps(summary_stats, ensure_ascii=False, default=str)[:3500]
    except (TypeError, ValueError):
        stats_json = str(summary_stats)[:3500]
    prompt = (
        "다음은 특허 IP Landscape 분석 '%s' 의 요약 통계입니다.\n"
        "요약 통계(JSON): %s\n\n"
        "위 통계만 근거로 3문장 이내의 한국어 인사이트를 작성하세요. "
        "각 문장에는 분석 기간·비교 기준·핵심 수치를 포함하고, 긍정 요인과 위험 요인을 "
        "구분하세요. 통계에 없는 수치·법률적 판단·인과관계 주장은 금지합니다."
        % (sanitize_for_llm(analysis_name, 100), sanitize_for_llm(stats_json)))
    text = call_llm(prompt, llm_id=(settings or {}).get("llm_id"))
    out = dict(rule_insight)
    if text:
        out["sentences"] = [s.strip() for s in text.strip().split("\n") if s.strip()][:5]
        out["source"] = "llm"
        out["rule_sentences"] = rule_insight.get("sentences", [])
    else:
        out["llm_note"] = MESSAGES["llm_fallback"]
    return out
