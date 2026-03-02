# UI 운영 검증 분리 문서 (2026-02-28)

## 1) 목적
- claim 매핑 문서에서 UI 운영 검증 항목만 분리해 관리한다.
- 대상 Claim: `Q2-C12` (교차 브라우저 오프셋/하이라이트 회귀 검증)
- 기본 실행 경로: `tools/bench/run_user_delegated.cmd`

## 2) 통합 단계
1. Playwright preflight
- 명령: `python -c "import playwright; import playwright.sync_api"`
- 정책: import 실패 시 즉시 배치 실패

2. 3브라우저 회귀 실행
- 환경변수: `NF_RUN_BROWSER_TESTS=1`
- 명령: `python -m pytest -q tests/ui/test_editor_cross_browser_offsets_playwright.py -m browser`
- 대상 브라우저: Chromium, Firefox, WebKit

## 3) 통과 기준
1. preflight 성공
2. 회귀 테스트가 실패 없이 통과
3. 테스트 대상 시나리오에서 selection offset roundtrip 및 highlight 매칭 무결성 유지

## 4) 실패 대응
1. Playwright 미설치/브라우저 실행 불가
- 경고가 아니라 실패로 처리
- 배치를 중단하고 의존성 설치 후 재실행

2. 테스트 실패
- 즉시 실패
- `-StartStep` 재개 옵션으로 실패 step부터 재실행

## 5) 로그/아티팩트 경로
1. 배치 로그
- `verify/benchmarks/user_delegated_stack_<timestamp>_stdout.log`
- `verify/benchmarks/user_delegated_stack_<timestamp>_stderr.log`

2. 테스트 자산
- `tests/ui/test_editor_cross_browser_offsets_playwright.py`
- `tests/ui/fixtures/editor_harness.html`

## 6) 운영 메모
- `RunGraphProbeOnly` 모드는 기존 의미를 보존하기 위해 본 UI 운영 검증 단계를 실행하지 않는다.
- 일반 경로(`run_user_delegated.cmd` 기본 실행, `-RunRemainingMatrix`)에서는 운영 검증 단계가 항상 포함된다.
