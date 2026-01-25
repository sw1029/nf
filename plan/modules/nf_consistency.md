# nf-consistency (정합성 엔진) — MoSCoW 구현 계획

nf-consistency는 원고 구간을 세그먼트로 나누고, 근거(Evidence)를 구성한 뒤, layered judge로 판정(Verdict)과 로그를 저장한다.

참조:

- `plan/contracts.md`
- `plan/architecture_2.md` (6단계 파이프라인)

---

# [M] Must — 1차 배포(MVP+안정화)

## 0) 패키지/폴더 구조(placeholder 기준)

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

* ☐ 문장/절 segmentation
* ☐ 하드 필드 힌트 기반 claim 후보 추출(시간/나이/장소/관계 키워드)
* ☐ 출력: `(segment_span, claim_text, slots)` 리스트

## 2) Evidence Builder (근거 강제)

* ☐ 기본: FTS로 evidence를 구성(정확 인용)
* ☐ job 내부에서는 필요 시 vector 확장 가능(heavy job 경로)
  - 단, “근거 부재를 모델로 뒤집지 못함” 정책 유지
* ☐ Evidence는 `snapshot_id/chunk_id` 포함(가능하면)

## 3) Judge Layer 1 (Explicit only)

* ☐ schema_explicit_fact(승인된 것)과 비교하여 위배 감지
* ☐ 위배 시: `tag_path` + Evidence 스니펫을 반드시 포함

## 4) Judge Layer 2 (Heuristic, 보수적)

* ☐ alias/정규화/약한 동일성 처리(충돌 시 unknown)
* ☐ entity_id 불명확 시 unknown 우선

## 5) Judge Layer 3 (옵션 경로; 구조는 Must)

* ☐ 호출 조건 게이트:
  - user enabled
  - L1/2 inconclusive
  - evidence exists
* ☐ 모델 점수는 breakdown에만 반영(과신 방지)

## 6) Whitelist

* ☐ claim_fingerprint 기반 재경고 억제
* ☐ whitelist 적용 시 결과를 “오류→추가정보”로 표기할 수 있는 상태 필드 유지

## 7) Verdict Logging

* ☐ `VerdictLog` + `VerdictEvidenceLink` 저장 계약 준수
* ☐ schema_ver/input_snapshot_id를 함께 기록(재현성)

## 8) 테스트(pytest)

* ☐ `tests/test_nf_consistency_contracts.py`: ConsistencyRequest/ConsistencyEngine 계약 스모크
* ☐ (차순위) L1 위배 감지 스모크(간단 schema + claim)
* ☐ (차순위) 충돌/애매 시 unknown 강등 테스트
* ☐ (차순위) whitelist 적용 시 재경고 억제 테스트

---

# [S] Should — 권장

* ☐ Reliability calibration(보수적)
* ☐ Unknown 사유 표준 문구(UX)

---

# [C] Could — 여유 시

* ☐ 팩트/이벤트 기반 제약 검사(문장 비교 대체) 실험

---

# [W] Won’t (now)

* ☐ 암시 레이어를 자동 확정하여 스키마 반영

---

## 계약 인터페이스(요약)

- Inputs: `pid + input_doc_id + input_snapshot_id + range + schema_ver`
- Outputs: `VerdictLog[]` + `JobEvent` 스트리밍
- Invariants: Claim–Evidence–Verdict, unknown 허용, evidence_required

---

## 계약 인터페이스(상세; 구현 기준)

```python
from typing import Protocol, TypedDict


class ConsistencyRequest(TypedDict):
    pid: str
    input_doc_id: str
    input_snapshot_id: str
    range: dict  # {start,end} 또는 episode_range
    schema_ver: str

class ConsistencyEngine(Protocol):
    def run(self, req: ConsistencyRequest) -> list[VerdictLog]: ...
```

`schema_ver`는 승인된 스키마 뷰(approved facts)를 기준으로 한다.
