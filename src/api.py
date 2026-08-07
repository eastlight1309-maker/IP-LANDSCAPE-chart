# -*- coding: utf-8 -*-
"""
api.py — API 응답 모듈. register_routes(app) 로 모든 엔드포인트를 등록한다.

공통 규약:
- 요청: POST JSON {"dataset"?, "filters"?, ...분석별 옵션}. dataset 미지정 시
  Settings 에 저장된 dataset 사용.
- 정상 응답: 분석 envelope (viz_payload.ok_result/empty_result/disabled_result).
- 오류 응답: {"status":"error","code":<HTTP코드>,"message":<안내문>} (표준 형식).
- 데이터 없음: {"status":"empty", ...} / 컬럼 누락: {"status":"disabled", ...}.
- 모든 분석 결과는 cache.cached_analysis 로 (dataset, 필터, 설정) 키 캐싱.
- 보안: dataset 명 화이트리스트 검증, 매핑된 컬럼만 사용, LLM ID 는 프론트에
  노출하지 않음(라벨만), 오류 메시지에 내부 경로·스택 미노출.

엔드포인트 목록 (Docstring 에 요청/응답 명세):
  GET  /api/config              앱 구성·분석 가용성 매트릭스·실행 로그
  GET  /api/datasets            Dataset 목록
  GET  /api/columns             Dataset 컬럼 목록 (?dataset=)
  GET/POST /api/column-mapping  자동 추천/저장/검증
  POST /api/filter-options      필터바 옵션
  POST /api/overview            Executive Overview
  POST /api/technology-network  4.2 조합 네트워크
  POST /api/technology-transition 4.1 전이 Sankey
  POST /api/emerging-combinations 4.3 Emerging Radar
  POST /api/trajectory          4.4 궤적
  POST /api/company-dna         4.5 DNA (+유사도·중첩도)
  POST /api/lead-lag            4.6 선도-추종
  POST /api/lifecycle           4.7 생애주기
  POST /api/opportunity         4.8 White Space
  POST /api/claim-density       4.9 권리장벽 지형도
  POST /api/citation-diffusion  4.10 영향력 전파
  POST /api/inventor-mobility   4.11 발명자 이동
  POST /api/classification-quality 4.12 분류 품질
  POST /api/problem-solution    문제-해결수단 매트릭스 (+cell 상세)
  POST /api/scope-entropy       권리범위 엔트로피 레이더·시계열
  POST /api/combo-upset         미점유 조합 UpSet
  POST /api/emerging-clusters   신흥 기술 조기 탐지 (임베딩 군집)
  POST /api/semantic-influence  의미 기반 인용/영향력 대체 지표
  POST /api/similarity-network  특허 유사도 네트워크 (권리 중첩 그래프)
  POST /api/wips-deep           심층 시그널 (연차료 생존·진입 시차·대리인·심사·심판)
  POST /api/executive-summary   경영진 전략 대시보드 (BCG·경쟁 포지션·alert)
  POST /api/patents             근거 특허 drill-down (페이지네이션)
  POST /api/insight             LLM 인사이트 (요약 통계만 전달, 실패 시 규칙 기반)
  POST /api/export              Excel 다운로드
  POST /api/project/save|load   프로젝트 저장·불러오기 (+list)
  GET/POST /api/uploads         엑셀 업로드 작업 저장소 (+/load, /delete)
  GET/POST /api/settings        설정 조회/저장
  GET/POST /api/applicant-rules 출원인 표준화 규칙
  POST /api/filter-state        필터 상태 저장
"""
import io
import json
import logging
import re
import time
import traceback

import numpy as np
import pandas as pd

from src.config import (APP_NAME, APP_VERSION, ALLOWED_LLM_CANDIDATES, MESSAGES,
                        LEGAL_STATUS_CATEGORIES, ANALYSIS_UNITS, MULTICLASS_MODES,
                        LIMITS, THRESHOLDS, WEIGHTS, DEFAULT_SETTINGS,
                        merged_settings, get_limit)
from src.cache import cached_analysis, get_run_log, clear_all_caches
from src.column_mapping import (suggest_mapping, clean_mapping, analysis_availability,
                                concept_catalog, validate_mapping_values, CONCEPTS)
from src.preprocessing import apply_filters, filter_options, auto_standardize_name, \
    split_names
from src.data_access import (list_datasets, validate_dataset_name, get_dataset_columns,
                             get_prepared, inject_dataset, load_sample_dataframe)
from src import storage
from src.uploads import (save_upload as uploads_save, list_uploads as uploads_list,
                         load_upload as uploads_load,
                         delete_upload as uploads_delete,
                         ensure_loaded as uploads_ensure_loaded)
from src.insight_store import (add_insight, list_insights, delete_insight,
                               get_insights, build_pptx,
                               get_image as insight_get_image)
from src.insights import llm_augment_insight, llm_chat, build_insight, \
    format_chart_context
from src.viz_payload import jsonable, empty_result
from src.analyses.common import select_patents, patent_records, export_dataframe
from src.analyses.overview import compute_overview
from src.analyses.tech_network import compute_tech_network
from src.analyses.emerging import compute_emerging
from src.analyses.lifecycle import compute_lifecycle
from src.analyses.whitespace import compute_opportunity
from src.analyses.problem_solution import compute_problem_solution, cell_detail, \
    compute_ps_semantic
from src.analyses.transition import compute_transition, TRANSITION_MODES
from src.analyses.trajectory import compute_trajectory
from src.analyses.company_dna import compute_company_dna
from src.analyses.lead_lag import compute_lead_lag
from src.analyses.claim_density import compute_claim_density
from src.analyses.citation_influence import compute_citation_influence
from src.analyses.inventor_mobility import compute_inventor_mobility
from src.analyses.classification_quality import compute_classification_quality
from src.analyses.basic_stats import compute_basic_stats, compute_tech_year_bubble
from src.analyses.portfolio_index import compute_portfolio_index
from src.analyses.advanced_stats import compute_advanced_stats
from src.analyses.scope_entropy import compute_scope_entropy
from src.analyses.combo_upset import compute_combo_upset
from src.analyses.semantic_insights import (compute_emerging_clusters,
                                            compute_semantic_influence,
                                            compute_similarity_network)
from src.analyses.wips_deep import compute_wips_deep
from src.analyses.executive import compute_executive_summary
from src.analyses.axis_cross import compute_axis_cross
from src.analyses.ownership import compute_ownership
from src.web_search import search_web, format_web_context
from src.llm_client import sanitize_for_llm

logger = logging.getLogger("ip_landscape")

DEMO_DATASET_NAME = "__demo__"


def _error(code, message):
    return {"status": "error", "code": int(code), "message": str(message)}, int(code)


def _settings():
    return merged_settings(storage.load_settings())


def _make_demo_dataframe(n=400, seed=7):
    """Demo mode 전용 최소 합성 데이터 (반도체 패키징 도메인).

    사용자가 Settings 에서 demo_mode 를 명시적으로 켠 경우에만 사용된다.
    분석 본체는 실제 데이터 없이 값을 생성하지 않는다는 원칙의 예외가 아니라,
    '사용자가 명시적으로 선택한 Demo mode' 규칙에 따른 화면 확인용 데이터이다.
    """
    rng = np.random.default_rng(seed)
    l1 = ["패키징", "본딩", "테스트"]
    l2 = {"패키징": ["FOWLP", "FOPLP", "2.5D 인터포저", "3D 적층"],
          "본딩": ["하이브리드 본딩", "TCB", "와이어 본딩"],
          "테스트": ["웨이퍼 테스트", "번인 테스트"]}
    companies = ["삼성전자", "SK하이닉스", "TSMC", "Intel", "ASE", "Amkor", "네패스", "LB세미콘"]
    problems = ["휨(warpage) 저감", "미세피치 접합", "방열 개선", "수율 향상", "두께 감소"]
    solutions = ["몰드 소재 개선", "범프 구조 변경", "공정 온도 제어", "적층 구조 변경", "검사 알고리즘"]
    rows = []
    for i in range(n):
        a = l1[rng.integers(0, len(l1))]
        bs = l2[a]
        b = bs[rng.integers(0, len(bs))]
        multi = [b] + ([l2[l1[rng.integers(0, len(l1))]][0]] if rng.random() < 0.4 else [])
        year = int(rng.integers(2014, 2025))
        comp = companies[rng.integers(0, len(companies))]
        granted = rng.random() < 0.55
        rows.append({
            "공개번호": "KR10-%d-%07dA" % (year, i),
            "출원번호": "KR10-%d-%07d" % (year, i),
            "패밀리 ID": "F%05d" % (i // 2),
            "발명의 명칭": "%s 기반 %s 개선 기술" % (b, problems[i % len(problems)]),
            "요약": "%s 분야에서 %s 을(를) 위한 %s 접근." % (a, problems[i % len(problems)],
                                                     solutions[i % len(solutions)]),
            "독립청구항": ("반도체 패키지에 있어서, %s 구조를 포함하고 %s 특징을 갖는 "
                      "것을 특징으로 하는 %s 장치." % (b, solutions[i % len(solutions)], a)) * 2,
            "출원인": comp, "발명자": "발명자%d; 발명자%d" % (i % 40, (i + 7) % 40),
            "출원일": "%d-0%d-15" % (year, (i % 9) + 1), "국가": ["KR", "US", "JP", "CN"][i % 4],
            "법적상태": "등록" if granted else ["공개", "심사중", "거절", "소멸"][i % 4],
            "등록 여부": "Y" if granted else "N",
            "존속 여부": "Y" if granted and rng.random() < 0.8 else "N",
            "피인용 수": int(rng.poisson(3)), "인용 수": int(rng.poisson(5)),
            "패밀리 수": int(rng.integers(1, 8)), "패밀리 국가 수": int(rng.integers(1, 5)),
            "기술 대분류": a, "기술 중분류": b, "다중 기술분류": "; ".join(multi),
            "해결과제": problems[i % len(problems)], "해결수단": solutions[i % len(solutions)],
            "만료예정일": "%d-06-30" % (year + 20),
            "자사 특허 여부": "Y" if comp == "네패스" else "N",
        })
    return pd.DataFrame(rows)


def _resolve_dataset(body):
    """요청/설정에서 dataset 결정. demo_mode 면 데모 데이터 주입.

    업로드 dataset(upload__…)이 Backend 재시작으로 내려간 경우 저장 파일에서
    자동 재적재한다.
    """
    settings = _settings()
    name = (body or {}).get("dataset") or settings.get("dataset")
    if settings.get("demo_mode"):
        if DEMO_DATASET_NAME not in list_datasets():
            inject_dataset(DEMO_DATASET_NAME, _make_demo_dataframe())
        if not name or validate_dataset_name(name) is None:
            name = DEMO_DATASET_NAME
    if not name:
        raise LookupError(MESSAGES["no_dataset"])
    if validate_dataset_name(name) is None:
        uploads_ensure_loaded(name)
    valid = validate_dataset_name(name)
    if valid is None:
        raise LookupError("허용되지 않은 Dataset 입니다: %s" % name)
    return valid, settings


def _validated_auto_mapping(dataset, actual_cols):
    """자동 추천 매핑 + 샘플 값 검증 (형식 불일치 오매핑 제거). 실패 시 검증 생략."""
    auto = suggest_mapping(actual_cols)
    mapping = {k: v["column"] for k, v in auto.items()}
    try:
        sample = load_sample_dataframe(dataset, sorted(set(mapping.values())), limit=300)
        if len(sample):
            mapping, dropped = validate_mapping_values(sample, mapping)
            for d in dropped:
                logger.info("자동 매핑 제외: %s → %s (%s)",
                            d["label"], d["column"], d["reason"])
    except Exception as e:
        logger.warning("자동 매핑 값 검증 실패(생략): %s", e)
    return mapping


def _effective_mapping(dataset, actual_cols):
    """분석에 실제 사용하는 매핑 = 검증된 자동 추천 + 저장 매핑(우선).

    컬럼 매핑 화면의 'effective' 와 동일한 규칙 — 화면에 매핑된 것으로 보이는
    개념이 분석에서 빠지는 불일치를 방지한다. 저장 매핑은 항상 자동 추천을 덮어쓴다.
    """
    saved, _w = clean_mapping(storage.load_mapping_for(dataset), actual_cols)
    auto = _validated_auto_mapping(dataset, actual_cols)
    mapping = dict(auto)
    mapping.update(saved)
    return mapping


def _prepared_for(body):
    """요청 → (필터 적용된 표준 프레임, settings, dataset, mapping). 공통 진입점."""
    dataset, settings = _resolve_dataset(body)
    actual_cols = get_dataset_columns(dataset)
    mapping = _effective_mapping(dataset, actual_cols)
    rules = storage.load_applicant_rules()
    df, _ = get_prepared(dataset, mapping, rules, settings.get("analysis_unit", "family"))
    filters = (body or {}).get("filters") or {}
    filtered = apply_filters(df, filters)
    return filtered, settings, dataset, mapping, filters


def _analysis_route(analysis_name, compute_fn, extra_key_fields=()):
    """분석 엔드포인트 공통 핸들러 생성 (캐싱 + 오류 표준화)."""
    def handler(body):
        df, settings, dataset, mapping, filters = _prepared_for(body)
        avail = analysis_availability(mapping)
        req = avail.get(analysis_name)
        if req and not req["available"]:
            from src.viz_payload import disabled_result
            return disabled_result(req["missing"])
        extra = {k: (body or {}).get(k) for k in extra_key_fields}
        key_parts = [dataset, filters, extra,
                     {"unit": settings.get("analysis_unit"),
                      "mode": settings.get("multiclass_mode"),
                      "limits": settings.get("limits"), "thresholds": settings.get("thresholds"),
                      "weights": settings.get("weights")}]
        result = cached_analysis(analysis_name, key_parts,
                                 lambda: (compute_fn(df, settings, body or {}), len(df)))
        # 진단: 매핑상 존재하는 개념이 분석 시점에 비활성이면 원인 정보를 덧붙인다
        if isinstance(result, dict) and result.get("status") == "disabled" \
                and req and req.get("available"):
            label_to_key = {v["label"]: k for k, v in CONCEPTS.items()}
            details = []
            for label in result.get("missing_columns", []):
                key = label_to_key.get(label)
                col = mapping.get(key) if key else None
                if col:
                    in_df = key in df.columns
                    details.append("%s → 원본 컬럼 '%s' (%s)"
                                   % (label, col,
                                      "로딩됨·값 없음" if in_df else "로딩된 데이터에서 미발견"))
            if details:
                result = dict(result)
                result["message"] = (str(result.get("message", "")) +
                                     " [매핑 진단: " + "; ".join(details) +
                                     ". 컬럼 매핑 화면의 '예시 값'으로 실제 값을 확인하세요]")
        return result
    return handler


def register_routes(app):
    """Flask app 에 모든 라우트 등록. Dataiku Standard Webapp 의 app 객체를 받는다."""
    from flask import request, jsonify, send_file

    def json_body():
        try:
            return request.get_json(force=True, silent=True) or {}
        except Exception:
            return {}

    def wrap(fn):
        """표준 오류 처리 래퍼."""
        def inner(*args, **kwargs):
            try:
                out = fn(*args, **kwargs)
                if hasattr(out, "status_code") and hasattr(out, "headers"):
                    return out  # send_file 등 Flask Response 는 그대로 통과
                if isinstance(out, tuple):
                    payload, code = out
                    return jsonify(jsonable(payload)), code
                return jsonify(jsonable(out))
            except LookupError as e:
                return jsonify(jsonable(_error(404, str(e))[0])), 404
            except (ValueError, KeyError, TypeError) as e:
                logger.warning("bad request: %s\n%s", e, traceback.format_exc())
                return jsonify(jsonable(_error(400, "요청 처리 오류: %s" % e)[0])), 400
            except Exception as e:
                logger.error("internal error: %s\n%s", e, traceback.format_exc())
                return jsonify(jsonable(_error(500, "내부 오류가 발생했습니다: %s" % e)[0])), 500
        inner.__name__ = "route_" + fn.__name__
        return inner

    # ---------------- 구성·메타 ----------------
    @app.route("/api/config", methods=["GET"])
    @wrap
    def api_config():
        """GET /api/config → 앱 정보, 설정(민감값 제외), 분석 가용성, 실행 로그.

        응답: {"app","version","settings","llm_options":[label...],"availability",
               "concepts","legal_status_categories","analysis_units","multiclass_modes",
               "limits_defaults","thresholds_defaults","weights_defaults","run_log",
               "filter_state","disclaimer"}
        """
        settings = _settings()
        dataset = settings.get("dataset")
        availability, mapping = {}, {}
        if settings.get("demo_mode") and not dataset:
            dataset = DEMO_DATASET_NAME
        if dataset:
            try:
                if settings.get("demo_mode") and dataset == DEMO_DATASET_NAME \
                        and DEMO_DATASET_NAME not in list_datasets():
                    inject_dataset(DEMO_DATASET_NAME, _make_demo_dataframe())
                cols = get_dataset_columns(dataset)
                mapping = _effective_mapping(dataset, cols) if cols else {}
                availability = analysis_availability(mapping)
            except Exception as e:
                logger.warning("config availability failed: %s", e)
        public_settings = {k: v for k, v in settings.items() if k != "llm_id"}
        llm_labels = [label for label, _id in ALLOWED_LLM_CANDIDATES]
        current_label = next((label for label, _id in ALLOWED_LLM_CANDIDATES
                              if _id == settings.get("llm_id")), llm_labels[0])
        return {"app": APP_NAME, "version": APP_VERSION,
                "settings": public_settings, "llm_options": llm_labels,
                "llm_current": current_label,
                "availability": availability, "mapping": mapping,
                "concepts": concept_catalog(),
                "legal_status_categories": LEGAL_STATUS_CATEGORIES,
                "analysis_units": ANALYSIS_UNITS, "multiclass_modes": MULTICLASS_MODES,
                "transition_modes": TRANSITION_MODES,
                "limits_defaults": LIMITS, "thresholds_defaults": THRESHOLDS,
                "weights_defaults": WEIGHTS,
                "run_log": get_run_log(50), "filter_state": storage.load_filter_state(),
                "disclaimer": MESSAGES["disclaimer"]}

    @app.route("/api/datasets", methods=["GET"])
    @wrap
    def api_datasets():
        """GET /api/datasets → {"datasets":[이름...]}"""
        return {"status": "ok", "datasets": list_datasets()}

    @app.route("/api/columns", methods=["GET"])
    @wrap
    def api_columns():
        """GET /api/columns?dataset=NAME → {"columns":[...]}. 404: 미허용 dataset."""
        name = validate_dataset_name(request.args.get("dataset"))
        if name is None:
            raise LookupError("허용되지 않은 Dataset 입니다.")
        return {"status": "ok", "dataset": name, "columns": get_dataset_columns(name)}

    @app.route("/api/column-mapping", methods=["GET", "POST"])
    @wrap
    def api_column_mapping():
        """컬럼 매핑 관리.

        GET  ?dataset= → 저장 매핑 + 자동 추천 + 가용성 매트릭스.
        POST {"dataset","mapping":{concept:column}} → 검증 후 저장.
        오류 400: 알 수 없는 개념/컬럼.
        """
        if request.method == "GET":
            name = validate_dataset_name(request.args.get("dataset"))
            if name is None:
                raise LookupError("허용되지 않은 Dataset 입니다.")
            cols = get_dataset_columns(name)
            saved, warnings = clean_mapping(storage.load_mapping_for(name), cols)
            suggestion = suggest_mapping(cols)
            # 샘플 값 검증: 형식 불일치 추천은 invalid 표시 + effective 에서 제외
            samples = {}
            try:
                sample_df = load_sample_dataframe(name, None, limit=120)
                for col in cols:
                    if col in sample_df.columns:
                        vals = sample_df[col].dropna().astype(str).str.strip()
                        vals = vals[(vals != "") & (~vals.str.lower().isin(["nan", "none"]))]
                        samples[col] = [v[:48] for v in vals.head(3).tolist()]
                auto_map = {k: v["column"] for k, v in suggestion.items()}
                _valid, dropped = validate_mapping_values(sample_df, auto_map)
                for d in dropped:
                    if d["concept"] in suggestion:
                        suggestion[d["concept"]]["valid"] = False
                        suggestion[d["concept"]]["reason"] = d["reason"]
                        warnings.append("자동 추천 제외: %s → %s (%s)"
                                        % (d["label"], d["column"], d["reason"]))
            except Exception as e:
                logger.warning("매핑 샘플 검증 실패(생략): %s", e)
            effective = dict({k: v["column"] for k, v in suggestion.items()
                              if v.get("valid", True)}, **saved)
            return {"status": "ok", "dataset": name, "columns": cols,
                    "saved": saved, "suggested": suggestion, "samples": samples,
                    "effective": effective, "warnings": warnings,
                    "availability": analysis_availability(effective),
                    "concepts": concept_catalog()}
        body = json_body()
        name = validate_dataset_name(body.get("dataset"))
        if name is None:
            raise LookupError("허용되지 않은 Dataset 입니다.")
        mapping = body.get("mapping") or {}
        cols = set(get_dataset_columns(name))
        clean = {}
        for concept, col in mapping.items():
            if concept not in CONCEPTS:
                return _error(400, "알 수 없는 개념 컬럼: %s" % concept)
            if col:
                if col not in cols:
                    return _error(400, "Dataset 에 없는 컬럼: %s" % col)
                clean[concept] = col
        storage.save_mapping_for(name, clean)
        clear_all_caches()
        return {"status": "ok", "saved": clean,
                "availability": analysis_availability(clean)}

    @app.route("/api/filter-options", methods=["POST"])
    @wrap
    def api_filter_options():
        """POST {"dataset"?} → 필터바 옵션 (연도범위·출원인·국가·법적상태·기술분류)."""
        df, settings, dataset, mapping, _f = _prepared_for(json_body())
        return {"status": "ok", "options": filter_options(df), "dataset": dataset,
                "n_rows": len(df)}

    # ---------------- 분석 ----------------
    handlers = {
        "overview": _analysis_route(
            "overview", lambda df, s, b: compute_overview(df, s)),
        "technology-network": _analysis_route(
            "technology-network",
            lambda df, s, b: compute_tech_network(df, s, scope=b.get("scope", "all"),
                                                  company=b.get("company"),
                                                  color_by=b.get("color_by", "l1")),
            extra_key_fields=("scope", "company", "color_by")),
        "emerging-combinations": _analysis_route(
            "emerging-combinations", lambda df, s, b: compute_emerging(df, s)),
        "lifecycle": _analysis_route(
            "lifecycle", lambda df, s, b: compute_lifecycle(df, s)),
        "opportunity": _analysis_route(
            "opportunity", lambda df, s, b: compute_opportunity(df, s)),
        "problem-solution": _analysis_route(
            "problem-solution",
            lambda df, s, b: (cell_detail(df, s, b.get("problem"), b.get("solution"))
                              if b.get("cell") else
                              (compute_ps_semantic(df, s)
                               if b.get("group_mode") == "semantic"
                               else compute_problem_solution(df, s))),
            extra_key_fields=("cell", "problem", "solution", "group_mode")),
        "technology-transition": _analysis_route(
            "technology-transition",
            lambda df, s, b: compute_transition(df, s, mode=b.get("mode"),
                                                period_years=b.get("period_years")),
            extra_key_fields=("mode", "period_years")),
        "trajectory": _analysis_route(
            "trajectory",
            lambda df, s, b: compute_trajectory(df, s, companies=b.get("companies"),
                                                method=b.get("method", "pca"),
                                                weighting=b.get("weighting")),
            extra_key_fields=("companies", "method", "weighting")),
        "company-dna": _analysis_route(
            "company-dna",
            lambda df, s, b: compute_company_dna(df, s, companies=b.get("companies")),
            extra_key_fields=("companies",)),
        "lead-lag": _analysis_route(
            "lead-lag",
            lambda df, s, b: compute_lead_lag(df, s, min_repeat=int(b.get("min_repeat", 1))),
            extra_key_fields=("min_repeat",)),
        "claim-density": _analysis_route(
            "claim-density",
            lambda df, s, b: compute_claim_density(df, s, tech=b.get("tech")),
            extra_key_fields=("tech",)),
        "citation-diffusion": _analysis_route(
            "citation-diffusion",
            lambda df, s, b: compute_citation_influence(df, s, top_n=b.get("top_n")),
            extra_key_fields=("top_n",)),
        "inventor-mobility": _analysis_route(
            "inventor-mobility",
            lambda df, s, b: compute_inventor_mobility(
                df, s, include_uncertain=bool(b.get("include_uncertain"))),
            extra_key_fields=("include_uncertain",)),
        "classification-quality": _analysis_route(
            "classification-quality", lambda df, s, b: compute_classification_quality(df, s)),
        "basic-stats": _analysis_route(
            "basic-stats", lambda df, s, b: compute_basic_stats(df, s)),
        "portfolio-index": _analysis_route(
            "portfolio-index", lambda df, s, b: compute_portfolio_index(df, s)),
        "advanced-stats": _analysis_route(
            "advanced-stats", lambda df, s, b: compute_advanced_stats(df, s)),
        "scope-entropy": _analysis_route(
            "scope-entropy",
            lambda df, s, b: compute_scope_entropy(df, s, companies=b.get("companies")),
            extra_key_fields=("companies",)),
        "combo-upset": _analysis_route(
            "combo-upset", lambda df, s, b: compute_combo_upset(df, s)),
        "emerging-clusters": _analysis_route(
            "emerging-clusters", lambda df, s, b: compute_emerging_clusters(df, s)),
        "semantic-influence": _analysis_route(
            "semantic-influence", lambda df, s, b: compute_semantic_influence(df, s)),
        "similarity-network": _analysis_route(
            "similarity-network",
            lambda df, s, b: compute_similarity_network(df, s,
                                                        threshold=b.get("threshold")),
            extra_key_fields=("threshold",)),
        "wips-deep": _analysis_route(
            "wips-deep", lambda df, s, b: compute_wips_deep(df, s)),
        "executive-summary": _analysis_route(
            "executive-summary",
            lambda df, s, b: compute_executive_summary(df, s,
                                                       company=b.get("company")),
            extra_key_fields=("company",)),
        "axis-cross": _analysis_route(
            "axis-cross", lambda df, s, b: compute_axis_cross(df, s)),
        "tech-year-bubble": _analysis_route(
            "tech-year-bubble",
            lambda df, s, b: compute_tech_year_bubble(df, s,
                                                      companies=b.get("companies")),
            extra_key_fields=("companies",)),
        "ownership": _analysis_route(
            "ownership", lambda df, s, b: compute_ownership(df, s)),
    }

    def make_analysis_view(path_name, handler):
        @wrap
        def view():
            return handler(json_body())
        view.__name__ = "api_" + path_name.replace("-", "_")
        return view

    for path_name, handler in handlers.items():
        app.add_url_rule("/api/%s" % path_name, "api_" + path_name.replace("-", "_"),
                         make_analysis_view(path_name, handler), methods=["POST"])

    # ---------------- Drill-down / Export ----------------
    @app.route("/api/patents", methods=["POST"])
    @wrap
    def api_patents():
        """POST {"dataset"?,"filters"?,"drill"?,"page","page_size"} → 근거 특허 목록.

        응답: {"status":"ok","total","page","page_size","records":[...]}.
        """
        body = json_body()
        df, settings, dataset, mapping, _f = _prepared_for(body)
        sub = select_patents(df, body.get("drill") or {})
        result = patent_records(sub, page=body.get("page", 1),
                                page_size=body.get("page_size",
                                                   get_limit(settings, "patents_page_size")),
                                max_page_size=get_limit(settings, "patents_max_page_size"))
        result["status"] = "ok"
        return result

    @app.route("/api/export", methods=["POST"])
    @wrap
    def api_export():
        """POST {"dataset"?,"filters"?,"drill"?,"filename"?} → Excel 파일 스트림."""
        body = json_body()
        df, settings, dataset, mapping, _f = _prepared_for(body)
        sub = select_patents(df, body.get("drill") or {})
        if not len(sub):
            return _error(404, "내보낼 데이터가 없습니다.")
        out_df = export_dataframe(sub, max_rows=get_limit(settings, "export_max_rows"))
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            out_df.to_excel(writer, index=False, sheet_name="patents")
        buf.seek(0)
        fname = str(body.get("filename") or "ip_landscape_export.xlsx")
        fname = "".join(ch for ch in fname if ch.isalnum() or ch in "._-가-힣") or "export.xlsx"
        if not fname.endswith(".xlsx"):
            fname += ".xlsx"
        return send_file(buf, as_attachment=True, download_name=fname,
                         mimetype="application/vnd.openxmlformats-officedocument"
                                  ".spreadsheetml.sheet")

    @app.route("/api/export-chart", methods=["POST"])
    @wrap
    def api_export_chart():
        """POST {"filename"?, "sheets":[{"name","columns":[...],"rows":[[...]]}]} →
        차트에 표시된 집계 데이터의 Excel 스트림 (시트당 1개 차트).

        상한: 시트 20개, 시트당 20,000행 × 100열. 초과분은 절단.
        오류 400: sheets 형식 오류/빈 데이터.
        """
        body = json_body()
        sheets = body.get("sheets")
        if not isinstance(sheets, list) or not sheets:
            return _error(400, "내보낼 차트 데이터가 없습니다.")
        buf = io.BytesIO()
        used_names = set()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            wrote = False
            for i, sheet in enumerate(sheets[:20]):
                if not isinstance(sheet, dict):
                    continue
                cols = [str(c)[:80] for c in (sheet.get("columns") or [])][:100]
                rows = [list(r)[:100] for r in (sheet.get("rows") or [])
                        if isinstance(r, (list, tuple))][:20000]
                if not cols or not rows:
                    continue
                # 컬럼 수 정합화
                rows = [r + [None] * (len(cols) - len(r)) if len(r) < len(cols)
                        else r[:len(cols)] for r in rows]
                name = re.sub(r"[\[\]:*?/\\]", " ", str(sheet.get("name") or "chart%d" % (i + 1)))
                name = (name.strip() or "chart%d" % (i + 1))[:28]
                base = name
                k = 2
                while name in used_names:
                    name = "%s_%d" % (base[:24], k)
                    k += 1
                used_names.add(name)
                pd.DataFrame(rows, columns=cols).to_excel(writer, index=False,
                                                          sheet_name=name)
                wrote = True
            if not wrote:
                return _error(400, "내보낼 차트 데이터가 없습니다.")
        buf.seek(0)
        fname = str(body.get("filename") or "chart_data.xlsx")
        fname = "".join(ch for ch in fname if ch.isalnum() or ch in "._-가-힣") or "chart.xlsx"
        if not fname.endswith(".xlsx"):
            fname += ".xlsx"
        return send_file(buf, as_attachment=True, download_name=fname,
                         mimetype="application/vnd.openxmlformats-officedocument"
                                  ".spreadsheetml.sheet")

    # ---------------- 인사이트 (LLM) ----------------
    @app.route("/api/insight", methods=["POST"])
    @wrap
    def api_insight():
        """그래프별 LLM 인사이트·챗.

        POST {"analysis", "metrics":{요약 통계}, "sentences":[규칙 문장...],
              "question"?: 사용자 추가 질문, "history"?: [{"role","content"}...],
              "description"?: 그래프 설명, "chat"?: true,
              "chart_data"?: [{"name","columns","rows"}...] — 화면 차트의 집계값
              (요약 통계가 빈 분석에서도 LLM 이 실제 수치를 근거로 해석),
              "web_search"?: true — 외부 웹 검색 결과를 참고 컨텍스트로 첨부}
        - chat/question 모드 → {"status":"ok","answer":…,"source":"llm|rule",
          "web_sources"?:[{"title","url"}...], "web_note"?:검색 실패 안내}
          (LLM 미가용·실패 시 규칙 기반 요약으로 자동 폴백)
        - 그 외(기존 방식) → 문장 목록 {"sentences":[...], "source":…}
        원문 특허 데이터는 전달하지 않는다 (요약 통계만). 웹 검색 결과는 신뢰
        경계를 명시해 sanitize 후 전달하며, 실패 시 내부 데이터만으로 답변한다.
        """
        body = json_body()
        settings = _settings()
        analysis = str(body.get("analysis", ""))[:60]
        metrics = body.get("metrics") or {}
        sentences = body.get("sentences") or []
        chart_context = format_chart_context(body.get("chart_data"))
        if body.get("chat") or body.get("question"):
            history = body.get("history")
            if not isinstance(history, list):
                history = []
            history = [h for h in history if isinstance(h, dict)][-8:]
            web_context, web_sources, web_note = None, [], None
            if body.get("web_search") and settings.get("web_search_enabled"):
                query = str(body.get("question") or "").strip() \
                    or "%s 특허 기술 동향" % analysis.replace("-", " ")
                try:
                    results = search_web(
                        query, max_results=get_limit(settings, "web_search_max_results"))
                except Exception as e:
                    logger.warning("웹 검색 오류: %s", e)
                    results = []
                if results:
                    web_context = format_web_context(results, sanitize_for_llm)
                    web_sources = [{"title": r["title"], "url": r["url"]}
                                   for r in results]
                else:
                    web_note = ("웹 검색 결과를 가져오지 못했습니다 (네트워크 차단 또는 "
                                "검색 실패) — 내부 데이터만으로 답변합니다.")
            out = llm_chat(analysis, metrics, sentences, body.get("question"),
                           history, settings,
                           description=body.get("description"),
                           web_context=web_context, chart_context=chart_context)
            out["status"] = "ok"
            if web_sources:
                out["web_sources"] = web_sources
            if web_note:
                out["web_note"] = web_note
            if out.get("source") == "llm" and out.get("answer"):
                try:
                    out["saved_id"] = add_insight(
                        analysis, title=str(body.get("question") or analysis),
                        sentences=str(out["answer"]).split("\n"),
                        dataset=settings.get("dataset"), kind="chat",
                        question=body.get("question"),
                        chart_image=body.get("chart_image"))
                except Exception as e:
                    logger.warning("인사이트 저장 실패: %s", e)
            return out
        rule = build_insight(sentences, metrics)
        out = llm_augment_insight(analysis, rule, metrics, settings,
                                  chart_context=chart_context,
                                  description=body.get("description"))
        out["status"] = "ok"
        if out.get("source") == "llm" and out.get("sentences"):
            try:
                out["saved_id"] = add_insight(
                    analysis, title=analysis, sentences=out["sentences"],
                    dataset=settings.get("dataset"), kind="report",
                    chart_image=body.get("chart_image"))
            except Exception as e:
                logger.warning("인사이트 저장 실패: %s", e)
        return out

    # ---------------- 설정 ----------------
    @app.route("/api/settings", methods=["GET", "POST"])
    @wrap
    def api_settings():
        """GET → 현재 설정(민감값 제외). POST {settings...} → 저장.

        llm 선택은 라벨("llm_label")로 받으며 서버가 고정 목록에서 ID 로 변환한다.
        """
        if request.method == "GET":
            s = _settings()
            return {"status": "ok",
                    "settings": {k: v for k, v in s.items() if k != "llm_id"}}
        body = json_body()
        current = storage.load_settings() or {}
        allowed_keys = set(DEFAULT_SETTINGS.keys()) | {"llm_label"}
        for k, v in body.items():
            if k not in allowed_keys:
                continue
            if k == "llm_label":
                match = next((_id for label, _id in ALLOWED_LLM_CANDIDATES if label == v), None)
                if match:
                    current["llm_id"] = match
                continue
            if k == "llm_id":
                continue  # 직접 지정 금지 (라벨 경유만 허용)
            if k == "analysis_unit" and v not in ANALYSIS_UNITS:
                return _error(400, "잘못된 분석 단위: %s" % v)
            if k == "multiclass_mode" and v not in MULTICLASS_MODES:
                return _error(400, "잘못된 다중분류 처리방식: %s" % v)
            if k == "dataset" and v and validate_dataset_name(v) is None:
                uploads_ensure_loaded(v)  # 업로드 dataset 자동 재적재 시도
                if validate_dataset_name(v) is None:
                    return _error(400, "허용되지 않은 Dataset: %s" % v)
            current[k] = v
        storage.save_settings(current)
        clear_all_caches()
        s = merged_settings(current)
        return {"status": "ok", "settings": {k: v for k, v in s.items() if k != "llm_id"}}

    @app.route("/api/applicant-rules", methods=["GET", "POST"])
    @wrap
    def api_applicant_rules():
        """출원인·권리자 표준화 관리.

        GET ?dataset= → 원본명/자동표준명/현재표준명 목록 + 저장 규칙 (검토·승인 UI 용).
        POST {"mapping":{원본:표준}, "groups":{표준:그룹}, "history_entry"?,
              "import"?:{...}} → 저장. "reset":[원본명...] → 해당 매핑 제거(원복).
        """
        if request.method == "GET":
            rules = storage.load_applicant_rules()
            names = []
            try:
                df, settings, dataset, mapping, _f = _prepared_for(
                    {"dataset": request.args.get("dataset")})
                raw_counts = df["applicant_raw"].replace("", np.nan).dropna().value_counts()
                user_map = (rules.get("mapping") or {})
                for raw, cnt in raw_counts.head(500).items():
                    auto = auto_standardize_name(raw)
                    names.append({"raw": str(raw), "auto": auto,
                                  "current": user_map.get(str(raw), auto),
                                  "approved": str(raw) in user_map, "count": int(cnt)})
            except (LookupError, ValueError):
                pass
            return {"status": "ok", "rules": rules, "names": names,
                    "note": "자동 표준화 결과는 확정값이 아니라 검토·승인 대상입니다."}
        body = json_body()
        rules = storage.load_applicant_rules() or {}
        if body.get("import"):
            imported = body["import"]
            if not isinstance(imported, dict):
                return _error(400, "가져오기 형식 오류: JSON 객체가 필요합니다.")
            rules = {"mapping": dict(imported.get("mapping") or {}),
                     "groups": dict(imported.get("groups") or {}),
                     "history": list(imported.get("history") or [])}
        if isinstance(body.get("mapping"), dict):
            rules.setdefault("mapping", {}).update(
                {str(k): str(v) for k, v in body["mapping"].items() if v})
        for raw in (body.get("reset") or []):
            rules.get("mapping", {}).pop(str(raw), None)
        if isinstance(body.get("groups"), dict):
            rules.setdefault("groups", {}).update(
                {str(k): str(v) for k, v in body["groups"].items() if v})
        for raw in (body.get("reset_groups") or []):
            rules.get("groups", {}).pop(str(raw), None)
        if body.get("history_entry"):
            rules.setdefault("history", []).append(
                {"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "entry": str(body["history_entry"])[:300]})
        storage.save_applicant_rules(rules)
        clear_all_caches()
        return {"status": "ok", "rules": rules}

    # ---------------- 프로젝트 저장·불러오기 / 필터 상태 ----------------
    @app.route("/api/project/save", methods=["POST"])
    @wrap
    def api_project_save():
        """POST {"name","filters","settings"?,"note"?,"worker"?} → 상태 저장.

        worker(작업자/팀명)를 함께 저장해 목록에서 '내 작업만 보기' 필터에
        사용한다 (선택 값 — 빈 문자열이면 '작업자 미지정'으로 분류).
        """
        body = json_body()
        name = str(body.get("name") or "").strip()
        if not name:
            return _error(400, "프로젝트 이름이 필요합니다.")
        projects = storage.load_projects()
        projects[name] = {"filters": body.get("filters") or {},
                          "settings": body.get("settings") or {},
                          "note": str(body.get("note") or "")[:500],
                          "worker": str(body.get("worker") or "").strip()[:60],
                          "saved_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        storage.save_projects(projects)
        return {"status": "ok", "projects": sorted(projects.keys())}

    @app.route("/api/project/load", methods=["POST"])
    @wrap
    def api_project_load():
        """POST {"name"?} → name 지정 시 해당 프로젝트, 미지정 시 목록."""
        body = json_body()
        projects = storage.load_projects()
        name = body.get("name")
        if not name:
            return {"status": "ok",
                    "projects": [{"name": k, "saved_at": v.get("saved_at"),
                                  "note": v.get("note"),
                                  "worker": v.get("worker", "")}
                                 for k, v in projects.items()]}
        if name not in projects:
            raise LookupError("프로젝트를 찾을 수 없습니다: %s" % name)
        if body.get("delete"):
            projects.pop(name)
            storage.save_projects(projects)
            return {"status": "ok", "deleted": name}
        return {"status": "ok", "project": projects[name], "name": name}

    @app.route("/api/filter-state", methods=["POST"])
    @wrap
    def api_filter_state():
        """POST {"filters":{...}} → 마지막 필터 상태 저장 (재방문 시 복원)."""
        storage.save_filter_state((json_body() or {}).get("filters") or {})
        return {"status": "ok"}

    # ---------------- 엑셀 업로드 작업 저장소 ----------------
    @app.route("/api/uploads", methods=["GET", "POST"])
    @wrap
    def api_uploads():
        """엑셀 업로드 작업 저장소.

        GET → {"items":[{id,worker,job,orig_filename,dataset,uploaded_at,
               n_rows,n_cols,loaded,file_exists}...]} (최신순).
        POST multipart form: file(필수), worker(작업자 이름, 필수),
             job(작업명, 필수) → 파일을 서버 저장소에 보관하고 메타데이터를
             영속화하며 즉시 분석 dataset 으로 등록.
        오류 400: 작업자/작업명 누락, 형식·크기 위반, 해석 불가.
        """
        if request.method == "GET":
            return {"status": "ok", "items": uploads_list()}
        f = request.files.get("file")
        if f is None:
            return _error(400, "파일이 첨부되지 않았습니다.")
        try:
            entry = uploads_save(f.read(), f.filename,
                                            request.form.get("worker"),
                                            request.form.get("job"))
        except ValueError as e:
            return _error(400, str(e))
        clear_all_caches()
        return {"status": "ok", "entry": entry, "items": uploads_list()}

    @app.route("/api/uploads/load", methods=["POST"])
    @wrap
    def api_uploads_load():
        """POST {"id"} → 저장된 작업을 파일에서 (재)적재해 분석 dataset 으로 등록."""
        entry = uploads_load((json_body() or {}).get("id"))
        clear_all_caches()
        return {"status": "ok", "entry": entry}

    @app.route("/api/uploads/delete", methods=["POST"])
    @wrap
    def api_uploads_delete():
        """POST {"id"} → 저장 작업 삭제 (메타데이터 + 서버 파일)."""
        entry = uploads_delete((json_body() or {}).get("id"))
        return {"status": "ok", "deleted": entry.get("id")}

    # ---------------- LLM 인사이트 보관함 / PPT 보고서 ----------------
    @app.route("/api/insights-log", methods=["GET"])
    @wrap
    def api_insights_log():
        """GET → 저장된 LLM 인사이트 목록 (최신순, 최대 300건).

        각 항목에 dataset_label(업로드 작업이면 "작업명 (작업자)")을 붙이고,
        현재 분석 중인 dataset 을 함께 반환한다 — 보관함이 '현재 작업' 항목만
        기본 표시하고 이전 작업은 그룹별로 구분해 보여줄 수 있게.
        """
        items = list_insights()
        job_labels = {}
        for up in (storage.load_uploads().get("items") or []):
            ds = str(up.get("dataset") or "")
            if ds:
                job_labels[ds] = "%s (%s)" % (up.get("job", ds), up.get("worker", "-"))
        for it in items:
            ds = str(it.get("dataset") or "")
            it["dataset_label"] = job_labels.get(ds, ds or "작업 미지정")
        return {"status": "ok", "items": items,
                "current_dataset": _settings().get("dataset")}

    @app.route("/api/insights-log/delete", methods=["POST"])
    @wrap
    def api_insights_log_delete():
        """POST {"id"} → 보관함 항목 삭제 (차트 이미지 파일 포함)."""
        delete_insight((json_body() or {}).get("id"))
        return {"status": "ok"}

    @app.route("/api/insights-log/image", methods=["GET"])
    @wrap
    def api_insights_log_image():
        """GET ?id= → 항목의 차트 캡처 이미지 스트림 (보관함 미리보기용)."""
        data, mime = insight_get_image(request.args.get("id"))
        if data is None:
            raise LookupError("이미지가 없습니다.")
        return send_file(io.BytesIO(data), mimetype=mime)

    @app.route("/api/insights-report", methods=["POST"])
    @wrap
    def api_insights_report():
        """POST {"ids"?: [...], "title"?} → 선택(또는 전체) 인사이트 PPT 스트림.

        python-pptx 미설치 환경에서는 내장 OOXML 생성기로 .pptx 를 만든다.
        """
        body = json_body()
        items = get_insights(body.get("ids"))
        if not items:
            return _error(404, "내보낼 인사이트가 없습니다 — 먼저 각 차트에서 "
                               "'LLM 인사이트 생성'을 실행하세요.")
        title = str(body.get("title") or "IP Landscape 인사이트 보고서")[:80]
        data = build_pptx(items, report_title=title)
        fname = "ip_landscape_insights_%s.pptx" % time.strftime("%Y%m%d_%H%M")
        return send_file(io.BytesIO(data), as_attachment=True, download_name=fname,
                         mimetype="application/vnd.openxmlformats-officedocument"
                                  ".presentationml.presentation")

    return app
