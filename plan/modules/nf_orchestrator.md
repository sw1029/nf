# nf-orchestrator (핵심 API) — MoSCoW 구현 계획

오케스트레이터는 로컬(루프백) API 서버로서, CRUD/쿼리/잡/스트리밍을 제공하고 정책을 강제한다.

참조:

- `plan/contracts.md`
- `plan/architecture_2.md`
- `plan/DECISIONS_PENDING.md` (D1~D5 반영 완료)

구현 순서(Phase, 전체 로드맵: `plan/IMPLEMENTATION_CHECKLIST.md`):

테스트는 conda의 `nf` 환경에서 수행한다.

- Phase 10: 루프백 HTTP + 스토리지 + 잡/SSE 골격
- Phase 30: 문서/쿼리(FTS-only) 동작 확보
- Phase 50: 태그/엔티티/스키마 승인 워크플로(D2/D3)
- Phase 60: 판정/근거/화이트리스트 조회·저장(정합성 결과 관찰)
- Phase 70: 벡터 잡(`INDEX_VEC`/`RETRIEVE_VEC`) 중계(D5)
- Phase 80: 제안 잡 중계 + 원격 API 옵트인 게이트(D4)
- Phase 90: 내보내기 잡 중계 + 산출물 접근

---

# [M] 필수 — 1차 배포(MVP+안정화)

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

## 1) HTTP API 표면(계약 기준)

* ☑ 루프백 HTTP 서버(기본) + JSON
* ☑ `/health` (준비/생존)
* ☑ CRUD
  - ☑ `/projects` GET/POST
  - ☑ `/projects/{project_id}` GET/PATCH/DELETE
  - ☑ `/projects/{project_id}/documents` GET/POST
  - ☑ `/projects/{project_id}/documents/{did}` GET/PATCH/DELETE
  - ☑ `/projects/{project_id}/episodes` GET/POST
  - ☑ `/projects/{project_id}/tags` GET/POST
  - ☑ `/projects/{project_id}/entities` GET/POST
  - ☑ `/projects/{project_id}/entities/{eid}/aliases` GET/POST/DELETE
  - ☑ `/projects/{project_id}/whitelist` POST/DELETE
* ☑ 스키마 뷰 + 승인(D3)
  - `/projects/{project_id}/schema` GET (현재 승인된 스키마 뷰)
  - `/projects/{project_id}/schema/facts` GET (filters: status/source/layer)
  - `/projects/{project_id}/schema/facts/{fact_id}` GET
  - `/projects/{project_id}/schema/facts/{fact_id}` PATCH `{status: APPROVED|REJECTED}`
* ☑ 쿼리(동기)
  - `/query/retrieval` POST (**FTS-only**)
  - `/query/evidence/{eid}` GET
  - `/query/verdicts` POST
* ☑ 잡(비동기)
  - `/jobs` POST
  - `/jobs/{jid}` GET
  - `/jobs/{jid}/cancel` POST
  - `/jobs/{jid}/events` GET (SSE 기본)

## 2) 잡 제출 규격(필수)

* ☑ `JobType` 지원:
  - `INGEST`, `INDEX_FTS`, `INDEX_VEC`, `CONSISTENCY`, `RETRIEVE_VEC`, `SUGGEST`, `PROOFREAD`, `EXPORT`
* ☑ `payload_json` 스키마를 타입별로 고정(최소)
  - `INGEST`: `{doc_id, snapshot_id?}`
  - `INDEX_FTS`: `{scope: doc_id|episode_range|global, snapshot_id?}`
  - `INDEX_VEC`: `{scope, shard_policy}`
  - `CONSISTENCY`: `{input_doc_id, input_snapshot_id, range, schema_ver?}`
  - `RETRIEVE_VEC`: `{query, filters, k}`
  - `SUGGEST`: `{range, mode: LOCAL_RULE|API|LOCAL_GEN, citations_required: true}`
  - `PROOFREAD`: `{doc_id, snapshot_id, range?}` (차순위: 배치)
  - `EXPORT`: `{range, format, include_meta}`

## 3) 스트리밍(SSE) 규격

* ☑ `JobEvent` 계약 준수(`plan/contracts.md`)
* ☑ `RETRIEVE_VEC`는 결과를 `JobEvent.payload`로 분할 송신 가능
  - 페이로드 예: `{results: [RetrievalResult...], page: n}`

## 4) 정책 강제(필수)

* ☑ `global_heavy_job_semaphore`로 무거운 잡 동시성 제한
* ☑ `sync_retrieval_mode=FTS_ONLY` 강제(D5)
* ☑ `explicit_fact_auto_approve=false` 기본 강제(D3 차순위 스위치)
* ☑ `enable_local_generator=false` 기본(D4 차순위)

## 5) 서비스 계층(최소 계약)

* ☑ 컨트롤러는 “검증/라우팅”만, 서비스가 도메인 로직 담당
* ☑ 레포지토리 계층으로 DB I/O 캡슐화

## 6) 테스트(pytest)

* ☑ `tests/test_nf_orchestrator_contracts.py`: 서비스 프로토콜(Project/Schema/Job) 계약 스모크
* ☐ (차순위) API 스모크(핸들러 임포트 + 요청 검증)
* ☐ (차순위) 잡 제출 검증 단위 테스트
* ☐ (차순위) 스키마 승인 워크플로 단위 테스트

---

# [S] 권장 — 권장

* ☑ OpenAPI 스펙 생성(로컬용)
* ☑ SSE 재연결 지원(Last-Event-ID)
* ☑ 로컬 토큰(옵션, `NF_ORCHESTRATOR_TOKEN`) 및 루프백 고정 강화

---

# [C] 선택 — 여유 시

* ☐ gRPC/NamedPipe 지원(Windows)
* ☐ 잡 우선순위/큐 다단계(인터랙션 우선)

---

# [W] 현재 제외

* ☐ 멀티 디바이스/클라우드 동기화

---

## 계약 인터페이스(요약)

- 인바운드: HTTP JSON → `nf_shared.protocol.dtos`
- 아웃바운드: JobQueue row + `JobEvent` 스트리밍
- 동기 쿼리는 `FTS-only` 계약을 준수하며, 벡터는 `RETRIEVE_VEC` 잡으로만 노출한다.

---

## 계약 인터페이스(상세; 구현 기준)

### A) 컨트롤러 → 서비스 (Python 호출 규격)

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
