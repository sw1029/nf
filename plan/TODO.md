## MoSCoW 기반 TODO Checklist (현재까지 논의된 구조/요구 전반, 누락 없이)

> 표기 규칙:
>
> * ☐ TODO / ☐ (완료 시 체크)
> * **[M] Must** / **[S] Should** / **[C] Could** / **[W] Won’t (now)**
> * “now”는 1차 배포(MVP+안정화) 기준
> * 구현 순서(Phase) 통제는 `plan/IMPLEMENTATION_CHECKLIST.md`를 1차 기준으로 함

---

# [M] Must — 1차 배포에 반드시 필요한 항목

## 0) 제품/운영 원칙 고정

* ☐ **로컬 우선**(Windows 데스크탑, 평범한 사용자 PC 기준) 아키텍처 확정
* ☐ “무거운 작업은 UI 프로세스 밖에서 실행” 원칙 고정(워커/큐)
* ☐ **검색 2단 고정**: BM25/FTS(정확 인용) → Vector(의미 확장)
* ☐ **정합성 출력 규격 고정**: Claim–Evidence–Verdict 구조 + unknown 허용
* ☐ “근거 없는 모델 출력 금지(evidence_required)” 정책 고정
* ☐ “암시/추정 자동 확정 금지(implicit_fact_auto_approve=off)” 정책 고정
* ☐ **화이트리스트(의도된 모순/거짓말) 지원** 정책 고정(재경고 억제)
* ☐ “미정/유저 승인 필요” 정책은 `plan/DECISIONS_PENDING.md`로 관리

---

## 1) 앱/프로세스 구조 (UI / Orchestrator / Workers)

### 1.1 Desktop UI (nf-desktop)

* ☐ 텍스트 에디터 기본 기능(열기/저장/편집, 구간 선택)
* ☐ Layout Settings UI: 자간/줄간격(레이아웃) 설정
* ☐ **태깅 UI**(드래그 후 태그 부여, 태그 경로 표시)
* ☐ 결과 패널: **Verdict + Evidence + Reliability breakdown** 렌더링
* ☐ 작업 패널: Job 상태(큐/실행/진행률/성공/실패), **취소/재시도**
* ☐ Proofread UI: 문법(띄어쓰기/문장부호) rule-base 실시간 표시(강도 조절)
* ☐ Schema Review UI: AUTO=PROPOSED fact 승인/거절/보류(명시/암시 공통)
* ☐ 설정 패널: (1) 로컬 모델 다운로드 여부 (2) API 키 입력/활성화 여부
* ☐ Export UI: txt/docx 내보내기

### 1.2 Orchestrator (nf-orchestrator)

* ☐ 로컬 IPC(권장: loopback HTTP) 서버 구현
* ☐ 프로젝트/문서/에피소드/태그/엔티티/화이트리스트 CRUD 서비스
* ☐ 스키마 fact 승인/거절 서비스(AUTO=PROPOSED → APPROVED/REJECTED)
* ☐ `/jobs` 제출, `/jobs/{id}` 상태 조회, `/jobs/{id}/cancel`
* ☐ `/jobs/{id}/events` 진행률 스트리밍(SSE/Websocket 중 1개)
* ☐ 동시작업 정책(전역 세마포어) 구현: heavy job 동시 1개 기본
* ☐ 회로차단(circuit breaker)/레이트리밋 훅(최소 골격)
* ☐ 저장소 계층(storage) + 마이그레이션 체계 구축

### 1.3 Workers (nf-workers)

* ☐ Job Runner(폴링/리스/하트비트/취소 토큰) 구현
* ☐ per-job 리소스 가드(소프트): 메모리/CPU 압력 시 PAUSE/FAILSAFE 정책(최소)
* ☐ job 타입별 실행기:

  * ☐ INGEST(문서→스키마)
  * ☐ INDEX_FTS(FTS 구축/갱신)
  * ☐ INDEX_VEC(벡터 샤드 구축/갱신)
  * ☐ CONSISTENCY(정합성 검사)
  * ☐ RETRIEVE_VEC(Vector 검색/확장; 비동기 스트리밍)
  * ☐ SUGGEST(개선 제안; 로컬/원격)
  * ☐ PROOFREAD(문법/룰 기반 교정; 옵션)
  * ☐ EXPORT(txt/docx)
* ☐ 크래시 복구: lease_expires 처리로 “유실 작업 재큐잉” 보장

---

## 2) 스토리지(디스크 우선) 및 DB 스키마

### 2.1 Project DB(SQLite) 필수 테이블

* ☐ project / document / doc_snapshot / episode / chunk / entity / entity_alias
* ☐ tag_def / tag_assignment
* ☐ schema_version
* ☐ schema_explicit_fact (High precision layer)
* ☐ schema_implicit_fact (Unknown/Proposed layer)
* ☐ whitelist_item
* ☐ evidence / verdict_log / verdict_evidence_link
* ☐ job_queue / job_event (+ job_run 선택)

### 2.2 DocStore(파일 저장)

* ☐ 원문 저장(raw) + 스냅샷(snapshot) 저장
* ☐ export 산출물 저장 경로 규격화

### 2.3 Audit/Provenance 기본

* ☐ verdict_log에 (claim_text, verdict, reliability, breakdown, whitelist 적용 여부, schema_ver, input_snapshot_id) 저장
* ☐ evidence에 (doc_id, snapshot_id, chunk_id, section_path, tag_path, snippet, fts_score, match_type, confirmed) 저장
* ☐ 근거 연결(verdict_evidence_link)로 SUPPORT/CONTRADICT 역할 저장

---

## 3) 문서 작성/태깅 → 스키마 변환 (nf-schema)

### 3.1 태그/계층/경로 체계

* ☐ tag_path 규격: `설정/인물/주인공/나이` 형태를 표준으로
* ☐ tag_def(기본 제공 태그 + 사용자 정의 태그) 관리
* ☐ 태그 할당(tag_assignment) 시 span(문서 위치) 저장

### 3.2 “명시 필드” 추출(High precision, Low recall)

* ☐ 나이/시간/장소/관계/사망 여부/소속 등 **하드 필드** 우선 구현
* ☐ 타입/단위 정규화(예: 나이 int, 날짜/시간 표준화)
* ☐ identity(동일 인물/장소) 보수적 매칭(충돌 시 unknown)
* ☐ AUTO로 추출된 명시 fact도 status=PROPOSED로 저장(유저 승인 전 자동 반영 금지)

### 3.3 “암시/추정/심리/서술 트릭” 레이어

* ☐ 기본값 unknown 허용(자동 확정 금지)
* ☐ 근거 충돌 시 보류(unknown 강등)
* ☐ status=PROPOSED로만 저장(승인/채택은 사용자 주도)

### 3.4 게이팅/오염 방지

* ☐ validators: 타입/범위/누락/상호제약 검증
* ☐ conflict 감지: 충돌 시 unknown 강등 규칙
* ☐ schema_versioning(버전 생성/저장/조회)

---

## 4) 검색 계층 (nf-retrieval): FTS-first → Vector-expand

### 4.1 FTS (정확 인용)

* ☐ SQLite FTS5 인덱스 구축(chunk_id/문서/스냅샷/섹션/태그 경로 + span 저장)
* ☐ snippet 생성기(문서ID/섹션/태그경로 포함, 길이 제한)
* ☐ fts_meta(체크섬 기반 증분 인덱싱)

### 4.2 Vector (샤딩 + 필요 시 로드/언로드)

* ☐ 임베딩 생성기(embedder) 인터페이스(로컬/외부 분리 가능)
* ☐ Vector manifest + shard 파일 구조 확정(+ chunk_map_path 등 매핑 포함)
* ☐ shard 빌드/로드/언로드 정책(기본: SHARDED)
* ☐ LRU 캐시 + max_loaded_shards / max_ram_mb 정책 적용

### 4.3 Hybrid Router

* ☐ 기본 라우팅(job 내부): FTS 결과 부족 시에만 Vector 확장
* ☐ UI 검색: sync는 FTS-only, Vector 확장은 `RETRIEVE_VEC` job으로 전환 + 스트리밍
* ☐ 필터: tag_path/section/episode/entity_id/time_key/timeline_idx 기반 샤드 선택(최소)

---

## 5) 정합성 검토 엔진 (nf-consistency): 3단 근거화 + unknown

### 5.1 Segmentation/Claim 추출

* ☐ 문장/절 segmentation
* ☐ 하드 필드 힌트 기반 claim 후보 추출(시간/나이/장소/관계 키워드)

### 5.2 Evidence Builder

* ☐ claim → FTS 질의 생성(필터 적용 가능하면 적용)
* ☐ evidence 표준 구조로 묶기(doc_id/snapshot_id/chunk_id/section_path/tag_path/snippet/score)

### 5.3 Judge Layer 1: Explicit only (High precision)

* ☐ schema_explicit_fact와 비교하여 위배 감지
* ☐ 위배 시: 근거(스키마 경로 + FTS 스니펫) 반드시 포함

### 5.4 Judge Layer 2: Heuristic (보수적)

* ☐ alias/정규화/약한 동일성 처리
* ☐ 충돌/애매 시 unknown 강등(결정 회피)

### 5.5 Judge Layer 3: 모델/외부 위임(“선택 기능”이지만, 엔진 구조는 Must)

* ☐ Layer3 호출 조건 게이트(사용자 활성화 + 근거 존재 + L1/2 불충분)
* ☐ 모델 점수는 **근거 부재를 뒤집지 못함**(evidence_required 강제)
* ☐ 결과는 reliability breakdown에 “model_score”로만 반영

### 5.6 Whitelist(의도된 모순/거짓말)

* ☐ UI에서 “의도된 모순” 체크 → whitelist_item 저장
* ☐ 동일 claim fingerprint 재경고 억제
* ☐ whitelist 적용 시 결과를 “오류→추가정보” 형태로 표기(상태 필드로)

### 5.7 Reliability Score(단일 점수 + 분해 항목)

* ☐ 점수 분해 저장: fts_strength / evidence_count / confirmed_evidence / model_score
* ☐ UI에 분해 항목을 그대로 노출(단일 점수만 강조하지 않음)

---

## 6) 모델 경계 (nf-model-gateway): 로컬 소형 / 외부 고성능 API 분리

* ☐ 로컬 ONNX Runtime 래퍼 골격
* ☐ “정합성 검토용 소형 모델” 인터페이스(없어도 동작하도록)
* ☐ “로컬 생성 모델(개선 제안)” 인터페이스/분기만 구현(실 모델은 차순위)
* ☐ 외부 API 클라이언트(OpenAI/Gemini 등) 인터페이스(옵트인)
* ☐ rate limit / circuit breaker 최소 구현
* ☐ evidence_required 정책 적용(근거 없이 생성/판정 금지)

---

## 7) Export (nf-export)

* ☐ txt export
* ☐ docx export
* ☐ 옵션: 메타데이터 포함/미포함(근거/태그 요약)

---

## 8) 배포/실행 형태 (Python → Windows EXE)

* ☐ 패키징 방식 확정(PyInstaller/Nuitka 중 1)
* ☐ “앱/모델 분리 다운로드” 흐름 설계(초기 설치 부담 완화)
* ☐ 모델/인덱스/런타임 종속성 최소화(가능하면 CPU 기본)
* ☐ 로컬 서비스(loopback) 방화벽/권한 이슈 최소화 가이드(내장)

---

# [S] Should — 안정성/성능/UX 향상을 위해 강력 권장

## 1) 성능/프리징 방지 강화

* ☐ heavy job 종류별 “동시 실행 제한” 세분화(예: index_vec와 model 호출 동시 금지)
* ☐ job 우선순위(사용자 인터랙션 작업 우선)
* ☐ index_vec 빌드 시 배치 크기/메모리 추정 기반 자동 throttling
* ☐ vector shard 선택 로직 고도화(episode overlap + 최근 사용 + doc_type)
* ☐ RETRIEVE_VEC 결과 캐시/샤드 프리로드(프리징 방지 범위 내)
* ☐ 워커 프로세스 격리 강화(작업별 별도 프로세스 풀)

## 2) 데이터 품질/오염 방지 고도화

* ☐ identity resolution(동일 인물/장소) 규칙 강화 + 보수적 디폴트
* ☐ entity/entity_alias 기반의 alias 관리 워크플로(사용자 주도 + 보수적 디폴트)
* ☐ schema 마이그레이션(버전 간 필드 변화) 자동화
* ☐ explicit_fact 승인 워크플로(UI에서 승인/거절/보류; AUTO=PROPOSED)
* ☐ implicit_fact 승인 워크플로(UI에서 승인/거절/보류)
* ☐ explicit_fact_auto_approve 스위치(기본 off; 차순위/선택 구현)

## 3) Retrieval 품질

* ☐ Vector 결과에 경량 rerank(로컬) 옵션
* ☐ FTS query builder 개선(슬롯 기반 부스팅, tag_path narrowing)

## 4) UX/설명가능성

* ☐ 결과 카드에 “근거 충돌/불충분” 사유 표준 문구 제공(unknown 설명)
* ☐ “반복 제안 억제” UI(whitelist 외에도 ‘무시’ 상태)
* ☐ job_event에 처리량/추정 남은시간 등 메트릭 제공(정확한 ETA가 아니라 상태 지표)

## 5) 보안/키 관리

* ☐ API key 저장은 OS keyring 사용
* ☐ 로컬 서버는 loopback 고정 + 임의 토큰(옵션)

## 6) 모델/제안(차순위)

* ☐ 로컬 생성 모델(Local generator) 실구현 + ModelStore 다운로드/업데이트/버전관리
* ☐ 모델 기반 문법 교정(옵트인; rule-base 결과 보조)

## 7) 개발/테스트 도구

* ☐ 루프백 임시 Web UI(개발용): `plan/loopback_web_ui.md`

---

# [C] Could — 여유가 되면 추가(실험/확장)

## 1) 에피소드 분석(옵션)

* ☐ 기승전결 분석(가능하면 rule/계량 지표 우선)
* ☐ 사건 밀도/등장인물 분포/떡밥 태그 변화량 지표 계산
* ☐ 에피소드별 datacard(요약 테이블) 생성

## 2) 사용자 태그 품질 모델(로컬 경량)

* ☐ 태그 일관성/희소성 기반 회귀/분류(초기엔 휴리스틱)
* ☐ 데이터가 쌓인 이후에만 학습/활성화

## 3) 자동 태깅(소형 모델 기반)

* ☐ 사용자 태그 미지정 시 제안 형태로만 제공(자동 확정 금지)
* ☐ 제안 수락 시 tag_assignment로 반영

## 4) 고급 검색/인덱싱 실험 기능

* ☐ HNSWlib 대체 백엔드
* ☐ semantic chunking 고도화(문서 타입별)
* ☐ graph/제약 엔진 분기(얕은 그래프 기반)
* ☐ GraphRAG/RAPTOR 실험적 플러그인 모듈화(옵션 선택형)

---

# [W] Won’t (now) — 1차 배포에서 제외(나중에 플러그인/실험으로)

* ☐ GraphRAG “필수 기능”으로 통합(기본 골조 완료 후 옵션으로만)
* ☐ RAPTOR/SELF-RAG를 기본 경로에 강제(실험적 기능으로 분리 유지)
* ☐ BitNet/Gemma 양자화 모델을 초기 필수 다운로드로 강제(선택 다운로드/옵트인 유지)
* ☐ 암시/추정 레이어를 자동 확정하여 스키마에 반영(오염 위험 때문에 금지)
* ☐ “단일 신뢰도 점수”만 전면 노출(분해 항목 동시 노출을 유지)

---

# 체크리스트 부록: “정합성 결과(Evidence/Verdict) 표준 스펙” 확정 항목

* ☐ Evidence 최소 필드: doc_id, snapshot_id(optional), chunk_id(optional), section_path, tag_path, snippet, fts_score, match_type, confirmed
* ☐ Verdict 최소 필드: claim_text, verdict(ok/violate/unknown), reliability_overall, breakdown_json, evidence[]
* ☐ Whitelist 적용 필드: whitelist_applied, claim_fingerprint
* ☐ 저장 위치: Project DB(SQLite) + UI 카드 렌더링

---

# 체크리스트 부록: “API 표면” 최소 세트

* ☐ /projects, /documents, /episodes, /tags, /entities, /schema(+/schema/facts)
* ☐ /jobs submit, /jobs status, /jobs cancel, /jobs events
* ☐ /query/retrieval, /query/verdicts, /query/evidence/{eid}
* ☐ /projects/{project_id}/whitelist add/remove
* ☐ /export
