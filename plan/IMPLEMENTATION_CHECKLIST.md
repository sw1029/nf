# 구현 개요/구현 순서 통제 (정렬된 TODO 체크리스트)

이 문서는 `plan/*` 설계 문서들을 기반으로 **구현 순서를 Phase 단위로 고정**하고,
진행 상황을 **체크리스트 형식**으로 통제한다.

참조:

- `plan/user_request.md` (요구사항 원문/목적)
- `plan/contracts.md` (계약/DTO/API/Job/Event)
- `plan/architecture_1.md`, `plan/architecture_2.md` (프로세스/잡 흐름)
- `plan/modules/*.md` (모듈별 MoSCoW 구현 계획)
- `plan/loopback_web_ui.md` (개발용 임시 웹 UI)

---

## 0) 운영 규칙(통제)

* ☐ 각 모듈 문서는 “구현 순서(Phase)”를 본 문서와 동일하게 유지한다.
* ☐ 요구사항(목적) 원문은 `plan/user_request.md`이며, 본 문서는 이를 “구현 관점”으로 Phase에 분해한다.
* ☐ 정책 선택(D1~D5)은 `plan/DECISIONS_PENDING.md`를 1차 기준으로 하며, Phase 순서로 우회하지 않는다.
* ☐ 실제 테스트는 conda의 `nf` 환경에서 수행한다.
* ☐ Phase 완료 기준:
  - 최소 1개의 종단 간 시나리오가 **오케스트레이터 → 잡 → SSE**로 관찰 가능
  - (가능하면) 해당 범위에 대한 pytest 스모크/단위 테스트 추가

---

## 1) Phase 개요(요약)

- Phase 00: 계약/공통 규격(nf-shared) 고정
- Phase 10: 오케스트레이터(루프백 HTTP) + 스토리지 기본 골격
- Phase 20: 워커(잡 실행기) + 큐/리스/이벤트 골격
- Phase 30: 문서 저장/청크 + FTS 인덱싱/동기 검색(FTS-only)
- Phase 40: 개발용 루프백 웹 UI(임시 디버그 UI)
- Phase 50: 태그/엔티티/스키마(INGEST) + 승인 워크플로(D2/D3)
- Phase 60: 정합성(CONSISTENCY) + 판정/근거 로그 + 화이트리스트
- Phase 70: 벡터 인덱스/검색(비동기) + `RETRIEVE_VEC` 스트리밍(D5)
- Phase 80: 제안(LOCAL_RULE 우선) + 모델 게이트웨이 옵션(D4)
- Phase 90: 내보내기 + 문법 교정(차순위 포함) (D1)
- Phase 95: 데스크톱 UI(nf-desktop) 제품 흐름 통합/마감

---

## 1.1) `user_request.md` 요구사항 ↔ Phase 매핑(요약)

* 1) 설정/플롯/등장인물 문서 + 태깅: Phase 50(데이터/스키마) + Phase 95(제품 UI)
* 2) 인덱싱/임베딩(RAG): Phase 30(FTS) + Phase 70(Vector)
* 3) 정합성 검토(근거 강제/unknown 허용/화이트리스트): Phase 60
* 4) 문법 교정(강도 조절; 규칙 기반 우선): Phase 90/95
* 5) 자간/줄간격(레이아웃 설정): Phase 95
* 6) 개선 제안(LOCAL_RULE 우선, API opt-in, LOCAL_GEN 차순위): Phase 80
* 7) 내보내기(txt/docx): Phase 90
* 8) 에피소드 청크 구성: Phase 30(청크/범위) + Phase 95(제품 UI 범위 지정)
* 9) 규칙 기반 우선 + 경량 로컬 AI(차순위): Phase 50/60/80에 분산(정책은 D1~D5 준수)
* 10~11) 로컬/원격 모델 분리 + opt-in: Phase 80(+ Phase 60 L3는 선택 게이트)
* 12) 3단 강제 근거화(evidence_required): Phase 60(핵심), Phase 80(모델 경계)

---

## 2) 구현 순서(체크리스트)

### Phase 00 — 계약/공통 규격 고정

* ☑ `modules/nf_shared/` DTO/Enum/직렬화/오류/설정 최소 구현(계약 v0)
* ☑ 계약 스모크 테스트 정규화(예: `tests/test_nf_shared_protocol.py` 등)
* ☑ project_id 명칭 통일 + “FTS-only vs 벡터 잡” 계약 표기 불일치 제거

관련 문서:

- `plan/contracts.md`
- `plan/modules/nf_shared.md`

---

### Phase 10 — 오케스트레이터 + 스토리지 기본 골격

* ☑ 루프백 HTTP 서버 구동 + 표준 오류 응답(AppError) 적용
* ☑ 프로젝트 DB(SQLite) 스키마/마이그레이션 최소 도입
* ☑ `/health`, `/projects` CRUD 최소 구현
* ☑ `/jobs` submit/status/cancel + `/jobs/{jid}/events`(SSE) 최소 구현
* ☑ 정책/보안 최소:
  - loopback 고정
  - (권장) 로컬 토큰(옵션) + 비활성 기본값

관련 문서:

- `plan/modules/nf_orchestrator.md`
- `plan/contracts.md` (HTTP API / Jobs)

---

### Phase 20 — Workers(Job Runner) + Queue/Events 골격

* ☑ `job_queue` 폴링/리스/하트비트/취소 플로우 구현
* ☑ `job_event` 기록/스트리밍(Orchestrator SSE와 연결) 골격
* ☑ “실행기 등록/디스패치” 구조 확립(타입별 handler)

관련 문서:

- `plan/modules/nf_workers.md`
- `plan/architecture_2.md` (job_queue/job_event 상태 머신)

---

### Phase 30 — 문서 저장/Chunk + FTS 인덱싱/Sync Retrieval

* ☑ 문서 저장(원문/raw + snapshot) 최소 구현
* ☑ Chunk 생성(span) 최소 구현(FTS/Vector 공통 키 확보)
* ☑ `INDEX_FTS` job 구현 + 결과 이벤트 출력
* ☑ Sync Retrieval(FTS-only) 구현: `/query/retrieval` POST
* ☑ evidence 조회(`/query/evidence/{eid}`) 최소 구현

관련 문서:

- `plan/modules/nf_schema.md` (Chunk/Section)
- `plan/modules/nf_retrieval.md` (FTS)
- `plan/modules/nf_orchestrator.md` (documents/query)

---

### Phase 40 — 개발용 루프백 Web UI(임시)

* ☐ `/_debug` 임시 UI 제공(기본 off)
* ☐ Jobs submit + SSE viewer(타임라인/프로그레스/JSON payload) 구현
* ☐ Retrieval(FTS-only) 폼 + 결과 렌더 구현
* ☐ 테스트 토글/fixture/리셋(강력 경고) 최소 구현

관련 문서:

- `plan/loopback_web_ui.md`

---

### Phase 50 — 태그/엔티티/스키마(INGEST) + 승인 워크플로(D2/D3)

* ☑ tag_def/tag_assignment CRUD 최소 구현(스키마 생성 입력)
* ☑ entity/entity_alias CRUD 최소 구현(D2 옵션2 우선)
* ☑ `INGEST` job 최소 구현:
  - schema_version 생성
  - AUTO fact는 `PROPOSED`(D3)
* ☑ schema view / facts list / approve(PATCH) 워크플로 최소 구현

관련 문서:

- `plan/modules/nf_schema.md`
- `plan/modules/nf_orchestrator.md` (schema/entities/tags)

---

### Phase 60 — 정합성(CONSISTENCY) + 로그/화이트리스트

* ☑ `CONSISTENCY` job 최소 구현:
  - Segment/Claim → Evidence(FTS-first) → Judge(L1/L2) → VerdictLog 저장
* ☑ verdict/evidence 링크 저장 + 조회(`/query/verdicts` 등) 최소 구현
* ☑ whitelist_item 저장/적용(재경고 억제) 최소 구현

관련 문서:

- `plan/modules/nf_consistency.md`
- `plan/modules/nf_orchestrator.md` (query/whitelist)

---

### Phase 70 — Vector 인덱스/검색 + `RETRIEVE_VEC` 스트리밍(D5)

* ☑ `INDEX_VEC` job: shard build + manifest 갱신(최소)
* ☑ `RETRIEVE_VEC` job: 결과를 이벤트로 페이지/청크 스트리밍(D5)
* ☑ shard 로드/언로드 + 리소스 상한(최소) 도입

관련 문서:

- `plan/modules/nf_retrieval.md` (Vector)
- `plan/modules/nf_workers.md` (retrieve_vec_job/index_vec_job)

---

### Phase 80 — Suggest(LOCAL_RULE 우선) + Model Gateway 옵션(D4)

* ☑ `SUGGEST` job: `LOCAL_RULE` 최소 구현(근거 묶기/요약/템플릿)
* ☑ `mode=API`는 opt-in으로만 실행 + 키/레이트리밋/회로차단 최소
* ☑ `LOCAL_GEN`은 “분기/인터페이스만”(차순위, 실구현 보류)

관련 문서:

- `plan/modules/nf_model_gateway.md`
- `plan/modules/nf_workers.md` (suggest_job)

---

### Phase 90 — Export + Proofread(차순위 포함)

* ☑ `EXPORT` job: txt/docx 내보내기 최소 구현
* ☑ Proofread(rule-base) 최소 구현(1차는 실시간 표시가 기본; batch job은 차순위)

관련 문서:

- `plan/modules/nf_export.md`
- `plan/modules/nf_desktop.md` (Proofread UI, Layout Settings)

---

### Phase 95 — Desktop UI(nf-desktop) 제품 흐름 통합/마감

* ☐ Editor/Range/Tagging 기본 플로우 구현(최소)
* ☐ Job Panel + SSE 스트리밍(진행률/취소/재시도) 제품 수준 UX 최소 확보
* ☐ Retrieval UI:
  - sync는 FTS-only
  - Vector 확장은 `RETRIEVE_VEC` job + 스트리밍(D5)
* ☐ Schema Review UI(AUTO=PROPOSED 승인/거절/보류) (D3)
* ☐ Result Panel(Verdict+Evidence+Breakdown) 렌더링 + unknown 사유 표준 문구(권장)
* ☐ Export 트리거(txt/docx) + 산출물 접근
* ☐ Proofread(rule-base 실시간 표시) + Layout Settings(자간/줄간격) 분리(D1)

관련 문서:

- `plan/modules/nf_desktop.md`
