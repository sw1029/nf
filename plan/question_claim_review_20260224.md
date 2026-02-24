# question.md 주장 검증 보고서 (2026-02-24)

## 목적
- `question.md`의 주장 타당성을 현재 코드 기준으로 재검증한다.
- 즉시 반영(비디자인)과 후속 이관(디자인) 범위를 명확히 분리한다.

## 주장별 판정
1. `타당` FTS/Vector 점수 체계 혼합 문제
- 근거: `modules/nf_consistency/engine.py`
- 반영: retrieval 점수를 source 무관 [0,1] 정규화 강도로 통일해 신뢰도 계산/승격 게이트에 일관 적용.

2. `타당` retrieval evidence의 `confirmed`가 사실상 false 고정
- 근거: `modules/nf_retrieval/fts/fts_index.py`, `modules/nf_retrieval/vector/manifest.py`
- 반영: 엔진에서 검색 결과 후처리로 사용자 태그/승인 근거 span 중첩 시 `confirmed=true` 승격.

3. `타당` UI `GET /jobs?limit=5` 호출 vs 서버 미지원
- 근거: `modules/nf_orchestrator/user_ui.html`, `modules/nf_orchestrator/main.py`
- 반영: `GET /jobs` 구현(프로젝트/limit 지원), UI 호출도 `project_id` 포함 형태로 정합화.

4. `타당` Export 결과 전달 계약 부재
- 근거: `modules/nf_workers/runner.py`, `modules/nf_orchestrator/storage/repos/job_repo.py`, `modules/nf_shared/protocol/dtos.py`
- 반영: `jobs.result_json` 저장, `Job.result` DTO 확장, `GET /jobs/{job_id}/artifact` 다운로드 API 추가, UI 다운로드 경로 연동.

5. `타당` TIMELINE 탭 문서 생성 타입 불일치 위험
- 근거: `modules/nf_orchestrator/user_ui.html`, `modules/nf_shared/protocol/dtos.py`
- 반영: TIMELINE 탭에서 신규 문서 생성 시 서버 허용 타입(`EPISODE`)으로 가드.

6. `타당` PROPOSE 탭 UI 대비 실제 SUGGEST 분기 미구현
- 근거: `modules/nf_orchestrator/user_ui.html`
- 반영: PROPOSE 모드에서 `SUGGEST` job 제출/대기/결과 렌더링(근거 포함) 구현.

7. `타당` 변경 구간 감지의 offset 키 의존으로 대규모 재검사 위험
- 근거: `modules/nf_orchestrator/user_ui.html`
- 반영: `(start,end)` 키 비교를 fingerprint 기반 안정 매칭(중복 대응 포함)으로 교체.

8. `부분 타당` 프로세스 분리 이슈
- 근거: `modules/nf_orchestrator/main.py`, `run_debug_ui.py`, `run_local_stack.py`
- 반영: `run_debug_ui.py`를 외부 worker process 실행 + `run_orchestrator(..., start_worker=False)` 구조로 통일.

9. `부분 타당` 화이트리스트 의미 분류 구조 저장 미흡
- 근거: `modules/nf_orchestrator/storage/repos/whitelist_repo.py`, `modules/nf_orchestrator/main.py`
- 반영: `whitelist_annotation` 테이블 및 API/서비스 확장(`intent_type`, `reason`, `meta`) 반영.

10. `타당(디자인 후속)` 시간축 타임라인/드래그 태깅 위젯 부재
- 근거: `modules/nf_orchestrator/user_ui.html`
- 반영 여부: 이번 사이클 제외(비디자인 우선). 후속 문서로 분리.

## 이번 사이클 반영 범위
- DB/DTO/API 계약 정합화
- 워커 결과 저장/EXPORT 다운로드 경로 확립
- consistency 신뢰도/confirmed 실효성 보강
- 사용자 UI 비디자인 계약 정합화(PROPOSE, jobs 패널, export, timeline type guard, 변경감지)
- 실행 스크립트 워커 분리 정리

## 후속 이관 범위 (디자인 변경)
- 세계관 시간축 타임라인 위젯
- 드래그 기반 태깅 위젯
- 인라인 플로팅 액션 등 인터랙션 디자인 확장
- 상세 요구사항은 `plan/ui_design_followup_requirements_20260224.md` 참고
