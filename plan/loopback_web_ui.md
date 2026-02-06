# 루프백 테스트 웹 UI (개발용 임시 웹 UI) — MoSCoW 구현 계획

이 문서는 개발/디버깅 중 **각 기능의 작동 확인**을 빠르게 하기 위한 **임시 웹 UI** 계획이다.
제품 UI(`nf-desktop`)와 별개이며, **루프백(127.0.0.1)에서만** 노출되는 것을 원칙으로 한다.

> 표기 규칙: ☐ TODO / ☑ Done / ◐ Partial(스텁/의도 미적용)

참조:

- `plan/contracts.md` (HTTP API + 잡/SSE 계약)
- `plan/architecture_1.md`, `plan/architecture_2.md` (프로세스/잡 흐름)
- `plan/DECISIONS_PENDING.md` (D1~D5 정책)

구현 순서(Phase, 전체 로드맵: `plan/IMPLEMENTATION_CHECKLIST.md`):

테스트는 conda의 `nf` 환경에서 수행한다.

- Phase 40에서 구현(선행: Phase 10~30 최소 API/잡/SSE/FTS 동작)
- 제품 UI(`nf-desktop`) 구현과 독립적이며, 개발/디버깅 목적에 한정

---

# [M] 필수 — 개발/디버깅 MVP

## 0) 목적/비목적

목적:

- 데스크톱 UI 없이도 **오케스트레이터/워커/각 모듈 기능**을 단계적으로 호출하고 결과를 관찰한다.
- 잡 + SSE 스트리밍 흐름(진행률/이벤트/페이로드)을 브라우저에서 즉시 확인한다.
- 정책 스위치/테스트 토글을 통해 **성공/실패/unknown(미확정)/정책 위반** 케이스를 재현한다.

비목적:

- 제품 UI 대체(UX 완성도/디자인/접근성) 또는 배포용 웹 UI.
- 외부 네트워크/원격 접근 지원(반드시 루프백 고정).

---

## 0.1) 현 구현 메모 (2026-02-06)

- 샘플 fixture는 `tag_def`만 seed하며 `tag_assignment`/episode 정의는 생성하지 않음 → Retrieval의 `tag_path/episode` 필터는 기본 상태에서 빈 값일 수 있음.
- Proofread는 PROOFREAD 잡 실행 결과(lint_items)를 레이아웃 미리보기 패널에 적용하는 방식(타이핑 중 자동 lint는 제품 UI에서).
- 원격 API(OpenAI/Gemini) provider는 현재 스텁이며, enable_remote_api는 “정책 게이트”로만 의미가 있음.

---

## 1) 실행/노출 조건(루프백 고정)

* ☑ 바인딩: `127.0.0.1` 전용(필수). `0.0.0.0` 바인딩 금지.
* ☑ 활성화 플래그(기본 꺼짐):
  - 예: `NF_ENABLE_DEBUG_WEB_UI=1` 또는 config에서 `enable_debug_web_ui=true`
* ☑ 경로 프리픽스: `/_debug` (권장)로 분리하여 제품 API와 충돌 방지
* ☑ 최소 보호:
  - 임시 토큰(쿼리/헤더) 1개(`NF_DEBUG_WEB_UI_TOKEN`) + 미설정 시 강제 비활성(권장)
  - 응답에 “DEV ONLY / LOOPBACK ONLY” 배너 표시

---

## 2) 페이지/기능 구성(최소)

### 2.1 홈/상태

* ☑ `/ _debug /` 대시보드
  - Orchestrator/Worker 프로세스 상태(heartbeat/last_seen)
  - 현재 프로젝트 선택(활성 project_id) + 전역 설정 스냅샷 표시

### 2.2 CRUD 확인(프로젝트/문서/태그)

* ☑ Projects: `/projects` GET/POST, `/projects/{project_id}` GET/PATCH
  - 프로젝트 생성/선택/설정 확인(스위치 포함)
* ☑ Documents: `/projects/{project_id}/documents` GET/POST
  - 업로드/등록(간이 텍스트 붙여넣기 포함)
* ☑ Tags: `/projects/{project_id}/tags` GET/POST
  - tag_def 생성/나열(간이)

### 2.3 Jobs(핵심) + SSE 이벤트 뷰어

* ☑ Jobs Panel:
  - `/jobs` submit 폼(공통): `type`, `project_id`, `inputs`, `params`, `priority`
  - `/jobs/{jid}` 상태 폴링
  - `/jobs/{jid}/cancel` 취소 버튼
* ☑ SSE Viewer:
  - `/jobs/{jid}/events` 구독(EventSource)
  - PROGRESS 이벤트는 타임라인/프로그레스바로 렌더
  - `payload`는 raw JSON 프리뷰 + “copy” 제공

### 2.4 Retrieval(정책 D5 준수)

* ☑ Sync Retrieval(FTS-only):
  - `/query/retrieval` POST만 사용(FTS-only)
  - 입력 조절: `query`, `filters(tag_path/section/episode/entity_id/time_key/timeline_idx)`, `k`
  - (주의) `tag_path/episode_id`는 “데이터가 있을 때”만 필터로 유의미함
    - `tag_path`: `tag_assignment`가 없으면 `""`로 인덱싱됨
    - `episode_id`: episode 정의 + EPISODE 문서 제목의 숫자 파싱이 있어야 할당됨(샘플 fixture는 기본적으로 비어 있음)
  - 결과 렌더: evidence 스니펫/경로/점수/confirmed 표시
* ☑ Vector 확장(비동기):
  - “Vector 확장” 버튼 → `/jobs`에 `RETRIEVE_VEC` 제출
  - 결과는 SSE `payload.results[]` 조각으로 스트리밍 표시(D5)
* ☑ (추가 요구) 시점/인물 chunk group 생성(사용자 요청 시):
  - “시점 그룹 생성/인물 그룹 생성” 버튼 → `/jobs`에 `INDEX_FTS` 제출 + `params.grouping` 사용
  - (선택) `timeline_doc_id` 입력/선택: 세계관 타임라인을 참조해 `timeline_idx` 부여
  - 결과: 제안된 span 개수/샘플 및 `PROPOSED` 저장 여부 표시

### 2.5 Consistency(정합성)

* ☑ `/jobs`에 `CONSISTENCY` 제출 폼
  - 입력 조절: `doc_id`, `snapshot_id`, `range(스팬/에피소드)`, `schema_ver`
  - 출력: verdict/evidence/breakdown/raw JSON 확인
* ☑ whitelist 연동 트리거:
  - 사용자가 “의도된 모순” 체크 → `/projects/{project_id}/whitelist` 호출(간이)

### 2.6 Schema Review(정책 D3 준수)

* ☑ facts 리스트:
  - `/projects/{project_id}/schema/facts` GET (filters: status/source/layer)
  - `AUTO`는 항상 `PROPOSED`(1차 정책)임을 UI에 명시
* ☑ 승인/거절:
  - `/projects/{project_id}/schema/facts/{fact_id}` PATCH `{status}`
  - fact/evidence 링크(raw) 확인 버튼
* ☑ (추가 요구) 시점/인물/타임라인 검토:
  - `entity_mention_span/time_anchor/timeline_event` 목록 조회 + 승인/거절(최소)

### 2.7 Suggest(정책 D4 준수)

* ☑ `/jobs`에 `SUGGEST` 제출 폼
  - mode: `LOCAL_RULE`(기본), `API`(옵트인), `LOCAL_GEN`(차순위 분기)
  - 입력 조절: range + citations 포함 여부(가능하면)
* ◐ 결과: suggestion text + citation cards 렌더 (include_citations=true일 때 citations 생성; tag_path는 태깅 없으면 `""` 가능 / 원격 API provider는 스텁)

### 2.8 Proofread/Layout(정책 D1 준수)

* ☑ Layout Settings(레이아웃):
  - 자간/줄간격(행간) 조절 슬라이더 + 프리뷰(교정 결과로 저장하지 않음)
  - 배경색/폰트(프리셋+커스텀)/글자 크기(px)/좌우 여백(px) 조절(클라이언트 전용)
  - (권장) 어두운 배경 선택 시 자동 대비(텍스트 색 자동 변경) 또는 테마 프리셋 제공
  - (권장) 설정값을 localStorage에 저장(리로드 후 유지)
  - 구현 상세: `plan/proofread_layout_style_controls.md`
* ◐ Proofread(문법):
  - rule-base lint 결과를 “미리보기 underline/tooltip” 형태로 관찰 (현재 규칙: double-space/trailing-whitespace/many-blank-lines/space-before-punct/repeated-punct/ellipsis; 강도 조절은 차순위)
  - 모델 기반 문법 교정은 차순위(옵트인)로만 노출

### 2.9 Export

* ☑ `/jobs`에 `EXPORT` 제출 폼
  - 입력 조절: range, format(txt/docx), include_meta
  - 산출물 링크/다운로드(가능하면)

---

## 3) 테스트 목적의 인터랙티브 조절(on/off) — 필수

아래 토글은 “제품 설정”과 “테스트/디버그 설정”을 분리한다.

### 3.1 제품/정책 스위치(프로젝트 설정과 연동)

* ☑ `sync_retrieval_mode` 표시: `FTS_ONLY` 고정(D5). 변경 시도는 “정책 위반”으로 표시.
* ☑ `enable_remote_api` 토글(기본 off): on 시에만 `SUGGEST/API` 호출을 허용
* ☑ `enable_local_generator` 토글(기본 off): on 시에도 1차는 “분기만” 활성(D4)
* ☑ `explicit_fact_auto_approve` 토글(기본 off; 차순위): UI에는 “실험/위험”으로 구분 표시(D3)

### 3.2 테스트/디버그 토글(루프백 UI 전용, 메모리 상태 가능)

* ☑ Fault injection:
  - 다음 요청 강제 실패(on/off): `force_error_code`, `force_latency_ms`
  - SSE drop/fragment simulation(스트리밍 견고성 확인)
* ☑ Data/fixture:
  - 샘플 프로젝트/문서/태그/스키마 seed 버튼(재현 가능한 고정 시드)
  - 초기화(reset) 버튼(테스트 DB/DocStore 삭제는 강력 경고 후 실행)
* ◐ Worker behavior(부분 구현: max_* 변경은 재시작 필요):
  - “heavy job 동시 1개” 정책 활성/비활성(관찰용)
  - max_loaded_shards/max_ram_mb 등 제한값을 UI에서 조절(테스트용)

---

## 4) UI 구현 방식(권장)

* ☑ 빌드 파이프라인 없이 동작:
  - 단일 HTML(+CSS+vanilla JS) 또는 HTMX 수준(선택)
* ☑ API 호출은 `plan/contracts.md`의 HTTP API를 그대로 사용(계약 검증 목적)
* ☑ SSE는 브라우저 `EventSource`로 구현

---

## 5) 테스트(pytest) (선택이 아니라 권장)

* ☐ debug UI가 기본 off인 것 확인(unit)
* ☐ loopback 외 바인딩/접근 차단 확인(unit)
* ☐ 토큰 미설정 시 접근 차단 확인(unit)
* ☐ `/jobs/{jid}/events` 스트리밍 연결이 최소 형태로 동작하는지(스모크)

---

# [S] 권장 — 개발 생산성

* ☑ 시나리오 프리셋:
  - “INGEST→INDEX_FTS→CONSISTENCY” 원클릭 실행
  - “FTS query→RETRIEVE_VEC 확장” 원클릭 실행
* ☑ cURL/JSON export:
  - UI에서 실행한 요청을 cURL로 복사
  - 마지막 N개 요청/응답 로그를 파일로 저장
* ☑ SSE reconnect(Last-Event-ID) 지원(가능하면)

---

# [C] 선택 — 여유 시

* ☐ VerdictLog diff 뷰(동일 claim 재실행 비교)
* ☐ Evidence 하이라이트(원문/스냅샷 렌더 + 스팬 강조)
* ☐ 성능 관찰 패널(메모리/CPU 추정치, shard load 상태)

---

# [W] 현재 제외

* ☐ 외부 네트워크 접근/계정/권한 시스템
* ☐ 제품 UI 수준의 완성도/디자인
