> 구현 순서(Phase) 통제: `plan/IMPLEMENTATION_CHECKLIST.md`

## 1) “더 촘촘한” 전체 구조도 (프로세스/스토리지/IPC/큐까지 포함)

```text
┌───────────────────────────────────────────────────────────────────────────────┐
│                                Windows Desktop                                │
│  nf-desktop (PySide6)                                                          │
│  - Editor / Tagging / Episode Range                                            │
│  - Result Panel (Verdict + Evidence + Reliability breakdown)                   │
│  - Job Panel (progress/cancel/retry)                                           │
│  - Settings (local model download, API key)                                    │
│  - Layout Settings (char/line spacing)                                         │
│  - Proofread (grammar/punctuation, rule-base; real-time)                       │
└───────────────────────────────┬───────────────────────────────────────────────┘
                                │  IPC (권장: local HTTP over loopback)
                                │  - http://127.0.0.1:{port}
                                │  - Alternatively: gRPC / NamedPipe
                                ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                           nf-orchestrator (Core API)                           │
│  - Auth: local-only token(옵션)                                                 │
│  - Policies: global semaphore, memory caps hints, circuit breaker, rate limit  │
│  - Services: Project/Doc/Episode/Schema/Whitelist/Retrieval/Consistency/Suggest/Proofread │
│  - Job submit + status streaming                                                │
│                                                                               │
│  API calls:                                                                    │
│   UI -> orchestrator:                                                          │
│     1) CRUD: 프로젝트/문서/태그/에피소드                                         │
│     2) enqueue: ingest/index/consistency/retrieve_vec/suggest/proofread/export │
│     3) query: retrieval(FTS-only), evidence view, schema view                   │
│     4) whitelist: accept intended contradiction                                 │
└──────────────┬───────────────────────────────┬───────────────────────────────┘
               │                               │
               │ enqueue(job)                  │ read/query (sync)
               ▼                               ▼
┌───────────────────────────────┐     ┌────────────────────────────────────────┐
│  nf-workers (Job Runner)      │     │    FTS Query Path (sync)              │
│  - N worker processes          │     │  nf-retrieval                          │
│  - job lease/heartbeat         │     │  - FTS only (SQLite FTS5)              │
│  - cancel token check          │     │  - Vector retrieval: via /jobs         │
│  - per-job resource guard      │     │  - result stream: /jobs/{jid}/events   │
└──────────────┬────────────────┘     └───────────────────┬────────────────────┘
               │                                            │
               ▼                                            ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                                   Storage                                     │
│  (disk-first, process-safe, crash-resilient)                                   │
│                                                                               │
│  A) Project DB (SQLite)                                                        │
│   - project, document, doc_snapshot, section, chunk, episode                   │
│   - tag_def/tag_assignment, entity/entity_alias, schema_version                │
│   - schema_explicit_fact, schema_implicit_fact                                 │
│   - whitelist_item, verdict_log, evidence                                       │
│   - job_queue, job_run, job_event                                               │
│                                                                               │
│  B) DocStore (files)                                                           │
│   - raw documents, snapshots, user exports                                      │
│                                                                               │
│  C) FTS Index (SQLite FTS5)                                                     │
│   - fts_docs(content + chunk_id/snapshot_id + doc_id/section_path/tag_path)     │
│                                                                               │
│  D) VectorStore (shards on disk)                                                │
│   - embeddings shard files + meta (manifest)                                    │
│                                                                               │
│  E) ModelStore (optional downloads)                                             │
│   - local NLI/TagQuality ONNX + tokenizer assets                                │
└───────────────────────────────────────────────────────────────────────────────┘
```

---

## 2) IPC/API를 “기능 단위”로 쪼갠 상세 구조도

### 2.1 API 표면(오케스트레이터가 제공하는 최소 엔드포인트/핵심 메서드)

```text
/health
/projects                      GET/POST
/projects/{pid}                GET/PATCH/DELETE

/projects/{pid}/documents      GET/POST
/projects/{pid}/documents/{did} GET/PATCH/DELETE
/projects/{pid}/episodes       GET/POST        (n~m 구간 정의/수정)
/projects/{pid}/tags           GET/POST        (기본/사용자 정의)
/projects/{pid}/entities       GET/POST        (인물/장소 등 엔티티)
/projects/{pid}/entities/{eid}/aliases GET/POST/DELETE
/projects/{pid}/schema         GET             (현재 승인된 스키마 뷰)
 /projects/{pid}/schema/facts  GET             (filters: status/source/layer)
 /projects/{pid}/schema/facts/{fid} GET
 /projects/{pid}/schema/facts/{fid} PATCH      (approve/reject)

/jobs                          POST            (enqueue)
  body: {type, pid, inputs, priority, params}
 /jobs/{jid}                   GET             (status)
/jobs/{jid}/cancel             POST
/jobs/{jid}/events             GET (SSE/Websocket)

/query/retrieval               POST            (FTS-only 검색; sync)
  body: {pid, query, filters(tag_path/section/episode), k}
/query/evidence/{eid}          GET
/query/verdicts                POST            (특정 원고 구간 verdict 조회)

/projects/{pid}/whitelist      POST            (의도된 모순 등록)
 /projects/{pid}/whitelist/{wid} DELETE

/export                        POST            (txt/docx)
  body: {pid, range, format, include_meta}
```

**핵심 원칙**

* UI는 “무거운 일”을 직접 하지 않고 전부 `/jobs`로 넘김.
* 검색만은 UX 상 sync query 허용하되 **FTS-only**로 제한하고, Vector는 **job+스트리밍**으로 처리.

---

## 3) Job Queue 내부 구조도 (상태/리스/취소/재시도)

### 3.1 Job 상태 머신(필수)

```text
NEW -> QUEUED -> RUNNING -> {SUCCEEDED | FAILED | CANCELED}
                 |
                 +-> PAUSED (optional: resource pressure)
FAILED -> RETRYING -> QUEUED (max_retries 정책)
```

### 3.2 Queue 테이블/리스/하트비트(작업자 크래시 복구 포함)

```text
job_queue
- job_id (PK)
- type (INGEST|INDEX_FTS|INDEX_VEC|CONSISTENCY|RETRIEVE_VEC|SUGGEST|PROOFREAD|EXPORT)
- project_id
- payload_json
- priority
- status
- created_at, queued_at, started_at, finished_at
- lease_owner (worker_id)
- lease_expires_at
- cancel_requested (bool)
- attempts, max_attempts
- error_code, error_message

job_event (for UI streaming)
- event_id (PK)
- job_id
- ts
- level (INFO|WARN|ERROR|PROGRESS)
- message
- progress (0..1)
- metrics_json (optional: docs_processed, shards_built, mem_estimate)
```

### 3.3 Worker Runner 루프(간략)

```text
worker:
  poll job_queue where status=QUEUED order by priority, created_at
  try acquire lease (compare-and-swap lease_expires_at)
  set RUNNING
  while running:
     check cancel_requested
     emit job_event(progress)
     periodically extend lease (heartbeat)
  on success -> SUCCEEDED
  on error -> FAILED (+attempts)
  on cancel -> CANCELED
```

---

## 4) 데이터/스키마/근거(증거) 저장 구조도 (SQLite 관점)

### 4.1 프로젝트/문서/구간

```text
project
- project_id (PK), name, created_at, settings_json

document
- doc_id (PK), project_id (FK)
- title, type (SETTING|PLOT|CHAR|EPISODE|NOTE)
- path (DocStore raw path), created_at, updated_at
- head_snapshot_id (DocStore snapshot)
- checksum, version

doc_snapshot
- snapshot_id (PK), project_id, doc_id (FK)
- version
- path (DocStore snapshot path)
- checksum
- created_at

episode
- episode_id (PK), project_id
- start_n, end_m
- label, created_at

section (optional: 검색/필터링 편의)
- section_id (PK), project_id, doc_id (FK), snapshot_id (FK)
- section_path
- span_start, span_end (optional)

chunk (권장: FTS/Vector 공통 키)
- chunk_id (PK), project_id
- doc_id (FK), snapshot_id (FK)
- section_path, episode_id (optional)
- span_start, span_end
- token_count_est (optional)
- created_by (AUTO|USER)
- created_at
```

### 4.2 태그/계층 경로(“설정/인물/주인공/나이” 같은 tag_path)

```text
tag_def
- tag_id (PK), project_id
- tag_path (unique)              # "설정/인물/주인공/나이"
- kind (EXPLICIT|IMPLICIT|USER)
- schema_type (int|float|str|enum|time|loc|rel|bool|unknown)
- constraints_json               # 범위/단위/허용값

tag_assignment
- assign_id (PK), project_id
- doc_id, span_start, span_end
- tag_path
- user_value_json (optional)
- created_by (USER|AUTO)

entity (identity 정규화)
- entity_id (PK), project_id
- kind (CHAR|LOC|ORG|OBJ|EVENT)
- canonical_name
- created_at

entity_alias
- alias_id (PK), project_id, entity_id (FK)
- alias_text
- created_by (USER|AUTO)
- created_at
```

### 4.3 스키마(명시/암시 레이어 분리 + 버전)

```text
schema_version
- schema_ver (PK), project_id
- created_at
- source_snapshot_id (DocStore snapshot)
- notes

schema_explicit_fact
- fact_id (PK), project_id, schema_ver
- entity_id (nullable; normalized pointer), tag_path
- value_json
- evidence_eid (FK -> evidence)
- confidence (0..1)  # 명시 레이어는 보수적으로 높게만
- source (USER|AUTO)
- status (APPROVED|PROPOSED|REJECTED)  # AUTO는 기본 PROPOSED(유저 승인 필요)

schema_implicit_fact
- fact_id (PK), project_id, schema_ver
- entity_id (nullable), tag_path
- value_json (often "unknown" or distribution)
- evidence_eid
- confidence (0..1)
- status (PROPOSED|APPROVED|REJECTED)  # 자동 확정 금지의 구현 포인트
- source (USER|AUTO)
```

### 4.4 근거(Evidence)와 판정(Verdict) 로그

```text
evidence
- eid (PK), project_id
- doc_id
- snapshot_id (DocStore snapshot)
- chunk_id (optional; FK -> chunk)
- section_path
- tag_path
- snippet_text
- span_start, span_end (optional)
- fts_score
- match_type (EXACT|FUZZY|ALIAS)
- confirmed (bool)  # 명시 필드/사용자 승인 등으로 "확정 근거" 여부
- created_at

verdict_log
- vid (PK), project_id
- input_doc_id (원고), segment_span
- input_snapshot_id (DocStore snapshot)
- schema_ver (FK -> schema_version)
- claim_text
- verdict (OK|VIOLATE|UNKNOWN)
- reliability_overall (0..1)
- breakdown_json  # {fts_strength, evidence_count, confirmed_evidence, model_score}
- whitelist_applied (bool)
- created_at

verdict_evidence_link
- vid, eid, role (SUPPORT|CONTRADICT)
```

### 4.5 화이트리스트(의도된 모순/거짓말)

```text
whitelist_item
- wid (PK), project_id
- claim_fingerprint (hash)
- scope (doc_id|episode_range|global)
- note
- created_at
```

---

## 5) 인덱싱 계층 “샤딩/로드/언로드”까지 포함한 내부 구조도

### 5.1 FTS(SQLite FTS5)

```text
fts_docs (FTS5 virtual table)
- content
- chunk_id (stored)
- doc_id (stored)
- snapshot_id (stored)
- section_path (stored)
- tag_path (stored)
- episode_id (stored)
- span_start, span_end (stored, optional)

fts_meta
- doc_id, updated_at, checksum
- last_indexed_at
```

### 5.2 VectorStore(FAISS/HNSW Shards + Manifest)

```text
vector_manifest.json
- embedding_model_id
- dim
- shards: [
    { shard_id, path, doc_ids[], chunk_count_est, chunk_map_path, token_count_est, built_at, checksum },
    ...
  ]

shard files
- shard_000.faiss
- shard_001.faiss
- ...

policy
- load only top-N shards by:
   (episode range overlap) OR (doc_type filter) OR (recently used)
- LRU cache of loaded shards
- hard cap: max_loaded_shards, max_ram_mb
```

---

## 6) 정합성 검토 “3단 강제 근거화” 파이프라인 상세도 (실행 흐름)

### 6.1 Consistency Job 내부 서브스텝

```text
Input: draft text range (doc_id + span or episode range)

[Step 0] Segment
  - sentence/paragraph segmentation
  - claim candidates (time/age/location/rel keywords 우선)

[Step 1] Evidence retrieval (FTS-first)
  - query = claim text + extracted slots
  - filters: pid, tag_path narrowing if possible
  - output: top-k evidence (exact snippet + tag_path)

[Step 2] Judge Layer 1 (Explicit fields only)
  - compare claim slots vs schema_explicit_fact
  - if contradiction w/ confirmed evidence -> VIOLATE (high precision)
  - else if insufficient evidence -> UNKNOWN

[Step 3] Judge Layer 2 (Heuristic / weak inference)
  - alias/temporal normalization
  - ambiguous entity resolution (conservative)
  - conflict -> UNKNOWN downgrade

[Step 4] Judge Layer 3 (optional model/API)
  - only if: (a) user enabled, (b) Layer1/2 inconclusive, (c) evidence exists
  - output: model_score but cannot override “근거 부재”
  - hallucination 방지: evidence_required gate

[Step 5] Reliability scoring + logging
  - reliability = f(fts_strength, evidence_count, confirmed, model_score)
  - store verdict_log + verdict_evidence_link

[Step 6] Whitelist apply
  - if claim_fingerprint in whitelist -> mark + suppress repeated alerts
```

---

## 7) “문장 개선/생성”과 “정합성 검토” 분리 구조도 (모델 경계)

```text
                 ┌────────────────────────────┐
                 │ nf-model-gateway           │
                 │  - safety/evidence_required│
                 │  - rate limit/circuit brkr │
                 └───────────┬────────────────┘
                             │
       ┌───────────────┬─────┴───────────────┬───────────────┐
       │               │                     │               │
       ▼               ▼                     ▼               ▼
┌──────────────────┐ ┌───────────────────┐  ┌────────────────────────┐
│ Local small model │ │ Local generator   │  │ Remote high-perf API    │
│ (ONNX Runtime)    │ │ (quantized; 2nd)  │  │ (OpenAI/Gemini etc.)    │
│ - NLI/consistency │ │ - rewrite/suggest │  │ - rewrite/suggest       │
│ - tag quality     │ │   (차순위 구현)   │  │ - optional story analysis│
└──────────────────┘ └───────────────────┘  └────────────────────────┘

Rule: “정합성 검토”는 Local 우선 + unknown 허용
Rule: “개선 제안(SUGGEST)”은 1차: LOCAL(rule-base) / 옵션: Remote API(opt-in) / 2차: Local generator
```

---

## 8) 3가지 대표 유스케이스별 “시퀀스 다이어그램” 수준 상세 흐름

### 8.1 문서 추가 → 스키마 생성 → 인덱싱(FTS/Vector)

```text
UI -> Orchestrator: POST /projects/{pid}/documents (upload/register)
UI -> Orchestrator: POST /jobs {type:INGEST, doc_id}
Orchestrator -> Queue: enqueue(INGEST)

Worker(ingest) -> DocStore: read raw
Worker(ingest) -> nf-schema: parse/tag/normalize/gate
Worker(ingest) -> ProjectDB: write schema_version + facts(AUTO=PROPOSED, USER=APPROVED)

UI -> Orchestrator: POST /jobs {type:INDEX_FTS, scope:doc_id}
UI -> Orchestrator: POST /jobs {type:INDEX_VEC, scope:doc_id, shard_policy}
Workers -> FTS DB: build/update
Workers -> Vector shards: build shard + update manifest
```

### 8.2 원고 작성 중 정합성 검토(세그먼트 + 근거 + 판정)

```text
UI -> Orchestrator: POST /jobs {type:CONSISTENCY, draft_range}
Worker(consistency) -> Segment -> Retrieval(FTS->Vector) -> Judge(3 layers)
Worker -> ProjectDB: verdict_log/evidence links
UI -> Orchestrator: /jobs/{jid}/events (stream)
UI -> Orchestrator: POST /whitelist (if user marks intended)
```

### 8.3 개선 제안(근거 인용 기반, API는 선택)

```text
UI -> Orchestrator: POST /jobs {type:SUGGEST, range, mode:LOCAL_RULE|API|LOCAL_GEN(2nd)}
Worker(suggest) -> Retrieval -> build citation(bundle of doc_id/section/tag_path)
Worker(suggest) -> (optional) Remote API: rewrite using provided citations only
Worker -> ProjectDB: store suggestion + citations
UI renders suggestion with citation cards
```

---

### 8.4 검색(FTS sync + Vector job 스트리밍)

```text
UI -> Orchestrator: POST /query/retrieval (FTS-only, sync)

UI -> Orchestrator: POST /jobs {type:RETRIEVE_VEC, query, filters, k} (optional)
Worker(retrieve_vec) -> Retrieval(Vector shards) -> results stream
UI -> Orchestrator: /jobs/{jid}/events (stream)
```

---

## 9) “촘촘한 구조”에서 반드시 고정해야 하는 분기/정책 지점(구현상 스위치)

```text
[Policy Switches]
- enable_remote_api (default off)
- enable_layer3_model (default off)
- enable_local_generator (default off; 차순위)
- vector_index_mode: OFF | SHARDED | ALWAYS_ON (default SHARDED)
- max_loaded_shards / max_ram_mb
- sync_retrieval_mode: FTS_ONLY (default)
- global_heavy_job_semaphore (default 1)
- evidence_required_for_model_output (always on)
- implicit_fact_auto_approve (always off)
- explicit_fact_auto_approve (default off; 차순위)
```

미정/유저 승인(옵트인) 성격의 정책 선택은 `plan/DECISIONS_PENDING.md`에 별도로 정리합니다.
