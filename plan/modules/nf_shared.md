# nf-shared (공통 규격) — MoSCoW 구현 계획

본 문서는 공통 타입/DTO/에러/설정/직렬화 규격을 정의한다.

> 표기 규칙: ☐ TODO / ☑ Done / ◐ Partial(스텁/의도 미적용)

참조:

- `plan/contracts.md`
- `plan/architecture_1.md`
- `plan/architecture_2.md`

구현 순서(Phase, 전체 로드맵: `plan/IMPLEMENTATION_CHECKLIST.md`):

테스트는 conda의 `nf` 환경에서 수행한다.

- Phase 00에서 선행 구현(모든 모듈의 전제)
- 완료 기준: 계약 스모크 테스트(`tests/test_nf_shared_protocol.py`)가 통과

---

# [M] 필수 — 1차 배포(MVP+안정화)

## 0) 패키지/폴더 구조(플레이스홀더 기준)

```text
modules/nf_shared/
  __init__.py
  config.py
  errors.py
  logging.py
  protocol/
    __init__.py
    dtos.py
    serialization.py
```

## 1) 공통 DTO/Enum 확정(계약 v0)

* ☑ `plan/contracts.md`의 Enum/DTO를 코드 타입으로 고정
  - `JobType/JobStatus`, `Verdict`, `FactStatus/FactSource`, `SuggestMode` 등
* ☑ DTO는 “내부 타입 ↔ JSON” 변환을 지원

## 2) 직렬화/역직렬화 규격

* ☑ `to_json(obj) -> dict`, `from_json(type, dict) -> obj` 형태의 최소 API
* ☑ 타임스탬프(ISO-8601 UTC), UUID(string) 정규화
* ☑ 전방 호환성: unknown field 보관/무시 정책을 명시

## 3) 오류/예외 표준화

* ☑ `AppError(code, message, details)` 기본형 + 변환기
* ☑ HTTP API 오류 응답 포맷(`plan/contracts.md`)을 1차 기준으로 고정

## 4) 설정 스키마(최소)

* ☑ 정책 스위치를 하나의 설정 객체로 노출
  - 예: `enable_remote_api`, `enable_local_generator`, `sync_retrieval_mode=FTS_ONLY`, `vector_index_mode`, `explicit_fact_auto_approve`
* ☑ 로컬 파일 기반 설정 로딩(기본값 포함) + 환경변수 오버라이드(선택)

## 5) 테스트(pytest)

* ☑ `tests/test_nf_shared_protocol.py`: Enum/Settings 기본값, DTO 직렬화(dump/load) 왕복, AppError 응답 포맷

---

# [S] 권장 — 권장(안정성/유지보수)

* ☐ `dtos.py`를 “외부 계약(HTTP)”과 “내부 계약(모듈 간)”으로 파일 분리
* ☐ JSON 스키마(문서 생성) 자동화 스크립트(선택)
* ☑ 에러 코드 카탈로그(`ERRORS.md`) 추가

---

# [C] 선택 — 여유 시

* ☐ pydantic/dataclasses 선택에 따른 성능/유지보수 비교 문서화
* ☐ API 버전 협상(`X-Contracts-Version`) 도입

---

# [W] 현재 제외

* ☐ 외부 공개 SDK(별도 패키지로 배포)

---

## 계약 인터페이스(요약)

nf-shared는 다음 “계약 인터페이스”를 제공한다.

- `protocol.dtos`
  - `Project`, `Document`, `DocSnapshot`, `Episode`, `Chunk`, `Section`
  - `TagDef`, `TagAssignment`, `Entity`, `EntityAlias`
  - `SchemaVersion`, `SchemaFact`
  - `Evidence`, `VerdictLog`, `VerdictEvidenceLink`
  - `Job`, `JobEvent`
- `protocol.serialization`
  - `dump_json(obj)`, `load_json(type, data)`
- `errors`
  - `AppError`, `ErrorCode`(enum)
- `config`
  - `Settings`(policy switches + limits)
