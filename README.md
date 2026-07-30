# IP Landscape Advanced Insight Webapp

WIPS/PatentSquare 수준의 단순 통계를 넘어 **기술 진화·융합 탐지, 경쟁사 전략 분석,
권리장벽 진단, 화이트스페이스·R&D 기회 도출**을 수행하는
**Dataiku DSS Standard Webapp** 입니다. (최대 50,000건 안정 처리)

> 면책: 본 앱의 모든 분석은 특허 데이터에 기반한 탐색적 스크리닝 결과이며,
> 법률적 FTO 판단, 특허 유효성 판단 또는 인과관계를 의미하지 않습니다.

---

## 1. Dataiku 설치·실행 방법

### 1-1. 코드 라이브러리 환경 (필수 패키지)

Webapp 이 사용할 **Code environment** (Python 3.9+)에 다음 패키지를 설치하세요.

```
pandas>=1.5
numpy>=1.23
scikit-learn>=1.3
scipy>=1.9
openpyxl>=3.0
networkx>=3.0          # (권장) 조합 네트워크 Louvain 커뮤니티
sentence-transformers  # (권장) KR-SBERT 임베딩 — snunlp/KR-SBERT-Medium-extended-patent2024-hn
umap-learn>=0.5        # (선택) UMAP 투영 — 없으면 PCA 자동 폴백
hdbscan>=0.8           # (선택) sklearn<1.3 인 경우의 HDBSCAN — 없으면 DBSCAN 폴백
```

임베딩: 기본 설정(모델명 비움 = 자동)은 사내 서버에 설치된 로컬 모델 경로
`/dataiku/cache/huggingface/hub/models--snunlp--KR-SBERT-Medium-extended-patent2024-hn/snapshots/2a89bb1bbd16d851c05fa67629a76187dfc7d552`
를 먼저 시도합니다 — 네트워크 다운로드 없이 디스크에서 직접 로드되어 비용이 들지
않습니다. 로컬 경로가 없으면 `snunlp/KR-SBERT-Medium-extended-patent2024-hn` →
`snunlp/KR-SBERT-Medium-extended-patent2023` (한국어 특허 특화 SBERT) 순으로
HF 캐시에서 로드합니다 (GPU 자동 사용, 텍스트 해시 캐시). 우선순위: 사전 계산
임베딩 컬럼 → KR-SBERT → TF-IDF 폴백이며, 실제 사용된 방식은 화면(청구항 밀집도
"방법")에 표시됩니다. LLM Mesh 에 임베딩 모델로 등록한 경우 Settings → 임베딩
Adapter → "LLM Mesh" 로 연결할 수도 있습니다. 로컬 경로는 `src/config.py` 의
`LOCAL_SBERT_MODEL_DIR` 에서 변경할 수 있습니다.

GPU 환경(선택): RAPIDS `cuml`/`cupy` 가 설치되어 있으면 PCA/UMAP/HDBSCAN/유사도
계산에 자동으로 GPU 를 사용하고, 없으면 CPU(scikit-learn/numpy)로 자동 폴백합니다.
별도 설정은 필요 없습니다.

`flask` 와 `dataiku` 는 DSS 가 기본 제공합니다.

### 1-2. Standard Webapp 생성 및 탭별 붙여넣기

1. DSS 프로젝트 → **Webapps → + New webapp → Code webapp → Standard** 생성.
2. 각 탭에 `webapp/` 의 파일 내용을 그대로 붙여넣습니다.

| Dataiku 탭 | 파일 |
|---|---|
| HTML | `webapp/index.html` |
| CSS | `webapp/style.css` |
| JavaScript | `webapp/app.js` |
| Python | `webapp/backend.py` |

3. Webapp Settings 에서 위 1-1 의 Code environment 를 지정합니다.
4. **시각화 라이브러리**: `index.html` 상단의 CDN `<script>` 3줄이
   Plotly.js / Cytoscape.js / Apache ECharts 를 로드합니다. 인스턴스가 외부 CDN 에
   접근할 수 없다면, 동일 버전을 Webapp 의 JS 라이브러리 설정(또는 사내 미러)으로
   추가하고 CDN 3줄을 제거하세요.
5. Backend 를 시작(Start backend)하고 View 탭에서 확인합니다.

### 1-3. 최초 설정 순서

1. **Settings & Administration** 메뉴 → Dataset 선택
   (WIPS Excel 을 업로드해 만든 Dataset).
2. **컬럼 매핑 관리**: 자동 추천 매핑을 검토하고 필요한 항목을 드롭다운으로 수정 후
   저장. 분석별 활성/비활성 매트릭스가 함께 갱신됩니다.
   (매핑은 Dataiku 프로젝트 변수에 저장되며, 미가용 환경에서는 로컬 JSON 폴백)
3. **출원인·권리자 표준화**: 자동 표준화 후보를 검토·승인. 그룹(자회사→모회사) 설정
   및 규칙 JSON Export/Import 지원.
4. 필요 시 분석 단위(기본: 패밀리), 다중분류 처리방식, 임계값·가중치, LLM,
   사내 임베딩 Adapter 를 설정합니다.
5. 실제 Dataset 없이 화면만 확인하려면 **Demo mode** 를 켜세요
   (명시적으로 켠 경우에만 합성 샘플 데이터를 사용하며, 분석 본체는 절대 데이터를
   임의 생성하지 않습니다).

---

## 2. 구현 범위 (전 단계 구현 완료)

### 1단계 — MVP ✅ 완전 구현
- Dataiku Dataset 연결, 자동 컬럼 매핑(40개 개념 컬럼, 한/영/약어/WIPS 변형 사전
  + 정규화 + 유사도 매칭), 컬럼 매핑 관리 화면, 필수 컬럼 검증·분석 가용성 매트릭스
- 공통 필터 바(기간/출원인/기술 대·중·소분류/국가/법적상태/유효특허)
- Executive Overview (KPI + 성장/쇠퇴 Top10, 신규 조합 Top10, 전략변화 Top5,
  권리장벽/공백영역, 핵심특허·핵심기업 경보, 카드 → 상세 메뉴 이동)
- 4.2 기술분류 조합 네트워크 (Cytoscape, 동시출현·Jaccard·Lift·PMI/NPMI·성장률·
  신규출원인, 전체/기업/기업 제외 3-스코프 비교, Louvain 커뮤니티, Top-N 상한)
- 4.3 Emerging Combination Radar (가중 기하평균 Score, log1p→Winsorize→scaling
  정규화, CAGR 대체지표 사다리, 4분면 주석)
- 4.7 기술 생애주기 Phase Map (6단계 + Re-emerging 탐지 규칙 별도 함수,
  전년 대비 이동 화살표)
- 4.8 Actionable White Space Map (기회×장벽 2×2, 자사 역량 3방식, 가중치 슬라이더
  — 서버 재계산 없이 즉시 갱신)
- 문제–해결수단 매트릭스 (셀 클릭 패널: 특허 리스트·추이·대표 청구항·유효비율·
  Opportunity Score·인사이트 / 컬럼 없으면 비활성 + 안내만)
- 근거 특허 Drill-down(모든 그래프), Excel/PNG/SVG 다운로드, 규칙 기반 인사이트

### 2단계 — 경쟁사·전략 ✅ 완전 구현
- 4.1 기술분류 전이 Sankey (전이 정의 4종 드롭다운: 패밀리/출원인 포트폴리오/
  후속출원(패밀리 근사)/공동출현 증가)
- 4.4 Technology Trajectory Map (PCA 기본, UMAP 선택 + 자동 폴백, 구성비/TF-IDF)
- 4.5 경쟁사 기술 DNA (12지표, 레이더↔히트맵 자동 전환 + 평행좌표, 원값·표준화값
  동시 제공, 규칙 기반 기업 유형 6종 자동 분류)
- 4.6 선도–추종 분석 (lagged correlation, 최소 관측·표본 필터, 반복 관측 집계,
  Lead-Lag Network — "시계열상 선행 신호"로만 표기)
- 전략 유사도(코사인)·포트폴리오 중첩도(Jaccard) 히트맵

### 3단계 — 고급 권리·의미 분석 ✅ 완전 구현
- 4.9 청구항 권리장벽 지형도 (전처리→임베딩(컬럼/Adapter/TF-IDF 폴백)→유사도(GPU
  cuML/cupy 우선)→UMAP/PCA→HDBSCAN/DBSCAN→KDE 등고선, 클러스터 요약,
  "우선 검토 스크리닝 도구" 명시)
- 4.10 핵심특허 영향력 전파 (Influence Score 6지표 가중합, Citation Diffusion
  Sankey — 인용쌍 부재 시 근사 명시, 인용 데이터 없으면 비활성 + 안내)
- 4.11 발명자 이동 네트워크 (동명이인 식별 신뢰도 점수: 공동발명자·기술분류·시점·
  국가·희소성, 임계값 미만 "추정 이동" 기본 제외 + 포함 옵션, 시간 슬라이더)
- 4.12 기술분류 품질·경계 진단 (응집도·분리도·실루엣·다중분류/저신뢰 비율·드리프트·
  키워드 안정성, Confusion Map, 통합/분리/키워드 재정의/다중분류 기준 검토 제안)
- 사내 임베딩 Adapter (추상 클래스 + REST / 사전 계산 Dataset 두 구현체)
- LLM 인사이트 (Dataiku LLM Mesh, 고정 4모델 목록, 요약 통계만 전달 + sanitization,
  실패 시 규칙 기반 자동 폴백, 근거 지표 동시 표시)

### 남은 스텁
- 없음 — 명세된 전 기능이 실행 코드로 구현되어 있습니다. 단, 아래는 데이터 제약에
  따른 **명시적 근사/폴백**입니다 (화면·meta 에 표기됨):
  - 후속출원·계속·분할출원 전이(4.1 모드③): 전용 컬럼이 없어 패밀리 내 시차 출원으로 근사
  - 간접 피인용·타 기업 확산(4.10): 인용쌍(citing-cited) 데이터 부재 시 피인용 수 기반 근사
  - 임베딩 부재 시(4.9/4.12): TF-IDF 문자 n-gram 벡터/중복 비율 기반으로 degrade

---

## 3. 저장소 구조

```
├── README.md                  # 본 문서
├── docs/ARCHITECTURE.md       # 요구사항 요약·아키텍처 결정
├── webapp/                    # Dataiku 4개 탭에 붙여넣는 최종 파일
│   ├── backend.py             # ⚠ tools/build_backend.py 가 src/ 를 병합해 자동 생성
│   ├── index.html / style.css / app.js
├── src/                       # 개발용 모듈 소스 (테스트 대상)
│   ├── config.py              # 상수·ALLOWED_LLM_CANDIDATES·임계값·가중치·상한
│   ├── column_mapping.py      # 40개 개념 컬럼 사전 + 자동 매핑
│   ├── preprocessing.py       # 다중분류 파싱·패밀리 dedup·법적상태·출원인 표준화·필터
│   ├── metrics.py             # Lift/PMI/HHI/entropy/CAGR 사다리/정규화 파이프라인
│   ├── storage.py             # 프로젝트 변수↔로컬 JSON 저장 체인
│   ├── data_access.py         # Dataset 로딩(컬럼 최소화)·화이트리스트·전처리 캐시
│   ├── gpu_utils.py           # cuML/cupy ↔ sklearn/numpy 자동 폴백
│   ├── cache.py               # LRU+TTL 결과 캐시·실행 로그
│   ├── embedding_adapter.py   # 사내 임베딩 Adapter (REST/Dataset)
│   ├── llm_client.py          # LLM Mesh 호출(고정 목록·sanitization·폴백)
│   ├── viz_payload.py         # Plotly/Cytoscape/ECharts payload + 결과 envelope
│   ├── insights.py            # 규칙 기반 + LLM 인사이트
│   ├── api.py                 # 전체 API 라우트
│   └── analyses/              # 분석별 1파일 (4.1–4.12, overview, problem_solution)
├── tools/build_backend.py     # src/ → webapp/backend.py 병합 빌드
├── tests/                     # pytest (요구 12개 케이스 포함, 77개 테스트)
└── generate_sample_data.py    # 테스트·데모 전용 합성 데이터 (반도체 패키징 도메인)
```

수정 워크플로: `src/` 수정 → `python tools/build_backend.py` → `webapp/backend.py`
갱신 → Dataiku Python 탭에 재붙여넣기.

## 4. 로컬 개발·테스트

```bash
pip install pandas numpy scikit-learn scipy flask openpyxl pytest networkx
python -m pytest tests/            # 77 tests
python generate_sample_data.py sample_patents.csv --rows 600
IP_LANDSCAPE_DATA_DIR=. python webapp/backend.py --serve 5000   # CSV 폴백 모드
```

테스트 커버리지(요구 케이스): ①필수 컬럼 완비 ②선택 컬럼 누락 ③다중분류
쉼표/세미콜론/파이프/JSON ④1건뿐인 분류 ⑤최근 연도 0건 ⑥중복 패밀리 ⑦출원인명
다형 ⑧법적상태 누락 ⑨인용 없음 ⑩임베딩 없음 ⑪50,000건 성능 ⑫한·영·일 혼재.

## 5. API 요약

`/api/config` `/api/datasets` `/api/columns` `/api/column-mapping`
`/api/filter-options` `/api/overview` `/api/technology-network`
`/api/technology-transition` `/api/emerging-combinations` `/api/trajectory`
`/api/company-dna` `/api/lead-lag` `/api/lifecycle` `/api/opportunity`
`/api/claim-density` `/api/citation-diffusion` `/api/inventor-mobility`
`/api/classification-quality` `/api/problem-solution` `/api/patents`
`/api/insight` `/api/export` `/api/project/save` `/api/project/load`
(+ `/api/settings` `/api/applicant-rules` `/api/filter-state`)

- 오류 표준 형식: `{"status":"error","code":…,"message":…}`
- 데이터 없음: `{"status":"empty",…}` / 필수 컬럼 누락: `{"status":"disabled",
  "missing_columns":[…]}` — 각 엔드포인트 Docstring 에 요청/응답 명세.

## 6. 보안 메모

- LLM 모델은 `ALLOWED_LLM_CANDIDATES` 고정 목록만 허용, 호출은 Backend 전용이며
  프론트에는 표시명만 전달(모델 ID·키 미노출), LLM 입력은 요약 통계만 + sanitization.
- Dataset·컬럼명 화이트리스트 검증, 사용자 입력 eval/query 삽입 없음,
- 프론트 렌더링 시 모든 데이터 문자열 HTML escape (XSS 방지),
- 대용량 응답 방지(페이지네이션·Top-N 상한·Excel 행 상한).
