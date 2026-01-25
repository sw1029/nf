# nf-desktop (Windows UI) — MoSCoW 구현 계획

nf-desktop은 사용자의 글 작성 흐름을 담당하며, 오케스트레이터와 IPC로 통신한다.

핵심 정책:

- D1: 자간/줄간격은 **레이아웃 설정**, 문법(띄어쓰기/문장부호)은 **Proofread**로 분리, 실행은 **실시간 표시**
- D5: 검색은 **FTS-only sync**, Vector는 `RETRIEVE_VEC` job + 스트리밍

참조:

- `plan/contracts.md`
- `plan/architecture_2.md` (프로세스 구조, API)
- `plan/DECISIONS_PENDING.md`

구현 순서(Phase, 전체 로드맵: `plan/IMPLEMENTATION_CHECKLIST.md`):

- Phase 30 이후: OrchestratorClient/SSE 구독 + Job Panel 최소 연결(관찰 목적)
- Phase 50: Tagging/Schema Review UI(승인 워크플로)
- Phase 60: Result Panel(Verdict+Evidence+Breakdown) 렌더링
- Phase 70: Vector 확장 버튼 → `RETRIEVE_VEC` job + 스트리밍 결과 표시(D5)
- Phase 90: Export 트리거 + Proofread(rule-base 실시간 표시, D1) 마감
- Phase 95: 제품 흐름 통합/마감(패키징/배포)

---

# [M] Must — 1차 배포(MVP+안정화)

## 0) 화면/기능 구성

* ☐ Editor
  - 열기/저장/편집
  - 구간 선택(range)
* ☐ Layout Settings (D1)
  - 자간/줄간격 UI 제공(레이아웃)
* ☐ Tagging
  - 드래그 후 태그 부여(tag_path)
  - 태그 경로 표시/필터링
* ☐ Proofread (D1)
  - 문법(띄어쓰기/문장부호 포함) rule-base 실시간 표시(underline + tooltip)
  - 강도(레벨) 조절
* ☐ Result Panel
  - Verdict + Evidence + Reliability breakdown 렌더링
* ☐ Job Panel
  - 상태/진행률/취소/재시도
  - 이벤트 스트리밍 표시(SSE)
* ☐ Schema Review (D3)
  - AUTO=PROPOSED fact 승인/거절/보류 UI
* ☐ Retrieval UI (D5)
  - Sync 검색은 FTS-only
  - “Vector 확장” 버튼 → `RETRIEVE_VEC` job 생성 + 스트리밍 결과 표시
* ☐ Settings
  - API 키(opt-in)
  - 로컬 모델 다운로드(차순위 기능의 토글은 노출 가능)
* ☐ Export
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

* ☐ `tests/test_nf_desktop_contracts.py`: OrchestratorClient/ProofreadRuleEngine 계약 스모크
* ☐ (차순위) UI 로직(뷰모델) 단위 테스트(가능한 범위)
* ☐ (차순위) orchestrator client 요청/응답 파싱 테스트

---

# [S] Should — 권장

* ☐ Lint/Proofread 결과에 “unknown/보류” 사유 표준 문구 제공
* ☐ 반복 제안 억제 UI(whitelist/ignore)
* ☐ 대용량 문서에서도 UI 프리징 방지(비동기 렌더링)

---

# [C] Could — 여유 시

* ☐ 문서/에피소드 분석 대시보드(사건 밀도/등장인물 분포 등)

---

# [W] Won’t (now)

* ☐ 클라우드 동기화/계정 시스템

---

## 계약 인터페이스(상세; 구현 기준)

```python
from typing import Iterator, Protocol


class OrchestratorClient(Protocol):
    def post_query_retrieval_fts(self, pid: str, query: str, filters: dict, k: int) -> list[dict]: ...
    def submit_job(self, pid: str, job_type: str, inputs: dict, params: dict) -> dict: ...
    def stream_job_events(self, job_id: str) -> Iterator[dict]: ...

class ProofreadRuleEngine(Protocol):
    def lint(self, text: str) -> list[dict]: ...  # spans + message + severity
```

UI는 “vector 확장”을 직접 호출하지 않고 `RETRIEVE_VEC` job을 생성한다(D5).
