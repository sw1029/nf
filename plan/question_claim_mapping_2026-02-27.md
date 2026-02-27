# questions 3개 문서 주장 타당성 검토 및 미비점-개선점 매핑 (2026-02-27)

## 1) 검토 기준/범위
- 대상 문서: `questions/question1.md`, `questions/question2.md`, `questions/question3.md`
- 판정 등급: `타당`, `부분 타당`, `비타당`
- 판정 원칙:
  - `타당`: 코드 + 테스트(또는 계약 테스트) 근거 확인
  - `부분 타당`: 방향은 맞으나 근거가 시점/운영/정량 수치에 의존하거나 구현과 일부 불일치
  - `비타당`: 현재 코드/테스트로 반증
- 분류 태그: `IMPLEMENTATION_GAP`, `UI_DESIGN_SPEC`, `PIPELINE_LOGIC_CHANGE`, `NO_ACTION`
- 문서 분리:
  - UI 디자인 명세: `plan/question_claim_ui_design_specs_2026-02-27.md`
  - 파이프라인 대변경 제안: `plan/question_claim_pipeline_logic_proposals_2026-02-27.md`

## 2) 문서별 주장 판정

### 2.1 question1.md

| Claim ID | 원문 출처 | 주장 요약 | 판정 | 근거(코드/테스트) | 현재 구현 미비점 | 개선점 | 분류 태그 | 분리 문서 링크 또는 N/A |
|---|---|---|---|---|---|---|---|---|
| Q1-C01 | questions/question1.md | 본문/설정/구상/타임라인 탭 + config-panel이 구현되어 있다 | 타당 | `modules/nf_orchestrator/user_ui.html:95`, `:99`, `:102`, `:105`, `:291`, `tests/test_nf_orchestrator_user_ui_contracts.py:70` | 없음 | [P3] 회귀 테스트 유지 | NO_ACTION | N/A |
| Q1-C02 | questions/question1.md | action-popover로 whitelist/ignore 액션을 수행할 수 있다 | 타당 | `modules/nf_orchestrator/user_ui.html:376`, `:382`, `:384`, `modules/nf_orchestrator/assets/user_ui.assistant.js:745`, `:746`, `:818`, `:837`, `tests/test_nf_orchestrator_user_ui_contracts.py:103` | 없음 | [P3] 액션 성공/실패 토스트 표준화 | NO_ACTION | N/A |
| Q1-C03 | questions/question1.md | PROPOSE 탭에서 교정 강도 선택 후 API 호출한다 | 타당 | `modules/nf_orchestrator/user_ui.html:486`, `:490`, `:494`, `modules/nf_orchestrator/assets/user_ui.assistant.js:509`, `:515`, `:521` | 없음 | [P3] 레벨 설명 문구 정교화 | NO_ACTION | N/A |
| Q1-C04 | questions/question1.md | inline-tag-widget로 인라인 태깅/메모가 가능하다 | 타당 | `modules/nf_orchestrator/user_ui.html:348`, `:356`, `:360`, `modules/nf_orchestrator/assets/user_ui.editor.js:1364`, `:1420` | 없음 | [P2] 태깅 후 저장 경로 안내 추가 | NO_ACTION | N/A |
| Q1-C05 | questions/question1.md | txt/docx export, API 키/모델 설정 UI가 있다 | 타당 | `modules/nf_orchestrator/user_ui.html:541`, `:548`, `:522`, `:528`, `modules/nf_orchestrator/assets/user_ui.docs_tree.js:881`, `:902`, `modules/nf_orchestrator/assets/user_ui.api.js:6`, `:7`, `:9` | 없음 | [P2] 키 저장 보안 경고/정책 명시 | NO_ACTION | N/A |
| Q1-C06 | questions/question1.md | 신뢰성 점수 분해(FTS/확정근거/모델점수)가 UI에 직접 노출되지 않는다 | 타당 | 백엔드 분해 존재: `modules/nf_shared/protocol/dtos.py:364`, `:382`, `modules/nf_consistency/engine.py:1591`, `:1603`; UI 단일 노출: `modules/nf_orchestrator/assets/user_ui.assistant.js:730` | 분해 근거가 카드 1차 뷰에 없음 | [P1] 카드에 breakdown 항목/툴팁 노출 | UI_DESIGN_SPEC | `plan/question_claim_ui_design_specs_2026-02-27.md#ui-01` |
| Q1-C07 | questions/question1.md | time/entity/timeline 매핑을 시각적으로 확인/수정하는 워크플로가 부족하다 | 타당 | 필터 입력은 존재: `modules/nf_orchestrator/user_ui.html:461`, `:463`, `:465`; 백엔드 엔드포인트 존재: `modules/nf_orchestrator/main.py:95`~`:100`; user_ui 자산에서 직접 호출 부재(검색 결과 없음) | UI에서 생성/승인/재매핑 흐름 부재 | [P1] 타임라인/엔티티 매핑 작업면 추가 | UI_DESIGN_SPEC | `plan/question_claim_ui_design_specs_2026-02-27.md#ui-03` |
| Q1-C08 | questions/question1.md | whitelist 일괄 조회/수정/취소 UI가 없다 | 타당 | API/저장소는 존재: `modules/nf_orchestrator/main.py:109`, `:110`, `modules/nf_orchestrator/storage/db.py:300`; user_ui는 POST 액션 위주: `modules/nf_orchestrator/assets/user_ui.assistant.js:818`, `:837` | 사용자 UI에서 목록/삭제/어노테이션 수정 부재 | [P1] 예외 관리 패널 + undo 제공 | UI_DESIGN_SPEC | `plan/question_claim_ui_design_specs_2026-02-27.md#ui-02` |
| Q1-C09 | questions/question1.md | paginateText의 동기 높이 측정은 대용량에서 프리징 리스크가 있다 | 타당 | `modules/nf_orchestrator/assets/user_ui.editor.js:151`~`:187`, `:201`, `:205`, `:368` | 메인 스레드 측정/재페이지네이션 비용 누적 가능 | [P1] 비동기 배치/가상화/idle 분할 | IMPLEMENTATION_GAP | N/A |
| Q1-C10 | questions/question1.md | 작업 대기는 SSE+폴링 혼용으로 추적한다 | 타당 | `modules/nf_orchestrator/assets/user_ui.assistant.js:81`, `:119`, `:214`, `:216`, `:218`, `tests/test_nf_orchestrator_user_ui_contracts.py:121` | 없음 | [P3] 상태 머신 로깅 추가 | NO_ACTION | N/A |
| Q1-C11 | questions/question1.md | 이벤트 유실 시 영구 대기 위험이 있다 | 부분 타당 | SSE 실패 시 폴백 있음: `modules/nf_orchestrator/assets/user_ui.assistant.js:214`~`:218`; 다만 `/jobs/{id}` 상태가 장시간 RUNNING이면 사용자 체감 대기 지속 가능 | 영구 대기 완전 방지 UX 부족 | [P2] 타임아웃/중단 가이드/재시도 정책 명시 | IMPLEMENTATION_GAP | N/A |
| Q1-C12 | questions/question1.md | 오판 whitelist 오염을 되돌리는 사용자 워크플로가 없다 | 타당 | 저장/삭제 API 존재: `modules/nf_orchestrator/main.py:109`, `:996`, `:1031`, `modules/nf_orchestrator/services/whitelist_service.py:37`, `:56`; user_ui 삭제 UI 부재 | UI undo/관리 기능 미제공 | [P1] 예외 관리 대시보드와 이력 | UI_DESIGN_SPEC | `plan/question_claim_ui_design_specs_2026-02-27.md#ui-02` |
| Q1-C13 | questions/question1.md | 정합성 엔진의 하드제약 + Layer3 승격 흐름은 설계상 타당하다 | 타당 | `modules/nf_consistency/engine.py:843`, `:1640`, `:2064`~`:2117` | 없음 | [P3] 레이어별 설명 문서화 | NO_ACTION | N/A |
| Q1-C14 | questions/question1.md | `_resolve_excluded_self_fact_eids`의 청크 반복 조회는 병목 가능성이 있다 | 타당 | `modules/nf_consistency/engine.py:770`, `:790`~`:792` | 대규모 eid에서 반복 SQL 호출 | [P1] temp table/bulk join 방식으로 변경 | PIPELINE_LOGIC_CHANGE | `plan/question_claim_pipeline_logic_proposals_2026-02-27.md#pl-04` |
| Q1-C15 | questions/question1.md | verification loop의 재검색 반경 증가가 최악 지연을 키운다 | 타당 | `modules/nf_consistency/engine.py:2158`, `:2176` | 근거 빈약 케이스에서 반복 비용 증가 | [P1] 조기 중단/예산 기반 loop | PIPELINE_LOGIC_CHANGE | `plan/question_claim_pipeline_logic_proposals_2026-02-27.md#pl-03` |
| Q1-C16 | questions/question1.md | `_compare_slot`의 사전 치환 + 토큰 중복 기반 판정은 의미론 한계가 있다 | 타당 | `modules/nf_consistency/engine.py:111`, `:449`, `:490`, `:515`; `modules/nf_consistency/extractors/rule_extractor.py:153`, `:160`, `:167` | 동의어/문맥 변형 처리 취약 | [P1] 슬롯별 의미 임베딩/정규화 강화 | PIPELINE_LOGIC_CHANGE | `plan/question_claim_pipeline_logic_proposals_2026-02-27.md#pl-05` |
| Q1-C17 | questions/question1.md | `p95 7.65s`와 목표 미달 수치는 현재 정적 코드만으로 확정 가능하다 | 부분 타당 | 코드로는 수치 확정 불가. 과거 벤치 문서에 수치 존재: `plan/IMPLEMENTATION_STATUS.md`(2026-02-11 섹션) | 최신 측정값 부재 | [P2] 벤치 재실행 후 문서 갱신 | IMPLEMENTATION_GAP | N/A |
| Q1-C18 | questions/question1.md | ColBERT/Cross-Encoder 전면 도입 제안은 구조 대변경 이슈다 | 부분 타당 | 현재 엔진은 FTS+vector+rereank/NLI 혼합: `modules/nf_consistency/engine.py:1888`, `:1996` | 고비용 모델 상시 도입 시 자원 리스크 | [P2] 선택적/조건부 라우팅 실험 | PIPELINE_LOGIC_CHANGE | `plan/question_claim_pipeline_logic_proposals_2026-02-27.md#pl-08` |
| Q1-C19 | questions/question1.md | Self-RAG/Graph-augmented 제안은 대규모 파이프라인 변경이다 | 부분 타당 | 그래프 확장은 이미 옵션 존재: `modules/nf_workers/runner.py:1392`, `modules/nf_retrieval/graph/rerank.py:105` | 그래프 품질 게이트/오염 통제가 핵심 리스크 | [P2] 옵트인 + 승인형 그래프 추출 | PIPELINE_LOGIC_CHANGE | `plan/question_claim_pipeline_logic_proposals_2026-02-27.md#pl-07` |
| Q1-C20 | questions/question1.md | 고위험 UNKNOWN에만 고비용 판정 라우팅하는 해법이 적합하다 | 타당 | 현재도 verifier/triage/verification_loop 옵션화: `modules/nf_orchestrator/assets/user_ui.state.js:367`, `modules/nf_workers/runner.py:1509`, `:1526`, `:1537` | 정책이 코드/UX에 명확히 문서화되지 않음 | [P1] 라우팅 정책 계약 문서화 | PIPELINE_LOGIC_CHANGE | `plan/question_claim_pipeline_logic_proposals_2026-02-27.md#pl-08` |
| Q1-C21 | questions/question1.md | n~m episode 스코프를 사용자 UI에서 직관적으로 지정하는 기능이 없다 | 타당 | `modules/nf_orchestrator/user_ui.html` 내 범위 입력 컨트롤 부재, `modules/nf_orchestrator/assets/user_ui.docs_tree.js:750`~`:759` | 범위 기반 실행 UX 부재 | [P1] n~m 범위 선택/실행 패널 | UI_DESIGN_SPEC | `plan/question_claim_ui_design_specs_2026-02-27.md#ui-04` |
| Q1-C22 | questions/question1.md | 인물/시점 필터가 고급 옵션 하위에 있어 접근성이 낮다 | 부분 타당 | 컨트롤 위치: `modules/nf_orchestrator/user_ui.html:455`~`:465` | 초심자 발견성 낮음 | [P2] 프리셋/가이드/추천값 추가 | UI_DESIGN_SPEC | `plan/question_claim_ui_design_specs_2026-02-27.md#ui-03` |

### 2.2 question2.md

| Claim ID | 원문 출처 | 주장 요약 | 판정 | 근거(코드/테스트) | 현재 구현 미비점 | 개선점 | 분류 태그 | 분리 문서 링크 또는 N/A |
|---|---|---|---|---|---|---|---|---|
| Q2-C01 | questions/question2.md | 문서 분류/탭 분리는 동작한다 | 타당 | `modules/nf_orchestrator/user_ui.html:95`~`:105` | 없음 | [P3] 유지 | NO_ACTION | N/A |
| Q2-C02 | questions/question2.md | 문서 수 증가 시 탐색 UX 취약 가능성이 있다 | 타당 | 트리/리스트 중심 구조: `modules/nf_orchestrator/assets/user_ui.docs_tree.js:299`~`:386` | 검색/필터 중심 탐색 부족 | [P2] 문서 검색/필터/핀 기능 | UI_DESIGN_SPEC | `plan/question_claim_ui_design_specs_2026-02-27.md#ui-10` |
| Q2-C03 | questions/question2.md | 저장 후 INGEST→INDEX_FTS→배경 점검 파이프라인이 동작한다 | 타당 | `modules/nf_orchestrator/assets/user_ui.assistant.js:236`, `:245`, `:251`, `:256` | INDEX_VEC는 기본 경로에 없음 | [P2] 옵션형 vec 후처리 도입 | NO_ACTION | N/A |
| Q2-C04 | questions/question2.md | 인덱싱/점검 진행률 가시성은 제한적이다 | 부분 타당 | jobs/consistency 배지 존재: `modules/nf_orchestrator/user_ui.html:197`, `:206`, `modules/nf_orchestrator/assets/user_ui.jobs.js:39` | 상세 단계/예상 소요/병목 설명 부족 | [P2] 상태 모델/원인코드 뷰 강화 | UI_DESIGN_SPEC | `plan/question_claim_ui_design_specs_2026-02-27.md#ui-05` |
| Q2-C05 | questions/question2.md | 재시도 버튼은 실제 retry가 아닌 mock 동작이다 | 타당 | `modules/nf_orchestrator/assets/user_ui.jobs.js:121`, `:124`, `:128`; 서버는 `/jobs/{id}/cancel`만 제공: `modules/nf_orchestrator/main.py:114` | 재큐잉 API 부재/오해 유발 | [P1] `POST /jobs/{id}/retry` 또는 payload 재실행 | IMPLEMENTATION_GAP | N/A |
| Q2-C06 | questions/question2.md | 정합성 segmentation + 하이라이트 + 예외처리는 구현되어 있다 | 타당 | `modules/nf_orchestrator/assets/user_ui.state.js:85`, `:494`; `modules/nf_orchestrator/assets/user_ui.assistant.js:745`~`:848`; `tests/test_nf_orchestrator_user_ui_contracts.py:103` | 없음 | [P3] 유지 | NO_ACTION | N/A |
| Q2-C07 | questions/question2.md | 신뢰도 분해 미노출(중복: Q1-C06) | 타당 | 동일 근거: `modules/nf_orchestrator/assets/user_ui.assistant.js:730`, `modules/nf_consistency/engine.py:1591` | 분해 설명 부족 | [P1] breakdown 카드 도입 | UI_DESIGN_SPEC | `plan/question_claim_ui_design_specs_2026-02-27.md#ui-01` |
| Q2-C08 | questions/question2.md | whitelist/ignore 되돌리기 UX 없음(중복: Q1-C12) | 타당 | 동일 근거: `modules/nf_orchestrator/assets/user_ui.assistant.js:818`, `:837`; 삭제 API는 백엔드에만: `modules/nf_orchestrator/main.py:109`, `:110`, `:996`, `:1031` | 사용자 undo 없음 | [P1] 예외 관리 패널 | UI_DESIGN_SPEC | `plan/question_claim_ui_design_specs_2026-02-27.md#ui-02` |
| Q2-C09 | questions/question2.md | 문장 경계 규칙이 단순해 오탐/UNKNOWN이 늘 수 있다 | 타당 | `modules/nf_orchestrator/assets/user_ui.state.js:55`, `:97`; `modules/nf_consistency/engine.py:181`~`:214` | 장르별 문장 분리 품질 보정 없음 | [P1] tokenizer 개선/옵션화 | IMPLEMENTATION_GAP | N/A |
| Q2-C10 | questions/question2.md | 문법 교정 강도 UX는 부분 구현이다 | 타당 | user_ui는 PROPOSE만 사용: `modules/nf_orchestrator/assets/user_ui.assistant.js:509`~`:521`; PROOFREAD job은 백엔드에 존재: `modules/nf_workers/runner.py:1783` | UI에서 proofread 전용 흐름 부재 | [P2] PROOFREAD 전용 모드 분리 | UI_DESIGN_SPEC | `plan/question_claim_ui_design_specs_2026-02-27.md#ui-07` |
| Q2-C11 | questions/question2.md | 자간/줄간격/폰트 설정은 충족된다 | 타당 | `modules/nf_orchestrator/user_ui.html:291`~`:313`, `modules/nf_orchestrator/assets/user_ui.editor.js:1175` | 없음 | [P3] 유지 | NO_ACTION | N/A |
| Q2-C12 | questions/question2.md | 브라우저 렌더 차이로 페이지/하이라이트 어긋남 리스크가 있다 | 부분 타당 | 페이지네이션/오프셋 의존: `modules/nf_orchestrator/assets/user_ui.editor.js:201`, `:342`, `:397`; fallback highlight 존재: `modules/nf_orchestrator/assets/user_ui.state.js:494` | 브라우저별 오프셋 오차 회귀 테스트 부족 | [P2] 교차 브라우저 스냅샷 회귀 | IMPLEMENTATION_GAP | N/A |
| Q2-C13 | questions/question2.md | PROPOSE 근거 표시는 title/snippet 중심이고 tag_path 중심이 약하다 | 타당 | `modules/nf_orchestrator/assets/user_ui.assistant.js:564`, `:568`; `citation.tag_path` 렌더 미사용 | 경로 기반 설명력 부족 | [P1] citation 카드에 tag_path/section_path 추가 | UI_DESIGN_SPEC | `plan/question_claim_ui_design_specs_2026-02-27.md#ui-06` |
| Q2-C14 | questions/question2.md | 제안(SUGGEST) 반복 억제 UX가 약하다 | 타당 | 백엔드 억제는 존재: `modules/nf_workers/runner.py:1714`; user_ui에는 SUGGEST ignore/undo 컨트롤 부재 | SUGGEST suppress 제어 미노출 | [P2] 제안 카드에 suppress/복원 버튼 | UI_DESIGN_SPEC | `plan/question_claim_ui_design_specs_2026-02-27.md#ui-06` |
| Q2-C15 | questions/question2.md | export 기능 자체는 구현되어 있다 | 타당 | `modules/nf_orchestrator/assets/user_ui.docs_tree.js:881`, `:902`; `modules/nf_orchestrator/main.py:113`, `:1810`; `tests/test_nf_orchestrator_user_ui_contracts.py:52` | 없음 | [P3] 유지 | NO_ACTION | N/A |
| Q2-C16 | questions/question2.md | n~m episode chunk 지정 UX가 불명확하다 | 타당 | user_ui 범위 컨트롤 부재, `modules/nf_orchestrator/assets/user_ui.assistant.js`는 전체/변경구간 위주 실행 | 사용자 스코프 지정 불가 | [P1] 범위 선택기 + 실행 프리셋 | UI_DESIGN_SPEC | `plan/question_claim_ui_design_specs_2026-02-27.md#ui-04` |
| Q2-C17 | questions/question2.md | time_key/entity_id grouping 생성/승인 워크플로가 약하다 | 타당 | 서버 API는 존재: `modules/nf_orchestrator/main.py:95`~`:100`; user_ui는 필터 입력만: `modules/nf_orchestrator/user_ui.html:461`~`:465` | 생성/검증 단계 없음 | [P1] 추출-검토-승인 3단 UI | UI_DESIGN_SPEC | `plan/question_claim_ui_design_specs_2026-02-27.md#ui-03` |
| Q2-C18 | questions/question2.md | 타임라인 문서 지속 확장 편집 UX가 단절되어 있다 | 타당 | 타임라인 뷰는 메타 표시 중심: `modules/nf_orchestrator/assets/user_ui.docs_tree.js:191`~`:236`; 편집 컨텍스트 메뉴는 episode_no만: `:597`, `:651` | time_key/timeline_idx 편집 경로 부족 | [P1] 타임라인 메타 편집/승인 UI | UI_DESIGN_SPEC | `plan/question_claim_ui_design_specs_2026-02-27.md#ui-10` |
| Q2-C19 | questions/question2.md | 태깅 품질 진단(희소/중복/일관성) 피드백이 없다 | 타당 | 인라인 태깅 UI는 존재: `modules/nf_orchestrator/assets/user_ui.editor.js:1364`; 품질 진단 로직/UI 부재 | 태깅 품질 가이드 없음 | [P2] 태그 품질 리포트/권고 | UI_DESIGN_SPEC | `plan/question_claim_ui_design_specs_2026-02-27.md#ui-11` |
| Q2-C20 | questions/question2.md | API 키를 localStorage 평문 저장해 보안 UX가 취약하다 | 타당 | `modules/nf_orchestrator/assets/user_ui.bootstrap.js:13`, `:25`; `modules/nf_orchestrator/assets/user_ui.api.js:6`, `:7` | 민감정보 저장 정책 미흡 | [P1] OS 키링/토큰 수명 정책 | UI_DESIGN_SPEC | `plan/question_claim_ui_design_specs_2026-02-27.md#ui-08` |
| Q2-C21 | questions/question2.md | CHECK/PROPOSE 분리는 있으나 경계 정책 설명이 부족하다 | 부분 타당 | 모드 분리: `modules/nf_orchestrator/user_ui.html:436`, `:442`, `:446`; 정책 설명 UI는 제한적 | SLA/비용/정확도 안내 부족 | [P2] 모드별 정책 가이드 추가 | UI_DESIGN_SPEC | `plan/question_claim_ui_design_specs_2026-02-27.md#ui-12` |
| Q2-C22 | questions/question2.md | UNKNOWN 사유는 보이지만 다음 행동 가이드는 부족하다 | 타당 | 사유 표시는 존재: `modules/nf_orchestrator/assets/user_ui.assistant.js:691`, `:737`, `:898` | 사유->조치 매핑 부재 | [P1] 사유별 추천 액션 버튼 | UI_DESIGN_SPEC | `plan/question_claim_ui_design_specs_2026-02-27.md#ui-09` |

### 2.3 question3.md

| Claim ID | 원문 출처 | 주장 요약 | 판정 | 근거(코드/테스트) | 현재 구현 미비점 | 개선점 | 분류 태그 | 분리 문서 링크 또는 N/A |
|---|---|---|---|---|---|---|---|---|
| Q3-C01 | questions/question3.md | 설정/본문/구상/타임라인 흐름은 구현되어 있다 | 타당 | `modules/nf_orchestrator/user_ui.html:95`~`:105`, `modules/nf_orchestrator/assets/user_ui.docs_tree.js:170`~`:185` | 없음 | [P3] 유지 | NO_ACTION | N/A |
| Q3-C02 | questions/question3.md | EPISODE 트리 정렬/드래그 재배치는 구현되어 있다 | 타당 | `modules/nf_orchestrator/assets/user_ui.docs_tree.js:363`, `:365`, `:432`~`:480` | 없음 | [P3] 유지 | NO_ACTION | N/A |
| Q3-C03 | questions/question3.md | 에디터 레이아웃/페이지/상태바 UX가 구현되어 있다 | 타당 | `modules/nf_orchestrator/user_ui.html:317`, `:390`, `modules/nf_orchestrator/assets/user_ui.editor.js:201`, `:607`, `tests/test_nf_orchestrator_user_ui_contracts.py:170` | 없음 | [P3] 유지 | NO_ACTION | N/A |
| Q3-C04 | questions/question3.md | 작가 도우미(CHECK/SEARCH/PROPOSE)+필터/프리셋이 구현되어 있다 | 타당 | `modules/nf_orchestrator/user_ui.html:436`~`:465`, `modules/nf_orchestrator/assets/user_ui.state.js:318`~`:375`, `tests/test_nf_orchestrator_user_ui_contracts.py:70`, `:88` | 없음 | [P3] 유지 | NO_ACTION | N/A |
| Q3-C05 | questions/question3.md | verdict 하이라이트 + 인라인 액션이 구현되어 있다 | 타당 | `modules/nf_orchestrator/assets/user_ui.state.js:404`, `:478`, `:494`, `modules/nf_orchestrator/assets/user_ui.assistant.js:745`, `:1231`, `:1233` | 없음 | [P3] 유지 | NO_ACTION | N/A |
| Q3-C06 | questions/question3.md | jobs/consistency 상태 위젯이 구현되어 있다 | 타당 | `modules/nf_orchestrator/user_ui.html:197`, `:206`, `:245`, `:264`, `modules/nf_orchestrator/assets/user_ui.jobs.js:12` | 없음 | [P3] 유지 | NO_ACTION | N/A |
| Q3-C07 | questions/question3.md | 메모리 압력 이벤트(reason_code)는 워커/유저UI에 연동되어 있다 | 타당 | `modules/nf_workers/runner.py:73`, `:166`; `modules/nf_orchestrator/assets/user_ui.assistant.js:65`, `:66`; `modules/nf_orchestrator/user_ui.html:189` | 없음 | [P3] 유지 | NO_ACTION | N/A |
| Q3-C08 | questions/question3.md | 인라인 태그가 tag_assignment로 저장되는 UX 연결이 불명확하다 | 타당 | 태그 UI: `modules/nf_orchestrator/assets/user_ui.editor.js:1364`; user_ui에서 `/tags/assignments` 호출 부재(검색 결과 없음); ingest는 tag_assignment 읽음: `modules/nf_workers/runner.py:816` | UI 태그와 스키마 파이프라인 연결성 낮음 | [P1] 태그 저장 API 연동 + 저장 상태 표시 | IMPLEMENTATION_GAP | N/A |
| Q3-C09 | questions/question3.md | 타임라인 메타 편집(time_key/timeline_idx) UX가 부족하다 | 타당 | 타임라인 표시는 메타 기반: `modules/nf_orchestrator/assets/user_ui.docs_tree.js:196`, `:221`; 편집 메뉴는 episode_no 위주: `:597`, `:651` | time_key/timeline_idx 편집/검증 부재 | [P1] 메타 편집 폼 추가 | UI_DESIGN_SPEC | `plan/question_claim_ui_design_specs_2026-02-27.md#ui-10` |
| Q3-C10 | questions/question3.md | n~m 범위 분석 UX가 없다 | 타당 | user_ui 입력 컨트롤 부재, 실행 payload는 문서 전체/변경구간 중심: `modules/nf_orchestrator/assets/user_ui.assistant.js:606` | 범위 기반 분석 요청 불가 | [P1] 범위 선택 UI + 백엔드 입력 계약 연결 | UI_DESIGN_SPEC | `plan/question_claim_ui_design_specs_2026-02-27.md#ui-04` |
| Q3-C11 | questions/question3.md | deep/strict UI 카피가 실제 payload(`explicit_only`) 대비 과장될 수 있다 | 타당 | UI 카피: `modules/nf_orchestrator/user_ui.html:451`, `:454`; payload 고정: `modules/nf_orchestrator/assets/user_ui.assistant.js:332`, `:606`, `modules/nf_orchestrator/assets/user_ui.state.js:392` | 사용자 기대와 엔진 범위 차이 | [P1] 레벨별 실제 적용 범위 명시 | UI_DESIGN_SPEC | `plan/question_claim_ui_design_specs_2026-02-27.md#ui-12` |
| Q3-C12 | questions/question3.md | `handleExport` 중복 정의 + 로딩 순서 의존으로 충돌 위험이 있다 | 타당 | `modules/nf_orchestrator/assets/user_ui.docs_tree.js:881`, `modules/nf_orchestrator/assets/user_ui.editor.js:901`, 로딩 순서: `modules/nf_orchestrator/user_ui.html:560`, `:561`, `:564` | 함수명 충돌 잠재 리스크 | [P1] export 핸들러 단일화 | IMPLEMENTATION_GAP | N/A |
| Q3-C13 | questions/question3.md | 명시 슬롯(age/time/place/relation/affiliation/job/talent/death) 체계는 구현되어 있다 | 타당 | `modules/nf_consistency/extractors/contracts.py:8`, `modules/nf_consistency/engine.py:490` | 없음 | [P3] 유지 | NO_ACTION | N/A |
| Q3-C14 | questions/question3.md | 근거 표준화(doc/section/tag/snippet)는 구현되어 있다 | 타당 | `modules/nf_consistency/engine.py:324`, `modules/nf_orchestrator/services/query_service.py:163`, `modules/nf_orchestrator/assets/user_ui.assistant.js:920`, `:941` | 없음 | [P3] 유지 | NO_ACTION | N/A |
| Q3-C15 | questions/question3.md | 충돌 근거 시 UNKNOWN 처리 정책이 구현되어 있다 | 타당 | `modules/nf_consistency/engine.py:872`, `:2055`, `:2120` | 없음 | [P3] unknown taxonomy 유지/정교화 | NO_ACTION | N/A |
| Q3-C16 | questions/question3.md | 추출 기본 모드는 `rule_only`다 | 타당 | `modules/nf_consistency/extractors/contracts.py:80`, `modules/nf_workers/runner.py:315`, `:1464` | 기본 모드에서 recall 낮을 수 있음 | [P1] 프로젝트별 기본 profile 재설계 | PIPELINE_LOGIC_CHANGE | `plan/question_claim_pipeline_logic_proposals_2026-02-27.md#pl-01` |
| Q3-C17 | questions/question3.md | rule_only 규칙은 명시 키워드 패턴 의존이 커 저재현 위험이 있다 | 타당 | `modules/nf_consistency/extractors/rule_extractor.py:153`, `:160`, `:167`, `:188`; 테스트는 최소 계약만 보장: `tests/test_nf_consistency_extractors.py:53`, `:63` | 일반 서술형 문장 recall 한계 | [P1] hybrid 기본화/규칙 확장 | PIPELINE_LOGIC_CHANGE | `plan/question_claim_pipeline_logic_proposals_2026-02-27.md#pl-01` |
| Q3-C18 | questions/question3.md | hybrid_local/remote/dual은 존재하나 기본 사용자 플로우에서 활성화되지 않는다 | 타당 | 모드 정의: `modules/nf_consistency/extractors/contracts.py:29`; 입력은 옵션: `modules/nf_workers/runner.py:315`, `:1464`; user_ui에서 extraction 설정 UI 부재 | 고급 추출 활성 경로 미노출 | [P2] extraction profile 설정 UI/프로젝트 정책 추가 | PIPELINE_LOGIC_CHANGE | `plan/question_claim_pipeline_logic_proposals_2026-02-27.md#pl-01` |
| Q3-C19 | questions/question3.md | `explicit_only`는 REJECTED 제외(PROPOSED 포함)라 노이즈 가능성이 있다 | 타당 | `modules/nf_consistency/engine.py:719`, `:733`; 재현 테스트: `tests/consistency/test_scope_slots_core.py:157`, `:227`, `:228` | 미승인 팩트 영향 가능 | [P1] 승인도 기반 가중/게이트 | PIPELINE_LOGIC_CHANGE | `plan/question_claim_pipeline_logic_proposals_2026-02-27.md#pl-02` |
| Q3-C20 | questions/question3.md | time/entity/timeline 백엔드 기능 대비 user_ui 노출이 약하다 | 타당 | 백엔드 API: `modules/nf_orchestrator/main.py:95`~`:100`; user_ui는 필터 입력 중심: `modules/nf_orchestrator/user_ui.html:461`~`:465` | 기능 발견성/검증 루프 부족 | [P1] 생성-검토-승인 UI | UI_DESIGN_SPEC | `plan/question_claim_ui_design_specs_2026-02-27.md#ui-03` |
| Q3-C21 | questions/question3.md | verification loop 구조는 지연 리스크가 있다(중복: Q1-C15) | 타당 | 동일 근거: `modules/nf_consistency/engine.py:2158`, `:2176` | 지연 예산 정책 부족 | [P1] 라운드/시간 예산 기반 종료 | PIPELINE_LOGIC_CHANGE | `plan/question_claim_pipeline_logic_proposals_2026-02-27.md#pl-03` |
| Q3-C22 | questions/question3.md | INDEX_VEC가 존재해도 post-save 기본 파이프라인에는 포함되지 않는다 | 타당 | INDEX_VEC 핸들러 존재: `modules/nf_workers/runner.py:757`; post-save는 INGEST+INDEX_FTS: `modules/nf_orchestrator/assets/user_ui.assistant.js:245`, `:251` | 벡터 리콜 개선이 기본 흐름에서 비활성 | [P2] 조건부 INDEX_VEC 후처리 | PIPELINE_LOGIC_CHANGE | `plan/question_claim_pipeline_logic_proposals_2026-02-27.md#pl-06` |

## 3) 통합 매트릭스 요약

### 3.1 판정 집계

| 판정 | 건수 |
|---|---:|
| 타당 | 53 |
| 부분 타당 | 7 |
| 비타당 | 0 |

### 3.2 분류 태그 집계

| 분류 태그 | 건수 |
|---|---:|
| NO_ACTION | 20 |
| UI_DESIGN_SPEC | 20 |
| PIPELINE_LOGIC_CHANGE | 14 |
| IMPLEMENTATION_GAP | 6 |

## 4) 검증 시나리오별 판정 매핑

1. 신뢰성 점수 분해 노출: `Q1-C06`, `Q2-C07`  
2. whitelist/ignore 관리/undo: `Q1-C08`, `Q1-C12`, `Q2-C08`  
3. jobs retry mock 여부: `Q2-C05`  
4. time/entity/timeline 워크플로: `Q1-C07`, `Q2-C17`, `Q2-C18`, `Q3-C20`  
5. extraction 기본값(rule_only): `Q3-C16`, `Q3-C17`, `Q3-C18`  
6. explicit_only + PROPOSED 영향: `Q3-C19`  
7. post-save에 INDEX_VEC 포함 여부: `Q2-C03`, `Q3-C22`  
8. export 함수 충돌/로딩 순서 의존: `Q3-C12`  
9. 성능 절대수치의 정적 검증 한계: `Q1-C17`

## 5) 공용 API/인터페이스/타입 변경 영향
- 이번 작업은 문서화만 수행하므로 API/DTO/DB 스키마 변경 없음.

## 6) 가정 및 기본값(적용 결과)
1. 작성 언어는 한국어 사용.
2. 기존 문서는 보존하고 날짜 포함 신규 문서 생성.
3. 판정은 코드+테스트 근거 우선.
4. 정량 성능 수치는 정적 분석 한계가 있어 `부분 타당`으로 처리.
5. 코드 수정 없이 분석/문서화 범위로 제한.
