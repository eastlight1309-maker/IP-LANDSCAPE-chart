# -*- coding: utf-8 -*-
"""기술분류 정비(유사 병합·노이즈→미분류) + 제외 출원인 필터 회귀 테스트."""
import json

import pandas as pd
import pytest
from flask import Flask

from conftest import make_prepared
from generate_sample_data import generate_sample
from src import storage
from src.api import register_routes
from src.cache import clear_all_caches
from src.data_access import inject_dataset
from src.preprocessing import apply_tech_rules, is_tech_noise, TECH_UNCLASSIFIED
from src.analyses.common import applicant_counts, applicant_series

DS = "techrules_ds"


@pytest.fixture(scope="module")
def client():
    df = generate_sample(n=200, seed=42)
    # 유사 표기 변형 + 노이즈 주입: FOWLP 문헌 일부를 'FO-WLP'/'fowlp'/'-' 로
    df = df.copy()
    hit = df["다중 기술분류"].astype(str).str.contains("FOWLP")
    idx = df.index[hit]
    df.loc[idx[: len(idx) // 3], "다중 기술분류"] = \
        df.loc[idx[: len(idx) // 3], "다중 기술분류"].str.replace("FOWLP", "FO-WLP")
    df.loc[idx[len(idx) // 3: 2 * len(idx) // 3], "다중 기술분류"] = \
        df.loc[idx[len(idx) // 3: 2 * len(idx) // 3], "다중 기술분류"] \
        .str.replace("FOWLP", "fowlp")
    df.loc[df.index[:5], "다중 기술분류"] = "-"
    inject_dataset(DS, df)
    storage.save_settings({"dataset": DS, "demo_mode": False})
    storage.save_tech_rules({})
    clear_all_caches()
    app = Flask(__name__)
    register_routes(app)
    app.testing = True
    with app.test_client() as c:
        yield c
    storage.save_tech_rules({})
    clear_all_caches()


def _post(client, path, body=None):
    return client.post(path, data=json.dumps(body or {}),
                       content_type="application/json")


# ---------------- 자동 노이즈 → 미분류 ----------------
def test_auto_noise_to_unclassified():
    assert is_tech_noise("-") and is_tech_noise("···") and is_tech_noise("42")
    assert is_tech_noise("nan") and is_tech_noise("미상")
    assert not is_tech_noise("FOWLP") and not is_tech_noise("하이브리드 본딩")
    assert not is_tech_noise("A")   # 한 글자 알파벳 코드는 정당한 분류일 수 있음
    df = pd.DataFrame({"_tech_list": [["FOWLP", "-"], ["123"], []]})
    out = apply_tech_rules(df, None)   # 규칙 없이도 자동 노이즈 적용
    assert out["_tech_list"].tolist() == [["FOWLP", TECH_UNCLASSIFIED],
                                          [TECH_UNCLASSIFIED], []]


def test_apply_tech_rules_mapping_noise_chain():
    df = pd.DataFrame({"_tech_list": [["FO-WLP", "fowlp", "FOWLP"], ["본딩"]],
                       "_tech_l2_list": [["FO-WLP"], ["본딩"]]})
    rules = {"mapping": {"FO-WLP": "FOWLP", "fowlp": "FOWLP",
                         "FOWLP": "팬아웃 패키지"},   # 연쇄 규칙
             "noise": ["본딩"]}
    out = apply_tech_rules(df, rules)
    # 병합 + 연쇄 + 중복 제거
    assert out["_tech_list"].tolist()[0] == ["팬아웃 패키지"]
    assert out["_tech_list"].tolist()[1] == [TECH_UNCLASSIFIED]
    assert out["_tech_l2_list"].tolist() == [["팬아웃 패키지"], [TECH_UNCLASSIFIED]]


# ---------------- API: 제안 → 승인 → 분석 반영 ----------------
def test_tech_rules_api_suggest_and_apply(client):
    got = client.get("/api/tech-rules?dataset=%s" % DS).get_json()
    assert got["status"] == "ok"
    names = {c["name"] for c in got["classes"]}
    assert {"FOWLP", "FO-WLP", "fowlp"} <= names
    # 자동 노이즈('-')는 목록에서 이미 미분류로 합산
    assert "-" not in names and TECH_UNCLASSIFIED in names
    # 유사 제안에 FOWLP 변형 그룹이 있어야 함
    grp = next((g for g in got["suggestions"]
                if {"FOWLP", "FO-WLP", "fowlp"} <=
                {m["name"] for m in g["members"]}), None)
    assert grp is not None, got["suggestions"]
    target = grp["target"]
    # target = 그룹 내 최다 건수 표기
    assert target == max(grp["members"], key=lambda m: m["count"])["name"]
    merged_away = {"FOWLP", "FO-WLP", "fowlp"} - {target}
    # 승인(병합) POST → 분석 프레임에 변형 표기가 사라짐
    mapping = {m["name"]: target for m in grp["members"] if m["name"] != target}
    save = _post(client, "/api/tech-rules", {"mapping": mapping}).get_json()
    assert save["status"] == "ok"
    got2 = client.get("/api/tech-rules?dataset=%s" % DS).get_json()
    by = {c["name"]: c for c in got2["classes"]}
    va = next(iter(merged_away))
    assert by[va]["current"] == target and by[va]["approved"]
    r = _post(client, "/api/basic-stats", {"filters": {}}).get_json()
    assert r["status"] == "ok"
    labels = {str(t) for t in list(r["tech"]["data"][0]["y"]) +
              list(r["tech"]["data"][0]["x"])}
    assert not (merged_away & labels), (merged_away, labels)
    assert target in labels
    # 노이즈 지정 → 미분류로 표기
    _post(client, "/api/tech-rules", {"noise": [target]})
    r2 = _post(client, "/api/basic-stats", {"filters": {}}).get_json()
    labels2 = {str(t) for t in list(r2["tech"]["data"][0]["y"]) +
               list(r2["tech"]["data"][0]["x"])}
    assert target not in labels2 and TECH_UNCLASSIFIED in labels2
    # 원복(unnoise + reset)
    _post(client, "/api/tech-rules", {"unnoise": [target],
                                      "reset": list(mapping.keys())})


# ---------------- 제외 출원인 필터 ----------------
def test_exclude_applicants_from_rankings():
    prep = make_prepared(generate_sample(n=300, seed=42))
    from src.config import merged_settings
    settings = merged_settings({})
    full = applicant_counts(prep, settings)
    target = str(full.index[0])
    ex = dict(settings, _exclude_applicants=[target])
    cut = applicant_counts(prep, ex)
    assert target not in cut.index
    assert target not in set(applicant_series(prep, ex))
    # 다른 회사 건수는 불변 (문헌 자체는 유지)
    other = str(full.index[1])
    assert int(cut.get(other, 0)) == int(full.get(other, 0))
    # first 모드에서도 제외
    ex_first = dict(ex, coapplicant_mode="first")
    assert target not in applicant_counts(prep, ex_first).index


def test_exclude_applicants_api_but_not_coapplicant_network(client):
    # 대상: 데이터 최다 출원인
    r0 = _post(client, "/api/basic-stats", {"filters": {}}).get_json()
    top_label = str(r0["applicants"]["data"][0]["y"][-1])  # 가로 막대 마지막=1위
    body = {"filters": {"exclude_applicants": [top_label]}}
    r1 = _post(client, "/api/basic-stats", body).get_json()
    assert r1["status"] == "ok"
    assert top_label not in set(map(str, r1["applicants"]["data"][0]["y"]))
    # 전체 KPI(문헌 수)는 그대로 — 문헌 제거가 아님
    assert r1["kpi"]["total"] == r0["kpi"]["total"]
    # 공동출원 자체 분석(협력 네트워크)에는 적용되지 않음
    adv = _post(client, "/api/advanced-stats", body).get_json()
    sec = (adv.get("sections") or {}).get("coapplicant")
    if sec and sec.get("network"):
        node_ids = {n["data"]["id"] for n in sec["network"]["nodes"]}
        assert top_label in node_ids, "공동출원 네트워크에서는 제외되면 안 됨"
