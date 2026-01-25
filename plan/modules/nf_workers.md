# nf-workers (Job Runner) — MoSCoW 구현 계획

nf-workers는 오케스트레이터가 enqueue한 작업을 실행하고, lease/heartbeat/cancel을 처리하며, job_event로 스트리밍한다.

참조:

- `plan/contracts.md`
- `plan/architecture_2.md` (job_queue/job_event 상태 머신)

---

# [M] Must — 1차 배포(MVP+안정화)

## 0) 패키지/폴더 구조(placeholder 기준)

```text
modules/nf_workers/
  __init__.py
  runner.py
  queue/
    interface.py
    sqlite_queue.py
  jobs/
    ingest_job.py
    index_fts_job.py
    index_vec_job.py
    consistency_job.py
    retrieve_vec_job.py
    suggest_job.py
    proofread_job.py
    export_job.py
  runtime/
    resource_guard.py
    process_pool.py
```

## 1) Queue/Lease/Heartbeat 계약

* ☐ `job_queue` 폴링 → lease 획득(compare-and-swap) → RUNNING
* ☐ heartbeat로 lease 연장(`lease_expires_at`)
* ☐ cancel flag(`cancel_requested`) 주기 체크
* ☐ 크래시 복구: lease 만료 job은 QUEUED로 재전환

## 2) Job 실행기 계약(타입별)

### 2.1 INGEST

* ☐ 입력: `{doc_id, snapshot_id?}`
* ☐ 동작: 문서 파싱/태깅/정규화/identity → schema_version + facts 기록
* ☐ 정책: `AUTO` fact는 `PROPOSED`로 저장(D3)
* ☐ 출력: `job_event(payload={schema_ver, proposed_fact_count})`

### 2.2 INDEX_FTS

* ☐ 입력: `{scope, snapshot_id?}`
* ☐ 동작: chunk 단위로 FTS 인덱스 갱신(증분)
* ☐ 출력: `job_event(payload={chunks_indexed})`

### 2.3 INDEX_VEC

* ☐ 입력: `{scope, shard_policy}`
* ☐ 동작: shard 빌드 + manifest 갱신
* ☐ 리소스: 메모리 추정 기반 throttling(최소)

### 2.4 CONSISTENCY

* ☐ 입력: `{input_doc_id, input_snapshot_id, range, schema_ver?}`
* ☐ 동작: Segment → Retrieval(FTS + 필요 시 Vector) → Judge(3 layers) → Verdict log
* ☐ 출력: `job_event(payload={vid_count, violate_count, unknown_count})`

### 2.5 RETRIEVE_VEC (D5)

* ☐ 입력: `{query, filters, k}`
* ☐ 동작: Vector shards 검색(+ 선택 rerank) 후 결과를 이벤트로 스트리밍
* ☐ 출력: `job_event(payload={results:[...], page:n})`

### 2.6 SUGGEST (D4)

* ☐ 입력: `{range, mode}`
* ☐ 1차: `mode=LOCAL_RULE` 구현(근거 묶기/요약/템플릿)
* ☐ `mode=API`는 옵션(사용자 opt-in)으로만 실행
* ☐ `mode=LOCAL_GEN`은 분기만(차순위)
* ☐ 출력: `job_event(payload={suggestion_id, citations:[...]})`

### 2.7 PROOFREAD (D1)

* ☐ 1차는 “실시간 표시”가 기본이므로 batch job은 최소 구현 또는 스텁
* ☐ 차순위: 대용량 문서 범위 교정 결과를 이벤트로 스트리밍

### 2.8 EXPORT

* ☐ 입력: `{range, format, include_meta}`
* ☐ 출력: artifact path + 메타

## 3) 리소스 가드(최소)

* ☐ per-job soft guard: 메모리/CPU 압력 시 PAUSE 또는 FAILSAFE
* ☐ heavy job 동시 실행은 orchestrator semaphore를 전제로 함

## 4) 테스트(pytest)

* ☐ `tests/test_nf_workers_contracts.py`: JobHandler/JobContext 계약 스모크
* ☐ (차순위) queue 상태 머신(unit)
* ☐ (차순위) 각 job 타입의 payload validation(unit)
* ☐ (차순위) cancel/lease 만료 복구 시나리오(unit)

---

# [S] Should — 권장

* ☐ job 이벤트에 처리량/ETA 유사 지표 제공
* ☐ job 실행기별 별도 프로세스 풀 분리

---

# [C] Could — 여유 시

* ☐ 워커 자동 재시작/감시(로컬 단일기기용)

---

# [W] Won’t (now)

* ☐ 분산 큐/멀티 호스트 워커

---

## 계약 인터페이스(상세; 구현 기준)

### A) JobHandler 표준

```python
class JobHandler(Protocol):
    job_type: JobType
    def run(self, ctx: JobContext) -> None: ...

class JobContext(Protocol):
    job_id: JobID
    project_id: ProjectID
    payload: dict
    def emit(self, event: JobEvent) -> None: ...
    def check_cancelled(self) -> bool: ...
```

### B) Event 스트리밍 규칙

- PROGRESS 이벤트는 `progress ∈ [0,1]`을 유지
- 결과가 큰 경우(`RETRIEVE_VEC` 등) `payload`를 페이지/청크로 분할 송신
