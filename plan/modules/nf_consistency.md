# nf-consistency (정합성 엔진) — MoSCoW 구현 계획

nf-consistency는 원고 구간을 세그먼트로 나누고, 근거(Evidence)를 구성한 뒤, 계층형 판정으로 판정(Verdict)과 로그를 저장한다.

> 표기 규칙: ☐ TODO / ☑ Done / ◐ Partial(스텁/의도 미적용)

참조:

- `plan/contracts.md`
- `plan/architecture_2.md` (6단계 파이프라인)

구현 순서(Phase, 전체 로드맵: `plan/IMPLEMENTATION_CHECKLIST.md`):

테스트는 conda의 `nf` 환경에서 수행한다.

- Phase 60에서 구현(선행: Phase 30 FTS 검색, Phase 50 스키마 승인 뷰)
- 1차는 L1/L2 보수적 판정 + evidence_required 준수(근거 없으면 unknown)

---

# [M] 필수 — 1차 배포(MVP+안정화)

## 0) 패키지/폴더 구조(플레이스홀더 기준)

```text
modules/nf_consistency/
  __init__.py
  segment/
    segmenter.py
    claim_extractor.py
  evidence/
    builder.py
  judge/
    layer1_explicit.py
    layer2_heuristic.py
    layer3_model.py
  scoring/
    reliability.py
  whitelist/
    policy.py
  output/
    verdict.py
```

## 1) Segment/Claim 추출

* ◐ 문장/절 세그먼트 분리 (현재는 줄바꿈 기반; 문장부호/절 기반으로 개선 필요)
* ☑ 하드 필드 힌트 기반 클레임 후보 추출(시간/나이/장소/관계 키워드)
* ☑ 출력: `(segment_span, claim_text, slots)` 리스트

## 2) Evidence Builder (근거 강제)

* ☑ 기본: FTS로 evidence를 구성(정확 인용) (tag_path 전파 지원; 태깅 없으면 빈 값 가능)
* ☑ 잡 내부에서는 필요 시 벡터 확장 가능(무거운 잡 경로)
  - 단, “근거 부재를 모델로 뒤집지 못함” 정책 유지
* ☑ Evidence는 `snapshot_id/chunk_id` 포함(가능하면)
* ☑ 성능 보강: claim 정규화 키 기반 retrieval LRU cache(기본 256) + 재조회 제거

## 3) Judge Layer 1 (명시만)

* ◐ schema_explicit_fact(승인된 것)과 비교하여 위배 감지 (현재는 최소 규칙 기반 비교)
* ◐ 위배 시: `tag_path` + Evidence 스니펫을 반드시 포함 (현재 Evidence 스니펫은 저장, tag_path는 전파 경로에 따라 비어 있을 수 있음)

## 4) Judge Layer 2 (휴리스틱, 보수적)

* ☑ alias/정규화/약한 동일성 처리(충돌 시 unknown)
* ☑ entity_id 불명확 시 unknown 우선
* ☑ fact 선형 스캔 제거: `(slot_key, entity_id|*)` 인덱스 기반 판정

## 5) Judge Layer 3 (옵션 경로; 구조는 Must)

* ☑ 호출 조건 게이트:
  - 사용자 활성화
  - L1/2 결론 불가
  - evidence 존재
* ☑ 모델 점수는 breakdown에만 반영(과신 방지)

## 6) Whitelist

* ☑ claim_fingerprint 계산 + whitelist_applied 기록(최소) (재경고 억제 로직은 구현, 제품 UI/UX는 차순위)
* ☑ whitelist scope(global/doc 단위) 정책 적용(정합성(CONSISTENCY)에서 동일 지문 재경고 억제: whitelist/ignore 시 skip)
* ☑ verdict_log에 claim_fingerprint(whitelist/ignore 연계)
* ◐ whitelist 적용 시 결과를 “오류→추가정보”로 표기할 수 있는 상태 필드 유지 (필드는 존재, UI 표기/억제는 미구현)

## 7) Verdict Logging

* ☑ `VerdictLog` + `VerdictEvidenceLink` 저장 계약 준수
* ☑ schema_ver/input_snapshot_id를 함께 기록(재현성)

## 8) 테스트(pytest)

* ☑ `tests/test_nf_consistency_contracts.py`: ConsistencyRequest/ConsistencyEngine 계약 스모크
* ☑ L1 위배 감지/OK/UNKNOWN 스모크(간단 schema + claim): `tests/test_nf_consistency_engine.py`
* ◐ DS-200 성능 게이트: `consistency_p95 <= 5.0s` 목표(중간 게이트)
* ◐ DS-800 성능 게이트: `consistency_p95 <= 6.0s` 목표(중간 게이트)
* ☐ (차순위) 충돌/애매(동명이인/alias) 시 unknown 강등 테스트
* ☐ (차순위) whitelist 적용 시 재경고 억제 테스트

---

# [S] 권장 — 권장

* ☑ 신뢰도 보정(보수적)
* ☐ Unknown 사유 표준 문구(UX)

---

# [C] 선택 — 여유 시

* ☐ 팩트/이벤트 기반 제약 검사(문장 비교 대체) 실험

---

# [W] 현재 제외

* ☐ 암시 레이어를 자동 확정하여 스키마 반영

---

## 계약 인터페이스(요약)

- 입력: `project_id + input_doc_id + input_snapshot_id + range + schema_ver`
- 출력: `VerdictLog[]` + `JobEvent` 스트리밍
- 불변 조건: Claim–Evidence–Verdict, unknown 허용, evidence_required

---

## 계약 인터페이스(상세; 구현 기준)

```python
from typing import Protocol, TypedDict


class ConsistencyRequest(TypedDict):
    project_id: str
    input_doc_id: str
    input_snapshot_id: str
    range: dict  # {start,end} 또는 episode_range
    schema_ver: str

class ConsistencyEngine(Protocol):
    def run(self, req: ConsistencyRequest) -> list[VerdictLog]: ...
```

`schema_ver`는 승인된 스키마 뷰(approved facts)를 기준으로 한다.

---

## Extraction V2 Addendum (2026-02-11)

### Must (additive, contract-safe)

- Introduce `ExtractionPipeline` as the single slot extraction path for `CONSISTENCY`.
- Keep deterministic baseline: default mode is `rule_only`.
- Add optional extraction profile in job params:
  - `mode`: `rule_only|hybrid_local|hybrid_remote|hybrid_dual`
  - `use_user_mappings`
  - `model_slots`
  - `model_timeout_ms`
- Add user mapping layer with priority above builtin rules.
- Enforce `VIOLATE -> CONTRADICT evidence` contract unchanged.

### Partial/Follow-up

- Improve slot-level confidence policy for model candidates.
- Add per-slot extraction error counters for long-run diagnostics.

### Tests/DoD

- Regression: `tests/test_nf_consistency_engine.py`
- Scope/slot coverage: `tests/test_nf_consistency_scope_and_slots.py`
- New extractor tests: `tests/test_nf_consistency_extractors.py`
- E2E gate: `tests/e2e/test_global_context_detection.py`
