# 구현 개요/구현 순서 통제 (정렬된 TODO 체크리스트)

이 문서는 `plan/*` 설계 문서들을 기반으로 **구현 순서를 Phase 단위로 고정**하고,
진행 상황을 **체크리스트 형식**으로 통제한다.

참조:

- `plan/user_request.md` (요구사항 원문/목적)
- `plan/contracts.md` (계약/DTO/API/Job/Event)
- `plan/architecture_1.md`, `plan/architecture_2.md` (프로세스/잡 흐름)
- `plan/modules/*.md` (모듈별 MoSCoW 구현 계획)
- `plan/loopback_web_ui.md` (개발용 임시 웹 UI)

> 표기 규칙: ☐ TODO / ☑ Done / ◐ Partial(스텁/의도 미적용)

> 참고: UI 구현은 보류한다. (제품 UI/디버그 UI의 스타일·UX 고도화는 본 작업 범위에서 제외)

---

## 0) 운영 규칙(통제)

* ☐ 각 모듈 문서는 “구현 순서(Phase)”를 본 문서와 동일하게 유지한다.
* ☐ 요구사항(목적) 원문은 `plan/user_request.md`이며, 본 문서는 이를 “구현 관점”으로 Phase에 분해한다.
* ☐ 정책 선택(D1~D8)은 `plan/DECISIONS_PENDING.md`를 1차 기준으로 하며, Phase 순서로 우회하지 않는다.
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
- Phase 62: CONSISTENCY/FTS 성능 안정화(contract 유지)
- Phase 70: 벡터 인덱스/검색(비동기) + `RETRIEVE_VEC` 스트리밍(D5)
- Phase 72: Graph Hybrid 옵션 경로(기본 off)
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
* 8) 에피소드/시점/인물 chunk 구성(+ 세계관 타임라인): Phase 30(청크/FTS) + Phase 50(엔티티/타임라인 문서) + Phase 95(요청/검토 UI)
* 9) 규칙 기반 우선 + 경량 로컬 AI(차순위): Phase 50/60/80에 분산(정책은 D1~D8 준수)
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
* ☑ Orchestrator+Worker 동시 기동 런처 제공: `run_local_stack.py`

관련 문서:

- `plan/modules/nf_workers.md`
- `plan/architecture_2.md` (job_queue/job_event 상태 머신)

---

### Phase 30 — 문서 저장/Chunk + FTS 인덱싱/Sync Retrieval

* ☑ 문서 저장(원문/raw + snapshot) 최소 구현
* ☑ Chunk 생성(span) 최소 구현(FTS/Vector 공통 키 확보)
* ☑ Episode chunk 구성(n~m 구간): chunk에 episode_id 할당 + 인덱스로 전파(episode 필터 동작 보장)
* ☑ tag_path 전파: tag_assignment(span overlap) 기반으로 chunk/FTS/vector/evidence에 tag_path 채우기(인용 품질 확보)
* ☑ (추가 요구) 사용자 요청 시 시점/인물 chunk group 메타 생성(1차 제안) + Retrieval 필터(entity_id/time_key/timeline_idx) 최소 지원
* ☑ `INDEX_FTS` job 구현 + 결과 이벤트 출력 (snapshot 단위 replace; tag_path/episode 메타 전파 포함)
* ☑ Sync Retrieval(FTS-only) 구현: `/query/retrieval` POST (tag_path/section/episode 필터 지원)
* ☑ evidence 조회(`/query/evidence/{eid}`) 최소 구현

관련 문서:

- `plan/modules/nf_schema.md` (Chunk/Section)
- `plan/modules/nf_retrieval.md` (FTS)
- `plan/modules/nf_orchestrator.md` (documents/query)

---

### Phase 40 — 개발용 루프백 Web UI(임시)

* ☑ `/_debug` 임시 UI 제공(기본 off)
* ☑ Jobs submit + SSE viewer(타임라인/프로그레스/JSON payload) 구현
* ☑ Retrieval(FTS-only) 폼 + 결과 렌더 구현 (tag_path/episode 메타 포함)
* ☑ Layout 프리뷰: 자간/행간 + 스타일(배경/폰트/크기/여백) + localStorage 유지
* ◐ Proofread 프리뷰: PROOFREAD 잡 결과(lint_items)를 underline/tooltip 형태로 표시 (강도 조절/제품 UI 실시간 연동은 차순위)
* ☑ 테스트 토글/fixture/리셋(강력 경고) 최소 구현

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
* ☑ (추가 요구) 세계관 타임라인 문서 + timeline_event(상대 time_key 우선) 생성/승인 최소 구현

관련 문서:

- `plan/modules/nf_schema.md`
- `plan/modules/nf_orchestrator.md` (schema/entities/tags)

---

### Phase 60 — 정합성(CONSISTENCY) + 로그/화이트리스트

* ☑ `CONSISTENCY` job 최소 구현:
  - Segment/Claim → Evidence(FTS-first) → Judge(L1/L2) → VerdictLog 저장
* ☑ verdict/evidence 링크 저장 + 조회(`/query/verdicts` list + `/query/verdicts/{vid}` detail) 최소 구현
* ☑ whitelist_item 저장 + verdict_log.whitelist_applied 플래그 재계산(표기/억제 UX는 차순위) (지문 저장 + scope(global/doc) 적용)
* ☑ verdict 상세 조회: verdict_log ↔ verdict_evidence_link ↔ evidence를 묶어 evidence[]/role까지 반환
* ☑ verdict_log에 claim_fingerprint(또는 segment_fingerprint) 저장 (whitelist/ignore 연계 및 재경고 억제)
* ☑ ignore_item 저장 + API + 엔진 연동(정합성/제안 재경고 억제; 제품 UI는 차순위)

관련 문서:

- `plan/modules/nf_consistency.md`
- `plan/modules/nf_orchestrator.md` (query/whitelist)

---

### Phase 62 — CONSISTENCY/FTS 성능 안정화(contract 유지)

* ☑ Must: claim 단위 retrieval 경로에서 대량 `IN(doc_ids/snapshot_ids)` 필터 제거(project 범위 고정)
* ☑ Must: fact 선형 스캔 제거(fact index: `(slot_key, entity_id|*)`)
* ☑ Must: claim text 정규화 기반 job-scope LRU 캐시(기본 256)
* ☑ Must: FTS adaptive fetch/refill(`max(30, k*6)` 시작, 증분 확장, 상한 240)
* ☑ Must: `chunks(project_id, chunk_id)` 보조 인덱스 추가 + FTS insert batch화
* ◐ Partial: DS-200 `consistency_p95 <= 5.0s` (대체로 접근, 조건별 편차 있음)
* ◐ Partial: DS-800 `consistency_p95 <= 6.0s` (최신 7.6s로 미달)
* ◐ Partial: DS-200 `retrieval_fts_p95 <= 300ms`, DS-800 `<= 450ms` (최신 634ms로 미달)

DoD(테스트 포함):
* ☑ `pytest -q tests/e2e/test_global_context_detection.py` 회귀 0
* ☑ `pytest -q -m "not soak"` 회귀 0
* ◐ `run_pipeline_bench.py` 200/800 측정 결과에서 `consistency_p95` 및 `retrieval_fts_p95` 중간 게이트 충족

관련 문서:

- `plan/modules/nf_consistency.md`
- `plan/modules/nf_retrieval.md`
- `plan/modules/nf_orchestrator.md`

---

### Phase 70 — Vector 인덱스/검색 + `RETRIEVE_VEC` 스트리밍(D5)

* ☑ `INDEX_VEC` job: shard build + manifest 갱신(최소) (shard 엔트리 meta(tag_path/episode_id) 전파 포함)
* ☑ `RETRIEVE_VEC` job: 결과를 이벤트로 페이지/청크 스트리밍(D5) (tag_path/section/episode 필터 + 인용 메타 포함)
* ☑ shard 로드/언로드 + 리소스 상한(최소) 도입
* ☑ vector shard에 tag_path/episode_id 등 메타 포함(또는 post-filter 보강)하여 인용/필터 품질 확보

관련 문서:

- `plan/modules/nf_retrieval.md` (Vector)
- `plan/modules/nf_workers.md` (retrieve_vec_job/index_vec_job)

---

### Phase 72 — Graph Hybrid 옵션 경로(기본 off)

* ☑ Must: `INDEX_FTS.params.grouping.graph_extract` 추가(기본 `false`)
* ☑ Must: `RETRIEVE_VEC.params.graph.enabled/max_hops/rerank_weight` 추가(기본 off)
* ☑ Must: graph materialized index(`entity_mention_span/time_anchor/timeline_event/approved facts`) 생성 경로 확보
* ☑ Must: graph rerank는 옵션 경로에서만 적용, 기본 FTS/vector 경로 불변
* ☑ Must: 결과 JSON은 기존 스키마 유지 + `graph` 블록만 선택 추가
* ◐ Partial: graph on/off A/B 회귀를 DS-200/800 기준으로 상시화(단기 수동 검증만 완료)

DoD(테스트 포함):
* ☑ `tests/test_nf_retrieval_graph_rerank.py` 통과
* ☑ graph off/on 모두 기존 contract 응답 필드와 호환(추가 필드만 존재)
* ◐ graph on에서 baseline 대비 성능 악화 없는지 200/800 반복 검증

관련 문서:

- `plan/modules/nf_retrieval.md`
- `plan/modules/nf_workers.md`
- `plan/modules/nf_graphrag.md`

---

### Phase 80 — Suggest(LOCAL_RULE 우선) + Model Gateway 옵션(D4)

* ☑ `SUGGEST` job: `LOCAL_RULE` 최소 구현(근거 묶기/요약/템플릿) + citations/evidence 연동
* ◐ `mode=API`는 opt-in으로만 실행 + 키/레이트리밋/회로차단 최소 (원격 호출은 스텁/차순위)
* ☑ `LOCAL_GEN`은 “분기/인터페이스만”(차순위, 실구현 보류)
* ☑ citations/evidence 연동: 문서ID/섹션/태그 경로(tag_path)까지 포함해 제안 결과 카드 렌더 가능하도록

관련 문서:

- `plan/modules/nf_model_gateway.md`
- `plan/modules/nf_workers.md` (suggest_job)

---

### Phase 90 — Export + Proofread(차순위 포함)

* ☑ `EXPORT` job: txt/docx 내보내기 최소 구현
* ☑ Proofread(rule-base) 최소 구현(1차는 실시간 표시가 기본; batch job은 차순위) (double-space 외 기본 규칙 확장; 강도 조절은 차순위)

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

---

## 부록) 현 구현 메모 (2026-02-06)

- Debug Web UI(Phase 40)는 `modules/nf_orchestrator/debug_ui.html` 기반으로 동작하며, Layout 스타일/ localStorage 저장은 구현 완료.
- Sync Retrieval/필터(tag_path/episode)는 “태깅(span tag_assignment) / episode 정의+EPISODE 제목 번호”가 있어야 값이 채워져 유의미하게 동작함(샘플 fixture는 기본값이 빈 상태).
- Vector 검색은 현재 token overlap 기반 스텁(실제 임베딩/FAISS 등은 차순위).
- ignore_item은 API/엔진 연동까지 구현(정합성/제안 suppress). 제품 UI/UX는 차순위.
- 원격 API(OpenAI/Gemini)는 현재 스텁(provider가 prompt를 그대로 반환)이며, 키 저장(OS keyring) 등은 차순위.
- 제품 UI(nf-desktop) 및 UI helper 레이어는 미구현(Phase 95).
