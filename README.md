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
- 권리범위 엔트로피 (Competitor Intelligence 탭): 기업별 정규화 Shannon 엔트로피를
  기술분류·IPC·청구구조(KR-SBERT 임베딩 클러스터)·청구 카테고리·시장(국가)·키워드
  차원에서 계산 — 레이더 + 연도별 시계열 + 다양성 vs Top-1 집중도, 전략 국면
  자동 판정(탐색 확대/핵심 집중/전략 분산/수렴) 및 탐색→수렴 전환 연도 추정
- 미점유 조합 UpSet (White Space 탭): 3개 이상 기술요소 교집합의 UpSet 차트
  (막대 색=유효특허 비율, 테두리=최근 3년 출원) + 기대-실제 격차 점수 기반
  미점유 조합 후보 표 (요소 독립 가정 기대 건수 대비 결합 청구 공백)
- LLM 인사이트 웹 검색 컨텍스트: AI 패널의 "웹 검색 포함" 체크 시 DuckDuckGo
  검색 결과(제목·요약·URL)를 신뢰 경계를 명시해 sanitize 후 참고 자료로 첨부,
  답변에 웹 출처 링크 표시. 네트워크 차단·실패 시 내부 데이터만으로 답변
  (Settings `web_search_enabled` 로 전체 비활성 가능)
- 신흥 기술 조기 탐지 (Technology Evolution 탭, 임베딩): 전체 문헌 임베딩을
  KMeans 군집화 후 군집별 출원 시점 분포 분석 — 최근 3년 집중 + 신규 출원인
  유입 + 새 군집 여부로 신흥 후보 판정, 군집 중심 인근 특허의 특징 키워드로
  자동 라벨링 (버블: X=평균 출원연도, Y=최근 비중, 색=신규 출원인 비율)
- 의미 기반 인용/영향력 대체 지표 (Patent Power 탭, 임베딩): 특허 이후 코사인
  유사도 임계값 이상의 '타 기업 후속 출원' 수로 영향력을 근사 — 원천 특허 →
  후속 기업 Sankey + 피인용 vs 의미 후속 비교 산점도(숨은 영향력 탐지).
  인용의 대체 신호일 뿐 인과관계 아님을 화면·meta 에 명시
- 특허 유사도 네트워크 / 권리 중첩 그래프 (Patent Power 탭, 임베딩): 코사인
  ≥ 임계값(기본 0.85, 화면에서 조정) 특허쌍을 엣지로 한 Cytoscape 네트워크 —
  연결 성분=중첩 지대(지배 출원인·유효 비율 표), 관절점=브리지 특허(빨간
  테두리), 노드 색=출원인. FTO 판단 아님 명시
- 매트릭스류 Excel 다운로드에 행/열 축 의미를 헤더에 표기 (예: "해결과제(행) \\
  해결수단(열)"), 문제-해결수단 매트릭스는 전체 라벨 건수 시트 추가 포함
- 심층 시그널 9종 (Basic Statistics → "심층 시그널" 탭): 출원건수·출원인·기술분류
  축이 아니라 잘 활용되지 않는 WIPS 필드를 주 축으로 사용 — ① 연차료 생존곡선
  (Kaplan-Meier, 등록일+소멸일; 5년 조기포기 영역 vs 18년 완주 영역) ② 지정국
  진입 시차 (우선일→국가별 출원 시차, 기업×국가 히트맵 + 1순위 진입국 전환 감지)
  ③ 대리인 전환 시그널 (신규 대리인 비중 급증 — 상관 관찰 명시) ④ 심사관의 눈
  (OA 인용 vs 자발 인용 산점도 — 선행기술 과소평가/무효 리스크 영역) ⑤ 우선심사
  긴급도 (기술×연도 버블 + 급등 랭킹) ⑥ 분할·계속출원 타임라인 (180일 버스트
  탐지; 산업 이벤트 정렬은 이벤트 데이터 부재로 미지원 명시) ⑦ 심사기간 이상탐지
  (분류별 바이올린 + MAD 기반 이상치 — 장기 심사 후 등록=강한 권리 후보)
  ⑧ 개시 충실도 (도면 수 분류 내 z-score — 상대비교 전용 명시) ⑨ 무효심판 충돌
  지도 (청구인→권리자 방향성 네트워크, 병목 특허 보유자 탐지). 각 섹션은 필요한
  컬럼(소멸일/대리인/우선심사/원출원번호/심판 이력 등 신규 매핑 개념 12종)이
  매핑된 경우에만 계산되고 나머지는 사유와 함께 생략됩니다
- 연도 축 전역 규칙: 제목에 '연도'가 든 수치축은 항상 1년=1칸(dtick=1, 정수 표기)
  으로 강제 렌더링됩니다 (프론트 공통 처리 — 모든 현재·미래 차트에 적용)
- 출원인 × 출원연도 버블 (Basic Statistics → 국가·출원인 탭): X=출원연도,
  Y=출원인(누적 1위가 맨 위), 버블 크기·색=그 해 출원건수, 클릭 시 해당
  기업·연도 특허 drill-down
- 경영진 전략 대시보드 (Executive Overview 하단): 자사 기준 KPI(시장 순위·
  점유율·성장률 격차·유효율·5년 내 만료 비중) + BCG 스타일 성장-점유 매트릭스
  (X=상대 시장점유율 로그축, Y=시장 성장률, 크기=시장 규모, Star/Question/
  Cash Cow/Dog 분면) + 경쟁 포지션 맵(X=성장률, Y=품질, ◇=자사) + 경영 Alert
  (핵심특허 만료 임박·급성장 경쟁사·자사 부재 고성장 분류). 자사는 Settings
  자사명 → 자사 특허 여부 컬럼 → 최다 출원인 순으로 자동 결정되며 화면에서
  직접 선택 가능. 특허 지표는 R&D 프록시임을 명시

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
python -m pytest tests/            # 전체 테스트 (빌드 시점 실측 집계는 앱의 검증 리포트에 표시)
python generate_sample_data.py sample_patents.csv --rows 600
IP_LANDSCAPE_DATA_DIR=. python webapp/backend.py --serve 5000   # CSV 폴백 모드
```

테스트 커버리지(요구 케이스): ①필수 컬럼 완비 ②선택 컬럼 누락 ③다중분류
쉼표/세미콜론/파이프/JSON ④1건뿐인 분류 ⑤최근 연도 0건 ⑥중복 패밀리 ⑦출원인명
다형 ⑧법적상태 누락 ⑨인용 없음 ⑩임베딩 없음 ⑪50,000건 성능 ⑫한·영·일 혼재.

### 검증 체계 (앱 화면에도 공개 — Data Quality → 검증 리포트)

- **독립 재계산 검증**: 생존곡선(Kaplan-Meier)은 손계산 표본과 대조, 기술 DNA
  각 축은 정의표대로 재계산해 대조, 차트 집계는 원본 데이터 수동 집계와 대조.
- **반례(함정) 회귀 테스트**: 공동출원 중복 카운팅, 발명자 이동 오인, 법인
  접미사 오분리, 역상관의 선행신호 오인, 실무 파일의 결측(NaN) 왜곡 등
  실제로 발견해 수정한 버그마다 재발 방지 테스트를 남김.
- **계약 테스트**: 전 API 엔드포인트 호출·캐시 키·오류 형식 검증 + 실제
  브라우저(Chromium/Playwright) 전 메뉴 순회 스모크(콘솔 오류 0건 기준).
- **정직성 규칙**: 계산 불가는 이유와 함께 '계산 불가'로, 표본 부족은 경고로
  표시 — 검증 리포트의 셀프 체크도 확인 불가 항목을 통과로 위장하지 않음.
- 빌드 스크립트(`tools/build_backend.py`)가 테스트 수를 **실측 집계**해 병합
  파일에 기록하며, 앱은 그 값을 그대로 표시한다 (지어낸 수치 금지).

## 5. API 요약

`/api/config` `/api/datasets` `/api/columns` `/api/column-mapping`
`/api/filter-options` `/api/overview` `/api/technology-network`
`/api/technology-transition` `/api/emerging-combinations` `/api/trajectory`
`/api/company-dna` `/api/lead-lag` `/api/lifecycle` `/api/opportunity`
`/api/claim-density` `/api/citation-diffusion` `/api/inventor-mobility`
`/api/classification-quality` `/api/problem-solution` `/api/patents`
`/api/insight` `/api/export` `/api/project/save` `/api/project/load`
`/api/quality-report`
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
