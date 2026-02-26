# user_request.md 12항목 전수 판정 매트릭스 (2026-02-26)

## 판정 기준
- `충족`: 요구사항 핵심 동작이 코드/실기동 근거로 확인됨
- `부분`: 일부 경로는 구현되었으나 품질/운영/UX 또는 모델 고도화가 미완
- `미충족`: 핵심 경로가 아직 없음

## 전수 매트릭스

| ID | 요구사항 | 코드 근거 | UI 관찰 근거 | 판정 | 리스크 | 후속조치 |
|---|---|---|---|---|---|---|
| 1 | 설정/플롯/등장인물 문서 작성/분류 | `modules/nf_orchestrator/main.py`, `modules/nf_orchestrator/assets/user_ui.docs_tree.js` | 좌측 탭/문서 생성 경로 존재 | 충족 | 대규모 문서 운용 UX | 트리 필터/검색 UX 보강 |
| 2 | 문서 인덱싱/임베딩(RAG) | `modules/nf_workers/runner.py`, `modules/nf_retrieval/*` | 도우미 검색/잡 파이프라인 연결 | 충족 | 대규모 인덱싱 시간 | 백그라운드 상태 가시화 강화 |
| 3 | 정합성 세그멘트/근거/신뢰성/예외처리 | `modules/nf_consistency/engine.py`, `modules/nf_orchestrator/assets/user_ui.assistant.js` | verdict 카드/whitelist/ignore/액션 팝업 | 부분 | Layer3/고급 추론 품질 편차 | Layer3/NLI 품질 게이트 강화 |
| 4 | 문법 교정 강도 조절 | `modules/nf_workers/runner.py` (`PROOFREAD`), `user_ui.assistant.js` 제안 모드 | 도우미 교정/제안 UI 경로 존재 | 부분 | 강도별 품질 일관성 | 레벨별 룰셋/평가 기준 명시 |
| 5 | 에디터 자간/줄간격(레이아웃 설정) | `modules/nf_orchestrator/assets/user_ui.editor.js`, `user_ui.html` 설정 패널 | 슬라이더 즉시 반영 + 저장 유지 | 충족 | 브라우저별 폰트 렌더 차이 | Edge 교차 회귀 1회 |
| 6 | 개선 제안 + 근거 인용 + 신뢰성 | `modules/nf_workers/runner.py`, `user_ui.assistant.js` | 제안 카드 + citation 렌더 | 부분 | 생성 품질/근거 정밀도 | citation quality 규칙 강화 |
| 7 | txt/docx export | `modules/nf_orchestrator/assets/user_ui.editor.js` (`handleExport`) | 내보내기 모달/형식 선택 | 충족 | docx 변환 호환성 | 샘플 문서 교차 검증 |
| 8 | n~m episode chunk 구성 | `modules/nf_workers/runner.py`, `modules/nf_schema/chunking.py` | 에피소드 기반 문서 운용/검색 필터 경로 | 부분 | 사용성(옵션 노출) | 요청형 실행 UX 노출 |
| 8-1 | time_key/entity_id 기준 grouping/filter | `modules/nf_workers/runner.py`, `main.py`, `user_ui.assistant.js` 필터 입력 | entity/time/timeline 필터 입력 UI 존재 | 부분 | 사용자 안내 부족 | 필터 프리셋/결과 설명 추가 |
| 8-2 | 세계관 타임라인 문서 참조/확장 | `modules/nf_orchestrator/storage/db.py`, `user_ui.docs_tree.js` 타임라인 뷰 | TIMELINE 탭/메타 노출 | 부분 | 편집 워크플로 단절 | 타임라인 편집 UX 강화 |
| 9 | 룰 베이스 + 사용자 태깅 병행 | `user_ui.editor.js` 인라인 태그/메모, `nf_schema` 경로 | 드래그 태깅/메모 UI 제공 | 충족 | 태깅 품질 편차 | 태그 품질 진단(희소/중복) 추가 |
| 10 | 고용량 모델 선택적 사용/API 키 | `modules/nf_model_gateway/gateway.py`, `user_ui.html` 글로벌 설정 | API Key/모델 입력 모달 존재 | 충족 | 키 관리/보안 | 키링 저장 정책 도입 |
| 11 | 정합성 모델 vs 생성 모델 분리 | `modules/nf_model_gateway/gateway.py`, `modules/nf_workers/runner.py` | CHECK/PROPOSE 모드 분리 | 부분 | 경계 정책 문서화 부족 | 모드별 SLA/품질 지표 분리 |
| 12 | 3단 검증 + unknown 처리 | `modules/nf_consistency/engine.py`, `user_ui.assistant.js` unknown 표시 | UNKNOWN 사유/근거 상세 렌더 | 부분 | UNKNOWN 과다/설명 난해 | unknown reason taxonomy 정교화 |

## UI 직결 항목 vs 비직결 항목
- UI 직결(이번 수정 영향 큼): `3`, `5`, `9`, `10`
- 비직결(엔진/아키텍처 중심): `1`, `2`, `6`, `7`, `8`, `8-1`, `8-2`, `11`, `12`

## 이번 수정으로 해결된 항목
- `작가 도우미 X 닫기`:
  - `toggle` 단일 의존에서 `openRightSidebar/closeRightSidebar/toggleRightSidebar` 분리
  - 탭 전환 후에도 X 동작 유지, `Esc` 닫기 추가
- `switchAssistTab/switchNavTab` 전역 `event` 의존 제거:
  - `switchAssistTab(event, mode)`, `switchNavTab(event, type)`로 정리
- `빠른 태그/메모/액션 팝업 좌표`:
  - `positionPopoverInMainContent(...)` 공통 좌표/클램프/flip 적용
  - 스크롤/리사이즈/레이아웃 변경 재배치 훅 연결
- `Enter 개행`:
  - 페이지 경계 키 처리 내 Enter 경로 명시 처리
  - composition(IME) 분기 조건 명시

## 여전히 부분/미충족인 항목
- 부분: `3`, `4`, `6`, `8`, `8-1`, `8-2`, `11`, `12`
- 미충족: 없음

## 참고
- 세부 UI 스모크 결과: `verify/user_ui_smoke_checklist_2026-02-26.md`
- 구현/반영 베이스라인: `plan/IMPLEMENTATION_STATUS.md`, `plan/IMPLEMENTATION_CHECKLIST.md`
