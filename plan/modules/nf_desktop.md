# nf-desktop (윈도우 UI) — MoSCoW 구현 계획

nf-desktop은 사용자의 글 작성 흐름을 담당하며, 오케스트레이터와 IPC로 통신한다.

> 표기 규칙: ☐ TODO / ☑ Done / ◐ Partial(스텁/의도 미적용)

핵심 정책:

- D1: 자간/줄간격은 **레이아웃 설정**, 문법(띄어쓰기/문장부호)은 **문법 교정**으로 분리, 실행은 **실시간 표시**
- D5: 검색은 **FTS-only 동기**, 벡터는 `RETRIEVE_VEC` 잡 + 스트리밍

참조:

- `plan/contracts.md`
- `plan/architecture_2.md` (프로세스 구조, API)
- `plan/DECISIONS_PENDING.md`

구현 순서(Phase, 전체 로드맵: `plan/IMPLEMENTATION_CHECKLIST.md`):

테스트는 conda의 `nf` 환경에서 수행한다.

- Phase 30 이후: 오케스트레이터 클라이언트/SSE 구독 + 잡 패널 최소 연결(관찰 목적)
- Phase 50: 태깅/스키마 리뷰 UI(승인 워크플로)
- Phase 60: 결과 패널(Verdict+Evidence+Breakdown) 렌더링
- Phase 70: 벡터 확장 버튼 → `RETRIEVE_VEC` 잡 + 스트리밍 결과 표시(D5)
- Phase 90: 내보내기 트리거 + 문법 교정(규칙 기반 실시간 표시, D1) 마감
- Phase 95: 제품 흐름 통합/마감(패키징/배포)

---

# [M] 필수 — 1차 배포(MVP+안정화)

## 0) 화면/기능 구성

* ☐ 에디터
  - 열기/저장/편집
  - 구간 선택(range)
* ☐ 레이아웃 설정 (D1)
  - 자간/줄간격 UI 제공(레이아웃)
* ☐ 태깅
  - 드래그 후 태그 부여(tag_path)
  - 태그 경로 표시/필터링
* ☐ 문법 교정 (D1)
  - 문법(띄어쓰기/문장부호 포함) 규칙 기반 실시간 표시(밑줄 + 툴팁)
  - 강도(레벨) 조절
* ☐ 결과 패널
  - Verdict + Evidence + Reliability breakdown 렌더링
* ☐ 잡 패널
  - 상태/진행률/취소/재시도
  - 이벤트 스트리밍 표시(SSE)
* ☐ 스키마 리뷰 (D3)
  - AUTO=PROPOSED fact 승인/거절/보류 UI
* ☐ 검색 UI (D5)
  - Sync 검색은 FTS-only
  - (추가 요구) 필터: tag_path/section/episode + 인물(entity_id) + 시점(time_key/timeline_idx)
  - “벡터 확장” 버튼 → `RETRIEVE_VEC` 잡 생성 + 스트리밍 결과 표시
  - (추가 요구) “시점/인물 그룹 생성” 버튼(사용자 요청 시): `INDEX_FTS` + `params.grouping`로 메타 생성
  - (추가 요구) 세계관 타임라인 문서 지정/편집 + `timeline_event` 검토(승인/조정)
* ☐ 설정
  - API 키(옵트인)
  - 로컬 모델 다운로드(차순위 기능의 토글은 노출 가능)
* ☐ 내보내기
  - txt/docx 내보내기 트리거

## 1) Orchestrator 연동(계약)

* ☐ `plan/contracts.md`의 HTTP API를 클라이언트로 구현
* ☐ SSE 구독: `/jobs/{jid}/events`
* ☐ 오류 UX: 네트워크(로컬) 장애/권한/유효성 에러 표준 표시

## 2) UI 내부 구조(권장)

```text
modules/nf_desktop/
  app.py
  ui/
    editor_view.py
    tagging_view.py
    proofread_view.py
    schema_review_view.py
    retrieval_view.py
    jobs_view.py
    settings_view.py
  viewmodels/
    editor_vm.py
    jobs_vm.py
    retrieval_vm.py
  client/
    orchestrator_client.py
    sse_client.py
  rules/
    proofread_rules.py
```

## 3) 테스트(pytest)

* ☑ `tests/test_nf_desktop_contracts.py`: OrchestratorClient/ProofreadRuleEngine 계약 스모크
* ☐ (차순위) UI 로직(뷰모델) 단위 테스트(가능한 범위)
* ☐ (차순위) 오케스트레이터 클라이언트 요청/응답 파싱 테스트

---

# [S] 권장 — 권장

* ☐ Lint/문법 교정 결과에 “unknown/보류” 사유 표준 문구 제공
* ☐ 반복 제안 억제 UI(whitelist/ignore)
* ☐ 대용량 문서에서도 UI 프리징 방지(비동기 렌더링)

---

# [C] 선택 — 여유 시

* ☐ 문서/에피소드 분석 대시보드(사건 밀도/등장인물 분포 등)

---

# [W] 현재 제외

* ☐ 클라우드 동기화/계정 시스템

---

## 계약 인터페이스(상세; 구현 기준)

```python
from typing import Iterator, Protocol


class OrchestratorClient(Protocol):
    def post_query_retrieval_fts(self, project_id: str, query: str, filters: dict, k: int) -> list[dict]: ...
    def submit_job(self, project_id: str, job_type: str, inputs: dict, params: dict) -> dict: ...
    def stream_job_events(self, job_id: str) -> Iterator[dict]: ...

class ProofreadRuleEngine(Protocol):
    def lint(self, text: str) -> list[dict]: ...  # spans + message + severity
```

UI는 “벡터 확장”을 직접 호출하지 않고 `RETRIEVE_VEC` 잡을 생성한다(D5).
