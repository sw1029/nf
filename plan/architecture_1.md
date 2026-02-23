> 구현 순서(Phase) 통제: `plan/IMPLEMENTATION_CHECKLIST.md`

## 1) 상위 아키텍처 구조도 (프로세스/책임 분리)

```text
┌──────────────────────────────┐
│ Desktop UI (Windows)         │   PySide6(권장) / (대안: Qt+Tauri)
│ - 문서 편집기/태깅 UI         │
│ - 결과(근거+점수) 렌더링       │
│ - 작업 요청/취소/진행률        │
└───────────────┬──────────────┘
                │ IPC(로컬) / gRPC(선택)
                ▼
┌──────────────────────────────┐
│ App Orchestrator (Core API)   │  "한 곳에서 조율만" (상태/권한/세마포어)
│ - 프로젝트/문서/에피소드 관리   │
│ - 파이프라인 트리거            │
│ - 캐시/메모리 상한/동시작업 제한 │
└───────┬───────────┬──────────┘
        │           │
        │ enqueue   │ sync query
        ▼           ▼
┌──────────────────┐    ┌──────────────────────────────┐
│ Background Queue  │    │ Retrieval Layer              │
│ (작업 큐)          │    │ - BM25/FTS (정확 인용)        │
│ - job meta         │    │ - Vector (의미 확장, shard)    │
│ - cancel/retry     │    │ - Hybrid Search Router        │
└───────┬──────────┘    └───────────────┬──────────────┘
        │                               │
        ▼                               ▼
┌────────────────────────────────────────────────────────┐
│ Workers (분리 프로세스 권장)                            │
│ 1) Ingestion/Schema Worker                              │
│  - 문서→스키마(명시/암시 레이어 분리)                    │
│  - 태그/계층 분류/정규화/유효성검사/버전관리             │
│                                                        │
│ 2) Index Worker                                         │
│  - FTS 인덱스(SQLite FTS5 등, 디스크 기반)              │
│  - Vector 인덱스(FAISS/HNSW, shard 빌드/로드/언로드)     │
│                                                        │
│ 3) Consistency Worker                                   │
│  - Claim(텍스트 세그먼트) → Evidence(FTS/Vector) → Judge │
│  - 3단 강제 근거화 + unknown 강등                        │
│  - 화이트리스트(의도된 모순/거짓말) 처리                 │
│                                                        │
│ 4) Optional Model Gateway Worker                         │
│  - 로컬 NLI/분류기(ONNX)                                 │
│  - 외부 API(OpenAI/Gemini 등) 호출(선택)                 │
└────────────────────────────────────────────────────────┘
        │
        ▼
┌──────────────────────────────┐
│ Storage Layer (디스크 우선)   │
│ - Project DB (SQLite)         │  문서/태그/스키마/버전
│ - DocStore (원문/스냅샷)       │
│ - IndexStore(FTS/Vector shard)│
│ - Artifact(Export/docx/txt)   │
│ - Audit/Provenance(근거로그)  │
└──────────────────────────────┘
```

핵심 의도:

* **UI가 절대 죽지 않도록** 인덱싱/모델/정합성 검토를 **분리 프로세스 워커**로 격리.
* 검색은 **BM25/FTS → Vector** 2단을 기본으로 고정(정확 인용이 먼저).
* 정합성은 **Claim–Evidence–Verdict(unknown 허용)** “강제 근거화” 규격으로만 결과 출력.

---

## 2) 기능 모듈(도메인 기준) 분해

### A. 편집/태깅(사용자 주도, rule-base 우선)

* `Editor`: 글 작성, 에피소드(n~m화) 범위 관리
* `Layout`: 자간/줄간격 등 레이아웃 설정(Editor Settings)
* `Tagging`: 드래그 태깅(복선/사건/관계/장소/시간 등), 태그 품질(희소성/일관성) 점검(휴리스틱 우선)

### B. 문서→스키마(오염 방지 게이팅 포함)

* `Schema`:

  * **명시 필드 레이어(High precision/Low recall)**: 나이/시간/장소/관계/사망여부/소속 등 “하드 제약”
  * **암시/추정 레이어(Unknown 허용)**: 심리/서술트릭/암시 등은 자동 확정 금지, 근거 충돌 시 보류
* `Gating/Validation`: 타입/단위/정규화, ID(identity), 중복/동일성, 충돌 감지, 스키마 버전

### C. 인덱싱(디스크 기반 + 샤딩)

* `FTS`: SQLite FTS5(권장)로 문서ID/섹션/태그경로 기반 스니펫 인용
* `Vector`: FAISS/HNSW shard 인덱스(필요 샤드만 로드/언로드)
* `Hybrid Router`: job 내부는 FTS→Vector 확장 가능, UI sync query는 FTS-only + Vector는 job/스트리밍

### D. 정합성 검토(3단 강제 근거화)

* `Claim Extractor`: 사용자가 쓰는 텍스트를 세그먼트(문장/절/이벤트 후보)로 분리
* `Evidence Builder`: FTS 매칭 강도 + 스키마 경로 + 원문 스니펫을 증거로 구성
* `Judge`:

  * Layer1: 명시 필드 기반 “위배/비위배/unknown”
  * Layer2: 휴리스틱(약한 추론) + 충돌 시 unknown 강등
  * Layer3(선택): 로컬 NLI/분류기(ONNX) 또는 API 위임
* `Whitelist`: 의도된 모순/거짓말 체크 시 “오류→추가정보”로 상태 전환, 재경고 방지

### E. 신뢰성 점수(단일 점수 + 분해 근거)

* 점수는 **(FTS 강도 / 근거 개수 / 확정근거 유무 / 모델 추론 점수)**로 분해 저장·표시

### F. 개선 제안(선택, 고성능 모델은 API로 분리)

* `Suggestion Engine`: RAG 근거를 **문서ID/섹션/태그경로**로 인용하며 요약/개선 제안
* “문장 생성/개선”은 (1차) LOCAL(rule-base) 우선 + (옵션) 고성능 API(opt-in) + (차순위) 로컬 생성 모델

### G. Export

* TXT/DOCX 출력(+ 메타데이터 포함/미포함 옵션)

### H. Proofread/Formatting (선택, rule-base 우선)

* 문법(띄어쓰기/문장부호 포함) rule-base 실시간 표시(에디터 내 lint)
* 모델 기반 문법 교정은 차순위(옵트인): `plan/DECISIONS_PENDING.md` 참고
* 자간/줄간격은 Proofread가 아닌 Layout(Settings)으로 처리

---

## 3) 권장 Python 레포 구조 (모듈별 repo 분리 형태)

아래는 **멀티-레포(모듈별 책임 분산)**를 전제로 한 구조도입니다. (실제로는 mono-repo로도 운영 가능하지만, “앱/모델/인덱서 분리” 요구와 EXE 배포 이슈를 감안하면 모듈 분리가 관리에 유리)

```text
novel-forge/
  ├─ nf-desktop/                # UI/배포(Windows EXE)
  ├─ nf-orchestrator/           # Core API + 파이프라인 조율 + 정책(세마포어/메모리상한)
  ├─ nf-workers/                # 백그라운드 작업자(분리 프로세스/서비스)
  ├─ nf-schema/                 # 스키마/태그/정규화/게이팅(도메인 핵심)
  ├─ nf-retrieval/              # FTS/Vector/Hybrid 검색 계층
  ├─ nf-consistency/            # Claim-Evidence-Verdict 엔진(3단 근거화)
  ├─ nf-model-gateway/          # 로컬 ONNX + 외부 API 어댑터(키/레이트리밋/회로차단)
  ├─ nf-export/                 # txt/docx export
  └─ nf-shared/                 # 공통 타입/프로토콜/에러/로깅/설정
```

---

## 4) 각 repo 내부 구조(파이썬 패키지 기준)

### 4.1 `nf-desktop/` (UI + 로컬 IPC 클라이언트)

```text
nf-desktop/
  ├─ pyproject.toml
  ├─ src/nf_desktop/
  │   ├─ app.py
  │   ├─ ui/                    # Qt widgets/views
  │   ├─ editor/                # 에디터 상태/커서/선택영역/태깅 UI
  │   ├─ client/                # orchestrator 호출(IPC/gRPC/HTTP)
  │   ├─ viewmodels/            # 결과 렌더링(근거/점수/화이트리스트 상태)
  │   └─ assets/
  └─ packaging/                 # PyInstaller spec 등(또는 Nuitka)
```

### 4.2 `nf-orchestrator/` (정책/조율/프로젝트 관리)

```text
nf-orchestrator/
  ├─ pyproject.toml
  ├─ src/nf_orchestrator/
  │   ├─ main.py                # API 엔트리(IPC/gRPC/HTTP 중 택1)
  │   ├─ services/
  │   │   ├─ project_service.py  # 프로젝트/문서/에피소드 CRUD
  │   │   ├─ pipeline_service.py # 인덱싱/정합성/제안 트리거
  │   │   ├─ whitelist_service.py
  │   │   └─ settings_service.py # 모델 다운로드/키 관리(저장은 OS keyring 권장)
  │   ├─ policies/
  │   │   ├─ semaphore.py        # 동시 작업 제한(전역 토큰)
  │   │   ├─ memory_cap.py       # 워커별 메모리 상한 힌트
  │   │   └─ circuit_breaker.py  # API 오류/환각 위험 시 차단
  │   └─ storage/
  │       ├─ db.py               # SQLite 연결/마이그레이션
  │       └─ repos/              # 프로젝트/문서/스키마 메타 저장
  └─ migrations/
```

### 4.3 `nf-workers/` (백그라운드 작업자, “죽어도 UI 생존”)

```text
nf-workers/
  ├─ pyproject.toml
  ├─ src/nf_workers/
  │   ├─ runner.py              # 워커 프로세스 엔트리
  │   ├─ queue/
  │   │   ├─ interface.py       # 큐 추상화
  │   │   └─ sqlite_queue.py    # 로컬 단일기기용(디스크 기반) 권장
  │   ├─ jobs/
  │   │   ├─ ingest_job.py      # 문서→스키마
  │   │   ├─ index_job.py       # FTS/Vector build
  │   │   ├─ consistency_job.py # 정합성 검토 실행
  │   │   ├─ retrieve_vec_job.py# 선택: Vector 검색(비동기, UI 스트리밍)
  │   │   ├─ proofread_job.py   # 선택: 문법/룰 기반 교정
  │   │   └─ suggest_job.py     # 선택: 개선 제안(API/로컬)
  │   └─ runtime/
  │       ├─ process_pool.py    # 프로세스/스레드 풀
  │       └─ resource_guard.py  # 메모리/CPU 제한(소프트 가드)
```

### 4.4 `nf-schema/` (오염 방지 핵심: 타입/정규화/충돌/버전)

```text
nf-schema/
  ├─ pyproject.toml
  ├─ src/nf_schema/
  │   ├─ types.py               # DocumentID/SectionPath/TagPath/Claim 등 공통 타입
  │   ├─ ontology/              # 기본 제공 태그/계층 정의
  │   ├─ parser/
  │   │   ├─ markup_parser.py   # 사용자 태깅/마크업 파싱
  │   │   └─ episode_chunker.py # n~m화 에피소드 구성
  │   ├─ extraction/
  │   │   ├─ explicit_fields.py # 나이/시간/장소/관계 등(High precision)
  │   │   └─ implicit_fields.py # 암시/추정(unknown 우선)
  │   ├─ normalize/
  │   │   ├─ units.py           # 나이/시간 단위 정규화
  │   │   └─ identity.py        # 인물/장소 동일성(규칙+보수적)
  │   ├─ gating/
  │   │   ├─ validators.py      # 타입/범위/필드 누락/상호제약
  │   │   └─ conflict.py        # 충돌 시 unknown 강등 규칙
  │   └─ versioning/
  │       ├─ schema_version.py
  │       └─ migrations.py
```

### 4.5 `nf-retrieval/` (BM25/FTS → Vector, 인용 규격화)

```text
nf-retrieval/
  ├─ pyproject.toml
  ├─ src/nf_retrieval/
  │   ├─ fts/
  │   │   ├─ fts_index.py       # SQLite FTS5 인덱스
  │   │   └─ snippet.py         # 인용 스니펫 생성(문서ID/섹션/태그경로 포함)
  │   ├─ vector/
  │   │   ├─ embedder.py        # 임베딩(로컬/외부)
  │   │   ├─ faiss_store.py     # shard 저장/로드/언로드
  │   │   └─ hnsw_store.py      # 2차 후보군
  │   ├─ hybrid/
  │   │   ├─ router.py          # FTS 우선, 부족 시 vector 확장
  │   │   └─ rerank.py          # 경량 rerank(선택)
  │   └─ contracts.py           # Evidence, RetrievalResult 스펙
```

### 4.6 `nf-consistency/` (Claim–Evidence–Verdict + 3단 강제 근거화)

```text
nf-consistency/
  ├─ pyproject.toml
  ├─ src/nf_consistency/
  │   ├─ segment/
  │   │   ├─ segmenter.py       # 텍스트 segmentation
  │   │   └─ claim_extractor.py # claim 후보 추출
  │   ├─ judge/
  │   │   ├─ layer1_explicit.py # 명시 필드 기반 위배검사
  │   │   ├─ layer2_heuristic.py# 휴리스틱(충돌 시 unknown)
  │   │   └─ layer3_model.py    # NLI/분류기 또는 API 위임(선택)
  │   ├─ scoring/
  │   │   ├─ reliability.py     # 점수 분해(FTS/근거/확정/모델)
  │   │   └─ calibration.py     # 과신 방지(보수적)
  │   ├─ whitelist/
  │   │   └─ policy.py          # 의도된 모순/거짓말 처리
  │   └─ output/
  │       ├─ verdict.py         # {violate|ok|unknown} + 근거
  │       └─ provenance.py      # 근거로그 표준화
```

### 4.7 `nf-model-gateway/` (로컬/외부 모델 경계)

```text
nf-model-gateway/
  ├─ pyproject.toml
  ├─ src/nf_model_gateway/
  │   ├─ local/
  │   │   ├─ onnx_runtime.py    # ONNX Runtime 래퍼
  │   │   ├─ nli_model.py       # 정합성용 소형 모델
  │   │   └─ tag_quality.py     # 태깅 품질 판단(선택)
  │   ├─ remote/
  │   │   ├─ openai_client.py
  │   │   ├─ gemini_client.py
  │   │   └─ rate_limit.py
  │   └─ safety/
  │       ├─ evidence_required.py # 근거 없으면 답변 불가 정책
  │       └─ fallback.py          # unknown/보류 처리
```

### 4.8 `nf-export/` (TXT/DOCX)

```text
nf-export/
  ├─ pyproject.toml
  ├─ src/nf_export/
  │   ├─ txt_export.py
  │   ├─ docx_export.py
  │   └─ templates/             # 문서 서식(선택)
```

### 4.9 `nf-shared/` (공통 규격)

```text
nf-shared/
  ├─ pyproject.toml
  ├─ src/nf_shared/
  │   ├─ config.py              # 설정 스키마
  │   ├─ logging.py
  │   ├─ errors.py
  │   ├─ protocol/
  │   │   ├─ dtos.py            # IPC/gRPC 메시지 타입
  │   │   └─ serialization.py
  │   └─ constants.py
```

---

## 5) “근거 인용” 출력 규격(모든 모듈이 공유해야 하는 표준)

정합성/제안/검색 결과는 아래를 **최소 단위**로 강제하는 편이 안전합니다.

```text
Evidence:
- doc_id: ...
- snapshot_id:  (옵션) DocStore snapshot (재현성/감사 목적)
- chunk_id:     (옵션) FTS/Vector 공통 키
- section_path: 예) "설정/인물/주인공"
- tag_path:     예) "설정/인물/주인공/나이"
- span:         원문 위치(옵션)
- fts_snippet:  FTS에서 뽑은 짧은 인용(길이 제한)
- strength:
    - fts_score
    - match_type(exact|fuzzy|alias)
    - confirmed(True/False)  # 명시 필드 기반 확정 여부
```

Verdict는 반드시:

* `claim_text`
* `verdict` = {`violate`, `ok`, `unknown`}
* `reliability` = 단일 점수 + 분해 항목
* `evidence[]` = 위 규격의 리스트
* `notes` = 화이트리스트/보류 사유

---

## 6) “디바이스 프리징”을 구조로 막는 포인트(아키텍처 상 위치)

* **Vector 인덱스는 “항상 RAM 상주” 금지**: `nf-retrieval/vector/*`에서 shard 단위 로드/언로드를 기본 정책으로 박아야 함.
* **모델 추론과 인덱싱을 같은 프로세스에 두지 않기**: `nf-workers` 내 job별 워커 분리.
* **전역 세마포어**: `nf-orchestrator/policies/semaphore.py`에서 “동시 heavy job 1개” 같은 하드 리밋.
* **근거 없는 모델 출력 금지**: `nf-model-gateway/safety/evidence_required.py`에서 “evidence 미충족 → unknown” 강제.
