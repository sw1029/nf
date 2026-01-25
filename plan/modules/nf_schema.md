# nf-schema (스키마/정규화/오염 방지) — MoSCoW 구현 계획

nf-schema는 문서/태그/엔티티를 바탕으로 스키마 버전과 팩트(명시/암시)를 생성하고, 승인/거절 워크플로를 지원한다.

참조:

- `plan/contracts.md`
- `plan/architecture_2.md` (schema_version/fact/entity/chunk)
- `plan/DECISIONS_PENDING.md` (D2, D3)

구현 순서(Phase, 전체 로드맵: `plan/IMPLEMENTATION_CHECKLIST.md`):

- Phase 30: Chunk/Section 생성 최소 구현(FTS 인덱싱 전제)
- Phase 50: tags/entity/alias + fact/schema_version 생성(INGEST) + 승인 워크플로(D2/D3)

---

# [M] Must — 1차 배포(MVP+안정화)

## 0) 패키지/폴더 구조(placeholder 기준)

```text
modules/nf_schema/
  __init__.py
  ontology/
    base_tags.yaml
  parser/
    markup_parser.py
    episode_chunker.py
  extraction/
    explicit_fields.py
    implicit_fields.py
  normalize/
    units.py
    identity.py
  gating/
    validators.py
    conflict.py
  versioning/
    schema_version.py
```

## 1) Ontology/Tag 시스템

* ☐ `tag_path` 규격 고정(“설정/인물/주인공/나이”)
* ☐ 기본 태그(def) + 사용자 정의 태그 지원
* ☐ tag_def constraints(schema_type/범위/enum)를 저장/검증

## 2) Chunk/Section 생성(인덱싱 키)

* ☐ 입력: `DocumentSnapshot`(텍스트)
* ☐ 출력: `Chunk[]`(span 기반), 필요 시 `Section[]`
* ☐ chunk는 FTS/Vector 공통 키(`chunk_id`)로 사용(`plan/contracts.md`)

## 3) Entity/Identity (D2: 옵션2 우선)

* ☐ `entity`/`entity_alias`를 MVP부터 사용
* ☐ identity 해석 기본 정책:
  - tag_path에서 추정되는 엔티티 후보를 `entity`로 정규화(가능하면)
  - alias 매칭은 보수적: 다의성/충돌 시 entity_id 미지정(null) 또는 UNKNOWN 강등
* ☐ 사용자 주도 alias 관리(오케스트레이터 UI/서비스를 통한 CRUD)

## 4) Fact 생성/승인 정책 (D3)

* ☐ explicit/implicit 모두 `FactStatus`를 가진다
* ☐ `AUTO` fact는 기본 `PROPOSED`로 저장(유저 승인 필요)
* ☐ `USER` 근거(태깅/입력 기반)는 `APPROVED`로 저장(기본)
* ☐ `SchemaVersion` 생성 시 `source_snapshot_id`를 저장하여 재현성 확보

## 5) 명시 필드 추출(High precision, Low recall)

* ☐ 최소 필드: 나이/시간/장소/관계/사망 여부/소속
* ☐ 단위/형식 정규화: `units.py`
* ☐ 근거는 반드시 `Evidence`로 연결(evidence_required)

## 6) 암시/추정 레이어

* ☐ 기본값 unknown 허용
* ☐ 자동 확정 금지: `PROPOSED`로만 저장

## 7) Gating/Conflict

* ☐ validators: 타입/범위/누락/상호제약
* ☐ conflict: 충돌 시 unknown/PROPOSED 강등 규칙

## 8) 테스트(pytest)

* ☐ `tests/test_nf_schema_policy.py`: AUTO fact는 PROPOSED 강제(D3)
* ☐ (차순위) chunk 생성(span) 단위 테스트
* ☐ (차순위) identity/alias 매칭 보수성 테스트(충돌 시 null/unknown)

---

# [S] Should — 권장

* ☐ entity resolution 규칙 세분화(동명이인/호칭 변화)
* ☐ schema 마이그레이션(버전 간 필드 변화) 자동화

---

# [C] Could — 여유 시

* ☐ explicit_fact_auto_approve 스위치(기본 off; 차순위/선택 구현)

---

# [W] Won’t (now)

* ☐ 공격적(aggressive) identity 병합(오염 위험)

---

## 계약 인터페이스(요약)

- Inputs:
  - `DocumentSnapshot`, `TagAssignment[]`, `Entity/EntityAlias`(조회)
- Outputs:
  - `SchemaVersion`, `SchemaFact[]`(explicit/implicit), `Chunk[]`, `Evidence[]`
- Invariants:
  - `AUTO` fact는 `PROPOSED`
  - `Evidence`는 `snapshot_id/chunk_id`를 포함(가능하면)

---

## 계약 인터페이스(상세; 구현 기준)

```python
class Chunker(Protocol):
    def build_chunks(self, snapshot: DocSnapshot) -> list[Chunk]: ...

class IdentityResolver(Protocol):
    def resolve_entity(self, project_id: ProjectID, name: str, *, kind: str | None) -> EntityID | None: ...

class FactExtractor(Protocol):
    def extract_explicit(self, snapshot: DocSnapshot, assignments: list[TagAssignment]) -> list[SchemaFact]: ...
    def extract_implicit(self, snapshot: DocSnapshot) -> list[SchemaFact]: ...
```

### Fact 생성 규칙(고정)

- `source=AUTO` → `status=PROPOSED`
- `source=USER` → `status=APPROVED` (기본)
- 충돌 시: 해당 fact 또는 관련 fact를 `PROPOSED`로 강등하거나 `value=unknown`으로 저장
