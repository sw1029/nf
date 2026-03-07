> 활성 문서: 정합성/벤치/운영 품질 보완의 단일 실행 계획
> 기준일: 2026-03-07
> 적용 범위: `modules/nf_consistency`, `modules/nf_workers`, `modules/nf_retrieval`, `modules/nf_orchestrator`, `tools/bench/*`
> 이 문서는 아래 단발성 문서의 미진행 항목을 통합해 대체한다.
> - `plan/consistency_benchmark_followup_2026-03-07.md`의 이전 버전
> - `plan/final_operational_assessment_2026-03-02.md`
> - `plan/question_claim_pipeline_operational_verification_2026-02-28.md`
> 위 문서들은 실행 이력/평가 근거로만 유지하고, 남은 TODO의 단일 진실원본은 본 문서로 고정한다.

# Consistency Benchmark Integrated Remediation Plan (2026-03-07)

## 1) 목적
- 이미 끝난 “원인 진단”과 “1회성 재실행 로그”를 계획 본문에서 제거하고, 실제로 남아 있는 로직 보완 작업만 추린다.
- 정합성 엔진의 운영 완성도를 다음 6개 축으로 닫는다.
  - 코드 정확성
  - 운영 벤치 기준선 정렬
  - strict 의미 명확화
  - graph 실효성
  - unknown/actionability
  - soak/SQLite 안정성
- 향후 벤치 재실행 시 어떤 산출물을 봐야 하는지, 어떤 상태가 “완료”인지 한 문서에서 바로 판단 가능하게 만든다.

## 2) 현재 상태 요약

### 2.1 이미 완료되어 본 계획에서 제외하는 항목
- `latest_metrics_summary`의 상대/절대 의미 분리 계측 추가
- soak `failure_breakdown` / `failure_samples` 추가
- verification loop round 계측 추가
- graph probe의 `validation_mode` 분리
- strict payload의 layer3 capability diagnostics 추가
- graph normal path의 “0이 아닌 applied_count” 확인
- 0.5h soak `failed_ratio < 1%` 달성
- WS0 1차 조치 완료
  - `modules/nf_workers/runner.py`의 SQLite lock retry 판별기 중복 정의 제거
  - `database/schema/table is locked` 3종 메시지를 transient retry 대상으로 복구
  - 회귀 테스트 통과
- WS1 1차 조치 완료
  - `tools/bench/summarize_latest_metrics.py`에 `--label-mode operational` preset 추가
  - `tools/bench/run_user_delegated.ps1`가 고정 운영 preset을 사용하도록 정렬
  - canonical `verify/benchmarks/latest_metrics_summary.{json,md}`를 운영 라벨 기준으로 재생성
- WS1 2차 조치 완료
  - `tools/bench/summarize_latest_metrics.py`가 실패 artifact를 summary 후보에서 제외
  - `modules/nf_workers/runner.py`에 long-running job lease heartbeat 추가
  - `modules/nf_orchestrator/storage/repos/job_repo.py`가 성공 상태 전환 시 stale `error_code/error_message`를 정리
  - 관련 회귀 테스트 통과

위 항목은 재오픈 대상이 아니다. 이후 다시 다루는 경우는 회귀가 발견될 때만이다.

### 2.2 현재 남아 있는 핵심 결손
1. 운영 라벨 기준 canonical summary는 정렬됐고 DS-200/400은 운영 PASS까지 회복됐지만, DS-800은 기존 실패 artifact 2건이 summary에서 배제된 뒤에도 baseline 복구가 안 됐고, post-fix rerun은 `RemoteDisconnected`로 중단돼 아직 운영 재확인 완료가 아니다.
2. lease heartbeat는 추가됐지만, `lease_owner` 검증과 terminal state monotonicity(`FAILED -> SUCCEEDED` 같은 상태 역전 방지)는 아직 제도화되지 않았다.
3. bench/orchestrator front-door에서 `RemoteDisconnected`가 반복되는데, 현재 bench client는 single-shot 요청만 사용하고 structured failure artifact를 남기지 않아 원인 추적 효율이 낮다.
4. 운영 summary는 실패 artifact를 제외하도록 보강됐지만, 그 결과 dataset별 “최신 성공 실행(latest successful)”만 보이고 “최신 시도(latest attempt)”가 가려질 수 있다.
5. strict PASS는 현재 `strict core` PASS이지 `layer3 correctness` PASS가 아니다.
6. graph normal path는 살아났지만 `graph_runtime.applied_count = 3 / 30` 수준으로 아직 낮다.
7. quick 계열 `unknown_rate`가 여전히 높아 결과의 actionability가 낮다.
8. 0.5h soak는 통과했지만 `database is locked` tail 1건이 남아 있다.

### 2.3 현 시점 판정
- 코드 구조/진단 가능성: `B+`
- 운영 게이트 일치성: `B-`
- strict completeness: `C+`
- graph 실효성: `C+`
- unknown/actionability: `C`
- soak 장기 안정성: `B-`

## 3) 현재 기준 증거

### 3.1 핵심 artifact
- `verify/benchmarks/20260307T022223Z.json`
  - DS-400 check artifact
  - `consistency_p95 = 2108.89ms`
- `verify/benchmarks/20260307T035012Z.json`
  - graph normal path rerun
  - `graph_runtime.applied_count = 3 / 30`
- `verify/benchmarks/20260307T024925Z.json`
- `verify/benchmarks/20260307T025217Z.json`
  - strict rerun
  - `layer3_*_jobs = 0`
- `verify/benchmarks/soak_20260307T032658Z.json`
  - `failed_ratio = 0.000142...`
  - `database is locked` tail 1건
- `verify/benchmarks/latest_metrics_summary.json`
  - canonical 운영 summary
  - `overall_status = WARN`
  - `absolute_goal_status = FAIL`
  - DS-200 `status = PASS`, `absolute_status = PASS`
  - DS-400 `status = PASS`
  - DS-400 `absolute_status = PASS`
- `verify/benchmarks/20260307T064648Z.json`
  - DS-200 operational rerun
  - `consistency_p95 = 1615.80ms`
  - `retrieval_fts_p95 = 27.93ms`
- `verify/benchmarks/20260307T061120Z.json`
  - DS-400 operational rerun
  - `consistency_p95 = 2067.48ms`
  - `retrieval_fts_p95 = 28.26ms`
- `verify/benchmarks/20260307T071917Z.json`
  - DS-800 operational rerun 시도 1
  - `index_fts = FAILED`
- `verify/benchmarks/20260307T073717Z.json`
  - DS-800 operational rerun 시도 2
  - `index_fts = FAILED`
- 운영 라벨 재계산 기준:
  - `python tools/bench/summarize_latest_metrics.py --bench-dir verify/benchmarks --datasets "DS-200,DS-400,DS-800,DS-DIVERSE-200,DS-DIVERSE-400,DS-DIVERSE-800" --label-mode operational`
  - 이 관점에서는 DS-200/400은 운영 기준 PASS로 복구됐고, DS-800 실패 artifact 2건은 summary에서 제외된다.

### 3.2 현재 운영 해석
- final/summary/strict/soak의 “모든 의미”가 완전히 정렬된 상태는 아니다.
- strict gate는 현재 `verification loop + triage + conservative unknown` 검증에 가깝다.
- 운영 mainline absolute performance는 ad hoc artifact와 운영 라벨 artifact가 어긋나 있다.
- 운영 summary는 현재 “latest successful artifact” 중심 해석이고, “latest attempt failed”를 dataset 표에서 직접 보여주지 않는다.
- job 상태 일관성은 heartbeat 추가로 개선됐지만, 소유권 검증 없는 terminal 상태 전환은 여전히 별도 보강 대상이다.
- graph는 “경로 존재”까지는 확인됐지만 “운영적으로 의미 있는 적용률”은 미달이다.

## 4) 활성 작업 원칙
- 이미 구현된 계측을 또 늘리기보다, 남은 공백을 닫는 방향으로만 작업한다.
- ad hoc 재실행 결과는 보조 증거로 쓰되, 운영 완료 판정은 반드시 운영 라벨 artifact에서 닫는다.
- strict는 더 이상 하나의 의미로 쓰지 않는다. core와 layer3를 분리해 다룬다.
- 성능 개선은 “문턱 상향”과 “실제 병목 제거”를 분리해 기록한다.
- 문서의 완료 표기는 artifact와 gate에 반영된 뒤에만 사용한다.

## 5) 활성 Workstream

### WS0. 즉시 수정 — SQLite lock retry 정확성 복구
목적:
- 현재 남아 있는 가장 명확한 코드 버그를 먼저 제거한다.

상태:
- `완료 (2026-03-07)`

현재 근거:
- `modules/nf_workers/runner.py`에 `_is_transient_sqlite_lock_error`가 중복 정의되어 있다.
- 실제 런타임 판별은 `"database is locked"`만 인정하고 `"database schema is locked"`, `"database table is locked"`는 놓친다.

작업:
1. `modules/nf_workers/runner.py`
   - `_is_transient_sqlite_lock_error`를 1개만 남긴다.
   - 허용 토큰을 아래 3종으로 고정한다.
     - `database is locked`
     - `database schema is locked`
     - `database table is locked`
2. 테스트 보강
   - `tests/test_nf_workers_consistency_payload.py`
   - 필요 시 신규 unit test
   - schema/table lock 예외도 retry 대상으로 분류되는지 고정한다.
3. 회귀 검증
   - worker/consistency/storage 관련 테스트 재실행

완료 기준:
- retry helper가 세 종류의 lock 문자열을 모두 transient로 분류한다.
- 기존 `database is locked` retry 테스트와 함께 schema/table lock 테스트도 통과한다.
- 코드 리뷰 기준 “중복 정의에 의한 런타임 의미 축소”가 사라진다.

실행 메모:
- 코드 수정:
  - `modules/nf_workers/runner.py`
    - 중복 `_is_transient_sqlite_lock_error` 정의 제거
- 테스트 보강:
  - `tests/test_nf_workers_consistency_payload.py`
    - consistency retry 테스트를 3종 lock 메시지로 확장
  - `tests/test_nf_workers_runner_memory_pressure_events.py`
    - leasing retry 테스트를 3종 lock 메시지로 확장
    - non-lock 예외가 retry 대상이 아님을 고정
- 검증:
  - `pytest -q tests/test_nf_workers_runner_memory_pressure_events.py tests/test_nf_workers_consistency_payload.py`
  - 결과: `13 passed`

우선순위:
- `P0`

### WS1. 운영 기준선 정렬 — ad hoc 성능 개선을 operational gate로 승격
목적:
- DS-400 성능 개선이 실제 운영 summary/gate 경로에도 반영되도록 기준선을 정렬한다.

상태:
- `진행중 (1차 조치 완료, 운영 rerun 대기)`

현재 근거:
- `verify/benchmarks/20260307T022223Z.json`은 DS-400 `consistency_p95 <= 2500ms`를 달성했다.
- 하지만 운영 summary는 `operational-main:` 라벨 기준으로 집계되며, 현재 운영 DS-400 기준선은 여전히 2500ms 초과다.
- 이 상태에서는 “개선 완료”와 “운영 게이트 반영 완료”가 분리되어 있다.

작업:
1. 운영 벤치 재실행 규격 고정
   - DS-200: `operational-main:DS-200`
   - DS-400: `operational-main:DS-400`
   - DS-800: `operational-main:DS-800`
   - strict control/inject도 운영 라벨 체계로 재실행
2. `tools/bench/run_user_delegated.ps1`
   - 운영 summary 생성 시 사용하는 라벨 필터 규격을 문서에 고정한다.
   - `operational-main:` / `operational-diversity-main:` 외 라벨은 summary gate 기준선으로 사용하지 않음을 명시한다.
3. summary/gate 재생성
   - `latest_metrics_summary.json`
   - `latest_metrics_summary.md`
   - strict gate artifact
   - final gate artifact
4. 기준선 승격 규칙 명문화
   - ad hoc 검증 artifact는 “보조 증거”
   - 운영 완료 판정은 운영 라벨 artifact 재생성 후에만 허용
5. summary 의미 보강
   - dataset별 `latest_successful_run`과 `latest_attempt_run`을 분리해 보이거나 동등한 정보를 제공한다.
   - 실패 artifact를 baseline에서 제외하더라도, 마지막 시도 실패 자체는 숨기지 않는다.
6. job 상태 불변성 보강
   - success/failure/cancel 전환 시 `lease_owner` 또는 현재 상태를 함께 검증하는 compare-and-set 경로를 검토한다.
   - terminal 상태 이후 역전이 가능한지 테스트로 고정한다.
7. bench transport/front-door 안정화
   - `RemoteDisconnected`를 재시도/관찰 가능한 오류 유형으로 분리한다.
   - 최소한 실패 시 `attempt_stage`, `request_path`, `error_class`, `base_url`을 남기는 structured failure artifact를 추가한다.

검증:
1. 운영 라벨 summary에서 DS-400 `absolute_status` 재확인
2. 운영 라벨 summary에서 `status_semantics`와 `absolute_goal_status`가 모두 존재하는지 확인
3. strict/final gate 판독 순서와 해석이 문서와 일치하는지 확인
4. 실패한 operational rerun이 summary에서 baseline 후보로 배제되면서도, “latest attempt failed” 사실은 별도 필드/문서에서 확인 가능한지 검증
5. 장시간 job에서 lease 만료 후 상태 역전이 재발하지 않는지 검증
6. `RemoteDisconnected` 재현 시 bench 쪽에 구조화된 실패 근거가 남는지 검증

완료 기준:
- 운영 라벨 기준 `latest_metrics_summary.json`이 stale artifact 없이 재생성된다.
- DS-400 운영 artifact가 2500ms 이하이면 `absolute_goal_status`가 그에 맞게 갱신된다.
- DS-400이 여전히 실패면, 실패 상태가 운영 산출물에 그대로 반영되고 계획 문서도 그 상태를 유지한다.
- “운영 완료”와 “phase-only 완료”가 더 이상 혼동되지 않는다.
- 실패 artifact 제외 정책이 “실패 숨김”으로 이어지지 않는다.
- terminal 상태 역전 가능성이 테스트와 코드 양쪽에서 차단된다.
- front-door transport 실패가 재현되면 최소한 bench artifact만으로 시도 단계와 오류 유형이 드러난다.

실행 메모:
- 도구 보강:
  - `tools/bench/summarize_latest_metrics.py`
    - `--label-mode operational` 추가
    - label filter metadata에 `mode` / `note` 포함
  - `tools/bench/run_user_delegated.ps1`
    - summary generation이 hard-coded prefix 대신 operational preset을 사용하도록 정렬
- 테스트:
  - `tests/test_tools_bench_metrics_summary.py`
    - operational label mode preset 동작 고정
  - 결과: `5 passed`
- 산출물 갱신:
  - `verify/benchmarks/latest_metrics_summary.json`
  - `verify/benchmarks/latest_metrics_summary.md`
  - 현재 결과:
    - `label_filter.mode = operational`
    - 초기 재생성 시 모든 dataset이 `NO_BASELINE`
- operational rerun:
  - `verify/benchmarks/20260307T064648Z.json`
  - DS-200:
    - `consistency_p95 = 1615.80ms`
    - `retrieval_fts_p95 = 27.93ms`
    - summary 반영 후 `status = PASS`
    - summary 반영 후 `absolute_status = PASS`
    - previous operational baseline:
      - `verify/benchmarks/20260306T153830Z.json`
  - `verify/benchmarks/20260307T061120Z.json`
  - DS-400:
    - `consistency_p95 = 2067.48ms`
    - `retrieval_fts_p95 = 28.26ms`
    - summary 반영 후 `status = PASS`
    - summary 반영 후 `absolute_status = PASS`
    - previous operational baseline:
      - `verify/benchmarks/20260306T153831Z.json`
  - `verify/benchmarks/20260307T071917Z.json`
  - `verify/benchmarks/20260307T073717Z.json`
  - DS-800:
    - 두 번 모두 `index_fts = FAILED`
    - summary 후보에서 제외됨
- DS-800 원인 분해:
  - root DB 관찰:
    - 실패 job의 최종 DB 상태는 `SUCCEEDED`인데 stale `error_code = INTERNAL_ERROR`, `error_message = database is locked`가 남아 있었음
    - 동일 job에서 `failed` 뒤에 `fts indexed` / `done` 이벤트가 관찰되어 lease expiry 기반 중복 처리 가능성이 확인됨
  - 대응 구현:
    - `modules/nf_workers/runner.py`
      - `WorkerContext.heartbeat()` 추가
      - `INDEX_FTS` / `INDEX_VEC` long-running loop에서 lease 연장
    - `modules/nf_orchestrator/storage/repos/job_repo.py`
      - `SUCCEEDED`/`CANCELED` 전환 시 stale error 필드 제거
    - `tools/bench/summarize_latest_metrics.py`
      - 실패 artifact 제외
  - 회귀 검증:
    - `pytest -q tests/test_nf_workers_runner_memory_pressure_events.py tests/test_nf_orchestrator_storage.py tests/test_tools_bench_metrics_summary.py`
    - 결과: `19 passed`
- post-fix rerun:
  - `8085` stack:
    - `INDEX_VEC` 제출 시 `RemoteDisconnected`
  - `8080` stack:
    - project 생성 POST 단계에서 `RemoteDisconnected`
  - 해석:
    - lease expiry/stale error 경로는 보강됐으나, 현재 남은 DS-800 blocker는 API transport/orchestrator front-door 안정성 쪽이다.
- rerun 후 canonical summary:
  - `overall_status = WARN`
  - `absolute_goal_status = FAIL`
  - `label_filter.mode = operational`
  - `label_filter.excluded_unsuccessful_status = 2`
  - DS-200/400는 baseline 비교 가능 상태로 복구
  - DS-800은 실패 artifact 배제 후 `NO_BASELINE`
  - diversity 계열은 여전히 `NO_BASELINE`
- 남은 작업:
  - DS-800 `RemoteDisconnected` 원인 분해 및 operational baseline 복구
  - `lease_owner` 검증 및 terminal state monotonicity 보강 여부 결정
  - summary에 `latest_successful` / `latest_attempt` 분리 반영
  - bench transport 실패 시 structured failure artifact 추가
  - diversity operational baseline 복구 여부 결정 및 rerun
  - strict/final gate도 같은 기준선으로 재생성

우선순위:
- `P0`

### WS2. strict 의미 분리 — strict_core_gate / strict_layer3_gate
목적:
- strict PASS의 의미를 명확히 하고, layer3 비활성 상태를 “완료”로 오인하지 않게 만든다.

현재 근거:
- strict artifact에서 `layer3_model_enabled_jobs = 0`, `layer3_nli_capable_jobs = 0`
- 현재 strict PASS는 layer3 correctness PASS가 아니다.

작업:
1. 정책 결정
   - 옵션 A: layer3 계속 off
   - 옵션 B: local NLI/reranker 또는 remote API 중 하나를 활성화
2. gate 분리
   - `strict_core_gate`
     - 현재 strict 의미 유지
     - verification loop, triage, inject signal, timeout rate 중심
   - `strict_layer3_gate`
     - layer3 on일 때만 활성
     - capability, rerank applied, promoted ok, fallback 의미를 따로 판정
3. artifact 상단 명시
   - layer3 on/off
   - active capability source(local/remote)
   - strict_core / strict_layer3 판정 구분
4. 문서 정리
   - “strict PASS” 단독 표현 금지
   - 항상 core/layer3 중 무엇을 의미하는지 함께 표기

검증:
1. layer3 off 경로
   - strict_core는 정상 PASS
   - strict_layer3는 `SKIPPED` 또는 `N/A`
2. layer3 on 경로를 선택할 경우
   - 최소 1회 control/inject rerun
   - `layer3_*` 카운트가 실제로 0이 아닌지 확인

완료 기준:
- strict 결과물에서 core와 layer3 의미가 분리되어 보인다.
- 운영 문서/게이트/summary 어디에도 “strict PASS = layer3 PASS”로 읽힐 여지가 없다.
- 선택된 운영 방향(on/off)에 맞게 artifact와 gate가 일관된다.

우선순위:
- `P1`

### WS3. graph 실효성 확대 — path existence에서 applied rate 관리로 전환
목적:
- graph normal path가 살아 있는 수준을 넘어, 운영적으로 의미 있는 적용률과 재현성을 확보한다.

현재 근거:
- `verify/benchmarks/20260307T035012Z.json`
  - `graph_runtime.applied_count = 3 / 30`
- `graph_index_runtime`는 정상 생성되지만 query selection/seed 품질은 아직 최소 기능 수준이다.
- 이전 평가 문서의 “grouping 운영 E2E 커버리지 부족” 문제도 완전히 닫히지 않았다.

작업:
1. query selection 고도화
   - 시간 anchor 외에 entity alias, timeline signal을 우선 후보로 포함
   - graph apply가 된 query / 안 된 query 샘플을 artifact에 남김
2. runtime 계측 보강
   - `graph_runtime.applied_queries_sample`
   - `graph_runtime.skipped_reason_counts`
   - 필요 시 `seed_signal_type_counts`
3. 운영 A/B 벤치 추가
   - DS-200 graph off/on
   - DS-800 graph off/on
   - latency와 applied rate를 같이 기록
4. grouping E2E 보강
   - entity/time/timeline on-demand 시나리오를 소형 dataset으로 별도 확인
   - 기본 운영 CMD에서 최소 1개 grouping 검증 step이 누락되지 않게 정리

검증:
1. fresh stack graph-on rerun 2회 이상
2. DS-200/800 graph off/on 성능 비교
3. graph apply가 실제 retrieval candidate 변화로 이어지는지 샘플 확인

목표값:
- DS-200 graph-on: `applied_count / sampled_jobs >= 0.20`
- DS-800 graph-on: `applied_count > 0`를 안정적으로 반복
- graph on/off 성능 회귀는 설명 가능한 범위 내로 유지

완료 기준:
- graph 적용률이 단발성 `3/30` 확인 수준을 넘어 반복 재현된다.
- graph artifact만 읽어도 왜 적용됐는지/왜 스킵됐는지 설명 가능하다.
- grouping 운영 E2E 검증 공백이 해소된다.

우선순위:
- `P1`

### WS4. unknown/actionability 개선 — recall을 올리되 precision 손실은 통제
목적:
- quick/mainline에서 `unknown` 비율을 낮추고, 낮춘 이유가 진짜 recall 개선인지 설명 가능하게 만든다.

현재 근거:
- DS-400 quick `unknown_rate = 0.8962`
- DS-200 graph-on quick `unknown_rate = 0.8267`
- 현재 엔진은 보수적이라 precision 지향이지만 운영 액션 가능성이 낮다.

작업:
1. coverage 계측 추가
   - `segment_count`
   - `claim_count`
   - `slot_detection_rate`
   - `claims_skipped_low_confidence`
2. unknown 사유 분해 고정
   - `NO_EVIDENCE`
   - `CONFLICTING_EVIDENCE`
   - `SLOT_UNCOMPARABLE`
   - dataset/profile별 분리 집계
3. A/B 측정
   - baseline
   - metadata grouping on
   - verification loop on
   - triage 정책 조정
4. 규칙 조정은 계측 후 수행
   - slot 비교 가능성 확대
   - claim 추출 coverage 보완
   - triage/verifier 진입 기준 보정

검증:
1. DS-200/400 quick rerun
2. unknown 감소폭과 false positive 유입 여부 동시 확인
3. unknown 감소 원인이 어떤 사유 bucket 변화로 왔는지 보고

완료 기준:
- DS-200/400 quick에서 `unknown_rate`가 유의미하게 감소한다.
- 감소가 recall 향상인지 오탐 증가인지 artifact로 설명 가능하다.
- 최소 상위 2개 unknown 사유가 전체 unknown의 대부분을 차지하는 구조로 정리된다.

우선순위:
- `P1`

### WS5. soak tail lock 제거 — “통과”에서 “장기 안정”으로 이동
목적:
- soak가 이미 통과한 상태를 유지하되, 남아 있는 SQLite tail risk를 실질적으로 줄인다.

현재 근거:
- `verify/benchmarks/soak_20260307T032658Z.json`
  - `jobs_failed = 1 / 7028`
  - `sample error = database is locked`
- retry/busy_timeout/adaptive slot 제한 이후에도 tail 1건이 남아 있다.

작업:
1. WS0 반영 후 soak 재평가
   - retry 분류기 수정 반영
2. hotspot 계측 추가
   - evidence insert
   - verdict_log insert
   - verdict_evidence_link insert
   - final commit 직전 대기 시간
3. retry outcome 계측
   - `lock_retry_attempt_count`
   - `lock_retry_success_count`
   - `lock_retry_exhausted_count`
4. 필요 시 쓰기 전략 조정
   - batch insert
   - commit granularity 조정
   - consistency stage 내부 write ordering 재검토
5. soak 단계화
   - short soak
   - 0.5h soak
   - 필요 시 장시간 soak

검증:
1. short soak로 빠른 확인
2. 0.5h soak 재실행
3. tail이 남으면 failure sample과 hotspot span까지 함께 분석

완료 기준:
- 최소 0.5h soak에서 `database is locked`가 0건이거나,
- 0건이 되지 않더라도 retry/exhaust/hotspot 근거로 잔존 원인이 완전히 설명 가능하다.
- 운영 문서에 “잔존 리스크 수용” 또는 “완전 제거” 중 하나로 명시된다.

우선순위:
- `P1`

### WS6. 문서/운영 판독 정리 — 실행자 오해 방지
목적:
- 산출물 해석 순서와 각 gate의 의미를 문서상으로 완전히 정리한다.

작업:
1. `verify/benchmark_runbook.md` 또는 동등 문서에 판독 순서 고정
   - final gate
   - strict_core_gate
   - strict_layer3_gate
   - latest metrics summary
   - soak failure breakdown
   - graph validation mode
2. 본 문서와 artifact 용어 통일
   - `trend_relative`
   - `absolute_goal_status`
   - `operational-main`
   - `phase-only`
3. 단발성 문서 처리
   - 기존 문서는 history/assessment로만 유지
   - “active TODO는 본 문서”임을 상단에 명시할 필요가 있으면 별도 후속 반영

완료 기준:
- 새 실행자가 산출물 4~5개만 보고도 현재 상태를 오해하지 않는다.
- strict/summary/final/soak/graph의 의미가 문서마다 다르게 쓰이지 않는다.

우선순위:
- `P2`

## 6) 통합 실행 순서
1. WS1
   - 운영 기준선과 summary/gate 라인을 현재 코드 상태에 맞게 재정렬한다.
2. WS2
   - strict 의미를 core/layer3로 분리해 문서/게이트 해석을 고정한다.
3. WS3
   - graph의 “존재 확인”을 “적용률 관리”로 끌어올린다.
4. WS4
   - unknown/actionability를 계측 후 개선한다.
5. WS5
   - soak tail lock을 장기 안정성 기준으로 재검증한다.
6. WS6
   - runbook과 문서 용어를 정리해 운영 인수인계 가능한 상태로 마무리한다.

## 7) 실행 시 고정 규칙
- summary는 반드시 운영 라벨 필터를 적용한 산출물로 본다.
- ad hoc artifact는 완료 판정의 보조 증거로만 사용한다.
- strict는 core/layer3 분리 전까지 “core-only strict”로 해석한다.
- graph 개선은 applied rate와 latency를 동시에 본다.
- unknown 개선은 precision 손실 설명 없이 수치만 낮췄다고 완료 처리하지 않는다.
- soak는 `failed_ratio`만 보지 않고 failure sample과 retry outcome도 같이 본다.

## 8) 완료 정의
- 코드 정확성 버그가 제거되고 테스트로 고정된다.
- 운영 라벨 summary/final/strict 기준선이 현 코드 상태에 맞게 재생성된다.
- strict_core / strict_layer3 의미가 분리된다.
- graph는 재현 가능한 applied rate 목표를 충족한다.
- unknown 개선이 수치와 원인 모두 설명 가능해진다.
- soak tail lock이 제거되거나 명시적으로 수용 가능한 수준으로 문서화된다.
- 본 문서 외에 별도 단발성 follow-up 계획문서가 더 필요하지 않다.

## 9) 문서 갱신 규칙
- 상태 갱신은 `완료/진행중/보류`만 적지 않고 반드시 근거 artifact를 함께 남긴다.
- “완료” 표기는 운영 라벨 artifact 또는 gate 갱신 후에만 사용한다.
- ad hoc 검증만 끝난 경우 표기는 `검증 완료(운영 미반영)`로 통일한다.
- 새로운 TODO가 생기면 먼저 본 문서에 추가하고, 별도 일회성 계획문서는 만들지 않는다.
