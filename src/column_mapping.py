# -*- coding: utf-8 -*-
"""
column_mapping.py — 개념 컬럼 매핑 사전 + 자동 매핑 로직.

계산 논리:
1. CONCEPTS: 개념 컬럼별 정의(한글 라벨, 데이터 형식 설명, 헤더 변형 목록).
   변형 목록은 한글명·영문명·약어·WIPS 실제 헤더 변형을 포함한다.
2. 자동 추천 매핑 파이프라인 (suggest_mapping):
   a) 헤더 정규화: 소문자화, 공백/괄호/특수문자/개행 제거 → _norm()
   b) 사전 완전일치 (정규화된 변형 == 정규화된 실제 헤더)
   c) 사전 부분일치 (변형이 헤더에 포함 또는 그 반대, 길이>=2)
   d) difflib.SequenceMatcher 유사도 매칭 (임계값: THRESHOLDS.fuzzy_match_cutoff)
   각 실제 컬럼은 최대 1개 개념에만 배정한다 (신뢰도 높은 순서로 greedy).
3. 검증(validate_mapping): 분석별 필수 개념(ANALYSIS_REQUIREMENTS)과 매핑 상태를
   비교하여 활성/비활성 매트릭스를 생성한다.

예외처리: 실제 헤더가 비어있거나 중복이면 무시. 매핑 결과에 존재하지 않는 실제
컬럼이 있으면(데이터셋 교체 등) 해당 항목을 제거하고 warnings 에 기록.
"""
import difflib
import re

from src.config import THRESHOLDS

# ---------------------------------------------------------------------------
# 개념 컬럼 정의: key -> {label(한글), dtype(형식 안내), variants([헤더 변형...])}
# ---------------------------------------------------------------------------
CONCEPTS = {
    "pub_number": {
        "label": "공개번호", "dtype": "문자열 (예: KR10-2020-0001234A)",
        "variants": ["공개번호", "공개 번호", "공개(공고)번호", "공개공고번호", "publication number",
                     "pub number", "pub no", "pub_no", "pubno", "공보번호", "publication no",
                     "publn no", "공개번호(공개일)", "publication"],
    },
    "app_number": {
        "label": "출원번호", "dtype": "문자열 (예: KR10-2019-0123456)",
        "variants": ["출원번호", "출원 번호", "application number", "app number", "app no",
                     "appl no", "application no", "출원번호(출원일)", "filing number"],
    },
    "reg_number": {
        "label": "등록번호", "dtype": "문자열 (예: KR10-2345678)",
        "variants": ["등록번호", "등록 번호", "registration number", "reg number", "reg no",
                     "grant number", "patent number", "등록번호(등록일)", "특허번호"],
    },
    "family_id": {
        "label": "패밀리 ID", "dtype": "문자열 또는 숫자 (INPADOC/DOCDB 패밀리 식별자)",
        "variants": ["패밀리 id", "패밀리id", "패밀리 번호", "family id", "family_id", "famid",
                     "inpadoc family id", "docdb family id", "패밀리번호", "family no", "패밀리"],
    },
    "family_rep": {
        "label": "패밀리 대표문헌", "dtype": "문자열 (대표 공개/등록번호)",
        "variants": ["패밀리 대표문헌", "대표문헌", "대표 문헌", "family representative",
                     "representative document", "대표특허", "rep document", "대표문헌번호"],
    },
    "title": {
        "label": "발명의 명칭", "dtype": "문자열",
        "variants": ["발명의 명칭", "발명의명칭", "발명명칭", "명칭", "title", "invention title",
                     "발명의 명칭(국문)", "제목", "title of invention"],
    },
    "abstract": {
        "label": "요약", "dtype": "문자열 (요약문)",
        "variants": ["요약", "초록", "abstract", "요약문", "abstract text", "요약(국문)"],
    },
    "indep_claim": {
        "label": "독립청구항", "dtype": "문자열 (독립항 전문)",
        "variants": ["독립청구항", "독립 청구항", "대표청구항", "대표 청구항", "청구항 1",
                     "independent claim", "indep claim", "first claim", "claim 1", "청구항1",
                     "main claim", "representative claim"],
    },
    "claims": {
        "label": "전체 청구항", "dtype": "문자열 (청구항 전문)",
        "variants": ["전체 청구항", "청구항", "청구범위", "claims", "all claims", "claim text",
                     "청구항 전문", "claims text", "특허청구범위"],
    },
    "applicant": {
        "label": "출원인", "dtype": "문자열 (복수 시 구분자 포함)",
        "variants": ["출원인", "출원인명", "applicant", "applicants", "applicant name",
                     "출원인(국문)", "assignee applicant", "출원인 명칭"],
    },
    "applicant_std": {
        "label": "표준화 출원인", "dtype": "문자열 (정비된 대표 출원인명)",
        "variants": ["표준화 출원인", "표준 출원인", "대표 출원인", "출원인 대표명",
                     "standardized applicant", "normalized applicant", "std applicant",
                     "대표출원인", "출원인(정비)", "current assignee normalized", "출원인 그룹"],
    },
    "assignee": {
        "label": "현재 권리자", "dtype": "문자열",
        "variants": ["현재 권리자", "권리자", "현재권리자", "양수인", "assignee",
                     "current assignee", "owner", "patent owner", "right holder", "권리자명"],
    },
    "inventors": {
        "label": "발명자", "dtype": "문자열 (복수 시 구분자 포함)",
        "variants": ["발명자", "발명자명", "inventor", "inventors", "inventor name",
                     "발명자(국문)", "발명인"],
    },
    "app_date": {
        "label": "출원일", "dtype": "날짜 (YYYY-MM-DD 또는 YYYY.MM.DD)",
        "variants": ["출원일", "출원일자", "application date", "app date", "filing date",
                     "출원년월일", "filed date", "출원 일자"],
    },
    "pub_date": {
        "label": "공개일", "dtype": "날짜",
        "variants": ["공개일", "공개일자", "publication date", "pub date", "공개(공고)일",
                     "공개년월일", "공고일"],
    },
    "reg_date": {
        "label": "등록일", "dtype": "날짜",
        "variants": ["등록일", "등록일자", "registration date", "reg date", "grant date",
                     "등록년월일", "issue date"],
    },
    "priority_date": {
        "label": "우선일", "dtype": "날짜 (최우선일)",
        "variants": ["우선일", "우선권주장일", "최우선일", "priority date", "earliest priority",
                     "earliest priority date", "우선권 주장일", "최우선일자"],
    },
    "expiry_date": {
        "label": "만료예정일", "dtype": "날짜 (존속기간 만료 예정일)",
        "variants": ["만료예정일", "만료일", "존속기간 만료일", "존속기간만료일", "expiry date",
                     "expiration date", "expected expiry", "predicted expiry date", "만료 예정일"],
    },
    "country": {
        "label": "국가", "dtype": "문자열 (국가코드: KR/US/JP/CN/EP 등)",
        "variants": ["국가", "국가코드", "출원국", "출원국가", "country", "country code",
                     "jurisdiction", "office", "국가(코드)", "발행국"],
    },
    "legal_status": {
        "label": "법적상태", "dtype": "문자열 (등록/공개/거절/소멸 등)",
        "variants": ["법적상태", "법적 상태", "행정상태", "행정처분", "legal status", "status",
                     "current status", "법률상태", "법적상태정보"],
    },
    "is_granted": {
        "label": "등록 여부", "dtype": "불리언/문자열 (Y/N, True/False)",
        "variants": ["등록 여부", "등록여부", "granted", "is granted", "grant status",
                     "등록유무", "registered yn"],
    },
    "is_active": {
        "label": "존속 여부", "dtype": "불리언/문자열 (Y/N — 권리 유효 여부)",
        "variants": ["존속 여부", "존속여부", "유효 여부", "유효여부", "권리존속여부", "alive",
                     "is active", "active yn", "in force", "유효특허여부", "권리 존속 여부"],
    },
    "cites_backward": {
        "label": "인용 수", "dtype": "정수 (선행문헌 인용 수)",
        "variants": ["인용 수", "인용수", "인용문헌수", "인용 문헌 수", "backward citations",
                     "citing count", "cited references", "references cited", "인용특허수",
                     "backward citation count", "인용횟수"],
    },
    "cites_forward": {
        "label": "피인용 수", "dtype": "정수 (후행문헌에 의한 피인용 수)",
        "variants": ["피인용 수", "피인용수", "피인용횟수", "피인용 문헌 수", "forward citations",
                     "cited by count", "citation count", "forward citation count", "피인용특허수",
                     "cited by"],
    },
    "family_size": {
        "label": "패밀리 수", "dtype": "정수 (패밀리 문헌 수)",
        "variants": ["패밀리 수", "패밀리수", "패밀리 문헌 수", "family size", "family count",
                     "패밀리문헌수", "simple family size", "extended family size"],
    },
    "family_country_count": {
        "label": "패밀리 국가 수", "dtype": "정수",
        "variants": ["패밀리 국가 수", "패밀리 국가수", "패밀리국가수", "family country count",
                     "family countries", "지정국 수", "출원국 수", "국가 수"],
    },
    "tech_l1": {
        "label": "기술 대분류", "dtype": "문자열",
        "variants": ["기술 대분류", "대분류", "기술대분류", "tech l1", "level1", "level 1",
                     "category l1", "main category", "대분류명", "기술분류(대)", "1차분류"],
    },
    "tech_l2": {
        "label": "기술 중분류", "dtype": "문자열",
        "variants": ["기술 중분류", "중분류", "기술중분류", "tech l2", "level2", "level 2",
                     "category l2", "sub category", "중분류명", "기술분류(중)", "2차분류"],
    },
    "tech_l3": {
        "label": "기술 소분류", "dtype": "문자열",
        "variants": ["기술 소분류", "소분류", "기술소분류", "tech l3", "level3", "level 3",
                     "category l3", "detail category", "소분류명", "기술분류(소)", "3차분류"],
    },
    "tech_multi": {
        "label": "다중 기술분류", "dtype": "문자열 (쉼표/세미콜론/파이프/JSON 배열)",
        "variants": ["다중 기술분류", "다중분류", "복수 기술분류", "기술분류(전체)", "multi class",
                     "multi classification", "all classifications", "기술분류 목록", "복수분류",
                     "multiple categories", "다중기술분류"],
    },
    "class_confidence": {
        "label": "분류 신뢰도", "dtype": "실수 0~1",
        "variants": ["분류 신뢰도", "분류신뢰도", "신뢰도", "classification confidence",
                     "confidence", "confidence score", "class confidence", "분류 확신도"],
    },
    "problem": {
        "label": "해결과제", "dtype": "문자열",
        "variants": ["해결과제", "해결 과제", "과제", "기술적 과제", "problem", "technical problem",
                     "problem to solve", "해결하려는 과제", "발명의 과제"],
    },
    "solution": {
        "label": "해결수단", "dtype": "문자열",
        "variants": ["해결수단", "해결 수단", "수단", "과제 해결 수단", "solution",
                     "solution means", "technical solution", "과제해결수단"],
    },
    "product": {
        "label": "제품", "dtype": "문자열 (적용 제품)",
        "variants": ["제품", "적용제품", "적용 제품", "product", "products", "target product",
                     "응용제품"],
    },
    "process": {
        "label": "공정", "dtype": "문자열",
        "variants": ["공정", "제조공정", "제조 공정", "process", "manufacturing process", "공법"],
    },
    "material": {
        "label": "소재", "dtype": "문자열",
        "variants": ["소재", "재료", "material", "materials", "원재료", "소재/재료"],
    },
    "structure": {
        "label": "구조", "dtype": "문자열",
        "variants": ["구조", "structure", "구조/형상", "형상", "구성"],
    },
    "effect": {
        "label": "효과", "dtype": "문자열",
        "variants": ["효과", "발명의 효과", "effect", "effects", "기대효과", "기술적 효과"],
    },
    "embedding": {
        "label": "임베딩 벡터", "dtype": "문자열(JSON 배열) 또는 숫자 배열",
        "variants": ["임베딩 벡터", "임베딩", "embedding", "embedding vector", "vector",
                     "text embedding", "임베딩벡터", "doc vector", "문서벡터"],
    },
    "is_own": {
        "label": "자사 특허 여부", "dtype": "불리언/문자열 (Y/N)",
        "variants": ["자사 특허 여부", "자사특허여부", "자사 여부", "자사여부", "own patent",
                     "is own", "our patent", "당사 특허", "자사구분", "in-house"],
    },
}

CONCEPT_KEYS = list(CONCEPTS.keys())

# ---------------------------------------------------------------------------
# 분석별 필수/선택 개념 컬럼 (활성/비활성 매트릭스의 근거)
# 기술분류는 tech_l1/l2/l3/tech_multi 중 하나라도 있으면 되는 경우
# "any:" 그룹으로 표기한다.
# ---------------------------------------------------------------------------
ANY_TECH = ["tech_l1", "tech_l2", "tech_l3", "tech_multi"]
ANY_APPLICANT = ["applicant_std", "applicant"]
ANY_DATE = ["app_date", "priority_date", "pub_date"]

ANALYSIS_REQUIREMENTS = {
    "overview":              {"required": [{"any": ANY_TECH}, {"any": ANY_DATE}], "optional": ANY_APPLICANT + ["legal_status", "country"]},
    "technology-network":    {"required": [{"any": ANY_TECH}], "optional": ["family_id", "app_date"] + ANY_APPLICANT},
    "emerging-combinations": {"required": [{"any": ANY_TECH}, {"any": ANY_DATE}], "optional": ANY_APPLICANT + ["is_active", "legal_status"]},
    "lifecycle":             {"required": [{"any": ANY_TECH}, {"any": ANY_DATE}], "optional": ANY_APPLICANT + ["is_active", "legal_status", "cites_forward"]},
    "opportunity":           {"required": [{"any": ANY_TECH}, {"any": ANY_DATE}], "optional": ANY_APPLICANT + ["legal_status", "is_active", "problem", "product", "process", "family_country_count", "expiry_date", "is_own"]},
    "problem-solution":      {"required": ["problem", "solution"], "optional": [{"any": ANY_DATE}] + ANY_APPLICANT + ["indep_claim", "is_active", "legal_status"]},
    "technology-transition": {"required": [{"any": ANY_TECH}, {"any": ANY_DATE}], "optional": ["family_id"] + ANY_APPLICANT},
    "trajectory":            {"required": [{"any": ANY_TECH}, {"any": ANY_DATE}, {"any": ANY_APPLICANT}], "optional": ["family_id", "is_active"]},
    "company-dna":           {"required": [{"any": ANY_TECH}, {"any": ANY_DATE}, {"any": ANY_APPLICANT}], "optional": ["family_size", "family_country_count", "cites_forward", "legal_status", "inventors", "family_id"]},
    "lead-lag":              {"required": [{"any": ANY_TECH}, {"any": ANY_DATE}, {"any": ANY_APPLICANT}], "optional": []},
    "claim-density":         {"required": ["indep_claim", {"any": ANY_TECH}], "optional": ["embedding", "legal_status", "expiry_date", "family_id", "cites_forward"] + ANY_APPLICANT},
    "citation-diffusion":    {"required": ["cites_forward", {"any": ANY_TECH}], "optional": ["cites_backward", "family_size", "family_country_count", "legal_status", "expiry_date"] + ANY_APPLICANT},
    "inventor-mobility":     {"required": ["inventors", {"any": ANY_APPLICANT}, {"any": ANY_DATE}], "optional": [{"any": ANY_TECH}, "country"]},
    "classification-quality": {"required": [{"any": ANY_TECH}], "optional": ["embedding", "class_confidence", "title", "abstract", {"any": ANY_DATE}]},
}

_NORM_RE = re.compile(r"[\s\(\)\[\]\{\}\-_/\\.,:;'\"·|]+")


def _norm(s):
    """헤더 정규화: 소문자화 + 공백/특수문자 제거."""
    if s is None:
        return ""
    return _NORM_RE.sub("", str(s).strip().lower())


def suggest_mapping(actual_columns, cutoff=None):
    """실제 컬럼 목록 → {concept: {column, method, score}} 자동 추천 매핑.

    매칭 순서: 완전일치(1.0) → 부분일치(0.85) → difflib 유사도(cutoff 이상).
    하나의 실제 컬럼은 하나의 개념에만 배정 (점수 높은 순 greedy).
    """
    if cutoff is None:
        cutoff = THRESHOLDS["fuzzy_match_cutoff"]
    cols = [c for c in actual_columns if c is not None and str(c).strip() != ""]
    norm_cols = {c: _norm(c) for c in cols}

    candidates = []  # (score, concept, column, method)
    for concept, spec in CONCEPTS.items():
        norm_variants = [_norm(v) for v in spec["variants"]]
        for col, ncol in norm_cols.items():
            if not ncol:
                continue
            best = None
            if ncol in norm_variants:
                best = (1.0, "exact")
            else:
                for nv in norm_variants:
                    if len(nv) >= 2 and (nv in ncol or ncol in nv):
                        best = (0.85, "partial")
                        break
                if best is None:
                    ratio = max(
                        (difflib.SequenceMatcher(None, ncol, nv).ratio() for nv in norm_variants),
                        default=0.0)
                    if ratio >= cutoff:
                        best = (round(ratio, 3), "fuzzy")
            if best:
                candidates.append((best[0], concept, col, best[1]))

    candidates.sort(key=lambda t: (-t[0], t[1], t[2]))
    mapping, used_cols, used_concepts = {}, set(), set()
    for score, concept, col, method in candidates:
        if concept in used_concepts or col in used_cols:
            continue
        mapping[concept] = {"column": col, "method": method, "score": score}
        used_concepts.add(concept)
        used_cols.add(col)
    return mapping


def clean_mapping(mapping, actual_columns):
    """저장된 매핑에서 실제 존재하지 않는 컬럼 항목 제거. 반환: (clean, warnings)."""
    actual = set(actual_columns or [])
    clean, warnings = {}, []
    for concept, col in (mapping or {}).items():
        if concept not in CONCEPTS:
            warnings.append("알 수 없는 개념 컬럼 매핑 무시: %s" % concept)
            continue
        if col and col in actual:
            clean[concept] = col
        elif col:
            warnings.append("매핑된 컬럼이 데이터셋에 없어 제외: %s → %s" % (CONCEPTS[concept]["label"], col))
    return clean, warnings


def _requirement_met(req, mapped_concepts):
    """단일 필수 항목 충족 여부. req 는 개념 key 문자열 또는 {"any": [keys]}."""
    if isinstance(req, dict) and "any" in req:
        return any(k in mapped_concepts for k in req["any"])
    return req in mapped_concepts


def _requirement_label(req):
    if isinstance(req, dict) and "any" in req:
        return " 또는 ".join(CONCEPTS[k]["label"] for k in req["any"])
    return CONCEPTS[req]["label"]


def analysis_availability(mapping):
    """분석별 사용 가능 여부 매트릭스.

    mapping: {concept: actual_column} (단순 dict).
    반환: {analysis: {available, missing: [필수 라벨...], optional_missing: [...]}}
    """
    mapped = set(k for k, v in (mapping or {}).items() if v)
    out = {}
    for analysis, spec in ANALYSIS_REQUIREMENTS.items():
        missing = [_requirement_label(r) for r in spec["required"]
                   if not _requirement_met(r, mapped)]
        opt_missing = [_requirement_label(r) for r in spec.get("optional", [])
                       if not _requirement_met(r, mapped)]
        out[analysis] = {
            "available": len(missing) == 0,
            "missing": missing,
            "optional_missing": opt_missing,
            "required": [_requirement_label(r) for r in spec["required"]],
        }
    return out


def concept_catalog():
    """컬럼 매핑 화면용 개념 컬럼 카탈로그 (key, 라벨, 형식)."""
    return [{"key": k, "label": v["label"], "dtype": v["dtype"]} for k, v in CONCEPTS.items()]
