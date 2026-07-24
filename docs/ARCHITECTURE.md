# IP Landscape Advanced Insight Webapp — 아키텍처 문서

## 1. 요구사항 요약

WIPS에서 다운로드한 특허 Excel(→ Dataiku Dataset, 최대 50,000건)을 입력으로,
단순 통계를 넘어 다음 인사이트를 도출하는 Dataiku DSS **Standard Webapp**을 구현한다.

- **기술 진화·융합 탐지**: 기술분류 전이 Sankey(4.1), 조합 네트워크(4.2), Emerging
  Combination Radar(4.3), Technology Trajectory Map(4.4), 생애주기 Phase Map(4.7)
- **경쟁사 전략 분석**: 기술 DNA Fingerprint(4.5), 선도–추종 분석(4.6),
  전략 유사도·포트폴리오 중첩도
- **권리장벽 진단**: 청구항 중첩 기반 권리장벽 지형도(4.9), 핵심특허 영향력 전파(4.10)
- **화이트스페이스·R&D 기회**: Actionable White Space Map(4.8), 문제–해결수단 매트릭스
- **품질 진단**: 기술분류 품질·경계 진단(4.12), 발명자 이동 네트워크(4.11)
- **자동 인사이트**: 규칙 기반(1단계) + LLM Mesh 기반(3단계, 실패 시 규칙 기반 폴백)

## 2. 실행 환경 제약

| 항목 | 결정 |
|---|---|
| 실행 형태 | Dataiku DSS Standard Webapp (HTML / CSS / JS / Python backend 4개 탭) |
| 데이터 로딩 | `dataiku.Dataset(name).get_dataframe(columns=...)` — 필요한 컬럼만 로딩 |
| Backend↔Frontend | Flask `@app.route` + 프론트 `getWebAppBackendUrl()` |
| 시각화 | Plotly.js(일반·Sankey·버블·히트맵), Cytoscape.js(네트워크), ECharts(10만+ 셀 히트맵) |
| GPU | cuML/cupy 우선, 미탑재 시 scikit-learn/numpy 자동 폴백 (`gpu_utils.py`) |
| LLM | Dataiku LLM Mesh, 고정 모델 목록(`ALLOWED_LLM_CANDIDATES`)만 허용, Backend 전용 |

## 3. 모듈 구조 (개발 소스 `src/` → 병합 산출물 `webapp/backend.py`)

Dataiku Standard Webapp의 Python 탭은 단일 파일이므로, 개발은 `src/` 모듈로 하고
`tools/build_backend.py`가 의존성 순서대로 병합하여 `webapp/backend.py`를 생성한다.
병합 시 `from src.… import …` 형태의 내부 import 라인만 제거된다(테스트는 `src/`를
패키지로 직접 import).

병합 순서(= 의존성 순서):

```
config → gpu_utils → cache → column_mapping → preprocessing → metrics → storage
→ data_access → embedding_adapter → llm_client → viz_payload
→ analyses/(overview, tech_network, emerging, lifecycle, whitespace, problem_solution,
            transition, trajectory, company_dna, lead_lag,
            claim_density, citation_influence, inventor_mobility, classification_quality)
→ insights → api
```

### 역할 분리 (개발 기본 원칙 1)

- **전처리 모듈**: `preprocessing.py` — 다중분류 파싱(쉼표/세미콜론/파이프/JSON/복수컬럼),
  패밀리 dedup + 대표문헌 선정, 법적상태 정규화, 출원인 표준화, 날짜 파싱, 필터 적용
- **지표 계산 모듈**: `metrics.py` — Lift, PMI/NPMI, Jaccard, HHI, Shannon entropy,
  CAGR + 대체지표 사다리(선형회귀 기울기 → 기간대비 증가율 → Poisson trend → log1p slope),
  정규화 파이프라인(log1p → winsorize → robust/minmax scaling → 가중 기하평균)
- **분석 모듈**: `analyses/*.py` — 분석별 1파일, 상단 Docstring에 목적·필수/선택 컬럼·
  계산식·예외처리·인사이트 규칙·Drill-down 조건 서술
- **시각화 데이터 생성**: `viz_payload.py` — Plotly/Cytoscape/ECharts용 JSON 변환 헬퍼
- **API 응답 모듈**: `api.py` — `register_routes(app)`로 모든 엔드포인트 등록,
  표준 오류 형식 `{"status":"error","code":...,"message":...}`
- **Frontend 렌더링 모듈**: `webapp/app.js` — 뷰 라우팅, 렌더러, 필터바, Drill-down,
  다운로드, Spinner/Toast를 각각의 네임스페이스 객체로 분리

## 4. 성능·확장성 (50,000건 기준)

- **캐싱**: `cache.py` — (dataset, 분석명, 필터 해시, 설정 해시) 키의 in-memory LRU + TTL.
  전처리 결과(DataFrame)와 분석 결과(JSON)를 별도 캐시로 재사용.
- **컬럼 최소 로딩**: 컬럼 매핑 결과에서 분석에 필요한 실제 컬럼만 `get_dataframe(columns=)`.
- **상한 상수**: `config.py`의 `LIMITS` (네트워크 노드/엣지, Sankey 링크, 버블 수,
  히트맵 셀, drill-down 페이지 크기 등). Settings 화면에서 변경 가능.
- **필터 후 계산 / Top-N 표시 / 페이지네이션**: 모든 분석은 필터 적용 후 수행,
  응답은 Top-N + 총계, 특허 리스트는 서버 페이지네이션.

## 5. 우아한 저하 (graceful degradation)

각 분석 모듈은 `required_concepts` / `optional_concepts`를 선언하고,
`/api/config`가 분석×컬럼 가용성 매트릭스를 반환한다. 필수 개념 컬럼이 매핑되지
않은 분석은 (a) 메뉴 카드 비활성화, (b) "필수 컬럼이 없습니다" + 필요한 컬럼명·형식
안내를 표시한다. 데이터가 없거나 표본이 임계값 미만이면 "계산 불가" / "표본 부족"
응답(`status:"empty"`)을 반환하며 **값을 임의로 생성하지 않는다**. Demo mode는
사용자가 Settings에서 명시적으로 켠 경우에만 `generate_sample_data.py`와 동일한
합성 데이터 생성 함수를 사용한다.

## 6. 컬럼 매핑

- `column_mapping.py`: 39개 개념 컬럼 × (한글명/영문명/약어/WIPS 헤더 변형) 사전.
- 자동 매핑: 헤더 정규화(소문자·공백/특수문자 제거) → 사전 완전일치 → 부분일치 →
  difflib 유사도 매칭(임계값 0.75).
- 저장: Dataiku 프로젝트 변수(가능 시) → 실패 시 로컬 JSON(`storage.py` 폴백 체인).
- 다중분류 집계 방식: duplicate / fractional(1/N) / primary / level-separate — Settings에서 선택.

## 7. 통계·법률 표현 원칙

선행 관계는 "시계열상 선행 신호"로만 표기하고, 모든 관련 화면 하단에 고정 면책문구를
표시한다: "본 분석은 특허 데이터에 기반한 탐색적 스크리닝 결과이며, 법률적 FTO 판단,
특허 유효성 판단 또는 인과관계를 의미하지 않습니다."

## 8. 보안

- LLM ID·설정은 Backend 상수로만 존재, 프론트에는 표시명만 전달.
- Dataset명·컬럼명 화이트리스트 검증(`data_access.validate_dataset_name`,
  매핑된 컬럼만 사용), 사용자 입력을 eval/query 문자열에 삽입하지 않음.
- 프론트 렌더링 시 모든 데이터 문자열 HTML escape(`esc()` 유틸).
- LLM 프롬프트는 요약 통계만 전달 + sanitization(제어문자·프롬프트 인젝션 패턴 제거).

## 9. 단계별 구현 범위

- **1단계(MVP)**: Dataset 연결·컬럼 매핑 화면·공통 필터·Executive Overview·
  조합 네트워크(4.2)·Emerging Radar(4.3)·Phase Map(4.7)·White Space Map(4.8)·
  문제–해결수단 매트릭스·Drill-down·Excel/PNG/SVG 다운로드·규칙 기반 인사이트.
  2·3단계 API는 명세 Docstring + 501 스텁.
- **2단계**: 전이 Sankey(4.1)·Trajectory(4.4)·기술 DNA(4.5)·선도–추종(4.6)·
  전략 유사도·포트폴리오 중첩도.
- **3단계**: 권리장벽 지형도(4.9)·영향력 전파(4.10)·발명자 이동(4.11)·
  분류 품질 진단(4.12)·사내 임베딩 Adapter·LLM 인사이트.

각 단계 완료 시 `tools/build_backend.py`로 `webapp/` 병합 파일 4개를 갱신한다.

## 10. 주요 아키텍처 결정 및 근거

1. **단일 병합 파일 + 모듈 소스 이원화**: Dataiku 탭 제약(단일 Python 파일)과
   테스트 용이성(모듈 단위 pytest)을 동시에 만족.
2. **dataiku import 가드**: `import dataiku`를 try/except로 감싸 로컬 개발·테스트
   환경에서도 모든 모듈이 import 가능. 로컬에서는 CSV/DataFrame 주입 모드 지원.
3. **분석 결과 스키마 통일**: 모든 분석은
   `{"status": "ok|empty|disabled|error", "figure(s)":…, "insight":…, "meta":…}`
   구조를 반환 → 프론트 렌더러가 공통 처리(Spinner, 비활성 카드, 인사이트 박스).
4. **Drill-down 프로토콜**: 그래프 요소 클릭 → 프론트가 요소별 `drill` 파라미터
   (예: `{"type":"combo","a":…,"b":…}`)를 `/api/patents`에 전달 → 서버가 근거 특허
   목록을 페이지네이션으로 반환. Excel 다운로드는 동일 파라미터를 `/api/export`에 전달.
5. **가중치 슬라이더 즉시 반영**: `/api/opportunity`가 요소별 정규화 점수를 함께
   반환 → 프론트가 가중 기하평균만 재계산하여 서버 재호출 없이 갱신.
