# -*- coding: utf-8 -*-
"""
tools/build_backend.py — src/ 모듈을 병합하여 webapp/backend.py 생성.

동작:
- MODULE_ORDER 의존성 순서로 각 모듈 소스를 이어붙인다.
- `from src.… import …` / `from src import …` 내부 import 라인(괄호 멀티라인 포함)을
  제거한다. 병합 파일에서는 모든 심볼이 전역이므로 안전하다.
- `from src import storage` 는 SimpleNamespace 심(shim)으로 치환한다.
- 말미에 Dataiku Standard Webapp 부트스트랩(app 은 Dataiku 가 주입, 로컬 실행 시
  Flask 앱 생성)을 붙인다.

사용법: python tools/build_backend.py
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MODULE_ORDER = [
    "src/config.py",
    "src/gpu_utils.py",
    "src/cache.py",
    "src/column_mapping.py",
    "src/preprocessing.py",
    "src/metrics.py",
    "src/storage.py",
    "src/auth.py",
    "src/data_access.py",
    "src/uploads.py",
    "src/embedding_files.py",
    "src/insight_store.py",
    "src/embedding_adapter.py",
    "src/llm_client.py",
    "src/web_search.py",
    "src/viz_payload.py",
    "src/insights.py",
    "src/analyses/common.py",
    "src/analyses/overview.py",
    "src/analyses/tech_network.py",
    "src/analyses/emerging.py",
    "src/analyses/lifecycle.py",
    "src/analyses/whitespace.py",
    "src/analyses/problem_solution.py",
    "src/analyses/transition.py",
    "src/analyses/trajectory.py",
    "src/analyses/company_dna.py",
    "src/analyses/lead_lag.py",
    "src/analyses/claim_density.py",
    "src/analyses/citation_influence.py",
    "src/analyses/inventor_mobility.py",
    "src/analyses/classification_quality.py",
    "src/analyses/basic_stats.py",
    "src/analyses/portfolio_index.py",
    "src/analyses/advanced_stats.py",
    "src/analyses/scope_entropy.py",
    "src/analyses/combo_upset.py",
    "src/analyses/semantic_insights.py",
    "src/analyses/wips_deep.py",
    "src/analyses/exec_plus.py",
    "src/analyses/deep_plus.py",
    "src/analyses/executive.py",
    "src/analyses/axis_cross.py",
    "src/analyses/ownership.py",
    "src/api.py",
]

STORAGE_SHIM = """\
# (병합 shim) src.storage 모듈 네임스페이스
import types as _types
storage = _types.SimpleNamespace(
    load_store=load_store, save_store=save_store,
    load_settings=load_settings, save_settings=save_settings,
    load_mapping_for=load_mapping_for, save_mapping_for=save_mapping_for,
    load_applicant_rules=load_applicant_rules, save_applicant_rules=save_applicant_rules,
    load_projects=load_projects, save_projects=save_projects,
    load_filter_state=load_filter_state, save_filter_state=save_filter_state,
    load_uploads=load_uploads, save_uploads=save_uploads, upload_dir=upload_dir,
    insight_image_dir=insight_image_dir)
"""

HEADER = '''# -*- coding: utf-8 -*-
"""
IP Landscape Advanced Insight Webapp — Dataiku Standard Webapp Python Backend.

⚠ 이 파일은 tools/build_backend.py 가 src/ 모듈을 병합하여 자동 생성한다.
   수정은 src/ 에서 하고 다시 빌드할 것.

Dataiku Standard Webapp 의 "Python" 탭에 이 파일 전체를 붙여넣으면
Dataiku 가 제공하는 전역 `app`(Flask) 객체에 라우트가 등록된다.
"""
'''

FOOTER = '''

# ===========================================================================
# Webapp 부트스트랩
# ===========================================================================
# Dataiku Standard Webapp 은 전역 `app`(Flask) 을 주입한다.
# 로컬 개발·테스트 실행: python webapp/backend.py --serve [포트]
try:
    app  # noqa: F821  (Dataiku 주입 여부 확인)
except NameError:
    from flask import Flask
    app = Flask(__name__)

register_routes(app)

if __name__ == "__main__":
    import sys as _sys
    if "--serve" in _sys.argv:
        _port = 5000
        _idx = _sys.argv.index("--serve")
        if len(_sys.argv) > _idx + 1:
            try:
                _port = int(_sys.argv[_idx + 1])
            except ValueError:
                pass
        app.run(host="127.0.0.1", port=_port, debug=False)
'''

_IMPORT_START = re.compile(r"^\s*from\s+src(\.[\w.]+)?\s+import\b")


def strip_internal_imports(source):
    """`from src… import …` 라인 제거 (괄호 멀티라인 포함). storage 는 shim 치환."""
    out_lines = []
    lines = source.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if _IMPORT_START.match(line):
            if re.match(r"^\s*from\s+src\s+import\s+storage\b", line):
                out_lines.append("# [merged] from src import storage → shim 은 병합부에서 정의됨")
                i += 1
                continue
            # 괄호/백슬래시 연속 라인 소비
            joined = line
            while joined.count("(") > joined.count(")") or joined.rstrip().endswith("\\"):
                i += 1
                joined = joined.rstrip().rstrip("\\") + " " + lines[i]
            # `X as Y` 별칭은 병합 파일에서 `Y = X` 대입으로 보존
            indent = re.match(r"^\s*", joined).group(0)
            imported = joined.split(" import ", 1)[1].strip().strip("()")
            for item in imported.split(","):
                item = item.strip()
                if " as " in item:
                    orig, alias = [p.strip() for p in item.split(" as ", 1)]
                    if orig and alias and orig != alias:
                        out_lines.append("%s%s = %s  # [merged import alias]" % (indent, alias, orig))
            i += 1
            continue
        out_lines.append(line)
        i += 1
    return "\n".join(out_lines)


# 병합 시 모듈 간 이름공간이 하나로 합쳐진다 — 서로 다른 모듈이 같은 전역 이름을
# 정의하면 나중 모듈이 앞 모듈을 덮어써 침묵 버그가 된다 (예: wips_deep._SECTIONS
# 를 exec_plus._SECTIONS 가 덮어써 심층 시그널이 빈 결과를 반환). 빌드에서 차단.
_COLLISION_ALLOWED = {"logger"}   # logging.getLogger 동일 객체 — 무해


def check_name_collisions():
    import ast
    owners = {}
    problems = []
    for rel in MODULE_ORDER:
        with io.open(os.path.join(ROOT, rel), "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in tree.body:
            names = []
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names = [node.name]
            elif isinstance(node, ast.Assign):
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            for name in names:
                if name in _COLLISION_ALLOWED:
                    continue
                if name in owners and owners[name] != rel:
                    problems.append("'%s': %s ↔ %s" % (name, owners[name], rel))
                owners.setdefault(name, rel)
    if problems:
        raise SystemExit("병합 이름 충돌 — 한쪽 모듈에서 이름을 바꾸세요:\n  "
                         + "\n  ".join(sorted(set(problems))))


def build():
    check_name_collisions()
    parts = [HEADER]
    for rel in MODULE_ORDER:
        path = os.path.join(ROOT, rel)
        with io.open(path, "r", encoding="utf-8") as fh:
            src = fh.read()
        body = strip_internal_imports(src)
        parts.append("\n\n# %s\n# %s\n# %s\n%s" % ("=" * 75, rel, "=" * 75, body))
        if rel == "src/storage.py":
            parts.append("\n" + STORAGE_SHIM)
    parts.append(FOOTER)
    out_path = os.path.join(ROOT, "webapp", "backend.py")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with io.open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(parts))
    # 문법 검증
    import ast
    with io.open(out_path, "r", encoding="utf-8") as fh:
        ast.parse(fh.read())
    print("생성 완료: %s (%d bytes)" % (out_path, os.path.getsize(out_path)))


if __name__ == "__main__":
    build()
