# 제품 UI 연동 Helper 구현 계획 — MoSCoW

이 문서는 `nf-desktop`(추후 제품 UI)가 오케스트레이터(loopback HTTP)와 통신할 때 사용할 **공용 helper(클라이언트) 레이어**의 구현 계획이다.

목표:

- UI 코드에서 API 호출/에러 처리/SSE 스트리밍 처리를 일관되게 재사용한다.
- 토큰/민감정보 로깅 실수를 줄이고, UI ↔ 서버 계약 변경에 대한 영향 범위를 최소화한다.
- (선택) `modules/nf_orchestrator/debug_ui.html`에 있는 “임시 호출 코드”를 점진적으로 helper로 이전할 수 있게 한다.

비목적:

- 제품 UI(화면/UX) 구현 자체.
- 원격 접근/인증 시스템(오케스트레이터는 기본 loopback 전용).

---

## 전제 / 현 상태

- 서버: `modules/nf_orchestrator/main.py`의 loopback HTTP API(+ SSE).
- 임시 UI: `modules/nf_orchestrator/debug_ui.html`에서 직접 `fetch`/`EventSource`로 호출.
- 계약(참조): `plan/contracts.md`(엔드포인트/DTO/잡/SSE 이벤트 형태).

---

## MoSCoW

### [M] Must (반드시)

- 단일 설정 객체
  - `baseUrl`(기본 `http://127.0.0.1:8080`), `apiToken`(옵션), `debugToken`(옵션), 타임아웃/재시도 정책을 한 곳에서 관리
- 공통 요청 래퍼
  - JSON 요청/응답 파싱, HTTP 오류를 `ErrorCode`/메시지 형태로 정규화(서버 `{"error": {...}}` 포맷 우선)
  - 요청 헤더 자동 주입(`Authorization` 또는 `X-NF-Token`, 디버그는 `X-NF-Debug-Token`)
  - 민감정보 마스킹/로깅 훅(토큰, API 키 문자열 등)
- 핵심 API 메서드(최소 기능 세트)
  - Health / Projects / Documents / Tags / Jobs / Query(retrieval, evidence, verdicts)
  - UI에서는 “엔드포인트 문자열” 대신 메서드 호출만 사용하도록 유도
- SSE helper(잡 이벤트)
  - `connect(jobId, lastEventId?)`, `onEvent(cb)`, `onError(cb)`, `close()` 등 최소 인터페이스
  - 재연결 시 `Last-Event-ID` 이어받기 지원(브라우저 `EventSource`의 한계를 감안해 쿼리 파라미터 방식도 지원)
- 크로스 런타임 지원(Import 분기)
  - **브라우저**(제품 UI)에서는 `fetch`/`EventSource` 사용
  - **테스트/노드 런타임**(예: 빌드/테스트 도구)에서는 `fetch` 폴리필/대체 구현을 조건부 import로 분기
  - 플랫폼 차이(Windows/Linux)는 “경로/파일 다운로드/URL 오픈” 같은 주변 기능에서만 분기
- 최소 테스트
  - transport를 mock/stub 가능한 구조로 만들고, 요청/에러 정규화/SSE 재연결 로직을 단위 테스트

### [S] Should (권장)

- 응답 스키마 검증
  - 런타임 검증(예: Python이면 `pydantic`, TS면 `zod`)으로 서버 계약 변화 조기 감지
- Abort/Cancel 지원
  - 긴 요청/스트리밍에 대해 취소(AbortController 등) 인터페이스 제공
- 다운로드/내보내기 UX 지원
  - `EXPORT` 결과의 `artifact_path`를 “열기/폴더 열기/다운로드”로 연결하는 helper(플랫폼별 분기 포함)
- 리트라이/백오프 정책(제한적)
  - 네트워크 단절/일시 오류에 한해 짧은 백오프(멱등 요청만)
- 관측성(옵션)
  - “요청 로그”를 구조화된 이벤트로 내보내 UI에서 보기 쉽게 연결

### [C] Could (있으면 좋음)

- OpenAPI 기반 코드 생성
  - `openapi.json`을 단일 소스로 삼아 client/DTO를 생성(계약 동기화 비용 감소)
- 스트리밍 조립 도우미
  - `RETRIEVE_VEC`/`SUGGEST`처럼 조각 payload를 누적해 최종 결과로 변환하는 aggregator 제공
- 캐시/중복 요청 제어
  - 프로젝트 목록/설정 스냅샷 등 단기 캐시
- CLI 디버그 도구
  - 제품 UI 없이도 helper로 주요 호출을 재현하는 CLI(개발 생산성)

### [W] Won’t (지금은 하지 않음)

- 원격 접근/다중 사용자 인증 체계(오케스트레이터는 loopback 고정 원칙 유지)
- UI 컴포넌트/상태관리 프레임워크 강제(React/Vue/Electron 등 선택은 별도)
- 모델/프롬프트 정책 자체를 UI helper에서 해결(방어는 서버에서 우선)

---

## 제안 구조(초안)

- `modules/nf_desktop/` 하위에 UI 전용 패키지로 시작 후, 필요 시 별도 모듈로 분리
  - `modules/nf_desktop/api_client/`
    - `client.py|ts`: 공통 요청 래퍼 + 엔드포인트 메서드
    - `sse.py|ts`: SSE helper
    - `types.py|ts`: DTO 타입(또는 생성물)
    - `transport_*.py|ts`: 런타임별(브라우저/노드) import 분기
    - `masking.py|ts`: 민감정보 마스킹/로깅 훅

---

## 단계적 적용(권장)

1) Must 최소 세트부터 구현(요청 래퍼 + Projects/Jobs + SSE)
2) `debug_ui.html`의 호출 코드를 helper 방식으로 대체 가능한 단위부터 점진 이전
3) Should 항목(스키마 검증/다운로드/Abort)을 제품 UI 요구사항에 맞춰 확장

