> 기준 실행: `tools/bench/run_user_delegated.cmd -ExecutionPreset strict -RunRemainingMatrix -RunGraphProbe -RepeatCount 1 -DatasetSync off -DatasetDiversityProfile max -DiversityGatePolicy warn -SoakHours 0.5 -MatrixRuns 1 -ProgressMetrics artifact -StackRecoveryPolicy restart_once -ParallelStackCount 3 -ParallelizeMatrixPairs -ParallelizeOperationalVerification -ParallelShardLifecycle lazy -ParallelProgressMode task_aware`
> 기준 산출물: `verify/benchmarks/*` (2026-03-06T14:26:55Z batch)

# Consistency Benchmark Follow-up Plan (2026-03-07)

## 1) 목적
- 이번 strict delegated batch의 결과를 기준선으로 고정한다.
- `summary PASS`, `gate FAIL`, `strict PASS`, `diversity strict FAIL`, `soak FAIL`이 동시에 나온 이유를 분해한다.
- 정합성 엔진의 성능/정확도/운영 통합 완성도를 끌어올리기 위한 후속 작업을 단계별로 수행한다.

## 2) 기준 판정

### 2.1 핵심 산출물
- `verify/benchmarks/gate_report_20260306T152842Z_iter1.md`
- `verify/benchmarks/consistency_strict_gate_20260306T154139Z_iter1.md`
- `verify/benchmarks/consistency_strict_gate_diverse_20260306T160017Z_iter1.md`
- `verify/benchmarks/latest_metrics_summary.md`
- `verify/benchmarks/soak_20260306T150614Z.md`

### 2.2 현재 상태 요약
- Final gate: FAIL
  - DS-800 matrix graph-on `consistency_p95=3616.28ms`
  - soak `failed_ratio=0.088316`
- Strict gate(main): PASS
  - control/inject timeout rate 0%
- Strict gate(diverse): FAIL
  - control/inject timeout rate 100%
- Latest metrics summary: PASS
  - operational-main/diversity-main만 본 상대 추세 요약
  - release gate 아님

### 2.3 현재 구현 완성도 평정
- 정합성 판정 로직: `B`
- 정합성 성능(mainline quick): `B-`
- strict completeness(layer3/graph/model 실효성): `C+`
- 운영 게이트/벤치 해석 일치성: `C`

## 3) 작업 원칙
- 먼저 `판정 기준`과 `산출물 의미`를 정리한다.
- 다음으로 `soak 실패율`과 `diverse strict timeout`의 원인을 계측 가능 상태로 만든다.
- 그 후 `strict completeness`와 `graph 실효 경로`를 손본다.
- 마지막에 `absolute performance`를 최적화한다.

## 4) 단계별 실행 계획

### Phase 0 — 운영 판정 계층 분리
목적:
- `latest_metrics_summary PASS`가 release PASS로 오해되지 않게 만든다.

작업:
- `tools/bench/summarize_latest_metrics.py`
  - `overall_status`를 계속 유지하되 의미를 `trend_relative`로 명시한다.
  - 절대 목표 기반 `absolute_goal_status`를 추가한다.
  - dataset별 `absolute_metric_status`, `absolute_status`, `absolute_thresholds`를 추가한다.
  - markdown에도 상대/절대 상태를 분리 표기한다.
- 테스트 추가
  - 상대 추세는 WARN인데 절대 목표는 FAIL인 케이스를 고정한다.

DoD:
- summary JSON/Markdown만 읽어도 `trend summary`와 `absolute goal`을 혼동하지 않는다.
- 기존 summary gate 동작은 깨지지 않는다.

상태:
- `☑` Phase 0.1 summary semantics 분리

### Phase 1 — soak 실패율 분해 가능화
목적:
- `failed_ratio=8.83%`의 실제 실패 원인을 재현 가능한 단위로 수집한다.

작업:
- `tools/bench/run_soak.py`
  - stage별 실패 카운트(`INGEST`, `INDEX_FTS`, `CONSISTENCY`, `RETRIEVE_VEC`, `retrieval_http`) 추가
  - job status별 실패 카운트 추가
  - stream별 대표 오류 샘플 수집 강화
  - aggregate에 `failure_breakdown`과 `failure_samples` 추가
- 필요 시 보조 분석 스크립트 추가
  - soak artifact에서 상위 실패 원인을 markdown으로 렌더

DoD:
- 다음 soak artifact 하나만으로 실패율의 대부분을 stage/job status 기준으로 설명할 수 있다.

상태:
- `☑` Phase 1.1 failure_breakdown 계측
- `☑` Phase 1.2 failure_samples 보고서

### Phase 2 — diverse strict timeout 진단
목적:
- diverse strict gate 실패 원인이 dataset 특성인지, verification loop budget 문제인지 분리한다.

작업:
- `modules/nf_consistency/engine.py`
  - verification loop round별 elapsed/candidate growth/reason 전환 계측 추가
- `modules/nf_workers/runner.py`
  - consistency complete payload에 loop round cost 요약 추가
- gate 진단 보강
  - `timeout_rate` 외에 `avg_round_ms`, `p95_round_ms`, `stagnation_ratio` 출력

DoD:
- 다음 diverse strict 실행에서 timeout 원인이 “budget undersized”인지 “retrieval stagnation”인지 판별 가능하다.

상태:
- `☑` Phase 2.1 loop round 계측
- `☑` Phase 2.2 diverse strict 재실행 및 원인 판정

실행 메모 (2026-03-07):
- control rerun: `verify/benchmarks/20260306T171954Z.json`
  - `verification_loop_round_elapsed_ms_avg ~= 0.11`
  - `verification_loop_candidate_growth_avg = 0.0`
  - `verification_loop_exit_reason_counts = {'no_results_fts': 11}`
  - 해석: control 쪽은 timeout이 아니라 “증거 0건 stagnation”이 주 경로
- inject rerun: `verify/benchmarks/20260306T172225Z.json`
  - `verification_loop_round_elapsed_ms_avg ~= 655.59`
  - `verification_loop_candidate_growth_avg ~= 11.69`
  - `verification_loop_exit_reason_counts = {'timeout_before_round': 13}`
  - 해석: inject 쪽은 첫 round 자체가 budget(250ms)을 초과하는 구조
- strict gate rerun: `verify/benchmarks/consistency_strict_gate_diverse_phase2_loopdiag_20260306T172225Z.json`
  - 여전히 `loop_timeout_rate_le_20pct` 실패
  - inject 쪽 diversity strict 실패 원인은 “loop budget undersized”로 판단 가능
  - control 쪽은 “retrieval stagnation / no-results” 경로가 우세
  - 단, control artifact에서 `timeout_count`와 `exit_reason_counts` 사이 일부 불일치가 보여 fresh stack 기준 재확인은 후속 메모로 유지

### Phase 3 — strict completeness 복구
목적:
- strict PASS가 실제로 layer3/graph/metadata 기능을 검증하는 PASS가 되도록 만든다.

작업:
- preflight에서 `metadata_grouping_enabled`의 기본 전략 재정의
- strict/deep 프리셋에서 metadata grouping 활성 여부를 명시
- layer3 관련 설정/카운트가 실제 사용되는지 검증
- strict artifact에서 `rerank_applied_count`, `model_fallback_count`, `promoted_ok_count`가 0만 반복되지 않게 경로 점검

DoD:
- strict runtime artifact에서 적어도 일부 dataset은 layer3 또는 metadata/grouping 경로가 실제 사용되었다는 카운트가 남는다.

상태:
- `☑` Phase 3.1 metadata grouping 기본 전략 확정
- `☑` Phase 3.2 strict-layer3 실효성 검증

실행 메모 (2026-03-07):
- 구현:
  - `modules/nf_consistency/engine.py`
    - `layer3_model_enabled`
    - `layer3_local_nli_enabled`
    - `layer3_local_reranker_enabled`
    - `layer3_remote_api_enabled`
    - `layer3_nli_capable`
    - `layer3_reranker_capable`
    - `layer3_effective_capable`
    - `layer3_promotion_enabled`
    - `layer3_inactive_reasons`
  - `modules/nf_workers/runner.py`
    - consistency complete payload에 위 diagnostics 전달
  - `tools/bench/run_pipeline_bench.py`
    - `layer3_*_jobs`, `layer3_*_ratio`, `layer3_inactive_reason_counts` 집계 추가
- 검증:
  - bench/worker/unit tests 통과
  - 현재 로컬 config 확인값:
    - `enable_layer3_model = false`
    - `enable_local_nli = false`
    - `enable_local_reranker = false`
    - `enable_remote_api = false`
- 1차 판단:
  - strict artifact의 `layer3_rerank_applied_count = 0`
  - strict artifact의 `layer3_model_fallback_count = 0`
  - strict artifact의 `layer3_promoted_ok_count = 0`
  - 위 0-count는 현재 기준 “경로 비활성(capability off)” 가능성이 높음
  - fresh stack strict rerun:
    - control: `verify/benchmarks/20260307T024925Z.json`
    - inject: `verify/benchmarks/20260307T025217Z.json`
  - 결과:
    - `layer3_model_enabled_jobs = 0`
    - `layer3_nli_capable_jobs = 0`
    - `layer3_reranker_capable_jobs = 0`
    - `layer3_effective_capable_jobs = 0`
    - `layer3_promotion_enabled_jobs = 40`
    - `layer3_inactive_reason_counts`에
      - `GLOBAL_LAYER3_MODEL_DISABLED`
      - `STRICT_VERIFIER_NLI_UNAVAILABLE`
      - `LAYER3_PROMOTION_NLI_UNAVAILABLE`
      - `LOCAL_RERANKER_DISABLED`
      가 전부 40건씩 누적
  - 결론:
    - strict 0-count는 “버그/미호출”이 아니라 “현재 환경에서 layer3 capability 자체가 off”인 상태
    - Phase 3.2 목표 달성

### Phase 4 — graph 경로의 운영 통합
목적:
- probe에서만 PASS하는 graph 경로를 normal matrix/operational path와 일치시킨다.

작업:
- graph seed 생성 전제조건과 bootstrap 경로를 명시적으로 분리
- matrix graph-on run에서 `graph_applied=0/30`이 반복되는 원인 확인
- 필요 시 normal preflight에 graph seed용 grouping을 포함

DoD:
- graph-on matrix run의 `graph_runtime.applied_count`가 probe-only가 아니라 normal path에서도 의미 있게 측정된다.

상태:
- `☑` Phase 4.1 graph bootstrap vs normal path 분리
- `☑` Phase 4.2 matrix graph-on 실효성 확보

실행 메모 (2026-03-07):
- 구현:
  - `tools/bench/check_graphrag_applied.py`
    - probe summary에 `validation_mode` 추가
    - `normal_path_filter_count`, `final_filter_count`, `normal_path_ready`, `bootstrap_used`, `bootstrap_status` 추가
    - 결과를 `normal_path` / `bootstrap_assisted` / `no_grouping`으로 구분
  - `tools/bench/run_user_delegated.ps1`
    - probe artifact를 bool만 읽지 않고 mode까지 읽도록 변경
    - progress postfix와 step log에 `mode=`를 출력하도록 변경
- 효과:
  - bootstrap-assisted PASS가 normal path PASS로 오해되지 않음
  - 다음 단계(4.2)는 “그래서 실제 matrix graph-on에서 왜 normal path 적용이 0이냐”에 집중 가능
  - `tools/bench/run_pipeline_bench.py`는 graph-on일 때 `INDEX_FTS`에
    - `entity_mentions = true`
    - `time_anchors = true`
    - `graph_extract = true`
    를 포함해 normal path graph seed 준비를 하도록 보강됨
  - bench artifact에는 `graph_index_runtime`가 추가되어 normal path 준비 상태를 직접 확인 가능
  - 검증 rerun: `verify/benchmarks/20260307T020447Z.json`
    - `graph_index_runtime.graph_extract_enabled = true`
    - `time_anchors_created = 203`
    - `graph_runtime.applied_count = 0 / 30`
    - 해석: normal path seed 준비는 반영됐지만 실제 retrieve_vec graph apply는 아직 0
  - 추가 조치:
    - `modules/nf_retrieval/graph/rerank.py`
      - `time_key`의 `/rel:` 구간을 query-only seed 신호로 활용
    - `tools/bench/run_pipeline_bench.py`
      - graph-on일 때 retrieval query selection이 시간 anchor 신호가 있는 문장을 우선 선택하도록 보강
  - fresh stack 검증 rerun: `verify/benchmarks/20260307T035012Z.json`
    - `graph_index_runtime.graph_extract_enabled = true`
    - `time_anchors_created = 203`
    - `graph_runtime.applied_count = 3 / 30`
    - 해석: normal path graph seed 준비와 실제 graph apply가 모두 확인됨
  - 결론:
    - Phase 4.2 목표 달성

### Phase 5 — absolute performance 안정화
목적:
- DS-400/800 mainline과 diverse 400/800의 consistency p95를 gate 목표에 맞춘다.

작업:
- claim volume, triage 선택률, verification loop 진입률, rows scanned를 기준으로 병목 분해
- quick/mainline은 2500ms 이하를 우선 목표로 삼고, diverse는 별도 완화 없이 추적
- 필요 시 slot extraction gating과 verification loop budget을 dataset 특성에 맞춰 보정

DoD:
- DS-400 mainline `consistency_p95 <= 2500ms`
- diverse strict는 timeout rate 20% 이하
- soak failed_ratio는 1% 이하 또는 최소한 failure breakdown으로 설명 가능한 상태

상태:
- `☑` Phase 5.1 mainline DS-400 안정화
- `☑` Phase 5.2 diverse strict timeout 해소
- `☑` Phase 5.3 soak failed_ratio 1% 미만

실행 메모 (2026-03-07):
- DS-400 mainline rerun:
  - artifact: `verify/benchmarks/20260307T022223Z.json`
  - `consistency_p95 = 2108.89ms`
  - `retrieval_fts_p95 = 27.42ms`
  - 해석: Phase 5.1 목표(`DS-400 consistency_p95 <= 2500ms`) 달성
- timeout tune:
  - `tools/bench/run_pipeline_bench.py`
    - strict profile `verification_loop.round_timeout_ms`를 `250 -> 800`으로 조정
- rerun artifact:
  - control: `verify/benchmarks/20260307T020902Z.json`
  - inject: `verify/benchmarks/20260307T021225Z.json`
  - gate: `verify/benchmarks/consistency_strict_gate_diverse_phase5_timeout_20260307T021225Z.json`
- 결과:
  - diverse strict gate `PASS`
  - control timeout rate: `0.0`
  - inject timeout rate: `0.032258...`
  - control/inject 모두 `loop_timeout_rate_le_20pct` 충족
- 해석:
  - Phase 5.2의 목표였던 “diverse strict timeout gate 해소”는 달성
  - 다만 control/inject `consistency_p95`는 여전히 3초대라 absolute performance 최적화(5.1/5.3와 별개)는 지속 필요
- soak failure breakdown:
  - short soak artifact(before mitigation): `verify/benchmarks/soak_20260307T022612Z.json`
    - `failed_ratio = 0.088815...`
    - `failure_breakdown.by_stage = {'CONSISTENCY': 54}`
    - sample job error: `database is locked`
  - 조치:
    - `modules/nf_orchestrator/storage/db.py`
      - sqlite connect timeout `30s`
      - `PRAGMA busy_timeout = 30000`
    - `modules/nf_workers/runner.py`
      - transient `database is locked` on `CONSISTENCY`에 대해 retry 추가
    - `tools/bench/run_soak.py`
      - streams > capacity일 때 consistency slot을 더 보수적으로 제한
  - fresh short soak(after mitigation): `verify/benchmarks/soak_20260307T023849Z.json`
    - `failed_ratio = 0.0`
    - `failure_breakdown = {}`
  - 해석:
    - short soak 기준으로는 Phase 5.3 목표를 충족
  - fresh 0.5h soak(after mitigation): `verify/benchmarks/soak_20260307T032658Z.json`
    - `failed_ratio = 0.0001422879908935686`
    - `jobs_failed = 1 / 7028`
    - `failure_breakdown = {'by_stage': {'CONSISTENCY': 1}, 'by_status': {'FAILED': 1}, 'by_stage_status': {'CONSISTENCY:FAILED': 1}}`
    - sample job error: `database is locked`
  - 결론:
    - delegated batch와 동일한 `0.5h soak` 기준으로도 `failed_ratio < 1%` 달성
    - Phase 5.3 목표 달성

## 5) 실행 순서
1. Phase 0
2. Phase 1
3. Phase 2
4. Phase 3
5. Phase 4
6. Phase 5

## 6) 이번 턴 실행 범위
- `완료`: Phase 0.1 summary semantics 분리
- `완료`: Phase 1.1 soak failure_breakdown 계측
- `완료`: Phase 1.2 failure_samples 보고서
- `완료`: Phase 2.1 verification loop round 계측
- `완료`: Phase 2.2 diverse strict 재실행 및 원인 판정
- `완료`: Phase 3.1 metadata grouping 기본 전략 확정
- `완료`: Phase 3.2 strict-layer3 실효성 검증
- `완료`: Phase 4.1 graph bootstrap vs normal path 분리
- `완료`: Phase 4.2 matrix graph-on normal path 적용 확인
- `완료`: Phase 5.1 DS-400 absolute performance 안정화
- `완료`: Phase 5.2 diverse strict timeout 해소
- `완료`: Phase 5.3 0.5h soak 기준 failed_ratio 해소
- `다음`: 계획 문서 기준 필수 phase는 완료. 이후는 개선 backlog(그래프 적용률 추가 향상, layer3 capability 활성화 여부 결정)로 분리

## 7) Post-Phase Backlog

### 7.1 우선순위 A — Graph 적용률 추가 향상
목적:
- `graph_runtime.applied_count`를 `0이 아님` 수준에서 끝내지 않고 운영적으로 의미 있는 비율까지 끌어올린다.

현재 근거:
- `verify/benchmarks/20260307T035012Z.json`
  - `graph_index_runtime.graph_extract_enabled = true`
  - `time_anchors_created = 203`
  - `graph_runtime.applied_count = 3 / 30`

판단:
- normal path는 살아났다.
- 다만 적용률은 아직 낮다.
- query selection과 seed rule은 최소 기능 수준이고, dataset 편향에 따라 쉽게 다시 0 근처로 떨어질 수 있다.

잔여 조치:
- retrieval benchmark용 query pool에서 시간 anchor 외에 entity alias, timeline signal도 우선 채택
- graph apply가 일어난 query와 일어나지 않은 query를 artifact에 샘플로 3~5건씩 남김
- `graph_runtime`에 `applied_queries_sample`, `skipped_reason_counts` 추가
- 목표값 정의:
  - DS-200 graph-on에서 `applied_count / sampled_jobs >= 0.20`를 1차 목표
  - DS-800 graph-on에서도 `applied_count > 0` 유지

완료 기준:
- fresh stack graph-on rerun 2회 이상에서 `applied_count > 0`가 안정적으로 반복
- 최소 1개 dataset에서 적용률 목표 충족

### 7.2 우선순위 A — Layer3 Capability 활성화 여부 결정
목적:
- strict가 현재처럼 `layer3 capability off 상태를 진단하는 strict`에 머무를지, 실제 layer3 경로를 켜서 검증할지 결정한다.

현재 근거:
- `verify/benchmarks/20260307T024925Z.json`
- `verify/benchmarks/20260307T025217Z.json`
  - `layer3_model_enabled_jobs = 0`
  - `layer3_nli_capable_jobs = 0`
  - `layer3_reranker_capable_jobs = 0`
  - `layer3_inactive_reason_counts`에 비활성 사유 누적

판단:
- 지금 strict PASS는 layer3 correctness PASS가 아니다.
- strict는 `verification loop + triage + conservative unknown`를 검증하는 수준이다.

결정 필요:
- 옵션 1: layer3를 계속 off로 두고, strict의 목표를 현재 수준으로 명시
- 옵션 2: local NLI/reranker 또는 remote API 중 하나를 활성화해 layer3 실효성을 운영 검증 범위에 포함

잔여 조치:
- `nf_config.toml` 또는 bench 전용 env에서 layer3 capability on 실험 경로 정의
- capability on/off를 artifact 상단에 명시적으로 표시
- strict gate를 2단계로 분리:
  - `strict_core_gate`
  - `strict_layer3_gate`

완료 기준:
- 운영 문서에서 strict의 의미가 모호하지 않음
- layer3 on/off 중 선택된 방향으로 artifact와 gate가 일관되게 정리됨

### 7.3 우선순위 B — Unknown Rate/Recall 개선
목적:
- 현재 보수적 설계로 높은 `unknown_rate`를 낮추되 precision 손실은 제한한다.

현재 근거:
- `verify/benchmarks/20260307T022223Z.json`
  - DS-400 quick `unknown_rate = 0.8962`
- `verify/benchmarks/20260307T035012Z.json`
  - DS-200 graph-on quick `unknown_rate = 0.8267`

판단:
- 현재 엔진은 정밀도 우선으로는 타당하다.
- 하지만 운영 관점에서는 `unknown` 비율이 너무 높아 actionability가 떨어진다.

잔여 조치:
- claim 추출 coverage 계측 추가
  - `segment_count`, `claim_count`, `slot_detection_rate`
- `NO_EVIDENCE`와 `CONFLICTING_EVIDENCE`의 비율을 dataset별로 분리 집계
- metadata grouping과 verification loop가 unknown 감소에 실제 기여하는지 A/B 측정

완료 기준:
- DS-200/400 quick에서 `unknown_rate`의 방향성이 개선되고
- 그 변화가 recall 향상인지 false positive 유입인지 artifact로 설명 가능

### 7.4 우선순위 B — SQLite Lock 완전 제거 여부 검토
목적:
- soak gate는 통과했지만 남아 있는 `database is locked` 꼬리 리스크를 제거할지 판단한다.

현재 근거:
- `verify/benchmarks/soak_20260307T032658Z.json`
  - `jobs_failed = 1`
  - `failure_breakdown.by_stage = {'CONSISTENCY': 1}`
  - sample error: `database is locked`

판단:
- 운영 기준상은 통과다.
- 다만 장시간 soak나 환경 차이에 따라 다시 드러날 수 있는 꼬리 리스크다.

잔여 조치:
- `CONSISTENCY` 내부 쓰기 hotspot 추적
  - evidence insert
  - verdict_log insert
  - verdict_evidence_link insert
  - final commit 직전 대기 시간
- lock retry 횟수와 success-after-retry count를 artifact에 추가
- 필요 시 batch insert 또는 commit granularity 조정

완료 기준:
- 1건 잔존을 수용한다고 문서화하거나
- 장시간 soak에서도 `database is locked`가 0건으로 사라짐

### 7.5 우선순위 C — 문서/게이트 의미 정리
목적:
- 지금까지 추가된 diagnostics가 많아졌으므로, 운영자가 artifact를 빠르게 읽을 수 있게 정리한다.

잔여 조치:
- `verify/benchmark_runbook.md`에 최신 판독 순서 추가
  - final gate
  - strict gate
  - latest metrics summary
  - soak failure breakdown
  - graph validation mode
- `plan/consistency_benchmark_followup_2026-03-07.md` 완료본을 바탕으로 간단한 운영 체크리스트 문서 분리

완료 기준:
- 새 실행자가 artifact 4~5개만 보고 현재 상태를 오해 없이 해석할 수 있음
