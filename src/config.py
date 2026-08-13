# -*- coding: utf-8 -*-
"""
config.py — 전역 상수, 허용 LLM 목록, 임계값·가중치 기본값, 상한(LIMITS).

모든 설정값은 상수로 정의하며, 런타임에는 storage.load_settings()가 반환하는
사용자 설정(dict)이 이 기본값 위에 overlay 된다. UI 문자열(안내문·면책문구 등)은
MESSAGES 에 모아 계산 로직과 분리한다.
"""

APP_NAME = "IP Landscape Advanced Insight"
APP_VERSION = "3.0.0"  # 1단계=1.x, 2단계=2.x, 3단계=3.x

# =========================
# 사용 허용할 LLM 목록 (고정)
# =========================
ALLOWED_LLM_CANDIDATES = [
    ("gpt-5-mini | DW_AOAI_APIM_DES1_LOW", "azureopenai:DW_AOAI_APIM_DES1_LOW:gpt-5-mini"),
    ("gpt-5 | DW_AOAI_APIM_DES1_MID", "azureopenai:DW_AOAI_APIM_DES1_MID:gpt-5"),
    ("gpt-5.4-mini | DW_AOAI_APIM_DES1_LOW", "azureopenai:DW_AOAI_APIM_DES1_LOW:gpt-5.4-mini"),
    ("gpt-5.4 | DW_AOAI_APIM_DES1_MID", "azureopenai:DW_AOAI_APIM_DES1_MID:gpt-5.4"),
]
DEFAULT_LLM_ID = "azureopenai:DW_AOAI_APIM_DES1_LOW:gpt-5-mini"
ALLOWED_LLM_IDS = frozenset(llm_id for _, llm_id in ALLOWED_LLM_CANDIDATES)

# 구(舊) Connection → 신규 Connection 마이그레이션 (저장된 설정 자동 승계)
#   azoai_* / dw-aoai-chat-eastus2-cognitiv / dw-aoai-response-eastus2-cognitiv
#   → DW_AOAI_APIM_DES1_LOW(미니급) / _MID(상위) / _EMB(임베딩)
_OLD_CHAT_CONNS = ("azoai_gpt-5-mini", "azoai_gpt5", "dw-aoai-chat-eastus2-cognitiv",
                   "dw-aoai-response-eastus2-cognitiv")
LEGACY_LLM_ID_MAP = {}
for _conn in _OLD_CHAT_CONNS:
    LEGACY_LLM_ID_MAP["azureopenai:%s:gpt-5-mini" % _conn] = \
        "azureopenai:DW_AOAI_APIM_DES1_LOW:gpt-5-mini"
    LEGACY_LLM_ID_MAP["azureopenai:%s:gpt-5" % _conn] = \
        "azureopenai:DW_AOAI_APIM_DES1_MID:gpt-5"
    LEGACY_LLM_ID_MAP["azureopenai:%s:gpt-5.4-mini" % _conn] = \
        "azureopenai:DW_AOAI_APIM_DES1_LOW:gpt-5.4-mini"
    LEGACY_LLM_ID_MAP["azureopenai:%s:gpt-5.4" % _conn] = \
        "azureopenai:DW_AOAI_APIM_DES1_MID:gpt-5.4"
# 이전 허용 목록에만 있던 모델 → 등급이 비슷한 신규 모델로 승계
LEGACY_LLM_ID_MAP["azureopenai:dw-aoai-chat-eastus2-cognitiv:gpt-5.4-nano"] = \
    "azureopenai:DW_AOAI_APIM_DES1_LOW:gpt-5-mini"
LEGACY_LLM_ID_MAP["azureopenai:dw-aoai-chat-eastus2-cognitiv:gpt-5.3-chat"] = \
    "azureopenai:DW_AOAI_APIM_DES1_MID:gpt-5"
# 임베딩 Connection (LLM Mesh 임베딩 adapter 사용 시)
LEGACY_LLM_ID_MAP["azureopenai:azoai_embedding-3-small:text-embedding-3-small"] = \
    "azureopenai:DW_AOAI_APIM_DES1_EMB:text-embedding-3-small"
LEGACY_LLM_ID_MAP["azureopenai:azoai_embedding-3-large:text-embedding-3-large"] = \
    "azureopenai:DW_AOAI_APIM_DES1_EMB:text-embedding-3-large"

# 임베딩 모델 (Dataiku 사내 서버에 설치된 한국어 특허 특화 SBERT — 비용 없음)
# 사내 서버 로컬 설치 경로: 네트워크 다운로드 없이 디스크에서 직접 로드한다.
LOCAL_SBERT_MODEL_DIR = (
    "/dataiku/cache/huggingface/hub/"
    "models--snunlp--KR-SBERT-Medium-extended-patent2024-hn/"
    "snapshots/2a89bb1bbd16d851c05fa67629a76187dfc7d552")
DEFAULT_SBERT_MODEL = "snunlp/KR-SBERT-Medium-extended-patent2024-hn"
# 로딩 시도 순서: 로컬 경로(존재 시) → HF 캐시의 2024-hn → 구버전 2023
SBERT_MODEL_CANDIDATES = [
    LOCAL_SBERT_MODEL_DIR,
    DEFAULT_SBERT_MODEL,
    "snunlp/KR-SBERT-Medium-extended-patent2023",
]

# =========================
# 규모 상한 (Settings 에서 변경 가능 — settings["limits"] 로 overlay)
# =========================
LIMITS = {
    "network_max_nodes": 80,          # 조합 네트워크 노드 상한 (Top-N by weight)
    "network_max_edges": 250,         # 조합 네트워크 엣지 상한
    "sankey_max_links": 120,          # Sankey 링크 상한
    "bubble_max_points": 200,         # 버블차트 포인트 상한
    "heatmap_max_cells": 2500,        # Plotly 히트맵 셀 상한 (초과 시 ECharts 전환)
    "echarts_threshold_cells": 100000,  # ECharts 필요 기준 (10만 셀)
    "matrix_max_rows": 40,            # 문제-해결수단 매트릭스 행 상한
    "matrix_max_cols": 40,
    "patents_page_size": 25,          # drill-down 페이지 크기
    "patents_max_page_size": 200,
    "export_max_rows": 20000,         # Excel export 행 상한
    "top_n_default": 10,
    "max_companies_compare": 12,      # DNA 레이더 최대 기업 수 (초과 시 히트맵)
    "trajectory_max_companies": 10,
    "leadlag_max_companies": 20,
    "claim_density_max_points": 5000, # 지형도 산점 상한 (초과 시 샘플링)
    "inventor_network_max_edges": 200,
    "insight_llm_max_chars": 4000,    # LLM 에 전달하는 요약통계 문자열 상한
    "entropy_top_companies": 6,       # 권리범위 엔트로피 레이더 기업 수
    "upset_max_elements": 12,         # UpSet 추적 기술요소 상한
    "upset_max_combos": 25,           # UpSet 표시 조합 상한
    "web_search_max_results": 5,      # LLM 인사이트 웹 검색 결과 상한
    "semantic_max_docs": 3000,        # 의미 분석(신흥 탐지·의미 영향력) 임베딩 문헌 상한
    "simnet_max_docs": 600,           # 유사도 네트워크 문헌 상한 (가독성·메모리)
    "simnet_max_edges": 400,          # 유사도 네트워크 엣지 상한 (유사도 상위)
}

# =========================
# 분석 임계값 기본값 (Settings 에서 변경 가능 — settings["thresholds"])
# =========================
THRESHOLDS = {
    "min_combo_patents": 3,        # 조합 최소 표본 (미만 조합 제외)
    "min_class_patents": 3,        # 기술분류 최소 표본
    "recent_years": 3,             # "최근" 정의 (년)
    "fuzzy_match_cutoff": 0.75,    # 컬럼 자동매핑 유사도 임계값
    "winsor_pct": 0.02,            # Winsorization 양측 백분위
    "min_years_leadlag": 5,        # 선도-추종 최소 관측연도
    "min_patents_leadlag": 10,     # 선도-추종 최소 특허 수
    "max_lag_years": 3,            # 선도-추종 최대 시차
    "leadlag_min_corr": 0.5,       # 선도-추종 최소 상관
    "inventor_match_confidence": 0.6,  # 발명자 동일인 판정 신뢰도 임계값
    "low_confidence_class": 0.5,   # 저신뢰 분류 임계값 (분류 신뢰도 컬럼)
    "emerging_min_growth": 0.3,    # Emerging 단계 최소 성장률
    "reemerging_decline_years": 3, # Re-emerging: 과거 감소·정체 기간
    "insight_small_sample": 10,    # 표본 부족 경고 기준 (건)
    "sim_topk_per_doc": 20,        # 청구항 유사도 상위 K 이웃만 유지
    "semantic_sim_threshold": 0.8,   # 의미 기반 후속 특허 판정 코사인 임계값
    "overlap_sim_threshold": 0.85,   # 권리 중첩 네트워크 엣지 코사인 임계값
    "emerging_cluster_recent_share": 0.5,  # 신흥 군집: 최근 3년 출원 비중 기준
    "ps_group_distance": 0.45,       # 문제-해결수단 의미 그룹핑 코사인 거리 임계값
                                     # (낮을수록 엄격 → 그룹 많아짐)
}

# =========================
# 점수 가중치 기본값 (Settings 슬라이더 — settings["weights"])
# =========================
WEIGHTS = {
    # Emerging Combination Score = 가중 기하평균(성장률, Lift, 신규출원인, 다양성)
    "emerging": {"growth": 1.0, "lift": 1.0, "new_entrants": 1.0, "diversity": 0.5},
    # Opportunity Score = 매력도(기회) x 진입가능성(1/장벽)
    "opportunity": {
        "growth": 1.0, "new_entrants": 1.0, "combo_growth": 0.7,
        "keyword_growth": 0.5, "problem_recurrence": 0.5, "adjacency": 0.7,
        "barrier": 1.0,  # 분모(권리장벽)
    },
    # Influence Score
    "influence": {
        "direct_citations": 1.0, "indirect_citations": 0.7, "cross_class": 0.8,
        "cross_company": 0.8, "family_expansion": 0.6, "legal_strength": 0.6,
    },
    # 기업 유형 분류 기준값 (표준화 점수 기준, 사용자가 조정 가능)
    "dna_type_cutoff": 0.6,
}

# =========================
# 법적상태 정규화 카테고리 (원본값 보존, normalized 컬럼 병행)
# =========================
LEGAL_STATUS_CATEGORIES = [
    "Pending", "Granted-Active", "Granted-Expired", "Abandoned",
    "Withdrawn", "Rejected", "Lapsed", "Unknown",
]
ACTIVE_LEGAL_STATUSES = frozenset(["Granted-Active", "Pending"])
GRANTED_LEGAL_STATUSES = frozenset(["Granted-Active", "Granted-Expired"])

# 법적상태 원본 → 정규화 매핑 (소문자 부분일치, 순서 = 우선순위)
LEGAL_STATUS_PATTERNS = [
    ("존속기간만료", "Granted-Expired"), ("granted-expired", "Granted-Expired"),
    ("expired", "Granted-Expired"), ("만료", "Granted-Expired"),
    ("granted-active", "Granted-Active"), ("등록유지", "Granted-Active"),
    ("in force", "Granted-Active"), ("active", "Granted-Active"),
    ("유효", "Granted-Active"), ("존속", "Granted-Active"),
    ("소멸", "Lapsed"), ("lapsed", "Lapsed"), ("연차료불납", "Lapsed"),
    ("non-payment", "Lapsed"), ("포기", "Abandoned"), ("abandon", "Abandoned"),
    ("취하", "Withdrawn"), ("withdraw", "Withdrawn"),
    ("거절", "Rejected"), ("reject", "Rejected"), ("refus", "Rejected"),
    ("무효", "Rejected"),
    ("등록", "Granted-Active"), ("grant", "Granted-Active"), ("registered", "Granted-Active"),
    ("출원계속", "Pending"), ("심사중", "Pending"), ("pending", "Pending"),
    ("공개", "Pending"), ("published", "Pending"), ("examination", "Pending"),
    ("출원", "Pending"), ("filed", "Pending"),
]

# 분석 단위
ANALYSIS_UNITS = ["family", "publication", "application", "registration"]
DEFAULT_ANALYSIS_UNIT = "family"

# 다중 기술분류 집계 방식
MULTICLASS_MODES = ["duplicate", "fractional", "primary", "level_separate"]
DEFAULT_MULTICLASS_MODE = "duplicate"

# 공동출원(복수 출원인) 집계 방식 — 출원인별 순위·매트릭스·버블 등에 적용.
#   all   : 공동출원 1건을 각 공동출원인에게 1건씩 집계 (WIPS 방식, 합계>전체 가능)
#   first : 대표(첫) 출원인 1건만 집계
# 협력 네트워크·공동출원 비율 등 '공동출원 자체'를 분석하는 화면에는 적용되지 않는다.
COAPPLICANT_MODES = ["all", "first"]
DEFAULT_COAPPLICANT_MODE = "all"

# 생애주기 단계
LIFECYCLE_PHASES = ["Emerging", "Growing", "Competitive", "Mature", "Declining", "Re-emerging"]

# 기업 유형 (4.5 규칙 기반 분류)
COMPANY_TYPES = ["선도 개척형", "권리 장벽형", "집중 방어형", "융합 확장형", "추격 확장형", "양적 출원형"]

# =========================
# UI 문자열 (계산 로직과 분리)
# =========================
MESSAGES = {
    "disclaimer": ("본 분석은 특허 데이터에 기반한 탐색적 스크리닝 결과이며, "
                   "법률적 FTO 판단, 특허 유효성 판단 또는 인과관계를 의미하지 않습니다."),
    "small_sample": "현재 표본 수가 적어 추세를 확정하기 어렵습니다.",
    "missing_columns": "필수 컬럼이 없습니다. 컬럼 매핑 화면에서 다음 컬럼을 매핑하세요: {cols}",
    "no_data": "필터 조건에 해당하는 데이터가 없어 계산할 수 없습니다.",
    "not_implemented": "이 분석은 아직 구현되지 않았습니다 (다음 단계 예정).",
    "no_dataset": "Dataset 이 선택되지 않았습니다. Settings 에서 Dataset 을 선택하세요.",
    "llm_fallback": "LLM 응답에 실패하여 규칙 기반 인사이트로 대체되었습니다.",
    "estimated_move": "추정 이동",
}

# 오류 코드
ERR_BAD_REQUEST = 400
ERR_NOT_FOUND = 404
ERR_NOT_IMPLEMENTED = 501
ERR_INTERNAL = 500

# 데모 모드 기본값 (사용자가 Settings 에서 명시적으로 켠 경우에만 샘플 데이터 사용)
DEFAULT_SETTINGS = {
    "dataset": None,
    "demo_mode": False,
    "analysis_unit": DEFAULT_ANALYSIS_UNIT,
    "multiclass_mode": DEFAULT_MULTICLASS_MODE,
    "coapplicant_mode": DEFAULT_COAPPLICANT_MODE,
    "llm_id": DEFAULT_LLM_ID,
    "llm_insights_enabled": False,
    # none | dataset | rest | sbert(로컬 sentence-transformers) | llm_mesh
    # 기본: KR-SBERT 특허 특화 모델. model_name 이 비어 있으면 자동
    # (사내 로컬 경로 → HF 캐시 순서, SBERT_MODEL_CANDIDATES). 사전 계산 임베딩
    # 컬럼이 있으면 그것이 우선, 모델 로드 불가 환경에서는 TF-IDF 폴백.
    "embedding_adapter": {"type": "sbert", "model_name": ""},
    # 업로드된 임베딩 벡터 파일(.npy/.npz) entry id — 지정 시 raw 컬럼 매핑 대신
    # 출원번호/공개번호 매칭으로 _embedding 을 채운다 (모델 재계산보다 우선)
    "embedding_file_id": None,
    # LLM 인사이트에 외부 웹 검색 결과 컨텍스트 첨부 허용 (요청별 체크박스로 사용)
    "web_search_enabled": True,
    "limits": {}, "thresholds": {}, "weights": {},
    "transition_mode": "cooccurrence",  # 4.1 전이 정의 기본값
    "trajectory_weighting": "share",    # share | tfidf
    "dna_type_cutoffs": {},
    "own_company_names": [],            # 자사 표준 출원인명 목록
    "own_capability_keywords": [],      # 사용자가 입력한 보유 기술목록
}


def merged_settings(user_settings):
    """DEFAULT_SETTINGS 위에 사용자 설정을 overlay 한 dict 반환 (dict 값은 개별 병합)."""
    out = {}
    for k, v in DEFAULT_SETTINGS.items():
        out[k] = dict(v) if isinstance(v, dict) else (list(v) if isinstance(v, list) else v)
    for k, v in (user_settings or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def get_limit(settings, key):
    """상한값 조회: 사용자 설정 → 기본 LIMITS."""
    try:
        v = (settings or {}).get("limits", {}).get(key)
        if v is not None:
            return int(v)
    except Exception:
        pass
    return LIMITS[key]


def get_threshold(settings, key):
    """임계값 조회: 사용자 설정 → 기본 THRESHOLDS."""
    try:
        v = (settings or {}).get("thresholds", {}).get(key)
        if v is not None:
            return float(v)
    except Exception:
        pass
    return THRESHOLDS[key]


def get_weights(settings, group):
    """가중치 그룹 조회: 기본 WEIGHTS[group] 위에 사용자 설정 overlay."""
    base = dict(WEIGHTS.get(group, {}))
    user = (settings or {}).get("weights", {}).get(group, {})
    if isinstance(user, dict):
        for k, v in user.items():
            if k in base:
                try:
                    base[k] = float(v)
                except (TypeError, ValueError):
                    pass
    return base
