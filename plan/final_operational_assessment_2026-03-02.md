> 기준 요구: `plan/user_request.md`
> 기준 실행: `tools/bench/run_user_delegated.ps1` (resume)

# Final Operational Assessment (2026-03-02)

## 1) 범위
- UI 회귀 안정화 패치 적용
- 실패 지점(step 24) 재개 실행
- 최신 운영 벤치 아티팩트 기반 성능/요구반영도/미비점 최종 평가

## 2) 실행 및 증거 아티팩트

### 2.1 패치 적용 파일
- `tests/ui/fixtures/editor_harness.html`
  - 결정론 API 추가: `__setPageCharBudget`, `__repaginateWithBudget`
- `tests/ui/test_editor_cross_browser_offsets_playwright.py`
  - resize 의존 `__repaginate()` 제거, width 기반 고정 budget 호출로 전환

### 2.2 재개 실행
- 실행 모드: `-RunRemainingMatrix -StartStep 24 -AdaptiveHardFailAction warn`
- 상태 경로: `verify/bench_state/20260228T150911Z`
- 결과:
  - UI regression step 통과
  - `verify/benchmarks/ui_browser_regression_junit.xml`: `failures=0`, `errors=0`

### 2.3 분석 입력
- `verify/benchmarks/latest_metrics_summary.json`
- `verify/benchmarks/consistency_strict_gate_20260301T183806Z_iter1.json`
- `verify/benchmarks/20260301T135753Z.json` (DS-GROWTH-200, quick, dual)
- `verify/benchmarks/20260301T150955Z.json` (DS-GROWTH-400, quick, throughput)
- `verify/benchmarks/20260301T171748Z.json` (DS-GROWTH-800, quick, throughput)
- `verify/benchmarks/20260301T175737Z.json` (DS-CONTROL-D, strict)
- `verify/benchmarks/20260301T183804Z.json` (DS-INJECT-C, strict)

## 3) 운영 게이트 결과

### 3.1 Summary Gate
- 파일: `verify/benchmarks/latest_metrics_summary.json`
- `overall_status=PASS`

주의:
- `summarize_latest_metrics.py`가 `doc_count=200`을 `DS-200`으로 먼저 추론하여 strict 200문서(`DS-CONTROL-D`, `DS-INJECT-C`)를 DS-200로 오집계할 수 있음.
- 실제 최종 평가는 `dataset_path` 기준으로 재매핑해 수행함.

### 3.2 Strict Hard-Fail Gate
- 파일: `verify/benchmarks/consistency_strict_gate_20260301T183806Z_iter1.json`
- 판정: `passed=true`
- 세부 체크: 6/6 PASS
  - status success all: PASS
  - strict level set: PASS
  - required runtime keys present: PASS
  - strict perf ratio within limit: PASS
  - loop timeout rate <= 20%: PASS
  - inject conflict signal present: PASS

### 3.3 UI Operational Regression
- 파일: `verify/benchmarks/ui_browser_regression_junit.xml`
- 판정: PASS (`tests=1`, `failures=0`, `errors=0`)

## 4) 성능 분석

## 4.1 최신 성능(절대값 + 직전 대비)

| dataset | artifact | retrieval_fts_p95 (ms) | consistency_p95 (ms) | 직전 artifact | delta retrieval | delta consistency |
|---|---|---:|---:|---|---:|---:|
| DS-200 (quick/dual) | `20260301T135753Z.json` | 1562.93 | 9449.15 | `20260301T030809Z.json` | -3.85% | -0.05% |
| DS-400 (quick/throughput) | `20260301T150955Z.json` | 1553.06 | 9408.45 | 없음 | N/A | N/A |
| DS-800 (quick/throughput) | `20260301T171748Z.json` | 1545.69 | 9462.36 | `20260301T114005Z.json` | -0.99% | +0.17% |
| DS-CONTROL-D (strict) | `20260301T175737Z.json` | 1567.37 | 9437.14 | 없음 | N/A | N/A |
| DS-INJECT-C (strict) | `20260301T183804Z.json` | 1549.52 | 9404.52 | 없음 | N/A | N/A |

해석:
- 게이트 관점(상대비교)은 통과.
- 절대 성능 관점에서는 retrieval/consistency 모두 목표치(300ms/2500ms) 대비 큰 격차가 유지됨.

## 4.2 strict runtime(신규 계측)

| dataset | loop_trigger | loop_rounds | loop_timeout | timeout_rate | loop_stagnation_break | unknown_rate | violate_rate |
|---|---:|---:|---:|---:|---:|---:|---:|
| DS-CONTROL-D strict | 15 | 10 | 0 | 0.00 | 10 | 0.6818 | 0.3182 |
| DS-INJECT-C strict | 16 | 14 | 0 | 0.00 | 9 | 0.7273 | 0.2727 |

strict 신호:
- inject `unknown_reason_counts.CONFLICTING_EVIDENCE=16`
- inject `violate_count_total=6`
- hard-fail gate 규격의 inject signal 조건 충족

## 5) `user_request.md` 반영도 평가

평가 축은 요청된 5개 핵심 축 기준으로 정리.

| 축 | 등급 | 근거(코드/아티팩트) | 판정 근거 |
|---|---|---|---|
| Claim-Evidence-Verdict + unknown + whitelist/ignore | 충족 | `modules/nf_consistency/engine.py` (verdict/unknown reason/whitelist/ignore/verification loop) | 판정 구조와 unknown 강등, ignore/whitelist 경로가 구현되어 있으며 strict/quick 벤치에서 동작 계측 확인 |
| 근거 표준화(doc/section/tag/snippet) | 충족 | `modules/nf_consistency/engine.py` (`_bundle_evidence`: `doc_id`, `section_path`, `tag_path`, `snippet_text`) | 요구한 근거 필드 규격이 저장/전달 payload에 반영 |
| 요청형 grouping(time/entity/timeline) | 부분 충족 | `modules/nf_workers/runner.py` (grouping 처리, timeline events 생성), `modules/nf_consistency/engine.py` (metadata filter 사용) | 백엔드 경로는 존재하나 운영 벤치 기본 플로우에서 UI 요청형 제어의 E2E 검증 범위가 제한적 |
| 성능/운영 안정성 | 부분 충족 | strict gate PASS + summary PASS + UI step24 PASS, 단 절대 p95 고수준 유지 | 운영 게이트는 통과했으나 절대 성능 목표 대비 격차 큼 |
| 모델 분리/선택형 고비용 경로 | 부분 충족 | `modules/nf_model_gateway/gateway.py`, `modules/nf_workers/runner.py` (`purpose=consistency`/`purpose=suggest`) | 역할 분리/선택 경로는 존재하나 품질/비용 최적화는 추가 검증 필요 |

## 6) 미비점 최종 정리 (우선순위)

### P0
1. metrics summary dataset 오집계 가능성
- 증거 수치:
  - `latest_metrics_summary.json`의 `DS-200.latest_file=20260301T183804Z.json` (실제는 DS-INJECT-C strict)
- 영향:
  - 운영 상태판에서 dataset별 추세 해석 오류 가능, 잘못된 PASS/WARN 판단 위험
- 다음 액션:
  - `tools/bench/summarize_latest_metrics.py`의 dataset 추론을 `dataset_path` 우선으로 변경하고 strict/control/inject를 별도 key로 분리

### P1
1. 절대 성능 목표 미달(지속)
- 증거 수치:
  - DS-200 retrieval_fts_p95=1562.93ms (목표 300ms 대비 약 5.21x)
  - DS-200 consistency_p95=9449.15ms (목표 2500ms 대비 약 3.78x)
- 영향:
  - 운영 게이트 PASS여도 사용자 체감 지연/대기시간은 높음
- 다음 액션:
  - retrieval/consistency 각각 단계별 timing 분해(쿼리, evidence fetch, verifier, loop) 고정 계측 후 상위 2개 병목 우선 제거

2. quick 모드 unknown 비율 과다
- 증거 수치:
  - DS-800 quick unknown_rate=0.9333
  - DS-400 quick unknown_rate=0.8161
- 영향:
  - 위배 탐지 신뢰도/행동가능성 저하(“모름” 비중 과다)
- 다음 액션:
  - triage/verifier 정책의 샘플링 기준 보정 및 슬롯 비교 가능성(`SLOT_UNCOMPARABLE`) 축소 규칙 강화

### P2
1. 요청형 grouping의 운영 E2E 검증 커버리지 부족
- 증거:
  - 기능 코드는 존재하나, 운영 CMD 기본 벤치가 grouping ON/OFF 사용자 시나리오를 분리 측정하지 않음
- 영향:
  - 사용자 요청형 filtering 품질/성능 회귀 조기 탐지 한계
- 다음 액션:
  - DS-200 소형 시나리오에 grouping(entity/time/timeline) on-demand 벤치를 추가하고 p95/정확도 회귀 지표를 별도 게이트화

## 7) 결론
- 이번 목표 3개(UI 플래키 제거, 실패 지점 재개 완료, 최종 운영 분석)는 완료됨.
- 운영 게이트는 최신 기준 PASS이며 strict hard-fail 규격도 통과함.
- 다만 성능은 상대게이트 통과와 별개로 절대 목표 대비 미달이 지속되고, metrics summary dataset 매핑 정확도는 즉시 보완(P0) 대상임.
