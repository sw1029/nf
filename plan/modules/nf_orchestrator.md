# nf-orchestrator (Core API) — MoSCoW 구현 계획

오케스트레이터는 로컬(loopback) API 서버로서, CRUD/Query/Jobs/Streaming을 제공하고 정책을 강제한다.

참조:

- `plan/contracts.md`
- `plan/architecture_2.md`
- `plan/DECISIONS_PENDING.md` (D1~D5 반영 완료)

---

# [M] Must — 1차 배포(MVP+안정화)

## 0) 패키지/폴더 구조(placeholder 기준)

```text
modules/nf_orchestrator/
  __init__.py
  main.py
  controllers/
    health.py
    projects.py
    documents.py
    episodes.py
    tags.py
    schema.py
    entities.py
    whitelist.py
    query.py
    jobs.py
    export.py
  services/
    project_service.py
    document_service.py
    episode_service.py
    tag_service.py
    entity_service.py
    schema_service.py
    whitelist_service.py
    query_service.py
    job_service.py
    export_service.py
  policies/
    semaphore.py
    circuit_breaker.py
    rate_limit.py
  storage/
    db.py
    repos/
      project_repo.py
      document_repo.py
      schema_repo.py
      job_repo.py
      evidence_repo.py
```

## 1) HTTP API 표면(contracts 기준)

* ☐ Loopback HTTP 서버(기본) + JSON
* ☐ `/health` (readiness/liveness)
* ☐ CRUD
  - `/projects` GET/POST
  - `/projects/{pid}` GET/PATCH/DELETE
  - `/projects/{pid}/documents` GET/POST
  - `/projects/{pid}/documents/{did}` GET/PATCH/DELETE
  - `/projects/{pid}/episodes` GET/POST
  - `/projects/{pid}/tags` GET/POST
  - `/projects/{pid}/entities` GET/POST
  - `/projects/{pid}/entities/{eid}/aliases` GET/POST/DELETE
  - `/projects/{pid}/whitelist` POST/DELETE
* ☐ Schema view + 승인(D3)
  - `/projects/{pid}/schema` GET (현재 승인된 스키마 뷰)
  - `/projects/{pid}/schema/facts` GET (filters: status/source/layer)
  - `/projects/{pid}/schema/facts/{fact_id}` GET
  - `/projects/{pid}/schema/facts/{fact_id}` PATCH `{status: APPROVED|REJECTED}`
* ☐ Query (sync)
  - `/query/retrieval` POST (**FTS-only**)
  - `/query/evidence/{eid}` GET
  - `/query/verdicts` POST
* ☐ Jobs (async)
  - `/jobs` POST
  - `/jobs/{jid}` GET
  - `/jobs/{jid}/cancel` POST
  - `/jobs/{jid}/events` GET (SSE 기본)

## 2) Job 제출 규격(필수)

* ☐ `JobType` 지원:
  - `INGEST`, `INDEX_FTS`, `INDEX_VEC`, `CONSISTENCY`, `RETRIEVE_VEC`, `SUGGEST`, `PROOFREAD`, `EXPORT`
* ☐ `payload_json` 스키마를 타입별로 고정(최소)
  - `INGEST`: `{doc_id, snapshot_id?}`
  - `INDEX_FTS`: `{scope: doc_id|episode_range|global, snapshot_id?}`
  - `INDEX_VEC`: `{scope, shard_policy}`
  - `CONSISTENCY`: `{input_doc_id, input_snapshot_id, range, schema_ver?}`
  - `RETRIEVE_VEC`: `{query, filters, k}`
  - `SUGGEST`: `{range, mode: LOCAL_RULE|API|LOCAL_GEN, citations_required: true}`
  - `PROOFREAD`: `{doc_id, snapshot_id, range?}` (차순위: batch)
  - `EXPORT`: `{range, format, include_meta}`

## 3) Streaming(SSE) 규격

* ☐ `JobEvent` contract 준수(`plan/contracts.md`)
* ☐ `RETRIEVE_VEC`는 결과를 `JobEvent.payload`로 분할 송신 가능
  - payload 예: `{results: [RetrievalResult...], page: n}`

## 4) 정책 강제(필수)

* ☐ `global_heavy_job_semaphore`로 heavy job 동시성 제한
* ☐ `sync_retrieval_mode=FTS_ONLY` 강제(D5)
* ☐ `explicit_fact_auto_approve=false` 기본 강제(D3 차순위 스위치)
* ☐ `enable_local_generator=false` 기본(D4 차순위)

## 5) 서비스 계층(최소 계약)

* ☐ Controller는 “검증/라우팅”만, Service가 도메인 로직 담당
* ☐ Repository 계층으로 DB I/O 캡슐화

## 6) 테스트(pytest)

* ☐ `tests/test_nf_orchestrator_contracts.py`: Service Protocol(Project/Schema/Job) 계약 스모크
* ☐ (차순위) API 스모크(핸들러 import + request validation)
* ☐ (차순위) Job submit validation unit tests
* ☐ (차순위) Schema 승인 워크플로 unit tests

---

# [S] Should — 권장

* ☐ OpenAPI 스펙 생성(로컬용)
* ☐ SSE reconnect 지원(Last-Event-ID)
* ☐ 로컬 토큰(옵션) 및 loopback 고정 강화

---

# [C] Could — 여유 시

* ☐ gRPC/NamedPipe 지원(Windows)
* ☐ Job priority/큐 다단계(인터랙션 우선)

---

# [W] Won’t (now)

* ☐ 멀티 디바이스/클라우드 동기화

---

## 계약 인터페이스(요약)

- Inbound: HTTP JSON → `nf_shared.protocol.dtos`
- Outbound: JobQueue row + `JobEvent` streaming
- Sync Query는 `FTS-only` 계약을 준수하며, Vector는 `RETRIEVE_VEC` job으로만 노출한다.

---

## 계약 인터페이스(상세; 구현 기준)

### A) Controller → Service (Python 호출 규격)

```python
class ProjectService(Protocol):
    def list_projects(self) -> list[Project]: ...
    def create_project(self, name: str, settings: dict) -> Project: ...

class SchemaService(Protocol):
    def get_schema_view(self, project_id: ProjectID) -> SchemaView: ...
    def list_facts(self, project_id: ProjectID, *, status: FactStatus | None) -> list[SchemaFact]: ...
    def set_fact_status(self, project_id: ProjectID, fact_id: FactID, status: FactStatus) -> SchemaFact: ...

class JobService(Protocol):
    def submit(self, project_id: ProjectID, job_type: JobType, inputs: dict, params: dict) -> Job: ...
    def cancel(self, job_id: JobID) -> None: ...
    def get(self, job_id: JobID) -> Job: ...
```

`SchemaView`는 “승인된(APPROVED) fact만”을 기본으로 렌더링한다(정합성/L1 비교 기준).

### B) HTTP → DTO 변환(최소)

- Request validation 실패 시: `VALIDATION_ERROR`
- 존재하지 않는 리소스: `NOT_FOUND`
- 정책 위반(예: sync vector 요청): `POLICY_VIOLATION`
