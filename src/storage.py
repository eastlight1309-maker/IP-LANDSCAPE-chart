# -*- coding: utf-8 -*-
"""
storage.py — 설정·매핑·프로젝트 상태 영속화.

저장 체인 (가용한 첫 방법 사용):
1. Dataiku 프로젝트 변수 (dataiku.api_client().get_default_project().get_variables())
   — key: variables["standard"]["ip_landscape"][store_key]
2. 로컬 JSON 파일 (개발·테스트 환경 폴백): ./ip_landscape_store.json

저장 대상 store_key:
- "column_mapping"   : {dataset명: {concept: column}}
- "settings"         : 사용자 설정 (config.DEFAULT_SETTINGS overlay)
- "applicant_rules"  : {"mapping": {원본: 표준}, "groups": {표준: 그룹대표},
                        "history": [{"ts","action","from","to"}...]}  (합병·사명변경 이력)
- "projects"         : {프로젝트명: {"filters":…, "settings":…, "saved_at":…}}
- "filter_state"     : 마지막 필터 상태

모든 함수는 실패 시 예외를 삼키고 빈 dict 를 반환한다 (webapp 이 중단되지 않도록).
"""
import json
import logging
import os
import threading

logger = logging.getLogger("ip_landscape")

_VAR_ROOT = "ip_landscape"
_LOCAL_STORE_PATH = os.environ.get("IP_LANDSCAPE_STORE",
                                   os.path.join(os.path.abspath("."), "ip_landscape_store.json"))
_STORE_LOCK = threading.Lock()

try:
    import dataiku as _dataiku_mod
except ImportError:
    _dataiku_mod = None


def _project_variables():
    """Dataiku 프로젝트 변수 핸들. 미가용 시 None."""
    if _dataiku_mod is None:
        return None
    try:
        client = _dataiku_mod.api_client()
        return client.get_default_project()
    except Exception as e:
        logger.warning("Dataiku project variables unavailable: %s", e)
        return None


def _read_local():
    try:
        if os.path.exists(_LOCAL_STORE_PATH):
            with open(_LOCAL_STORE_PATH, "r", encoding="utf-8") as fh:
                return json.load(fh)
    except (OSError, ValueError) as e:
        logger.warning("local store read failed: %s", e)
    return {}


def _write_local(data):
    try:
        with open(_LOCAL_STORE_PATH, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1, default=str)
        return True
    except OSError as e:
        logger.warning("local store write failed: %s", e)
        return False


def load_store(store_key):
    """store_key 의 저장값 로드 (dict). 없으면 {}."""
    with _STORE_LOCK:
        project = _project_variables()
        if project is not None:
            try:
                variables = project.get_variables()
                return dict(variables.get("standard", {}).get(_VAR_ROOT, {}).get(store_key, {}))
            except Exception as e:
                logger.warning("project variable read failed (%s): %s", store_key, e)
        return dict(_read_local().get(store_key, {}))


def save_store(store_key, value):
    """store_key 에 값 저장. 성공 여부 반환."""
    with _STORE_LOCK:
        project = _project_variables()
        if project is not None:
            try:
                variables = project.get_variables()
                std = variables.setdefault("standard", {})
                root = std.setdefault(_VAR_ROOT, {})
                root[store_key] = value
                project.set_variables(variables)
                return True
            except Exception as e:
                logger.warning("project variable write failed (%s): %s", store_key, e)
        data = _read_local()
        data[store_key] = value
        return _write_local(data)


# --- 편의 함수 ---
def load_settings():
    return load_store("settings")


def save_settings(settings):
    return save_store("settings", settings)


def load_mapping_for(dataset_name):
    return load_store("column_mapping").get(str(dataset_name), {})


def save_mapping_for(dataset_name, mapping):
    all_mappings = load_store("column_mapping")
    all_mappings[str(dataset_name)] = mapping
    return save_store("column_mapping", all_mappings)


def load_applicant_rules():
    return load_store("applicant_rules")


def save_applicant_rules(rules):
    return save_store("applicant_rules", rules)


def load_user_datasets():
    """사용자별 활성 Dataset 선택 {사용자명: dataset}.

    Dataset 선택(settings.dataset)은 앱 전역값이라 한 사용자가 파일을 올리면
    다른 사용자의 화면까지 바뀌고, 남의 업로드가 전역으로 선택된 상태에서는
    일반 사용자가 접근 차단 오류만 보게 된다 — 사용자별 선택을 따로 기억해
    각자 자기 작업으로 분석하게 한다.
    """
    return load_store("user_datasets") or {}


def save_user_datasets(mapping):
    return save_store("user_datasets", mapping or {})


def load_projects():
    return load_store("projects")


def save_projects(projects):
    return save_store("projects", projects)


def load_filter_state():
    return load_store("filter_state")


def save_filter_state(state):
    return save_store("filter_state", state)


def load_uploads():
    """업로드 작업 메타데이터 목록 {"items": [...]}."""
    return load_store("uploads")


def save_uploads(uploads):
    return save_store("uploads", uploads)


def upload_dir():
    """업로드 엑셀 파일 저장 디렉터리 (로컬 store 파일 옆, 없으면 생성)."""
    base = os.environ.get("IP_LANDSCAPE_UPLOAD_DIR") or os.path.join(
        os.path.dirname(os.path.abspath(_LOCAL_STORE_PATH)), "ip_landscape_uploads")
    try:
        os.makedirs(base, exist_ok=True)
    except OSError as e:
        logger.warning("upload dir create failed: %s", e)
    return base


def insight_image_dir():
    """인사이트 차트 이미지 저장 디렉터리 (PPT 삽입용 PNG)."""
    base = os.path.join(upload_dir(), "insight_images")
    try:
        os.makedirs(base, exist_ok=True)
    except OSError as e:
        logger.warning("insight image dir create failed: %s", e)
    return base
