# 파이프라인 로직 대변경 제안 분리 문서 (2026-02-27)

## 목적
- 본 문서는 `PIPELINE_LOGIC_CHANGE` 태그 항목만 분리한 설계안이다.
- UI 레이아웃 변경이 아닌, 정합성/검색/추출 파이프라인의 구조적 변경 제안만 포함한다.
- 원본 매핑: `plan/question_claim_mapping_2026-02-27.md`

## 공통 원칙
1. 기본 경로는 경량/안정 우선, 고비용 경로는 조건부/옵트인.
2. 근거 없는 승격 금지(unknown 보수 유지).
3. 변경은 단계적 도입 + 명시적 롤백 기준 포함.

## PL-01 추출 프로파일 기본값 재설계(rule_only -> 정책형 기본)
- 관련 Claim IDs: `Q3-C16`, `Q3-C17`, `Q3-C18`
- 현행 로직:
  - extraction 기본 mode는 `rule_only`.
  - 사용자/프로젝트에서 extraction params를 넘기지 않으면 rule_only 유지.
- 변경 제안:
  - 프로젝트 설정에 `default_extraction_profile` 추가.
  - 기본값을 `rule_only`에서 `hybrid_local(light)`로 선택 가능하게 변경.
  - 슬롯별 모드 허용(예: age/time은 rule_only, relation/place는 hybrid_local).
- 효과 가설:
  - 일반 서술형 텍스트에서 슬롯 recall 개선.
  - UNKNOWN 비율 감소.
- 리스크:
  - 추론 비용/지연 증가.
  - 모델 오탐으로 인한 노이즈 증가.
- 단계적 도입/롤백 기준:
  - 1단계: 프로젝트 opt-in 실험.
  - 2단계: 200문서 벤치에서 UNKNOWN 감소 및 지연 허용 범위 확인.
  - 롤백: 지연 p95 급증 또는 오탐률 임계치 초과 시 `rule_only` 즉시 복귀.

## PL-02 explicit_only 스코프의 PROPOSED 반영 정책 분리
- 관련 Claim IDs: `Q3-C19`
- 현행 로직:
  - explicit_only는 REJECTED만 제외하고 PROPOSED를 포함.
- 변경 제안:
  - `explicit_only`를 두 단계로 세분화:
    - `explicit_strict`: APPROVED + USER 근거 우선
    - `explicit_relaxed`: 기존 explicit_only 동작
  - verdict 계산 시 PROPOSED 근거는 감점/낮은 가중치 적용.
- 효과 가설:
  - 미승인 팩트로 인한 과도 경고 완화.
- 리스크:
  - 실제 조기 경고 탐지율 감소 가능.
- 단계적 도입/롤백 기준:
  - A/B: `explicit_relaxed` 대비 false positive 체감 지표 비교.
  - 롤백: 누락 경고 증가가 임계치를 넘으면 기존 정책 유지.

## PL-03 verification loop 예산 기반 제어
- 관련 Claim IDs: `Q1-C15`, `Q3-C21`
- 현행 로직:
  - UNKNOWN 특정 사유에서 최대 라운드 반복, 라운드별 k 확장.
- 변경 제안:
  - claim 단위 `time_budget_ms`, `retrieval_budget` 도입.
  - 라운드별 개선량(delta) 기반 조기 종료.
  - metadata 필터가 있는 경우 loop 상한을 더 낮게 제한.
- 효과 가설:
  - 최악 지연 꼬리(p95/p99) 절감.
- 리스크:
  - 일부 케이스에서 회복 가능한 UNKNOWN을 조기 종료할 수 있음.
- 단계적 도입/롤백 기준:
  - 1단계: 계측만 추가.
  - 2단계: budget enforcement 활성화.
  - 롤백: VIOLATE/OK 전환율이 유의미하게 하락하면 완화.

## PL-04 self-evidence 제외 eid 조회 방식 개선
- 관련 Claim IDs: `Q1-C14`
- 현행 로직:
  - `chunk_size=200`으로 evidence eid를 반복 `IN` 조회.
- 변경 제안:
  - 임시 테이블 또는 CTE 기반 일괄 조인으로 변경.
  - 문서 단위 eid 인덱스 캐시 도입.
- 효과 가설:
  - 대규모 scope에서 DB round-trip 감소.
- 리스크:
  - 쿼리 복잡도 증가로 일부 환경에서 계획 최적화 실패 가능.
- 단계적 도입/롤백 기준:
  - 벤치(200/800 문서)에서 DB time 개선이 확인될 때만 기본화.
  - 회귀 시 기존 chunk 방식으로 즉시 롤백.

## PL-05 슬롯 비교의 의미론 강화
- 관련 Claim IDs: `Q1-C16`
- 현행 로직:
  - 문자열 치환 사전 + 토큰 중복도 중심 비교.
- 변경 제안:
  - 슬롯별 정규화 사전 외에 경량 임베딩 유사도 보조 추가.
  - `slot_key`별 임계치/비교기 플러그인화.
  - 숫자/시간/장소를 타입별 비교기로 분리.
- 효과 가설:
  - 동의어/표현 변형 대응 강화, 오탐/누락 완화.
- 리스크:
  - 임계치 튜닝 난이도 증가.
- 단계적 도입/롤백 기준:
  - 슬롯별 단계 도입(장소 -> 관계 -> 소속 순).
  - 슬롯 단위 feature flag로 롤백 가능하게 유지.

## PL-06 post-save 파이프라인의 옵션형 INDEX_VEC 추가
- 관련 Claim IDs: `Q3-C22`
- 현행 로직:
  - post-save는 기본적으로 INGEST + INDEX_FTS만 수행.
- 변경 제안:
  - 문서 크기/변경량/idle 상태를 기준으로 `INDEX_VEC` 조건부 실행.
  - vec 인덱싱은 background queue 우선순위 낮게 배치.
- 효과 가설:
  - 벡터 검색 recall 개선, 검색 다양성 향상.
- 리스크:
  - 로컬 자원 사용량 증가.
- 단계적 도입/롤백 기준:
  - 프로젝트 설정 opt-in으로 시작.
  - 메모리 압력 이벤트 증가 시 자동 비활성화.

## PL-07 그래프 추출/활용을 승인형 파이프라인으로 전환
- 관련 Claim IDs: `Q1-C19`, `Q3-C20`
- 현행 로직:
  - graph_extract/graph_expand는 옵션이 있으나 사용자 승인 워크플로가 약함.
- 변경 제안:
  - `graph_extract_request -> candidate review -> approve` 3단계 잡 타입 분리.
  - 승인된 anchor/entity만 graph seed로 사용.
- 효과 가설:
  - 그래프 오염/환각 전파 리스크 감소.
- 리스크:
  - 초기 사용성 저하(추가 승인 단계).
- 단계적 도입/롤백 기준:
  - 우선 strict 모드에서만 승인형 강제.
  - UX 부담 과다 시 hybrid(자동+검토)로 완화.

## PL-08 고비용 모델 라우팅 정책(조건부 ColBERT/Cross-Encoder)
- 관련 Claim IDs: `Q1-C18`, `Q1-C20`
- 현행 로직:
  - verifier/triage/loop 옵션은 있으나 고비용 모델은 전면 기본화되어 있지 않음.
- 변경 제안:
  - 라우팅 규칙:
    - 기본: 경량 경로(FTS/vector + existing rerank)
    - 승격: UNKNOWN 지속 + 고위험 claim + 사용자 동의 시 고비용 판정
  - 라우팅 로그/비용 추적 필드 추가.
- 효과 가설:
  - 품질과 지연/비용 균형 최적화.
- 리스크:
  - 정책 복잡도 증가.
- 단계적 도입/롤백 기준:
  - 실험 플래그로 제한 배포.
  - OOM/지연 급증 시 승격 경로 즉시 차단.

## PL-09 근거 분해 결과의 API 계약 명시 강화
- 관련 Claim IDs: `Q1-C06`, `Q2-C07`
- 현행 로직:
  - backend에 breakdown은 존재하지만, 프론트 소비 계약은 사실상 비공식.
- 변경 제안:
  - `/query/verdicts` 응답 계약에 breakdown 필드를 명시(스키마 문서 + 계약 테스트).
  - 불완전 데이터 시 fallback 규칙(0/unknown) 고정.
- 효과 가설:
  - UI 구현 일관성/회귀 방지.
- 리스크:
  - 기존 클라이언트 호환성 검토 필요.
- 단계적 도입/롤백 기준:
  - nullable 호환 필드로 선도입 후 required 전환.

## PL-10 성능 계측 표준화 및 시점 의존 수치 통제
- 관련 Claim IDs: `Q1-C17`
- 현행 로직:
  - 코드상 메트릭 필드는 있으나 문서 수치 최신성 보장이 약함.
- 변경 제안:
  - 벤치 실행 결과를 날짜/환경/commit hash와 함께 자동 기록.
  - 문서 내 정량 수치는 `검증 일자` 필수 기입.
- 효과 가설:
  - 과거 수치 재인용으로 인한 오판 감소.
- 리스크:
  - 벤치 운영 비용 증가.
- 단계적 도입/롤백 기준:
  - 야간 벤치 최소 세트부터 도입.
  - 운영 부담 과다 시 주간 배치로 축소.

