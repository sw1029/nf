# nf-shared (공통 규격) — MoSCoW 구현 계획

본 문서는 공통 타입/DTO/에러/설정/직렬화 규격을 정의한다.

참조:

- `plan/contracts.md`
- `plan/architecture_1.md`
- `plan/architecture_2.md`

---

# [M] Must — 1차 배포(MVP+안정화)

## 0) 패키지/폴더 구조(placeholder 기준)

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

## 1) 공통 DTO/Enum 확정(Contracts v0)

* ☐ `plan/contracts.md`의 Enum/DTO를 코드 타입으로 고정
  - `JobType/JobStatus`, `Verdict`, `FactStatus/FactSource`, `SuggestMode` 등
* ☐ DTO는 “내부 타입 ↔ JSON” 변환을 지원

## 2) 직렬화/역직렬화 규격

* ☐ `to_json(obj) -> dict`, `from_json(type, dict) -> obj` 형태의 최소 API
* ☐ timestamp(ISO-8601 UTC), UUID(string) 정규화
* ☐ forward compatibility: unknown field는 보관하거나 무시 정책을 명시

## 3) 오류/예외 표준화

* ☐ `AppError(code, message, details)` 기본형 + 변환기
* ☐ HTTP API 오류 응답 포맷(`plan/contracts.md`)을 1차 기준으로 고정

## 4) 설정 스키마(최소)

* ☐ policy switches를 하나의 설정 객체로 노출
  - 예: `enable_remote_api`, `enable_local_generator`, `sync_retrieval_mode=FTS_ONLY`, `vector_index_mode`, `explicit_fact_auto_approve`
* ☐ 로컬 파일 기반 config 로딩(기본값 포함) + 환경변수 override(선택)

## 5) 테스트(pytest)

* ☐ `tests/test_nf_shared_protocol.py`: Enum/Settings 기본값, DTO 직렬화(dump/load) round-trip, AppError 응답 포맷

---

# [S] Should — 권장(안정성/유지보수)

* ☐ `dtos.py`를 “외부 계약(HTTP)”과 “내부 계약(모듈 간)”으로 파일 분리
* ☐ JSON Schema(문서 생성) 자동화 스크립트(선택)
* ☐ 에러 코드 카탈로그(`ERRORS.md`) 추가

---

# [C] Could — 여유 시

* ☐ pydantic/dataclasses 선택에 따른 성능/유지보수 비교 문서화
* ☐ API 버전 협상(`X-Contracts-Version`) 도입

---

# [W] Won’t (now)

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
