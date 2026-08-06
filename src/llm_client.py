# -*- coding: utf-8 -*-
"""
llm_client.py — Dataiku LLM Mesh 호출 (고정 모델 목록, 인젝션 방지, 폴백).

보안 원칙:
- 허용 모델은 config.ALLOWED_LLM_CANDIDATES 로 고정. 그 외 llm_id 는 거부.
- LLM 호출은 Backend 전용. 프론트에는 표시명(label)만 전달하고 llm_id·키를 노출하지 않음.
- 원문 특허 데이터를 전송하지 않고 요약 통계 문자열만 전달 (호출부 책임 + 길이 상한).
- sanitize_for_llm(): 제어문자 제거, 프롬프트 인젝션 유도 패턴 무력화, 길이 제한.
- 호출 실패/미가용 시 호출부가 규칙 기반 인사이트로 폴백할 수 있도록 None 반환.
"""
import logging
import re

from src.config import ALLOWED_LLM_IDS, DEFAULT_LLM_ID, LIMITS, LEGACY_LLM_ID_MAP

logger = logging.getLogger("ip_landscape")

try:
    import dataiku as _dataiku_mod
except ImportError:
    _dataiku_mod = None

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# 프롬프트 인젝션에 흔한 지시 패턴 (대소문자 무시) — 통계 요약에 나타날 이유가 없는 문자열
_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|above|prior)\s+instructions?",
    r"disregard\s+(all\s+)?(previous|above|prior)",
    r"system\s*prompt", r"you\s+are\s+now", r"act\s+as\s+", r"jailbreak",
    r"이전\s*지시(를|사항)?\s*무시", r"시스템\s*프롬프트",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)


def sanitize_for_llm(text, max_chars=None):
    """LLM 입력 sanitization: 제어문자 제거 + 인젝션 패턴 마스킹 + 길이 제한."""
    if text is None:
        return ""
    s = str(text)
    s = _CONTROL_RE.sub(" ", s)
    s = _INJECTION_RE.sub("[제거됨]", s)
    limit = int(max_chars or LIMITS["insight_llm_max_chars"])
    return s[:limit]


def resolve_llm_id(requested_id):
    """요청된 llm_id 를 허용 목록과 대조. 허용되지 않으면 기본 모델.

    구(舊) Connection 의 ID 는 LEGACY_LLM_ID_MAP 으로 신규 Connection 에 자동
    승계된다 (저장된 설정 마이그레이션).
    """
    if requested_id in LEGACY_LLM_ID_MAP:
        migrated = LEGACY_LLM_ID_MAP[requested_id]
        logger.info("구 LLM Connection 자동 승계: %s → %s", requested_id, migrated)
        requested_id = migrated
    if requested_id in ALLOWED_LLM_IDS:
        return requested_id
    if requested_id:
        logger.warning("허용되지 않은 LLM ID 요청 차단: %r", requested_id)
    return DEFAULT_LLM_ID


def llm_available():
    """LLM Mesh 사용 가능 여부."""
    return _dataiku_mod is not None


def call_llm(prompt, llm_id=None, max_tokens=800, temperature=0.2):
    """LLM Mesh 호출. 성공 시 응답 텍스트, 실패·미가용 시 None (호출부 폴백).

    dataiku.api_client().get_default_project().get_llm(llm_id) 방식 사용.
    """
    if _dataiku_mod is None:
        logger.info("LLM Mesh 미가용 환경 — 규칙 기반 폴백")
        return None
    llm_id = resolve_llm_id(llm_id)
    safe_prompt = sanitize_for_llm(prompt)
    try:
        client = _dataiku_mod.api_client()
        project = client.get_default_project()
        llm = project.get_llm(llm_id)
        completion = llm.new_completion()
        completion.settings["maxOutputTokens"] = int(max_tokens)
        completion.settings["temperature"] = float(temperature)
        completion.with_message(
            "당신은 특허 데이터 분석 결과를 요약하는 조수입니다. 전달된 요약 통계만 근거로, "
            "법률적 판단이나 인과관계 주장 없이 한국어로 간결한 인사이트를 작성하세요. "
            "통계에 없는 수치를 만들어내지 마세요.", role="system")
        completion.with_message(safe_prompt, role="user")
        resp = completion.execute()
        if getattr(resp, "success", False):
            return getattr(resp, "text", None)
        logger.warning("LLM 응답 실패: %s", getattr(resp, "raw", None))
        return None
    except Exception as e:
        logger.warning("LLM 호출 오류: %s", e)
        return None
