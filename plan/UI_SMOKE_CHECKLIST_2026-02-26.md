# user_ui 스모크 체크리스트 결과 (2026-02-26)

## 1) 실행 환경
- OS: Windows (로컬)
- 브라우저: Chrome Headless (Selenium)
- 기준 URL: `http://127.0.0.1:8085/`
- 스택 실행: `python run_local_stack.py --host 127.0.0.1 --port 8085 --no-worker`

## 2) 실행 로그 요약
- 계약/회귀 테스트:
  - `pytest -q tests/test_nf_orchestrator_user_ui_contracts.py`
  - 결과: `18 passed`
- 실기동 HTTP 스모크:
  - `/health`, `/`, `/assets/user_ui.api.js`, `/assets/user_ui.editor.js`
  - 문서 저장 라운드트립(개행 포함) 확인: `newline_roundtrip_ok = true`
- 실기동 브라우저 스모크(헤드리스):
  - `작가 도우미 open/X close/탭 전환 후 close/Esc close` 확인
  - 결과: `opened=true, closed=true, closeAfterTab=true, escClose=true`

## 3) 12개 테스트 케이스 결과

| ID | 시나리오 | 결과 | 근거 |
|---|---|---|---|
| 1 | 도우미 열기 후 X 클릭 시 닫힘 | PASS | Selenium DOM 실행 결과 `opened=true`, `closed=true` |
| 2 | 도우미 탭 전환 후 X 정상 동작 | PASS | Selenium DOM 실행 결과 `closeAfterTab=true` |
| 3 | `Esc` 입력 시 도우미 닫힘 | PASS | Selenium DOM 실행 결과 `escClose=true` |
| 4 | Enter 개행 저장/재로드 유지 | PASS (구현+경로검증) | `user_ui.editor.js` Enter 처리 추가 + 실기동 API 개행 라운드트립 성공 |
| 5 | 한글 IME 조합 중 Enter 확정 시 유실 없음 | PARTIAL | composition 분기 코드 반영 완료, 실제 IME 수동 타이핑 회귀는 브라우저 수동 검증 필요 |
| 6 | 텍스트 선택 시 빠른 태그 팝업이 선택 근처 표시 | PASS (구현검증) | 공통 좌표 헬퍼(`positionPopoverInMainContent`) 적용 |
| 7 | 에디터 스크롤 후 팝업 재호출 좌표 오차 없음 | PASS (구현검증) | `scroll/resize/layout-changed` 재배치 훅 연결 |
| 8 | 좌/우 사이드바 상태에서도 팝업 화면 이탈 없음 | PASS (구현검증) | 클램프/flip 계산 + `toggleLeftSidebar` 레이아웃 이벤트 연동 |
| 9 | 태그/메모 제거 팝업 위치 정합 | PASS (구현검증) | `repositionTagRemovePopover` + 공통 좌표 계산 적용 |
| 10 | 정합성 액션 팝업 위치 정합 | PASS (구현검증) | `repositionActionPopover` + 공통 좌표 계산 적용 |
| 11 | 자동저장/수동저장/Ctrl+S 회귀 없음 | PASS | 기존 계약 테스트 통과, 저장 경로 함수 변화 없음 |
| 12 | 내보내기/설정/메모 카드 편집 회귀 없음 | PASS | 기존 계약 테스트 통과, 관련 핸들러/계약 유지 |

## 4) 관찰된 리스크
- IME(한글 조합) 실사용 입력은 헤드리스 자동화만으로 완전 재현이 어려워 수동 최종 확인 1회 필요.
- 팝업 위치 케이스(매우 좁은 뷰포트/고배율/다중 모니터)는 추가 수동 교차 확인 권장.

## 5) 결론
- 보고된 3개 증상(`작가 도우미 X`, `Enter 개행`, `빠른 태그/메모 좌표`)에 대한 구조적 수정은 반영 완료.
- 계약 테스트 + 실기동 스모크 기준으로 주요 회귀는 미발견.
- IME 특이 케이스는 수동 최종 체크 권장(현재 판정 PARTIAL).
