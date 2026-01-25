# nf-model-gateway (로컬/원격 모델 경계) — MoSCoW 구현 계획

nf-model-gateway는 모델 호출 경계를 제공한다: 로컬 소형 모델(ONNX), 원격 API, 그리고 차순위 로컬 생성 모델(로컬 생성기) 분기.

참조:

- `plan/contracts.md`
- `plan/DECISIONS_PENDING.md` (D4: 로컬 생성기 분기/차순위)

구현 순서(Phase, 전체 로드맵: `plan/IMPLEMENTATION_CHECKLIST.md`):

테스트는 conda의 `nf` 환경에서 수행한다.

- Phase 80: `LOCAL_RULE` 우선 + 원격 API 옵트인 + 안전 게이트 최소 구현
- `LOCAL_GEN`은 “분기/인터페이스만”(차순위; 실구현 보류)

---

# [M] 필수 — 1차 배포(MVP+안정화)

## 0) 패키지/폴더 구조(플레이스홀더 기준)

```text
modules/nf_model_gateway/
  __init__.py
  safety/
    evidence_required.py
    fallback.py
  local/
    onnx_runtime.py
    nli_model.py
    tag_quality.py
  remote/
    openai_client.py
    gemini_client.py
    rate_limit.py
  gateway.py
```

## 1) Safety Gate: evidence_required (필수)

* ☐ 입력에 Evidence가 없으면 “생성/판정” 결과를 UNKNOWN/보류로 강등
* ☐ 모델 출력은 항상 “근거 포함” 또는 “근거 부족”을 명시하도록 강제

## 2) 로컬 소형 모델(ONNX) 인터페이스(없어도 동작)

* ☐ NLI/분류기 호출 인터페이스만 고정
  - `infer_nli(premise_evidence, hypothesis_claim) -> score`
* ☐ 태그 품질 점수 인터페이스(옵션)

## 3) 원격 API 클라이언트(옵트인)

* ☐ API 키/레이트리밋/회로차단 최소 골격
* ☐ “SUGGEST/API” 요청에만 사용(기본 꺼짐)

## 4) 로컬 생성기 분기(차순위; 1차는 분기만)

* ☐ `suggest_local_gen(...)` 경로를 “선택 가능”하게만 노출
* ☐ ModelStore 다운로드/버전관리와 연결 포인트만 마련(실 모델은 차순위)

## 5) 테스트(pytest)

* ☐ `tests/test_nf_model_gateway_contracts.py`: EvidenceBundle/ModelGateway 계약 스모크
* ☐ (차순위) evidence_required 게이트 동작(unit)
* ☐ (차순위) 원격 클라이언트는 키 미설정 시 안전하게 비활성화(unit)

---

# [S] 권장 — 권장

* ☐ 제공자 추상화: OpenAI/Gemini 공통 인터페이스
* ☐ 요청/응답 로그의 민감정보 마스킹

---

# [C] 선택 — 여유 시

* ☐ 로컬 생성 모델 실구현(양자화 LLM) + 품질/안전 평가

---

# [W] 현재 제외

* ☐ 모델 기반 문법 교정을 1차 경로로 포함

---

## 계약 인터페이스(요약)

- 입력: `purpose`(consistency/suggest_local_rule/suggest_local_gen/remote_api) + 근거 번들
- 출력: model_score 또는 재작성 텍스트(근거 강제)

---

## 계약 인터페이스(상세; 구현 기준)

```python
from typing import Protocol, TypedDict


class EvidenceBundle(TypedDict):
    claim_text: str
    evidence: list[dict]  # Evidence DTO subset

class ModelGateway(Protocol):
    def nli_score(self, bundle: EvidenceBundle) -> float: ...
    def suggest_local_rule(self, bundle: EvidenceBundle) -> str: ...
    def suggest_remote_api(self, bundle: EvidenceBundle) -> str: ...
    def suggest_local_gen(self, bundle: EvidenceBundle) -> str: ...  # 차순위(실구현)
```
