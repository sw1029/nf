# Contracts (모듈 간 계약/인터페이스) v0

이 문서는 `plan/architecture_*.md`, `plan/TODO.md`를 기반으로 **모듈 간 계약(Contracts)** 을 정규화합니다.
각 모듈 구현 문서(`plan/modules/*.md`)는 본 문서의 타입/스펙을 참조하는 것을 기본으로 합니다.

> 목표: “구현을 시작할 수 있을 정도”의 DTO/API/Job/Event 계약을 고정한다.
> *정책(옵트인/승인 필요) 선택은 `plan/DECISIONS_PENDING.md`를 우선으로 따른다.*

---

## 0) 공통 규칙

### 0.1 ID/Path 규칙

- `ProjectID`, `DocID`, `SnapshotID`, `ChunkID`, `EpisodeID`, `JobID`, `EvidenceID`, `VerdictID`, `EntityID`, `TagID`, `FactID`는 문자열 UUID를 기본으로 한다.
- `tag_path`: `"설정/인물/주인공/나이"` 형태의 `/` 구분 경로 문자열
- `section_path`: `"설정/인물/주인공"` 형태의 `/` 구분 경로 문자열
- `span_start`, `span_end`: UTF-8 기준이 아닌 **문서 내부 “문자 인덱스(0-based)”** 를 기본으로 한다(정확한 기준은 구현 시 고정).

### 0.2 시간/버전

- `created_at`, `updated_at` 등 timestamp는 ISO-8601 UTC 문자열(예: `"2026-01-25T15:04:05Z"`)
- `schema_ver`: 프로젝트 단위 단조 증가 정수 또는 UUID(구현에서 택1). 외부 API에는 문자열로 노출.

### 0.3 오류 계약

모든 API 오류는 다음 형태를 기본으로 한다.

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "human readable",
    "details": { "field": "reason" }
  }
}
```

---

## 1) Enum/상수 (외부 계약)

### 1.1 DocumentType

- `SETTING | PLOT | CHAR | EPISODE | NOTE`

### 1.2 TagKind / SchemaType

- `TagKind`: `EXPLICIT | IMPLICIT | USER`
- `SchemaType`: `int | float | str | enum | time | loc | rel | bool | unknown`

### 1.3 FactStatus / FactSource

- `FactStatus`: `PROPOSED | APPROVED | REJECTED`
- `FactSource`: `USER | AUTO`
- 기본 정책: `AUTO` 생성 fact는 `PROPOSED` (유저 승인 필요)

### 1.4 EvidenceMatchType / EvidenceRole

- `EvidenceMatchType`: `EXACT | FUZZY | ALIAS`
- `EvidenceRole`: `SUPPORT | CONTRADICT`

### 1.5 Verdict

- `OK | VIOLATE | UNKNOWN`

### 1.6 JobType / JobStatus

- `JobType`: `INGEST | INDEX_FTS | INDEX_VEC | CONSISTENCY | RETRIEVE_VEC | SUGGEST | PROOFREAD | EXPORT`
- `JobStatus`: `NEW | QUEUED | RUNNING | SUCCEEDED | FAILED | CANCELED | PAUSED | RETRYING`

### 1.7 SuggestMode (SUGGEST)

- `LOCAL_RULE | API | LOCAL_GEN`
- 1차: `LOCAL_RULE` 구현 우선
- `LOCAL_GEN`은 분기/인터페이스만 1차, 실구현은 차순위

---

## 2) Core DTO (모듈 간 공유)

### 2.1 Project / Document / Snapshot

```json
{
  "project": { "project_id": "uuid", "name": "string", "created_at": "ts", "settings": {} },
  "document": {
    "doc_id": "uuid", "project_id": "uuid",
    "title": "string", "type": "SETTING",
    "path": "DocStore raw path",
    "head_snapshot_id": "uuid",
    "checksum": "sha256", "version": "int",
    "created_at": "ts", "updated_at": "ts"
  },
  "doc_snapshot": {
    "snapshot_id": "uuid", "project_id": "uuid", "doc_id": "uuid",
    "version": "int", "path": "DocStore snapshot path", "checksum": "sha256",
    "created_at": "ts"
  }
}
```

### 2.2 Episode / Chunk / Section (필터링/인덱싱 키)

```json
{
  "episode": { "episode_id": "uuid", "project_id": "uuid", "start_n": 1, "end_m": 3, "label": "string" },
  "chunk": {
    "chunk_id": "uuid", "project_id": "uuid",
    "doc_id": "uuid", "snapshot_id": "uuid",
    "section_path": "string", "episode_id": "uuid|null",
    "span_start": 0, "span_end": 120,
    "token_count_est": 256,
    "created_by": "AUTO|USER",
    "created_at": "ts"
  },
  "section": {
    "section_id": "uuid", "project_id": "uuid", "doc_id": "uuid", "snapshot_id": "uuid",
    "section_path": "string",
    "span_start": 0, "span_end": 1200
  }
}
```

### 2.3 TagDef / TagAssignment

```json
{
  "tag_def": {
    "tag_id": "uuid", "project_id": "uuid",
    "tag_path": "설정/인물/주인공/나이",
    "kind": "EXPLICIT",
    "schema_type": "int",
    "constraints": {}
  },
  "tag_assignment": {
    "assign_id": "uuid", "project_id": "uuid",
    "doc_id": "uuid", "snapshot_id": "uuid",
    "span_start": 10, "span_end": 20,
    "tag_path": "설정/인물/주인공/나이",
    "user_value": 17,
    "created_by": "USER|AUTO",
    "created_at": "ts"
  }
}
```

### 2.4 Entity / EntityAlias (D2)

```json
{
  "entity": {
    "entity_id": "uuid", "project_id": "uuid",
    "kind": "CHAR|LOC|ORG|OBJ|EVENT",
    "canonical_name": "string",
    "created_at": "ts"
  },
  "entity_alias": {
    "alias_id": "uuid", "project_id": "uuid", "entity_id": "uuid",
    "alias_text": "string",
    "created_by": "USER|AUTO",
    "created_at": "ts"
  }
}
```

---

## 3) Schema DTO (명시/암시, 승인 워크플로)

### 3.1 SchemaVersion / Facts

```json
{
  "schema_version": {
    "schema_ver": "string",
    "project_id": "uuid",
    "created_at": "ts",
    "source_snapshot_id": "uuid",
    "notes": "string|null"
  },
  "schema_fact": {
    "fact_id": "uuid",
    "project_id": "uuid",
    "schema_ver": "string",
    "layer": "explicit|implicit",
    "entity_id": "uuid|null",
    "tag_path": "string",
    "value": {},
    "evidence_eid": "uuid",
    "confidence": 0.0,
    "source": "USER|AUTO",
    "status": "PROPOSED|APPROVED|REJECTED"
  }
}
```

### 3.2 SchemaView (UI/정합성 기준 뷰)

`SchemaView`는 기본적으로 **APPROVED fact만** 포함하는 읽기 전용 뷰다.

```json
{
  "schema_view": {
    "project_id": "uuid",
    "schema_ver": "string",
    "facts": [ { "schema_fact": "..." } ],
    "created_at": "ts"
  }
}
```

---

## 4) Evidence / Verdict DTO

### 4.1 Evidence

```json
{
  "evidence": {
    "eid": "uuid",
    "project_id": "uuid",
    "doc_id": "uuid",
    "snapshot_id": "uuid",
    "chunk_id": "uuid|null",
    "section_path": "string",
    "tag_path": "string",
    "snippet_text": "string",
    "span_start": 0,
    "span_end": 120,
    "fts_score": 12.34,
    "match_type": "EXACT|FUZZY|ALIAS",
    "confirmed": true,
    "created_at": "ts"
  }
}
```

### 4.2 VerdictLog

```json
{
  "verdict_log": {
    "vid": "uuid",
    "project_id": "uuid",
    "input_doc_id": "uuid",
    "input_snapshot_id": "uuid",
    "schema_ver": "string",
    "segment_span": { "start": 0, "end": 50 },
    "claim_text": "string",
    "verdict": "OK|VIOLATE|UNKNOWN",
    "reliability_overall": 0.0,
    "breakdown": {
      "fts_strength": 0.0,
      "evidence_count": 0,
      "confirmed_evidence": 0,
      "model_score": 0.0
    },
    "whitelist_applied": false,
    "created_at": "ts"
  },
  "verdict_evidence_link": [
    { "vid": "uuid", "eid": "uuid", "role": "SUPPORT|CONTRADICT" }
  ]
}
```

---

## 5) Job 계약 (Queue + Events)

### 5.1 Job Submit Request

```json
{
  "type": "CONSISTENCY",
  "pid": "uuid",
  "inputs": {},
  "priority": 100,
  "params": {}
}
```

### 5.2 Job Status Response

```json
{
  "job": {
    "job_id": "uuid",
    "type": "CONSISTENCY",
    "project_id": "uuid",
    "status": "RUNNING",
    "created_at": "ts",
    "queued_at": "ts",
    "started_at": "ts",
    "finished_at": null
  }
}
```

### 5.3 Job Event (SSE/WebSocket payload)

```json
{
  "event_id": "uuid",
  "job_id": "uuid",
  "ts": "ts",
  "level": "INFO|WARN|ERROR|PROGRESS",
  "message": "string",
  "progress": 0.5,
  "metrics": { "docs_processed": 10, "mem_estimate_mb": 512 },
  "payload": {}
}
```

`payload`는 job 타입에 따라 확장 가능(예: `RETRIEVE_VEC` 결과 조각, `PROOFREAD` lint 결과 등).

---

## 6) HTTP API 계약 (Orchestrator)

### 6.1 CRUD (핵심)

- `/projects` GET/POST
- `/projects/{pid}` GET/PATCH/DELETE
- `/projects/{pid}/documents` GET/POST
- `/projects/{pid}/documents/{did}` GET/PATCH/DELETE
- `/projects/{pid}/episodes` GET/POST
- `/projects/{pid}/tags` GET/POST
- `/projects/{pid}/schema` GET
- `/projects/{pid}/whitelist` POST/DELETE

### 6.2 Schema 승인(필수: D3)

예시(구현 시 확정):

- `/projects/{pid}/schema/facts` GET (filters: status/source/layer)
- `/projects/{pid}/schema/facts/{fact_id}` GET
- `/projects/{pid}/schema/facts/{fact_id}` PATCH `{ "status": "APPROVED|REJECTED" }`

### 6.3 Query (sync)

- `/query/retrieval` POST (FTS-only)
- `/query/evidence/{eid}` GET
- `/query/verdicts` POST

### 6.3.1 RetrievalRequest/Result (DTO)

```json
{
  "retrieval_request": {
    "pid": "uuid",
    "query": "string",
    "filters": { "tag_path": "string|null", "section": "string|null", "episode": "uuid|null" },
    "k": 10
  },
  "retrieval_result": {
    "source": "fts|vector",
    "score": 0.0,
    "evidence": { "evidence": "..." }
  }
}
```

### 6.4 Jobs (async + streaming)

- `/jobs` POST
- `/jobs/{jid}` GET
- `/jobs/{jid}/cancel` POST
- `/jobs/{jid}/events` GET (SSE/WebSocket)

---

## 7) Proofread(문법) / Lint 결과 계약 (D1)

Proofread는 1차에서 “실시간 표시”가 기본이며, 결과는 UI 내부 렌더링을 목표로 한다.
batch job(`PROOFREAD`)은 차순위로 확장 가능하다.

```json
{
  "lint_item": {
    "span_start": 10,
    "span_end": 20,
    "rule_id": "string",
    "severity": "INFO|WARN|ERROR",
    "message": "string",
    "suggestion": "string|null"
  }
}
```

---

## 8) Suggestion 계약 (SUGGEST)

```json
{
  "suggestion": {
    "suggestion_id": "uuid",
    "project_id": "uuid",
    "mode": "LOCAL_RULE|API|LOCAL_GEN",
    "text": "string",
    "citations": [
      { "doc_id": "uuid", "snapshot_id": "uuid", "tag_path": "string", "section_path": "string", "snippet_text": "string" }
    ],
    "created_at": "ts"
  }
}
```

---

## 9) 구현 언어/런타임에 대한 최소 합의

- 내부 모듈 경계는 `nf_shared.protocol.dtos` (dataclasses 또는 pydantic)로 표준화한다.
- HTTP 경계는 JSON 계약을 우선으로 하고, 내부 타입으로 변환한다.
