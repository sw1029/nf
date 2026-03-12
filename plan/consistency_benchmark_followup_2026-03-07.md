> 활성 문서: 정합성/벤치/운영 품질 보완의 단일 실행 계획
> 기준일: 2026-03-07
> 적용 범위: `modules/nf_consistency`, `modules/nf_workers`, `modules/nf_retrieval`, `modules/nf_orchestrator`, `tools/bench/*`
> 이 문서는 아래 단발성 문서의 미진행 항목을 통합해 대체한다.
> - `plan/consistency_benchmark_followup_2026-03-07.md`의 이전 버전
> - `plan/final_operational_assessment_2026-03-02.md`
> - `plan/question_claim_pipeline_operational_verification_2026-02-28.md`
> 위 문서들은 실행 이력/평가 근거로만 유지하고, 남은 TODO의 단일 진실원본은 본 문서로 고정한다.

# Consistency Benchmark Integrated Remediation Plan (2026-03-07)

## 0) 2026-03-07 추가 구현 반영
- source-id / registry governance 보강 완료
  - `tools/bench/source_policy_registry.json`
    - `source_policy_registry_version = 20260307-r1`
    - tracked registry는 `source_id` + `content_sha256`만 보존
  - `tools/bench/build_novel_dataset.py`
    - tracked output에서 real corpus filename 제거
    - record/manifest/manual-review source를 모두 `source_id` 중심으로 전환
    - local reverse lookup은 `verify/datasets/source_name_lookup.local.json`로 분리
  - 실제 재생성 결과:
    - `verify/datasets/dataset_manifest.json`
    - `fallback_source_files = ["SRC-2e0ba0a8ee12"]`
    - `manual_review_sources.json`도 `source_id` 기준으로 저장
    - `manual_review_source_count = 1`
    - `manual_review_reason_counts = {"unsupported_or_ambiguous_source_structure": 1}`
- local-first judge scaffold 구현 완료
  - `modules/nf_shared/config.py`
    - `enable_test_judge_local_nli`
    - `enable_test_judge_remote_api`
    - `test_judge_local_nli_model_id`
    - `test_judge_timeout_ms`
    - `test_judge_min_confidence`
  - `tools/bench/judge_audit.py`
    - `source_policy_judge`
    - `judge_inject_quality`
  - 현재 해석:
    - test-only local judge scaffold는 구현 완료
    - 기본 설정은 off이므로 deterministic primary path는 그대로 유지
    - 현재 artifact 기준 source policy judge의 실적용은 0건이고, inject judge는 전건 `contextless_append`로 수렴한다
    - `enable_test_judge_remote_api`는 설정 플래그와 builder 조건에는 있으나 dataset judge path의 distinct backend로는 아직 연결되지 않았다
    - 따라서 현재 judge 경로는 “운영에 통합된 LLM as judge”가 아니라 “test-only secondary audit scaffold”로 취급해야 한다
- config loader BOM 호환 보강 완료
  - `modules/nf_shared/config.py`
    - UTF-8 BOM이 있는 `nf_config.toml`도 정상 로드
  - 해석:
    - PowerShell 5.1 `Set-Content -Encoding utf8`로 생성한 config에서도 `tomllib.TOMLDecodeError` 없이 로드 가능
- one-shot validation script 구현 완료
  - `tools/bench/run_one_shot_validation.ps1`
    - TOML 파일을 쓰지 않고 process-scoped env override만 사용
    - intentional failure probe는 `Invoke-PythonJsonAllowExpectedFailure`로 검증
    - dataset manifest / live bench artifact / failure artifact를 실제로 열어 필수 필드를 검사
    - delegated long-run 명령을 PowerShell one-liner로 출력
  - 해석:
    - PowerShell 5.1 BOM 이슈는 loader fix로 해소했고, 운영 절차는 TOML write보다 env override를 우선한다
    - 다만 현재 Step 4는 `frontdoor_probe`와 `dataset_manifest_entry` 존재만 확인하므로 runtime success gate까지 닫지는 못한다
    - 최신 one-shot live bench artifact(`verify/benchmarks/20260307T135531Z.json`)는 `index_vec = FAILED`, `ingest_failures = 1`, `consistency_failures = 1`, `retrieve_vec_failures = 1`, `guards.* = false`를 보였다
    - 따라서 current one-shot은 provenance/schema smoke로는 유효하지만 live bench 성공 smoke로는 미완료이며, 본 문서에서 `WS0A`로 재오픈한다
- structured inject subset 구현 완료
  - `tools/bench/build_novel_dataset.py`
    - `inject_case_id`
    - `inject_target_scope`
    - `inject_expected_primary_signal`
    - `inject_expected_core_verdict`
    - `DS-INJECT-C-STRUCTURED`
    - `DS-DIVERSE-INJECT-C-STRUCTURED`
  - 실제 재생성 결과:
    - `verify/datasets/DS-INJECT-C-STRUCTURED.jsonl`
      - `count = 49`
    - `verify/datasets/DS-DIVERSE-INJECT-C-STRUCTURED.jsonl`
      - `count = 49`
  - 해석:
    - generic append inject 전체를 대체하지는 않지만, deterministic structured subset이 추가되어 strict/analysis 보조지표에 활용 가능해졌다
- filename governance validation 구현 완료
  - `tools/quality/check_source_filename_governance.py`
  - 실제 실행 결과:
    - `python tools/quality/check_source_filename_governance.py --repo-root . --source-dir test_files`
    - `ok = true`
- dataset builder P0 1차 보강 완료
  - `tools/bench/build_novel_dataset.py`
    - `1화` / `0화 프롤로그` / `001. 프롤로그` / `1. 단편 제목` 계열 헤더 탐지 추가
    - content SHA-256 기반 provenance 추가
    - `dataset_manifest.json`에 `build_input_hash_policy`, `segmentation_summary`, `quality_warnings`, `sampling_strategy`, `source_order`, `candidate_boundary_counts`, `boundary_counts`, `content_length_stats` 추가
    - record에 `source_segmentation_mode`, `source_boundary_header`, `source_boundary_pattern`, `inject_strategy` 추가
  - 실제 재생성 결과:
    - `verify/datasets/dataset_manifest.json`
    - `segmentation_summary.files_total = 36`
    - `fallback_files = 10`
    - `episodes_total = 8260`
    - `fallback_episodes = 1797`
    - `fallback_episode_share = 0.217554`
  - 해석:
    - pre-fix `fallback_episode_share = 0.8247` 대비 큰 폭 개선
    - 다만 fallback file 10개와 일부 corpus의 partial over/under split은 여전히 남아 있다
- dataset builder P1 2차 보강 완료
  - `tools/bench/build_novel_dataset.py`
    - `<1화>` / `작품명 1화` / `< 챕터 제목(1) >` 계열 패턴 추가
    - `candidate_boundary_counts`를 source manifest에 추가
    - `quality_warnings`에 `FALLBACK_SOURCES_PRESENT`, `GROWTH_DATASET_PREFIX_BIAS`, `GENERIC_APPEND_INJECT_DATASET` 추가
  - 실제 재생성 결과:
    - `verify/datasets/dataset_manifest.json`
    - `fallback_files = 7`
    - `episodes_total = 8646`
    - `fallback_episodes = 1377`
    - `fallback_episode_share = 0.159264`
  - 해석:
    - 1차 조치 후 `0.217554`에서 추가 개선
    - 다만 헤더가 아예 없거나 ebook front matter 위주인 source 7개는 여전히 fallback으로 남는다
- dataset builder P1 3차 보강 완료
  - `tools/bench/build_novel_dataset.py`
    - `EP.0 ...`, `【1. ...】`, `제1조. ...`, `작품명 (1)` 계열 패턴 추가
    - `segmentation_summary.fallback_source_files` 추가
    - inject record에 `inject_subject_text`, `inject_expected_signal` 추가
  - 실제 재생성 결과:
    - `verify/datasets/dataset_manifest.json`
    - `fallback_files = 2`
    - `episodes_total = 8286`
    - `fallback_episodes = 218`
    - `fallback_episode_share = 0.026309`
    - `fallback_source_files = ["SRC-2e0ba0a8ee12", "SRC-4acdce6d77d8"]`
  - 해석:
    - pre-fix `0.8247` 대비 크게 개선됐고, source-specific 수동 검토가 필요한 잔여 source가 2개로 좁혀졌다
- dataset builder P1 4차 보강 완료
  - `tools/bench/build_novel_dataset.py`
    - composite dataset policy를 `exclude_fallback_sources_unless_empty`로 전환
    - `DS-GROWTH-*`를 file-prefix가 아니라 deterministic shuffled prefix로 재구성
    - composite pool metadata(`eligible_source_files`, `excluded_source_files`, `eligible_episode_count`, `excluded_episode_count`) 추가
  - 실제 재생성 결과:
    - `verify/datasets/dataset_manifest.json`
    - `composite_source_policy = exclude_fallback_sources_unless_empty`
    - `eligible_source_files = 34`
    - `excluded_source_files = 2`
    - `eligible_episode_count = 8068`
    - `excluded_episode_count = 218`
    - `DS-GROWTH-50.sampling_strategy = shuffled_seed_42_prefix_50`
    - `DS-INJECT-C.sampling_strategy = uniform_sample_from_eligible_sources_then_append_inject`
  - 해석:
    - remaining fallback source 2개는 더 이상 composite growth/diversity/inject/control benchmark pool에 섞이지 않는다
    - `DS-GROWTH-*`는 여전히 benchmark semantics 변경이므로 과거 수치와 직접 비교 시 주의가 필요하다
- dataset builder P1 5차 보강 완료
  - `tools/bench/build_novel_dataset.py`
    - `SRC-4acdce6d77d8`에 source-specific `standalone_number` segmentation override 적용
    - `source_segmentation_policy` 및 `MANUAL_REVIEW_SOURCE_POLICY` 추가
    - `dataset_generation_version = 20260307-r5` 추가
  - 실제 재생성 결과:
    - `verify/datasets/dataset_manifest.json`
    - `dataset_generation_version = 20260307-r5`
    - `fallback_files = 1`
    - `episodes_total = 8433`
    - `fallback_episodes = 99`
    - `fallback_episode_share = 0.01174`
    - `fallback_source_files = ["SRC-2e0ba0a8ee12"]`
  - 해석:
    - 남은 fallback source는 사실상 `SRC-2e0ba0a8ee12` 단일 source로 축소됐다
    - 이 source는 current heuristic보다 manual review 정책이 더 안전하다
- summary semantics 보강 완료
  - `tools/bench/summarize_latest_metrics.py`
    - dataset row에 `latest_successful_*`, `latest_attempt_*`, `latest_attempt_status`, `latest_attempt_succeeded` 추가
  - 실제 재생성 결과:
    - `verify/benchmarks/latest_metrics_summary.json`
    - DS-800:
      - `latest_successful_file = 20260306T153832Z.json`
      - `latest_attempt_file = 20260307T073717Z.json`
      - `latest_attempt_status = index_fts:FAILED`
- strict semantics 보강 완료
  - `tools/bench/check_consistency_strict_gate.py`
    - `strict_core_gate`와 `strict_layer3_gate`를 분리
  - 실제 재실행 결과:
    - `verify/benchmarks/consistency_strict_gate_20260307T103600Z_iter1.json`
    - `strict_core_gate.passed = true`
    - `strict_layer3_gate.status = SKIPPED`
    - 현재 layer3 correctness는 “미통과”가 아니라 “비활성으로 인해 미적용” 상태임이 artifact에서 직접 보인다
- future bench artifact provenance 보강 완료
  - `tools/bench/run_pipeline_bench.py`
    - `semantic.dataset_profile` 추가
    - future artifact에 `source_segmentation_mode_counts`, `source_boundary_pattern_counts`, `injected_kind_counts`, `inject_strategy_counts`, `generic_append_inject_present`, `growth_prefix_dataset`가 함께 저장되도록 보강
- transport/front-door failure artifact 보강 완료
  - `tools/bench/http_client.py`
    - `ApiRequestError` 추가
    - GET 및 safe POST(`/projects`, `/query/retrieval`)에 transient retry 추가
    - `request_body_shape`, `retry_count`, `retryable`, `backoff_total_sec` telemetry 추가
  - `tools/bench/run_pipeline_bench.py`
    - 실패 시 `failure_*.json/.md` structured artifact를 기록
    - `frontdoor_probe` 추가
    - 최소 보존 필드:
      - `attempt_stage`
      - `attempt_index`
      - `request_method`
      - `request_path`
      - `request_body_shape`
      - `error_class`
      - `error_message`
      - `retry_count`
      - `retryable`
      - `backoff_total_sec`
      - `base_url`
      - `transport`
  - 실제 재실행 결과:
    - `verify/benchmarks/failure_20260307T135330Z.json`
    - `attempt_stage = frontdoor_probe`
    - `request_method = GET`
    - `request_path = /health`
    - `error_class = URLError`
- live validation run 완료
  - `verify/benchmarks/20260307T110330Z.json`
    - local stack(`http://127.0.0.1:8085`)에 대해 `DS-INJECT-C`, `limit-docs=2`, `consistency-samples=1`, `quick`, `dual`로 실제 bench 실행
    - `semantic.dataset_profile`에 아래가 실제 저장됨을 확인
      - `source_segmentation_mode_counts`
      - `source_boundary_pattern_counts`
      - `injected_kind_counts`
      - `inject_strategy_counts`
      - `generic_append_inject_present`
      - `growth_prefix_dataset`
  - `verify/benchmarks/20260307T113957Z.json`
    - `semantic.dataset_profile.dataset_manifest_entry`가 실제 저장됨을 확인
    - `dataset_generation_version = 20260307-r5`
    - `composite_source_policy = exclude_fallback_sources_unless_empty`
  - `verify/benchmarks/20260307T120903Z.json`
    - source-id 전환 이후 live throughput run으로 `dataset_manifest_entry.top_source_distribution[*].source_id` 저장 확인
  - `verify/benchmarks/20260307T133528Z.json`
    - source-id / registry / structured inject / frontdoor probe 반영 이후 live throughput run
    - `semantic.dataset_profile.dataset_manifest_entry.source_policy_registry_version = 20260307-r1`
    - `semantic.dataset_profile.dataset_manifest_entry.manual_review_source_count = 0`
    - top-level `frontdoor_probe` 저장 확인
  - `verify/benchmarks/20260307T135325Z.json`
    - `tools/bench/run_one_shot_validation.ps1` 기준 1회 실행용 스크립트로 생성한 live throughput artifact
    - `runs.throughput.semantic.dataset_profile.dataset_manifest_entry` 경로로 manifest provenance 저장 확인
- 회귀 검증 완료
  - `pytest -q tests/test_tools_quality_source_filename_governance.py tests/test_nf_shared_protocol.py tests/test_tools_bench_http_client.py tests/test_tools_bench_build_novel_dataset.py tests/test_tools_bench_run_pipeline_bench.py tests/test_tools_bench_run_one_shot_validation.py tests/test_tools_bench_judge_audit.py tests/test_tools_bench_shared_utils.py tests/test_nf_consistency_filters.py tests/test_tools_bench_metrics_summary.py tests/test_tools_bench_strict_gate.py tests/test_nf_consistency_engine.py tests/test_nf_consistency_slot_equivalence.py tests/consistency/test_engine_quality_core.py tests/consistency/test_engine_quality_graph.py tests/consistency/test_engine_quality_layer3.py`
  - 결과: `106 passed`
- `powershell -ExecutionPolicy Bypass -File tools/bench/run_one_shot_validation.ps1 -BaseUrl http://127.0.0.1:8085 -DatasetInputDir test_files -DatasetOutputDir verify/datasets -BenchOutputDir verify/benchmarks -DiversityProfile max`
  - 결과:
    - dataset rebuild / governance / regression / live bench / expected failure probe 통과
    - failure probe는 non-zero exit가 아니라 `failure_*.json` 생성과 telemetry 필드 검증으로 성공 판정
    - delegated long-run 명령을 PowerShell one-liner로 출력

## 0A) 2026-03-08 후속 구현 반영
- WS4 2차 규칙 조정 및 rerun 반영
  - `modules/nf_consistency/engine.py`
    - relation/job 계열 single-token head match에서 설명형 phrase를 자동 `OK`로 보지 않도록 head-token guard 추가
  - `modules/nf_schema/extraction.py`
    - 설명형 head phrase를 explicit schema fact로 승격하지 않도록 추출 단계 필터 추가
  - 검증:
    - `pytest -q tests/test_nf_schema_extraction.py tests/test_nf_consistency_slot_equivalence.py tests/consistency/test_engine_quality_core.py tests/test_nf_consistency_engine.py`
    - 통과
  - fresh isolated rerun:
    - `verify/benchmarks/20260308T040937Z.json`
    - `verify/benchmarks/20260308T041421Z.json`
    - `verify/benchmarks/20260308T074141Z.json`
    - `verify/benchmarks/20260308T074957Z.json`
  - 해석:
    - relation-style descriptive support suppression만으로는 quick unknown을 유의미하게 낮추지 못했다
    - 다음 WS4 실타깃은 broader claim coverage / schema fact quality 쪽이다
    - 추가 isolated rerun(`20260308T074141Z`, `20260308T074957Z`)에서는 quick `unknown_rate = 0.0`까지 내려갔지만, 둘 다 `claim_count_total = 0`이어서 extractor over-pruning 상태임이 확인됐다
    - 따라서 WS4는 close가 아니라 false-positive suppression과 coverage recovery를 분리한 phase split으로 다뤄야 한다
- WS4 3차 운영 rerun + unknown reason 재분류 반영
  - `modules/nf_consistency/engine.py`
    - linked fact가 전혀 없는 retrieval-hit fallback을 `CONFLICTING_EVIDENCE`가 아니라 `NO_EVIDENCE`로 분류하도록 조정
  - 검증:
    - `pytest -q tests/test_nf_consistency_engine.py -k "unlinked_retrieval_hits_as_no_evidence or excludes_same_doc_hits_for_explicit_profile_claims"`
    - `pytest -q tests/consistency/test_engine_quality_core.py tests/test_nf_consistency_engine.py`
    - 통과
  - fresh current-code rerun:
    - `verify/benchmarks/20260308T131114Z.json`
      - `operational-main:DS-400`
      - `dataset_generation_version = 20260308-r6`
      - `unknown_reason_counts = {NO_EVIDENCE: 2}`
    - `verify/benchmarks/20260308T132814Z.json`
      - `operational-main:DS-800`
      - `dataset_generation_version = 20260308-r6`
      - `unknown_reason_counts = {NO_EVIDENCE: 7}`
      - `violate_count_total = 1`
    - `verify/benchmarks/gate_report_20260308T132814Z_with_soak.md`
      - `goal_achieved = PASS`
  - 해석:
    - 기존 `8090/8092` long-lived stack artifact는 patch 이전 worker code를 반영하고 있었고, fresh stack rerun에서만 `CONFLICTING_EVIDENCE -> NO_EVIDENCE` shift가 재현됐다.
    - 따라서 현재 WS4의 남은 핵심은 “false conflict 제거”보다는 “still-no-evidence claim을 어떻게 actionable하게 줄일지” 쪽이다.
- WS7-J1 judge provenance hardening 반영
  - `tools/bench/judge_audit.py`
    - `judge_requested_backend`
    - `judge_effective_backend`
    - `judge_model_id`
    - `judge_prompt_version`
    - `judge_fallback_used`
    - `judge_input_hash`
  - `tools/bench/build_novel_dataset.py`
    - source policy stats / inject rows에 provenance 필드 연결
  - `tools/bench/run_pipeline_bench.py`
    - dataset profile에 `requested_backend_counts`, `effective_backend_counts`, `prompt_version_counts`, `fallback_used_count` 추가
  - 해석:
    - remote API requested path는 현재 `unsupported`로 명시된다
    - local NLI model absence 시 `local_nli_fallback` provenance가 남는다
  - 2026-03-08 후속 보강
    - `modules/nf_model_gateway/local/text_pair_classifier.py`
      - actual local judge path의 effective backend를 `heuristic`으로 명시
    - `tools/bench/judge_audit.py`
      - hypothesis별 backend provenance를 병합할 때 `heuristic` / `local_nli_fallback`를 우선 보존
    - 해석:
      - current local judge path는 real model inference가 아니라 heuristic overlap scorer이므로 `local_nli_model`보다 `heuristic` 표기가 더 정확하다
- WS7-J2 developer-only shadow pipeline 반영
  - 새 엔트리포인트:
    - `tools/bench/run_dev_judged_dataset_pipeline.py`
  - 새 보조 모듈:
    - `tools/bench/render_dev_judge_report.py`
  - 보호장치:
    - `--developer-mode` 없으면 실행 실패
    - `verify/datasets` overwrite 차단
  - 실제 run-scoped 산출물:
    - `verify/judge_runs/ws7j2-20260308T042500Z/`
    - `baseline_snapshot/`
    - `judge_run_manifest.json`
    - `source_policy_judgments.jsonl`
    - `inject_quality_judgments.jsonl`
    - `comparison/dataset_diff_summary.json`
    - `comparison/bench_candidate_summary.json`
    - `report.md`
  - 해석:
    - source policy judged rows는 현재 corpus 기준 `0`
    - inject audit은 `rows_total = 100`, `effective_backend_counts = {"local_nli_fallback": 100}`, `label_counts = {"contextless_append": 100}`
    - canonical deterministic path를 오염시키지 않는 shadow pipeline 골격은 확보됐다

## 1) 목적
- 이미 끝난 “원인 진단”과 “1회성 재실행 로그”를 계획 본문에서 제거하고, 실제로 남아 있는 로직 보완 작업만 추린다.
- 정합성 엔진의 운영 완성도와 developer-only judge 실험 경로를 다음 7개 축으로 닫는다.
  - 코드 정확성
  - one-shot / live bench 정상성 게이트
  - 운영 벤치 기준선 정렬
  - strict 의미 명확화
  - graph 실효성
  - unknown/actionability
  - soak/SQLite 안정성
  - dataset/judge provenance 및 developer-only 일반화
- `LLM as judge` 일반화는 운영 mainline에 통합하지 않고, deterministic primary path와 분리된 developer-only shadow pipeline으로만 다룬다.
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
- WS1 3차 조치 완료
  - `tools/bench/summarize_latest_metrics.py`가 `latest_successful_*`와 `latest_attempt_*`를 동시에 제공
  - canonical `verify/benchmarks/latest_metrics_summary.{json,md}` 재생성 완료
- WS2 1차 조치 완료
  - `tools/bench/check_consistency_strict_gate.py`가 `strict_core_gate` / `strict_layer3_gate`를 분리
  - `verify/benchmarks/consistency_strict_gate_20260307T103600Z_iter1.json` 재실행으로 새 schema 확인
- WS2 2차 운영 실증 완료
  - layer3-enabled isolated stack(`http://127.0.0.1:8091`) 기준 `operational-strict-main:DS-CONTROL-D` / `DS-INJECT-C` rerun 완료
  - `verify/benchmarks/consistency_strict_gate_20260309T081000Z_iter1.json`에서 `strict_core_gate = PASS`, `strict_layer3_gate = PASS`, `layer3_summary.mode = on`, `active_capability_source = local_nli` 확인
- WS7 1차 조치 완료
  - `tools/bench/build_novel_dataset.py`의 episode header 탐지 및 provenance/manifest 보강
  - `verify/datasets/dataset_manifest.json` 재생성 완료

위 항목은 재오픈 대상이 아니다. 이후 다시 다루는 경우는 회귀가 발견될 때만이다.

### 2.2 현재 남아 있는 핵심 결손
1. `run_local_stack.py`의 legacy default shared storage가 concurrent local stack 간 SQLite contention을 유발했을 가능성이 매우 높다. 새 구현은 port-scoped isolated storage를 기본으로 사용하지만, 기존 8080/8085 legacy stack을 재기동하지 않으면 같은 충돌이 반복될 수 있다.
2. isolated stack(`http://127.0.0.1:8086`) 기준 one-shot rerun(`verify/benchmarks/20260307T152444Z.json`)은 guard 4종이 모두 true로 통과했고, `operational-main:DS-800` rerun(`verify/benchmarks/20260307T154050Z.json`)도 복구됐다. 이어 isolated stack(`http://127.0.0.1:8087`) 기준 strict/control/inject rerun과 strict/final gate 재생성까지 완료됐다.
3. worker-owned `lease_owner` / `RUNNING` compare-and-set 경로는 구현됐고, isolated `0.5h soak`(`verify/benchmarks/soak_20260307T164722Z.json`)에서도 상태 역전이나 lock failure가 재현되지 않았다. 다만 overnight 급 장시간 soak 증거는 아직 없다.
4. 운영 summary는 이제 dataset별 `latest_successful_*`와 `latest_attempt_*`를 모두 보여주고, `failure_*.json`도 latest attempt로 반영한다. strict/final/runbook 판독 순서도 현재 artifact 기준으로 상당 부분 정렬됐지만, diversity `NO_BASELINE`과 DS-800 trend `WARN` 해석은 여전히 함께 봐야 한다.
5. strict gate 출력은 이제 `strict_core_gate` / `strict_layer3_gate`로 분리됐고, off-path artifact(`verify/benchmarks/consistency_strict_gate_20260307T160123Z_iter1.json`)에서는 `SKIPPED`, layer3-enabled artifact(`verify/benchmarks/consistency_strict_gate_20260309T081000Z_iter1.json`)에서는 `PASS`가 남는다. 즉 strict 의미 분리는 코드/문서뿐 아니라 운영 artifact에서도 실증됐다.
6. graph normal path는 살아났고, artifact에는 이제 `graph_runtime.applied_queries_sample`, `graph_runtime.skipped_queries_sample`, `graph_runtime.skipped_reason_counts`, `graph_runtime.seed_signal_type_counts`가 함께 남는다. fresh stack(`8088`) 기준 A/B rerun에서는 DS-200 graph-on `6 / 30`, DS-800 graph-on `15 / 30`까지 올라왔고, delegated operational verification run(`verify/benchmarks/20260309T084739Z.json` + `verify/benchmarks/graphrag_probe_20260309T084742Z.json`)에서도 `operational-graph-main:DS-200`와 `validation_mode = normal_path` probe가 실제로 남았다.
7. quick 계열 `unknown_rate`는 latest isolated rerun(`verify/benchmarks/20260308T074141Z.json`, `verify/benchmarks/20260308T074957Z.json`)에서 `0.0`까지 내려갔다. 다만 이는 `claim_count_total = 0` 결과와 같이 나온 값이라 actionability closeout이 아니라 coverage collapse 신호로 봐야 한다.
8. isolated short soak(`verify/benchmarks/soak_20260307T161437Z.json`)와 `0.5h soak`(`verify/benchmarks/soak_20260307T164722Z.json`)는 모두 `jobs_failed = 0`, `failure_breakdown = {}`, `failure_samples = []`로 clean pass했다. 현재까지는 tail lock이 재현되지 않았다.
9. dataset builder는 크게 개선됐고 fallback source는 1개만 남았다. 다만 `SRC-2e0ba0a8ee12`는 여전히 manual-review 대상이며, generic append inject 전체를 완전히 대체할 typed benchmark 전환과 `DS-GROWTH-*` semantics 변경에 따른 historical comparability 문제가 남아 있다.
10. test-only judge scaffold는 이제 provenance hardening과 developer-only shadow pipeline, typed inject variant(`WS7-J3`), source policy shadow apply(`WS7-J4`), strict/layer3 secondary audit 연결(`WS7-J5`)까지 실증됐다. latest judge run(`verify/judge_runs/codex-ws7j5-layer3-r1/`)에서는 source policy `judged_rows = 11`, typed inject `clear_conflict_rows = 8`, strict/layer3 audit `status = evaluated`, `strict_layer3_gate = PASS`가 남는다. 다만 source policy 실제 apply 사례는 아직 `0`건이고, inject quality baseline은 여전히 `contextless_append` 중심이다.

### 2.3 현 시점 판정
- 코드 구조/진단 가능성: `A-`
- one-shot / live bench 정상성: `B`
- 운영 게이트 일치성: `B+`
- strict completeness: `C+`
- graph 실효성: `B-`
- unknown/actionability: `C-`
- soak 장기 안정성: `A-`
- dataset/judge provenance 및 일반화 준비도: `B-`

### 2.4 2026-03-08 기준 구현 완성도(정성 추정)
- 운영 안정화 mainline: `약 80~85%`
  - `WS0/WS0A/WS1/WS2/WS3/WS5`는 사실상 닫혔고, 남은 핵심은 `WS4` unknown/actionability closeout이다.
- developer-only judge subtrack: `약 70% 내외`
  - `WS7-J1/J2`는 완료됐고, `WS7-J3/J4/J5`는 초안 구현 상태이며 남은 핵심은 real backend / real strict artifact 연결 검증이다.
- 전체 통합 계획: `약 70%대 초반`
  - 현재 전체 closeout을 가장 크게 막는 항목은 `WS4`와 `WS7-J3`의 label quality 검증, 그리고 `WS7-J5`의 real artifact 적용 검증이다.

### 2.5 다음 구현 우선순위
1. 운영 mainline:
   - `WS4`
   - false-positive suppression은 일단 확보됐으므로, 이제 schema-backed explicit coverage recovery로 `claim_count_total`을 다시 올리면서 quick actionability를 회복한다.
2. developer-only judge subtrack:
   - `WS7-J3/J5`
   - typed inject variant의 label quality와 strict/layer3 secondary audit를 실제 judge backend + strict artifact 기준으로 재확인한다.
3. developer-only judge subtrack:
   - `WS7-J4`
   - low-confidence source가 생기면 source policy shadow apply 산출물을 실제 corpus에 적용해 본다.
4. 운영 해석 고정:
   - `WS2`
   - layer3를 계속 off로 둘지, 실제 capability source를 열지 정책을 확정한다.
5. 운영 검증 closeout:
   - `WS3`
   - delegated operational graph verification artifact 체인을 실제로 1회 닫는다.

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
- `verify/benchmarks/20260307T145704Z.json`
  - shared-storage stack(`8085`) 기준 latest `validation:one-shot` rerun artifact
  - `frontdoor_probe`는 존재하지만:
    - `index_vec = FAILED`
    - `ingest_failures = 1`
    - `consistency_failures = 1`
    - `retrieve_vec_failures = 1`
    - `guards.index_jobs_succeeded = false`
    - `guards.ingest_failures_zero = false`
    - `guards.consistency_failures_zero = false`
    - `guards.retrieve_vec_failures_zero = false`
- `verify/benchmarks/failure_20260307T151153Z.json`
  - shared-storage stack(`8085`) 기준 latest `operational-main:DS-800` rerun failure artifact
  - `attempt_stage = index_vec`
  - `request_method = POST`
  - `request_path = /jobs`
  - `error_class = RemoteDisconnected`
- `verify/benchmarks/20260307T152444Z.json`
  - isolated stack(`8086`) 기준 one-shot rerun artifact
  - `guards.index_jobs_succeeded = true`
  - `guards.ingest_failures_zero = true`
  - `guards.consistency_failures_zero = true`
  - `guards.retrieve_vec_failures_zero = true`
- `verify/benchmarks/20260307T154050Z.json`
  - isolated stack(`8086`) 기준 `operational-main:DS-800` rerun artifact
  - `index_fts = SUCCEEDED`
  - `index_vec = SUCCEEDED`
  - `ingest_failures = 0`
  - `consistency_failures = 0`
  - `retrieve_vec_failures = 0`
- `verify/benchmarks/20260307T155428Z.json`
  - isolated stack(`8087`) 기준 `operational-main:DS-200` rerun artifact
- `verify/benchmarks/20260307T155722Z.json`
  - isolated stack(`8087`) 기준 `operational-strict-main:DS-CONTROL-D` rerun artifact
- `verify/benchmarks/20260307T160110Z.json`
  - isolated stack(`8087`) 기준 `operational-strict-main:DS-INJECT-C` rerun artifact
  - `status.* = SUCCEEDED`
- `verify/benchmarks/consistency_strict_gate_20260307T160123Z_iter1.json`
  - isolated operational strict gate artifact
  - `strict_core_gate.passed = true`
  - `strict_layer3_gate.status = SKIPPED`
- `verify/benchmarks/soak_20260307T161437Z.json`
  - isolated short soak artifact
  - `jobs_failed = 0`
  - `failure_breakdown = {}`
  - `failure_samples = []`
- `verify/benchmarks/soak_20260307T164722Z.json`
  - isolated `0.5h soak` artifact
  - `jobs_failed = 0 / 6448`
  - `failure_breakdown = {}`
  - `failure_samples = []`
- `verify/benchmarks/20260308T040937Z.json`
  - fresh isolated stack(`8090`) 기준 `ws4-quick-ab:DS-200-baseline-r4`
  - `unknown_rate = 0.6875`
  - relation-style descriptive support suppression 후에도 quick unknown이 여전히 높음을 확인
- `verify/benchmarks/20260308T041421Z.json`
  - fresh isolated stack(`8090`) 기준 `ws4-quick-ab:DS-400-baseline-r4`
  - `unknown_rate = 0.6833`
  - `r3 -> r4`에서 의미 있는 개선이 없음을 확인
- `verify/benchmarks/20260308T074141Z.json`
  - fresh isolated stack(`8092`) 기준 `ws4-quick-ab:DS-200-baseline-r8`
  - `unknown_rate = 0.0`, `claim_count_total = 0`
  - false positive suppression은 성공했지만 quick coverage가 0으로 수축했음을 확인
- `verify/benchmarks/20260308T074957Z.json`
  - fresh isolated stack(`8092`) 기준 `ws4-quick-ab:DS-400-baseline-r9`
  - `unknown_rate = 0.0`, `claim_count_total = 0`
  - DS-400 full run에서도 동일하게 over-pruning 패턴이 재현됨을 확인
- `verify/benchmarks/gate_report_20260307T164722Z_with_soak.md`
  - isolated final gate artifact
  - `execution_complete = PASS`
  - `goal_achieved = FAIL`
  - failing check:
    - `retrieval_fts_p95_regression_le_10pct`
- `verify/datasets/dataset_manifest.json`
  - `dataset_generation_version = 20260307-r5`
  - `source_policy_registry_version = 20260307-r1`
  - `manual_review_source_count = 1`
  - `judge_audit_policy_count = 0`
- `verify/datasets/DS-INJECT-C.jsonl`
  - `inject_quality_label = contextless_append` 200 / 200
  - `inject_judge_backend = local_nli` 200 / 200
- `verify/datasets/DS-DIVERSE-INJECT-C.jsonl`
  - `inject_quality_label = contextless_append` 200 / 200
- `verify/datasets/DS-INJECT-C-STRUCTURED.jsonl`
  - `inject_quality_label = contextless_append` 49 / 49
  - structured subset은 deterministic filter이지 judge-derived subset은 아니다
- `verify/judge_runs/ws7j2-20260308T042500Z/report.md`
  - developer-only judged pipeline 첫 run-scoped report
  - `canonical_outputs_modified = False`
  - inject audit `effective_backend_counts = {"local_nli_fallback": 100}`
- `verify/judge_runs/ws7j2-20260308T042500Z/comparison/bench_candidate_summary.json`
  - source policy audit `judged_rows = 0`
  - inject audit `label_counts = {"contextless_append": 100}`
- 운영 라벨 재계산 기준:
  - `python tools/bench/summarize_latest_metrics.py --bench-dir verify/benchmarks --datasets "DS-200,DS-400,DS-800,DS-DIVERSE-200,DS-DIVERSE-400,DS-DIVERSE-800" --label-mode operational`
  - 이 관점에서는 DS-200/400은 운영 기준 PASS로 복구됐고, DS-800은 `latest_successful_file = 20260307T154050Z.json`, `latest_attempt_file = 20260307T154050Z.json`, `latest_attempt_status = SUCCEEDED`로 갱신됐다.

### 3.2 현재 운영 해석
- isolated operational baseline 기준 final/strict/summary/soak의 판독 순서는 이제 거의 정렬됐다.
- current one-shot은 이제 failure semantics와 success semantics를 모두 포함한 runtime gate로 동작한다.
- shared-storage stack에서는 one-shot/DS-800 failure가 재현됐고, isolated stack에서는 동일 시나리오가 통과했다.
- strict gate는 현재 `verification loop + triage + conservative unknown` 검증에 가깝고, `strict_core_gate = PASS`, `strict_layer3_gate = SKIPPED`로 읽어야 한다.
- final gate의 현재 residual fail은 transport/front-door가 아니라 DS-800 `retrieval_fts_p95_regression_le_10pct` 한 항목이다.
- 운영 summary는 latest successful과 latest failed attempt를 함께 보여주고, 현재 `overall_status = WARN`, `absolute_goal_status = FAIL`은 각각 DS-800 trend warning과 diversity `NO_BASELINE`을 반영한다.
- job 상태 일관성은 heartbeat에 더해 worker-owned terminal transition CAS까지 들어갔고, isolated `0.5h soak`에서도 상태 역전/lock failure 없이 유지됐다.
- graph는 “경로 존재”까지는 확인됐지만 “운영적으로 의미 있는 적용률”은 미달이다.
- WS4 최신 rerun 기준 unknown 문제는 relation-style false support 억제만으로 닫히지 않았고, broader claim coverage / schema fact quality 보정이 남아 있다.
- current `LLM as judge`는 이제 run-scoped shadow pipeline까지는 확보됐지만, source segmentation / inject quality를 canonical dataset generation의 primary path로 승격할 근거는 아직 부족하다.

## 4) 활성 작업 원칙
- 이미 구현된 계측을 또 늘리기보다, 남은 공백을 닫는 방향으로만 작업한다.
- ad hoc 재실행 결과는 보조 증거로 쓰되, 운영 완료 판정은 반드시 운영 라벨 artifact에서 닫는다.
- `validation:one-shot`은 `frontdoor_probe` 존재만으로 성공 처리하지 않고, live bench `guards` 성공까지 통과해야 성공으로 본다.
- strict는 더 이상 하나의 의미로 쓰지 않는다. core와 layer3를 분리해 다룬다.
- 성능 개선은 “문턱 상향”과 “실제 병목 제거”를 분리해 기록한다.
- `LLM as judge` 실험은 developer-only shadow pipeline에서만 수행하고, canonical `verify/datasets` / `verify/benchmarks`를 직접 오염시키지 않는다.
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

### WS0A. one-shot live bench 정상성 게이트화
목적:
- `validation:one-shot`을 provenance/schema smoke와 runtime success smoke로 분리하고, delegated long-run 위임 전 선행 게이트로 고정한다.

상태:
- `완료 (2026-03-07, 운영 rerun failure semantics 확인)`

현재 근거:
- `tools/bench/run_one_shot_validation.ps1`
  - Step 4가 이제 `frontdoor_probe` / `dataset_manifest_entry`뿐 아니라 runtime guard 4종까지 확인한다.
  - guard false 시 `live bench runtime smoke failed (stack reachable but bench failed)`로 즉시 실패한다.
  - delegated readiness가 없으면 non-zero exit로 종료한다.
- `tools/bench/run_pipeline_bench.py`
  - future artifact에 top-level `semantic` / `guards`를 함께 기록해 판독 경로를 단순화한다.
- `index_jobs_succeeded`
- `ingest_failures_zero`
- `consistency_failures_zero`
- `retrieve_vec_failures_zero`
- `tests/test_tools_bench_run_pipeline_bench.py`
  - top-level `semantic` / `guards` / `frontdoor_probe` exposure helper를 unit test로 고정했다.
- `tests/test_tools_bench_run_one_shot_validation.py`
  - runtime guard 강제, blocked delegated 단계, failure 메시지 분리를 문자열 기반 unit test로 고정했다.
- `verify/benchmarks/20260307T145704Z.json`
  - `frontdoor_probe`는 존재하지만 `guards.* = false`
  - 스크립트가 실제로 non-zero exit로 차단됨을 확인했다.
- `tools/bench/run_user_delegated.ps1`
  - operational verification phase 앞에서 `One-shot validation runtime gate`를 선행 실행하도록 정렬했다.

작업:
1. `tools/bench/run_one_shot_validation.ps1`
   - Step 4에서 `frontdoor_probe`와 `dataset_manifest_entry`뿐 아니라 runtime guard 4종도 필수 검증한다.
   - top-level `semantic.dataset_profile.*`와 `runs.throughput.semantic.dataset_profile.*`처럼 기존 호환 경로를 유지하되, `guards`도 동일하게 fallback path를 허용한다.
2. one-shot 판정 메시지 분리
   - `live bench schema/provenance smoke passed`
   - `live bench runtime smoke passed`
   - 둘 중 하나라도 실패하면 delegated long-run 단계로 넘어가지 않도록 exit semantics를 고정한다.
3. 실패 artifact 판독 규칙 고정
   - `frontdoor_probe`만 있고 `guards.* = false`면 “stack reachable but bench failed”
   - `frontdoor_probe` 자체가 없거나 실패면 “front-door unreachable”
   - 문서와 테스트에서 이 두 경우를 구분해 고정한다.
4. 테스트 보강
   - `tests/test_tools_bench_run_one_shot_validation.py`
   - frontdoor/provenance만 맞고 runtime guard가 false인 artifact를 실패로 판정하는 케이스를 추가한다.
   - runtime guard 4종이 true일 때만 성공하는 양수 케이스를 추가한다.
5. delegated command 출력 조건 정리
   - runtime smoke 실패 시 delegated long-run 명령은 “참고용 출력”이 아니라 “보류된 다음 단계”로 표기한다.
   - runbook과 본 계획 문서에서 long-run 실행 선행조건을 `validation:one-shot guard pass`로 고정한다.

실행 메모:
- 구현:
  - `tools/bench/run_one_shot_validation.ps1`
    - `Resolve-LiveBenchGuardState` 추가
    - `live bench schema/provenance smoke passed`
    - `live bench runtime smoke passed`
    - `Step 6/6 - delegated long runs blocked|ready`
    - delegated readiness 부재 시 non-zero exit
  - `tools/bench/run_pipeline_bench.py`
    - top-level `semantic`
    - top-level `guards`
    - top-level 판독용 helper `_top_level_output_fields`
  - `tools/bench/run_user_delegated.ps1`
    - `One-shot validation runtime gate` 선행 호출
- 테스트:
  - `pytest -q tests/test_tools_bench_run_pipeline_bench.py tests/test_tools_bench_run_one_shot_validation.py tests/test_tools_bench_run_user_delegated.py`
  - 결과: `14 passed`
  - `powershell -NoProfile -ExecutionPolicy Bypass -Command "[scriptblock]::Create((Get-Content -Raw 'tools/bench/run_one_shot_validation.ps1')) | Out-Null"`
  - `powershell -NoProfile -ExecutionPolicy Bypass -Command "[scriptblock]::Create((Get-Content -Raw 'tools/bench/run_user_delegated.ps1')) | Out-Null"`
  - 결과: PowerShell parse 통과
- 운영 산출물:
  - `powershell -NoProfile -ExecutionPolicy Bypass -File tools/bench/run_one_shot_validation.ps1 -BaseUrl http://127.0.0.1:8085 -DatasetInputDir test_files -DatasetOutputDir verify/datasets -BenchOutputDir verify/benchmarks -DiversityProfile max -SkipFailureProbe`
  - 결과:
    - `verify/benchmarks/20260307T145704Z.json`
    - `frontdoor_probe`는 존재하나 `guards.* = false`
    - script exit = non-zero
  - `powershell -NoProfile -ExecutionPolicy Bypass -File tools/bench/run_one_shot_validation.ps1 -BaseUrl http://127.0.0.1:8086 -DatasetInputDir test_files -DatasetOutputDir verify/datasets -BenchOutputDir verify/benchmarks -DiversityProfile max -SkipFailureProbe`
  - 결과:
    - `verify/benchmarks/20260307T152444Z.json`
    - `guards.* = true`
    - script exit = zero

검증:
1. synthetic / fixture 기반 one-shot 테스트에서 guard false path가 비정상 종료되는지 확인
2. local stack이 살아 있는 환경에서 재실행 시 최신 `validation:one-shot` artifact의 4개 guard가 모두 true인지 확인
3. failure probe path와 live bench runtime failure path가 서로 다른 단계/메시지로 분리되는지 확인

완료 기준:
- `validation:one-shot` 성공은 `frontdoor_probe` 존재가 아니라 guard 4종 true까지 포함한 의미로 재정의된다.
- latest one-shot artifact만 읽어도 “stack은 떴지만 bench는 실패”인지, “stack 자체가 안 떴는지”를 구분할 수 있다.
- delegated long-run 실행은 one-shot runtime smoke 통과 뒤에만 수행된다.

우선순위:
- `P0`

### WS1. 운영 기준선 복구 및 front-door/heavy-job 정상화 — operational gate 복원
목적:
- DS-800과 one-shot live bench를 함께 막고 있는 runtime/front-door failure family를 정리하고, operational summary/gate를 실제 성공 artifact 기준으로 복구한다.

상태:
- `완료 (2026-03-07, default isolated operational baseline 기준)`

현재 근거:
- shared-storage stack(`8085`)에서는 latest `validation:one-shot` rerun(`verify/benchmarks/20260307T145704Z.json`)이 `index_vec = FAILED`, `guards.* = false`로 실패했다.
- shared-storage stack(`8085`)에서는 latest `operational-main:DS-800` rerun이 `verify/benchmarks/failure_20260307T151153Z.json`에 `attempt_stage = index_vec`, `request_path = /jobs`, `error_class = RemoteDisconnected`로 기록됐다.
- isolated stack(`8086`)에서는 latest `validation:one-shot` rerun(`verify/benchmarks/20260307T152444Z.json`)이 `guards.* = true`로 통과했다.
- isolated stack(`8086`)에서는 `operational-main:DS-800` rerun(`verify/benchmarks/20260307T154050Z.json`)이 `index_fts = SUCCEEDED`, `index_vec = SUCCEEDED`, failure counts 0으로 복구됐다.
- isolated stack(`8087`)에서는 strict control/inject rerun(`verify/benchmarks/20260307T155722Z.json`, `verify/benchmarks/20260307T160110Z.json`)과 strict gate(`verify/benchmarks/consistency_strict_gate_20260307T160123Z_iter1.json`) 재생성이 완료됐다.
- isolated final gate(`verify/benchmarks/gate_report_20260307T164722Z_with_soak.md`)는 `execution_complete = PASS`, `goal_achieved = FAIL`이며 남은 fail은 `retrieval_fts_p95_regression_le_10pct` 하나다.
- 따라서 runtime/front-door recovery 자체는 default isolated stack 기준으로 닫혔고, 현재 남은 과제는 WS1 transport 복구가 아니라 DS-800 trend regression, diversity baseline, graph/unknown 후속이다.

작업:
1. `WS0A` 통과를 long-run 선행조건으로 고정
   - one-shot runtime smoke가 통과하기 전에는 DS-800 / strict delegated long-run을 완료 판정 근거로 쓰지 않는다.
2. 운영 벤치 재실행 규격 고정
   - DS-200: `operational-main:DS-200`
   - DS-400: `operational-main:DS-400`
   - DS-800: `operational-main:DS-800`
   - strict control/inject도 운영 라벨 체계로 재실행
3. `tools/bench/run_user_delegated.ps1`
   - 운영 summary 생성 시 사용하는 라벨 필터 규격을 문서에 고정한다.
   - `operational-main:` / `operational-diversity-main:` 외 라벨은 summary gate 기준선으로 사용하지 않음을 명시한다.
4. summary/gate 재생성
   - `latest_metrics_summary.json`
   - `latest_metrics_summary.md`
   - strict gate artifact
   - final gate artifact
5. 기준선 승격 규칙 명문화
   - ad hoc 검증 artifact는 “보조 증거”
   - 운영 완료 판정은 운영 라벨 artifact 재생성 후에만 허용
6. summary 의미 보강
   - dataset별 `latest_successful_run`과 `latest_attempt_run`을 분리해 보이거나 동등한 정보를 제공한다.
   - 실패 artifact를 baseline에서 제외하더라도, 마지막 시도 실패 자체는 숨기지 않는다.
7. job 상태 불변성 보강
   - success/failure/cancel 전환 시 `lease_owner` 또는 현재 상태를 함께 검증하는 compare-and-set 경로를 검토한다.
   - terminal 상태 이후 역전이 가능한지 테스트로 고정한다.
8. bench transport/front-door 안정화
   - `RemoteDisconnected`를 재시도/관찰 가능한 오류 유형으로 분리한다.
   - 최소한 실패 시 `attempt_stage`, `request_path`, `error_class`, `base_url`을 남기는 structured failure artifact를 추가한다.
   - small one-shot 실패와 DS-800 실패가 같은 stage / method / path family인지 묶어서 판독한다.

검증:
1. `WS0A` 반영 후 latest `validation:one-shot` artifact의 guard 4종이 true인지 확인
2. 운영 라벨 summary에서 DS-400 `absolute_status` 재확인
3. 운영 라벨 summary에서 `status_semantics`와 `absolute_goal_status`가 모두 존재하는지 확인
4. strict/final gate 판독 순서와 해석이 문서와 일치하는지 확인
5. 실패한 operational rerun이 summary에서 baseline 후보로 배제되면서도, “latest attempt failed” 사실은 별도 필드/문서에서 확인 가능한지 검증
6. 장시간 job에서 lease 만료 후 상태 역전이 재발하지 않는지 검증
7. `RemoteDisconnected` 재현 시 bench 쪽에 구조화된 실패 근거가 남는지, small one-shot과 DS-800에서 같은 failure family로 묶이는지 검증

완료 기준:
- 운영 라벨 기준 `latest_metrics_summary.json`이 stale artifact 없이 재생성된다.
- latest `validation:one-shot` live bench artifact가 runtime guard 4종을 모두 통과한다.
- DS-800 운영 artifact가 복구되면 `absolute_goal_status`가 그에 맞게 갱신된다.
- DS-800이 여전히 실패면, 실패 상태가 운영 산출물에 그대로 반영되고 계획 문서도 그 상태를 유지한다.
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
    - operational phase 앞에서 one-shot runtime gate를 선행 실행하도록 정렬
  - `run_local_stack.py`
    - port-scoped default storage(`verify/local_stack/<host>_<port>/...`)로 전환
  - `modules/nf_orchestrator/storage/db.py`
    - transient SQLite lock retry helper 추가
  - `modules/nf_orchestrator/storage/repos/job_repo.py`
    - `update_job_status_if_matches`
    - `set_job_result_if_matches`
    - `set_job_error_if_matches`
    - `extend_lease_if_matches`
  - `modules/nf_orchestrator/services/project_service.py`
    - project CRUD path에 transient SQLite retry 적용
  - `modules/nf_orchestrator/services/job_service.py`
    - job submit/cancel/get/list path에 transient SQLite retry 적용
  - `modules/nf_orchestrator/main.py`
    - uncaught `sqlite3.OperationalError`를 `503/500 JSON` error로 변환
    - `modules/nf_workers/runner.py`
      - worker-owned terminal transition compare-and-set 적용
      - lease loss 시 stale worker가 terminal state를 덮어쓰지 않도록 차단
- 테스트:
  - `tests/test_tools_bench_metrics_summary.py`
    - operational label mode preset 동작 고정
    - failure artifact를 latest attempt로 반영하는 동작 추가 고정
  - `tests/test_nf_orchestrator_storage.py`
    - owner/state mismatch 시 terminal transition 차단 고정
  - `tests/test_nf_workers_runner_memory_pressure_events.py`
    - wrong owner lease extension 차단 고정
  - `tests/test_tools_bench_run_user_delegated.py`
    - delegated script가 one-shot gate를 선행 호출하는지 고정
  - `tests/test_run_local_stack.py`
    - port-scoped default storage 경로 규칙 고정
  - `tests/test_nf_orchestrator_storage.py`
    - project/job service transient SQLite retry 동작 고정
  - 결과:
    - `pytest -q tests/test_nf_orchestrator_storage.py tests/test_nf_workers_runner_memory_pressure_events.py tests/test_tools_bench_metrics_summary.py tests/test_tools_bench_run_one_shot_validation.py tests/test_tools_bench_run_user_delegated.py tests/test_run_local_stack.py`
    - `32 passed`
- 산출물 갱신:
  - `verify/benchmarks/latest_metrics_summary.json`
  - `verify/benchmarks/latest_metrics_summary.md`
  - 현재 결과:
    - `label_filter.mode = operational`
    - DS-800 `latest_successful_file = 20260307T154050Z.json`
    - DS-800 `latest_attempt_file = 20260307T154050Z.json`
    - DS-800 `latest_attempt_status = SUCCEEDED`
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
  - `verify/benchmarks/20260307T145704Z.json`
  - one-shot rerun:
    - `frontdoor_probe`는 성공
    - `index_vec = FAILED`
    - `ingest_failures = 1`
    - `consistency_failures = 1`
    - `retrieve_vec_failures = 1`
    - `guards.* = false`
  - `verify/benchmarks/failure_20260307T151153Z.json`
  - DS-800 rerun:
    - `attempt_stage = index_vec`
    - `request_method = POST`
    - `request_path = /jobs`
    - `error_class = RemoteDisconnected`
  - `verify/benchmarks/20260307T152444Z.json`
  - isolated one-shot rerun:
    - `guards.index_jobs_succeeded = true`
    - `guards.ingest_failures_zero = true`
    - `guards.consistency_failures_zero = true`
    - `guards.retrieve_vec_failures_zero = true`
  - `verify/benchmarks/20260307T154050Z.json`
  - isolated DS-800 rerun:
    - `index_fts = SUCCEEDED`
    - `index_vec = SUCCEEDED`
    - `ingest_failures = 0`
    - `consistency_failures = 0`
    - `retrieve_vec_failures = 0`
- DS-800 원인 분해:
  - 환경 관찰:
    - `run_local_stack.py` 인스턴스가 `8080`, `8085`, `8095` 등 여러 포트에서 동시에 떠 있었고, 모두 explicit `--db-path` 없이 실행되고 있었다.
    - 기존 default path는 shared `nf_orchestrator.sqlite3` / `data/*` 계열이므로, concurrent local stack 간 state collision 가능성이 높았다.
  - root DB 관찰:
    - 실패 job의 최종 DB 상태는 `SUCCEEDED`인데 stale `error_code = INTERNAL_ERROR`, `error_message = database is locked`가 남아 있었음
    - 동일 job에서 `failed` 뒤에 `fts indexed` / `done` 이벤트가 관찰되어 lease expiry 기반 중복 처리 가능성이 확인됨
  - 대응 구현:
    - `modules/nf_workers/runner.py`
      - `WorkerContext.heartbeat()` 추가
      - `INDEX_FTS` / `INDEX_VEC` long-running loop에서 lease 연장
    - `modules/nf_orchestrator/storage/repos/job_repo.py`
      - `SUCCEEDED`/`CANCELED` 전환 시 stale error 필드 제거
      - worker-owned terminal transition compare-and-set 추가
    - `run_local_stack.py`
      - default storage를 port-scoped isolated state로 전환
    - `modules/nf_orchestrator/services/{project,job}_service.py`
      - transient SQLite lock retry 추가
    - `modules/nf_orchestrator/main.py`
      - uncaught DB error를 structured JSON error로 변환
    - `tools/bench/summarize_latest_metrics.py`
      - failure artifact를 latest attempt에 반영
  - 회귀 검증:
    - `pytest -q tests/test_nf_orchestrator_storage.py tests/test_nf_workers_runner_memory_pressure_events.py tests/test_tools_bench_metrics_summary.py tests/test_tools_bench_run_one_shot_validation.py tests/test_tools_bench_run_user_delegated.py`
    - 결과: `27 passed`
- post-fix rerun:
  - `8085` stack:
    - one-shot live bench는 front-door는 통과하지만 runtime guard 4종이 모두 false
    - DS-800은 `INDEX_VEC` 제출 시 `RemoteDisconnected`
  - `8086` isolated stack:
    - one-shot live bench는 runtime guard 4종을 모두 통과
    - DS-800 operational rerun도 성공
  - `8087` isolated stack:
    - DS-200 / strict control / strict inject rerun 성공
    - strict gate는 `strict_core_gate = PASS`, `strict_layer3_gate = SKIPPED`
    - final gate는 `execution_complete = PASS`, `goal_achieved = FAIL`
  - 해석:
    - lease expiry/stale error/terminal reversal 경로는 보강됐고, shared default storage collision이 `RemoteDisconnected`의 주원인일 가능성이 높다.
- rerun 후 canonical summary:
  - `overall_status = WARN`
  - `absolute_goal_status = FAIL`
  - `label_filter.mode = operational`
  - `label_filter.excluded_unsuccessful_status = 2`
  - DS-200/400는 baseline 비교 가능 상태로 복구
  - DS-800은 `latest_successful = 20260307T154050Z.json`, `latest_attempt = SUCCEEDED`, trend status = `WARN`
  - diversity 계열은 여전히 `NO_BASELINE`
- 남은 작업:
  - `WS2`
    - layer3 off 상태를 운영 정책으로 계속 둘지, 실제 capability source를 열지 결정
  - `WS3`
    - DS-200/DS-800 graph off/on A/B와 applied sample 계측 보강
  - `WS4`
    - quick 계열 unknown reduction과 actionability 보강
  - diversity 운영 baseline
    - 복구 여부 결정 및 rerun

우선순위:
- `P0`

### WS2. strict 의미 분리 — strict_core_gate / strict_layer3_gate
목적:
- strict PASS의 의미를 명확히 하고, layer3 비활성 상태를 “완료”로 오인하지 않게 만든다.

상태:
- `완료 (layer3 off/on artifact 양쪽 실증 + strict gate 재생성 완료)`

현재 근거:
- `verify/benchmarks/consistency_strict_gate_20260307T160123Z_iter1.json`
  - `strict_core_gate = PASS`
  - `strict_layer3_gate = SKIPPED`
  - `layer3_summary.mode = off`
- `verify/benchmarks/20260309T080639Z.json`
  - `operational-strict-main:DS-CONTROL-D`
  - `layer3_model_enabled_jobs = 40`
  - `layer3_local_nli_enabled_jobs = 40`
  - `layer3_effective_capable_jobs = 40`
  - `layer3_model_fallback_count = 1`
- `verify/benchmarks/20260309T080952Z.json`
  - `operational-strict-main:DS-INJECT-C`
  - `layer3_model_enabled_jobs = 40`
  - `layer3_local_nli_enabled_jobs = 40`
  - `layer3_effective_capable_jobs = 40`
  - `layer3_model_fallback_count = 44`
- `verify/benchmarks/consistency_strict_gate_20260309T081000Z_iter1.json`
  - `strict_core_gate = PASS`
  - `strict_layer3_gate = PASS`
  - `layer3_summary.mode = on`
  - `active_capability_source = local_nli`
  - 단, fallback count가 남아 있으므로 “source on + fallback-aware strict path 실증”으로 읽어야 한다

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
5. 테스트용 데이터 한정 `LLM as judge` 평가축 검토
   - 현재 repo는 layer3 NLI / remote API 경로를 보유하지만 기본 설정은 off
   - test-only audit로 사용할 경우:
     - primary hard gate가 아니라 secondary evaluation artifact로만 사용
     - deterministic prompt/output schema 고정
     - control/inject dataset 기준 false positive drift를 별도 기록
   - 단, dataset judge provenance hardening(`WS7-J1`)이 끝나기 전에는 layer3 audit에 바로 재사용하지 않는다

검증:
1. layer3 off 경로
   - strict_core는 정상 PASS
   - strict_layer3는 `SKIPPED` 또는 `N/A`
2. layer3 on 경로를 선택할 경우
   - 최소 1회 control/inject rerun
   - `layer3_*` 카운트가 실제로 0이 아닌지 확인
3. `LLM as judge`를 붙일 경우
   - local NLI 또는 remote API enable 후 control/inject rerun
   - `strict_layer3_gate` 외 별도 judge artifact 또는 judge field로만 기록
   - primary judge와 disagreement case를 별도 샘플링

완료 기준:
- strict 결과물에서 core와 layer3 의미가 분리되어 보인다.
- 운영 문서/게이트/summary 어디에도 “strict PASS = layer3 PASS”로 읽힐 여지가 없다.
- 선택된 운영 방향(on/off)에 맞게 artifact와 gate가 일관된다.

우선순위:
- `P1`

### WS3. graph 실효성 확대 — path existence에서 applied rate 관리로 전환
목적:
- graph normal path가 살아 있는 수준을 넘어, 운영적으로 의미 있는 적용률과 재현성을 확보한다.

상태:
- `완료 (운영 A/B + delegated operational graph benchmark/probe 실증 완료)`

현재 근거:
- `verify/benchmarks/20260307T035012Z.json`
  - `graph_runtime.applied_count = 3 / 30`
- `graph_index_runtime`는 정상 생성되지만 query selection/seed 품질은 아직 최소 기능 수준이다.
- 이전 평가 문서의 “grouping 운영 E2E 커버리지 부족” 문제도 완전히 닫히지 않았다.
- `tools/bench/run_pipeline_bench.py`
  - retrieval query selection이 time anchor 외에도 `entity_alias`, `timeline_signal` heuristic을 함께 분류한다.
  - artifact `graph_runtime`에 아래 필드가 추가됐다.
    - `applied_queries_sample`
    - `skipped_queries_sample`
    - `skipped_reason_counts`
    - `seed_signal_type_counts`
- `tests/test_tools_bench_run_pipeline_bench.py`
  - graph signal type 분류 / graph runtime sample 집계 / top-level output 노출 회귀 테스트 추가
  - 결과:
    - `pytest -q tests/test_tools_bench_run_pipeline_bench.py`
    - `13 passed`
- `verify/benchmarks/20260308T021123Z.json`
  - fresh stack(`8088`) 기준 `ws3-graph-ab:DS-200-off`
  - `graph_runtime.applied_count = 0 / 30`
  - `graph_runtime.skipped_reason_counts = {"disabled": 30}`
- `verify/benchmarks/20260308T021429Z.json`
  - 첫 `DS-200 on` rerun
  - `graph_runtime.applied_count = 0 / 30`
  - `graph_runtime.skipped_reason_counts = {"no_seeds": 29, "unknown": 1}`
- `verify/benchmarks/20260308T023711Z.json`
  - selection fix 이후 `ws3-graph-ab:DS-200-on-r2`
  - `graph_runtime.applied_count = 6 / 30`
  - `graph_runtime.seed_signal_type_counts = {"entity_alias": 15, "time_anchor": 7, "timeline_signal": 4}`
  - `graph_runtime.skipped_reason_counts = {"no_seeds": 23, "unknown": 1}`
- `verify/benchmarks/20260308T022346Z.json`
  - fresh stack(`8088`) 기준 `ws3-graph-ab:DS-800-off`
  - `graph_runtime.applied_count = 0 / 30`
  - `graph_runtime.skipped_reason_counts = {"disabled": 30}`
- `verify/benchmarks/20260308T023257Z.json`
  - 첫 `DS-800 on` rerun
  - `graph_runtime.applied_count = 1 / 30`
- `verify/benchmarks/20260308T024635Z.json`
  - selection fix 이후 `ws3-graph-ab:DS-800-on-r2`
  - `graph_runtime.applied_count = 15 / 30`
  - `graph_runtime.seed_signal_type_counts = {"time_anchor": 28, "timeline_signal": 3, "entity_alias": 11}`
  - `graph_runtime.skipped_reason_counts = {"no_seeds": 14, "unknown": 1}`
- `tools/bench/run_user_delegated.ps1`
  - operational verification phase에 `operational-graph-main:DS-200` graph-on benchmark와 `check_graphrag_applied.py` probe가 명시적으로 편입됐다.
  - 따라서 기본 delegated command flow에서 grouping 검증 step이 matrix phase 여부와 별개로 최소 1회 실행된다.
- `tests/test_tools_bench_run_user_delegated.py`
  - operational graph verification benchmark / grouping probe step 존재를 고정
  - 결과:
    - `pytest -q tests/test_tools_bench_run_user_delegated.py tests/test_tools_bench_run_one_shot_validation.py`
    - `5 passed`
- `verify/benchmarks/20260309T084739Z.json`
  - delegated operational verification phase 기준 `operational-graph-main:DS-200`
  - `graph_runtime.applied_count = 6 / 30`
  - `graph_runtime.skipped_reason_counts = {"no_seeds": 24}`
  - `graph_runtime.seed_signal_type_counts = {"entity_alias": 14, "timeline_signal": 6, "time_anchor": 7}`
- `verify/benchmarks/graphrag_probe_20260309T084742Z.json`
  - delegated operational graph probe artifact
  - `summary.validation_mode = normal_path`
  - `summary.applied_count = 1 / 1`
  - `summary.normal_path_ready = true`
  - `summary.bootstrap_used = false`

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

실행 메모:
- 코드 수정:
  - `tools/bench/run_pipeline_bench.py`
    - graph query signal heuristic 추가
    - retrieval-side graph runtime sample / skip-reason aggregation 추가
    - graph index capability(`nodes_time` / `nodes_entity` / `nodes_timeline`)를 반영해 query selection 우선순위를 조정
    - sparse signal 환경에서도 preferred query를 놓치지 않도록 retrieval query candidate scan을 `limit` 이전에 조기 종료하지 않도록 수정
  - `tools/bench/run_user_delegated.ps1`
    - operational verification phase에 `operational-graph-main:DS-200` graph-on benchmark 추가
    - 이어서 `check_graphrag_applied.py --bootstrap-grouping-if-empty --require-applied` probe를 강제 연결
    - planned step 계산에 operational graph verification benchmark + probe 2 step 반영
- 테스트:
  - `tests/test_tools_bench_run_pipeline_bench.py`
  - `tests/test_tools_bench_strict_gate.py`
  - `tests/test_tools_bench_run_one_shot_validation.py`
  - 결과:
    - `pytest -q tests/test_tools_bench_run_pipeline_bench.py tests/test_tools_bench_strict_gate.py tests/test_tools_bench_run_one_shot_validation.py`
    - `21 passed`
  - `tests/test_tools_bench_run_user_delegated.py`
  - 결과:
    - `pytest -q tests/test_tools_bench_run_user_delegated.py tests/test_tools_bench_run_one_shot_validation.py`
    - `5 passed`
- 운영 A/B:
  - fresh stack:
    - `http://127.0.0.1:8088`
  - artifacts:
    - `verify/benchmarks/20260308T021123Z.json`
    - `verify/benchmarks/20260308T021429Z.json`
    - `verify/benchmarks/20260308T022346Z.json`
    - `verify/benchmarks/20260308T023257Z.json`
    - `verify/benchmarks/20260308T023711Z.json`
    - `verify/benchmarks/20260308T024635Z.json`
- 현재 해석:
  - `DS-200 on-r2 = 6 / 30`으로 목표값 `>= 0.20`을 충족했다.
  - `DS-800 on-r2 = 15 / 30`으로 목표값 `> 0`을 충분히 충족했다.
  - selection fix 전에는 `entity_alias` 편향 때문에 `no_seeds`가 대부분이었고, fix 후에는 `time_anchor` 중심 샘플이 늘면서 applied rate가 크게 개선됐다.
  - 기본 delegated command flow에서도 이제 별도 operational graph verification artifact와 probe artifact가 실제로 남는다.
  - 2026-03-09 delegated run은 graph phase 이후 step 12 strict gate에서 중단됐지만, graph verification benchmark(step 8)와 graph probe(step 9)는 성공적으로 완료됐다.
- 남은 작업:
  - 필요 시 `check_graphrag_applied.py` 외 소형 grouping scenario probe를 추가

우선순위:
- `P1`

### WS4. unknown/actionability 개선 — recall을 올리되 precision 손실은 통제
목적:
- quick/mainline에서 `unknown` 비율을 낮추고, 낮춘 이유가 진짜 recall 개선인지 설명 가능하게 만든다.

상태:
- `진행중 (coverage/triage instrumentation 완료, relation-style suppression + fresh rerun 완료, mainline unknown 개선은 아직 미달)`

현재 근거:
- DS-400 quick `unknown_rate = 0.8962`
- DS-200 graph-on quick `unknown_rate = 0.8267`
- 현재 엔진은 보수적이라 precision 지향이지만 운영 액션 가능성이 낮다.
- `modules/nf_consistency/engine.py`
  - `segment_count`
  - `segments_with_claims_count`
  - `claim_count`
  - `claims_skipped_low_confidence`
  - `triage_total_claims` / `triage_selected_claims` / `triage_skipped_claims`
  - 를 `req_stats`로 누적한다.
- `modules/nf_workers/runner.py`
  - consistency complete payload에 위 coverage/triage 필드를 노출한다.
- `tools/bench/run_pipeline_bench.py`
  - `consistency_runtime` aggregate에 아래가 추가됐다.
    - `segment_count_total`
    - `segments_with_claims_count_total`
    - `claim_count_total`
    - `claims_processed_total`
    - `claims_skipped_low_confidence_total`
    - `slot_candidate_count_total`
    - `slot_candidate_selected_total`
    - `triage_total_claims_total`
    - `triage_selected_claims_total`
    - `triage_skipped_claims_total`
    - `slot_detection_rate`
    - `claims_skipped_low_confidence_rate`
    - `triage_selection_rate`
    - `avg_slot_confidence`
- `tools/bench/summarize_latest_metrics.py`
  - latest row에 `latest_consistency_runtime`, `latest_shadow_reference`, `latest_actionability_status`, `latest_actionability_note`를 함께 노출한다.
  - mainline `claim_count_total = 0`을 coverage collapse와 shadow separation으로 구분해 읽을 수 있게 됐다.
  - `label_mode = operational`에서는 `preferred_artifact_cohort = operational_closeout`를 우선하고, cohort-tagged latest가 생긴 뒤의 ad hoc `operational-main:*` artifact는 canonical baseline에서 제외한다.
- `tools/bench/render_gate_report.py`
  - final gate markdown에 `pipeline_actionability_status`, `pipeline_actionability_note`, `pipeline_shadow_reference_*`를 추가했다.
  - overall gate는 유지하되, mainline/shadow two-lane actionability 판독을 secondary line item으로 함께 남긴다.
- `tools/bench/run_pipeline_bench.py`
  - top-level `artifact_cohort`를 기록한다.
- `tools/bench/run_user_delegated.ps1`
  - canonical operational / graph / strict / diversity artifact에 explicit cohort를 붙이도록 정렬했다.
- `verify/benchmarks/20260309T090831Z.json`
  - fresh `operational-shadow:local-profile-only` rerun
  - `doc_count = 1`
  - `claim_count_total = 1`
  - `unknown_reason_counts = {NO_EVIDENCE: 1}`
- `verify/benchmarks/gate_report_ws4_actionability_preview_20260309.md`
  - preview gate
  - `pipeline_actionability_status = SEPARATED_TO_SHADOW`
  - `pipeline_shadow_reference_claim_count_total = 1`
- `verify/benchmarks/20260309T092830Z.json`
  - fresh `operational-main:DS-200`
  - `artifact_cohort = operational_closeout`
- `verify/benchmarks/20260309T092609Z.json`
  - fresh `operational-main:DS-400`
  - `artifact_cohort = operational_closeout`
- `verify/benchmarks/20260309T093357Z.json`
  - fresh `operational-main:DS-800`
  - `artifact_cohort = operational_closeout`
- `verify/benchmarks/20260309T093414Z.json`
  - fresh `operational-shadow:local-profile-only`
  - `artifact_cohort = operational_closeout`
- `verify/benchmarks/latest_metrics_summary.json`
  - canonical summary 재생성 완료
  - `label_filter.preferred_artifact_cohort = operational_closeout`
- `verify/benchmarks/gate_report_20260309T093500Z_with_soak.md`
  - canonical gate 재생성 완료
  - `pipeline_actionability_status = MAINLINE_ACTIVE`
- `tools/bench/run_pipeline_bench.py`
  - consistency target selection의 signal summary를 regex heuristic이 아니라 rule-only extractor-backed summary로 바꿨다.
  - unsupported `profile_prefix` / quoted bare age line에 끌리던 샘플을 줄이고, 실제 extractable slot이 있는 문서를 우선 고르게 맞췄다.
- `verify/benchmarks/20260309T124915Z.json`
  - ad hoc `ws4-mainline-check:DS-200`
  - `claim_count_total = 3`
  - `unknown_count_total = 3`
  - `selected_signal_positive_docs = 3`
  - `selected_signal_type_counts = {talent: 1, relation: 2}`
- `verify/benchmarks/20260309T125807Z.json`
  - ad hoc `ws4-mainline-check:DS-400`
  - `claim_count_total = 12`
  - `unknown_count_total = 11`
  - `violate_count_total = 1`
  - `selected_signal_positive_docs = 12`
  - `selected_signal_type_counts = {relation: 6, death: 3, talent: 1, place: 1, affiliation: 1}`
- `modules/nf_consistency/engine.py`
  - entity/place 계열 slot은 claim span을 bare slot token 대신 segment 문장 단위로 넓혀 verdict text와 auto-filter context를 보존하게 바꿨다.
- `verify/benchmarks/20260309T132315Z.json`
  - ad hoc `ws4-span-check-r2:DS-200`
  - `claim_count_total = 3`
  - `unknown_count_total = 3`
  - verdict text는 `천재 -> 노력하는 천재.`, `오로트 왕 폼페의 딸 -> “오로트 왕 폼페의 딸, 루이사입니다.”`처럼 문장 단위로 넓어졌지만 `NO_EVIDENCE` 자체는 그대로 남았다.
- `modules/nf_consistency/extractors/pipeline.py`
  - relation candidate 뒤에 `문제/사건/계획/...` 같은 planning noun이 붙는 경우를 reject 하도록 sanitize를 추가했다.
  - `장소는 ... 위고` 같은 trailing clause place value도 reject 하도록 `고` tail을 low-signal suffix로 추가했다.
- `modules/nf_model_gateway/gateway.py`
  - local heuristic extractor에서 bare `천재` fallback을 제거하고 explicit `재능:` 라벨만 남기도록 좁혔다.
- `verify/benchmarks/20260309T134325Z.json`
  - ad hoc `ws4-quality-check:DS-200`
  - `claim_count_total = 2`
  - `unknown_count_total = 2`
  - `selected_signal_type_counts = {relation: 1}`
  - 기존 `걸신들린 김 진사의 딸 문제...` planning relation claim은 사라졌고, 남은 verdict는 `“오로트 왕 폼페의 딸, 루이사입니다.”`, `천재` 2건이다.
- `modules/nf_consistency/extractors/pipeline.py`
  - relation candidate 뒤에 `, 루이사입니다` / `루이사입니다` 같은 `name + copula` self-intro tail이 오면 relation claim으로 승격하지 않도록 reported-intro filter를 추가했다.
- `modules/nf_consistency/extractors/rule_extractor.py`
  - implicit talent rule(`그녀는 천재였다.`)를 제거하고 explicit `재능:` 계열만 talent claim으로 남기도록 조정했다.
  - subject-scoped age는 `시로네는 올해 50세가 되었다.` 같은 `올해 ... 세가 되었다` 패턴까지 포착하도록 보강했다.
- `tests/test_nf_consistency_extractors.py`
  - `오로트 왕 폼페의 딸, 루이사입니다.`
  - `오로트 왕 폼페의 딸 루이사입니다.`
  - 두 패턴이 relation claim으로 추출되지 않음을 regression으로 고정했다.
  - `그녀는 천재였다.` 가 더 이상 talent claim으로 추출되지 않음을 regression으로 고정했다.
  - `시로네는 올해 50세가 되었다.` age extraction regression을 추가했다.
- 테스트:
- `tests/test_nf_workers_consistency_payload.py`
  - `tests/test_tools_bench_run_pipeline_bench.py`
  - 결과:
    - `pytest -q tests/test_nf_workers_consistency_payload.py tests/test_tools_bench_run_pipeline_bench.py`
    - `22 passed`
- `tests/test_nf_consistency_engine.py`
  - `tests/test_tools_bench_run_pipeline_bench.py`
  - 결과:
    - `pytest -q tests/test_nf_consistency_engine.py tests/test_tools_bench_run_pipeline_bench.py`
    - `44 passed`
- `tests/test_nf_consistency_extractors.py`
  - `tests/test_nf_model_gateway_selection.py`
  - 결과:
    - `pytest -q tests/test_nf_consistency_extractors.py tests/test_nf_model_gateway_selection.py`
    - `43 passed`
- `tools/bench/run_pipeline_bench.py`
  - quick profile 위에 아래 override를 CLI로 직접 얹을 수 있게 됐다.
    - `--index-grouping-enabled`
    - `--consistency-metadata-grouping`
    - `--consistency-layer3-promotion`
    - `--consistency-verifier-mode`
    - `--consistency-triage-mode`
    - `--consistency-triage-anomaly-threshold`
    - `--consistency-triage-max-segments`
    - `--consistency-verification-loop`
    - `--consistency-verification-loop-max-rounds`
    - `--consistency-verification-loop-timeout-ms`
- `verify/benchmarks/20260308T030844Z.json`
  - `ws4-quick-ab:DS-200-baseline`
  - `unknown_rate = 0.5962`
  - `slot_detection_rate = 0.0072`
  - `claims_skipped_low_confidence_rate = 0.0`
  - `triage_selection_rate = 1.0`
- `verify/benchmarks/20260308T031128Z.json`
  - `ws4-quick-ab:DS-200-grouping`
  - `unknown_rate = 0.5962`
  - `slot_detection_rate = 0.0072`
  - `claims_skipped_low_confidence_rate = 0.0`
  - `triage_selection_rate = 1.0`
- `verify/benchmarks/20260308T031641Z.json`
  - `ws4-quick-ab:DS-400-baseline`
  - `unknown_rate = 0.5849`
  - `slot_detection_rate = 0.0041`
  - `claims_skipped_low_confidence_rate = 0.0`
  - `triage_selection_rate = 1.0`
- `verify/benchmarks/20260308T032148Z.json`
  - `ws4-quick-ab:DS-400-grouping`
  - `unknown_rate = 0.5849`
  - `slot_detection_rate = 0.0041`
  - `claims_skipped_low_confidence_rate = 0.0`
  - `triage_selection_rate = 1.0`
- `modules/nf_consistency/engine.py`
  - entity-bound slot에서 `target_entity_id`가 resolve된 경우 entity-scoped fact를 우선하고, global fact는 fallback으로만 사용하도록 정렬
- `tests/consistency/test_engine_quality_core.py`
  - entity-bound slot이 entity-scoped fact와 global fact를 동시에 섞어 `CONFLICTING_EVIDENCE`를 만들지 않는지 고정
  - 결과:
    - `pytest -q tests/consistency/test_engine_quality_core.py tests/test_nf_workers_consistency_payload.py tests/test_tools_bench_run_pipeline_bench.py`
    - `42 passed`
- `verify/benchmarks/20260308T033237Z.json`
  - `ws4-quick-ab:DS-200-baseline-r2`
  - entity-scoped fact 우선 조정 후 rerun
  - `unknown_rate = 0.5962` (변화 없음)
  - `unknown_reason_counts = {"CONFLICTING_EVIDENCE": 30, "NUMERIC_CONFLICT": 3, "SLOT_UNCOMPARABLE": 3}`
- `verify/benchmarks/20260308T033750Z.json`
  - `ws4-quick-ab:DS-400-baseline-r2`
  - entity-scoped fact 우선 조정 후 rerun
  - `unknown_rate = 0.5849` (변화 없음)
  - `unknown_reason_counts = {"CONFLICTING_EVIDENCE": 31}`

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

실행 메모:
- 코드 수정:
  - `modules/nf_consistency/engine.py`
    - segment/claim/triage coverage stats 누적 추가
    - entity-bound slot에서 entity-scoped fact 우선 선택, global fact는 fallback-only로 조정
    - `relation/affiliation/job/talent`의 single-token head match에서 설명형 phrase(`... 돕는 조력자`)를 자동 `OK`로 보지 않도록 head-token guard 추가
- `modules/nf_workers/runner.py`
  - consistency complete payload에 coverage/triage/low-confidence fields 추가
  - `tools/bench/run_pipeline_bench.py`
    - consistency runtime aggregate / derived rates 추가
    - quick A/B를 위한 consistency override CLI 및 index-grouping 독립 스위치 추가
- 운영 A/B:
  - fresh stack:
    - `http://127.0.0.1:8089`
  - artifacts:
    - `verify/benchmarks/20260308T030844Z.json`
    - `verify/benchmarks/20260308T031128Z.json`
    - `verify/benchmarks/20260308T031641Z.json`
    - `verify/benchmarks/20260308T032148Z.json`
    - `verify/benchmarks/20260308T033237Z.json`
    - `verify/benchmarks/20260308T033750Z.json`
- 현재 해석:
  - 초기 단계는 unknown 감소 원인을 설명하기 위한 관측성 확보다.
  - 다음 quick rerun부터는 `unknown_rate`뿐 아니라 `slot_detection_rate`, `claims_skipped_low_confidence_rate`, `triage_selection_rate`까지 같이 볼 수 있다.
  - `metadata grouping on`만으로는 DS-200/400에서 `unknown_rate`가 실질적으로 내려가지 않았다.
  - `claims_skipped_low_confidence_rate = 0.0`, `triage_selection_rate = 1.0`이라 현재 bottleneck은 low-confidence gate나 triage보다 claim extraction coverage / slot comparability 쪽일 가능성이 높다.
  - 따라서 다음 규칙 조정 우선순위는 triage threshold가 아니라 extraction coverage와 slot comparison 범위 확대다.
  - entity-bound fact 우선 선택 조정만으로도 DS-200/400 quick `unknown_rate`와 `CONFLICTING_EVIDENCE`는 움직이지 않았다.
  - local DB sample 기준으로는 `CONFLICTING_EVIDENCE` 중 일부가 malformed relation-style fact value 또는 fact-link 없이 SUPPORT만 누적된 case에 가깝다.
  - 따라서 다음 실제 타깃은 triage가 아니라 schema fact false-positive suppression과 extractor/tag quality 쪽이다.
  - 2026-03-08 후속 조치로 설명형 relation-style support를 억제하는 slot comparison guard를 추가했고, 관련 unit regression은 통과했다.
  - 이어서 extraction 단계에서도 설명형 head phrase를 schema fact로 승격하지 않도록 필터를 추가했고, 관련 unit regression은 통과했다.
  - 하지만 fresh isolated rerun 결과 `verify/benchmarks/20260308T040937Z.json`, `verify/benchmarks/20260308T041421Z.json` 기준 `unknown_rate`는 각각 `0.6875`, `0.6833`으로 여전히 높고, `r3 -> r4` 변화도 사실상 0이었다.
  - 따라서 relation-style descriptive support suppression만으로는 mainline quick unknown 문제를 닫지 못했고, 다음 WS4 실타깃은 extractor/tag quality 추가 보정 또는 slot comparison 범위 확대가 아니라 broader claim coverage / schema fact quality 쪽으로 재조정해야 한다.
  - 추가 extractor tightening 이후 fresh isolated rerun(`verify/benchmarks/20260308T074141Z.json`, `verify/benchmarks/20260308T074957Z.json`)에서는 quick `unknown_rate`가 둘 다 `0.0`이 되었지만, 동시에 `claim_count_total = 0`으로 수렴했다.
  - 이 상태는 WS4 close가 아니다. false positive suppression은 확보했지만 quick actionability를 구성하는 claim coverage가 사라졌기 때문이다.
  - 따라서 다음 WS4 실타깃은 unknown 감소 자체가 아니라, schema-backed explicit claim만 다시 살려 `claim_count_total > 0`을 회복하면서도 `unknown_rate`를 낮게 유지하는 방향으로 좁혀야 한다.
  - 2026-03-08 추가 후속으로 extractor coverage를 일부 복구하고 `run_pipeline_bench.py` consistency target selection을 signal-window 기준으로 바꿨다. live quick rerun `verify/benchmarks/20260308T105749Z.json`에서는 `claim_count_total = 3`까지 회복됐지만, `사도련`, `5:31`, `5:45`가 모두 `UNKNOWN/CONFLICTING_EVIDENCE`라 standalone clock marker false positive가 남아 있었다.
  - 이어서 standalone bracketed time marker(`[PM 5:31]`)를 time claim으로 승격하지 않도록 extractor를 다시 조정하고, sampling signal도 `clock_marker`보다 structured profile line(`이름/별호/무위/출신`) 쪽으로 옮겼다.
  - 최신 live quick rerun `verify/benchmarks/20260308T110638Z.json`에서는 clock-marker claim이 제거되어 `claim_count_total = 1`로 정리됐다. 남은 claim은 `사도련` affiliation 1건이며 verdict는 여전히 `UNKNOWN/CONFLICTING_EVIDENCE`다.
  - 이어서 schema registry default tag mapping 오류(`주인공/소속 -> death`, `주인공/직업 -> affiliation` 등)를 바로잡았다. 이 수정 이후 live quick rerun `verify/benchmarks/20260308T111543Z.json` 기준 self doc의 `소속: 사도련 백전귀(百戰鬼)`가 더 이상 `주인공/직업`으로 오염되지 않고 `설정/인물/주인공/소속 = 사도련`으로 저장되는 것을 확인했다.
  - 그 다음 단계로 entity-bound string claim에서 slot anchor가 전혀 없는 retrieval snippet을 evidence 후보에서 제거하고, explicit profile line(`소속:`, `직업:`, `관계:` 등)에서 나온 claim은 self-evidence scope를 `doc`까지 넓혀 같은 문서의 후행 mention도 제외하도록 조정했다.
  - 최신 live quick rerun `verify/benchmarks/20260308T112255Z.json`에서는 same-doc 후행 mention이 여전히 남아 `UNKNOWN/CONFLICTING_EVIDENCE`였고, self-evidence handling이 마지막 blocker임이 드러났다.
  - 추가 self-evidence scope 보강 이후 live quick rerun `verify/benchmarks/20260308T112901Z.json`에서는 같은 claim(`사도련`)이 여전히 `UNKNOWN`이지만 unknown reason이 `CONFLICTING_EVIDENCE -> NO_EVIDENCE`로 바뀌었다. 즉 현재 남은 문제는 false conflict가 아니라, external corroboration 부재다.
  - 이어서 local-only explicit profile line을 공용 heuristic으로 분리하는 `consistency_corroboration_policy` 메타를 builder/bench에 추가했다. 현재 기준은 `이름/나이/소속/별호/무위/출신`류 explicit profile block이 3줄 이상 연속될 때 `local_profile_only`로 본다.
  - 기존 `verify/datasets/DS-GROWTH-200.jsonl`은 아직 old manifest(`dataset_generation_version = 20260307-r5`)라 레코드 메타가 없지만, bench는 fallback inference로 동일 정책을 적용하도록 했다.
  - 그 상태에서 live quick rerun `verify/benchmarks/20260308T114003Z.json`을 돌리면 `local_profile_only_docs_total = 1`, `skipped_local_profile_only_docs = 1`이 summary에 명시되고, `claim_count_total = 0`, `unknown_rate = 0.0`으로 수렴한다. 즉 local-only explicit profile claim은 primary consistency bench에서 분리되었고, 다시 coverage collapse가 아니라 policy separation 상태가 된 것이다.
  - 후속으로 canonical `verify/datasets`를 새 builder로 재생성했다. 현재 `verify/datasets/dataset_manifest.json`과 `DS-GROWTH-200.jsonl`은 `dataset_generation_version = 20260308-r6`이며, `consistency_corroboration_policy_counts = {default: 199, local_profile_only: 1}`가 메타에 고정됐다.
  - 같은 기준으로 local-profile-only shadow track CLI(`--only-local-profile-only --include-local-profile-only`)도 추가했다. live shadow run `verify/benchmarks/20260308T114345Z.json`에서는 `doc_count = 1`, `claim_count_total = 1`, `unknown_reason_counts = {NO_EVIDENCE: 1}`로 secondary lane이 독립적으로 동작함을 확인했다.
  - canonical r6 dataset 기준 mainline quick rerun `verify/benchmarks/20260308T114838Z.json`에서도 `dataset_generation_version = 20260308-r6`, `local_profile_only_docs_total = 1`, `skipped_local_profile_only_docs = 1`, `claim_count_total = 0`, `unknown_rate = 0.0`이 재현됐다. 즉 fallback inference가 아니라 canonical metadata 기준으로 같은 separation 결과가 나왔다.
  - 따라서 현재 WS4의 다음 실질 과제는 “분리 정책을 넣을지”가 아니라 “분리된 two-lane metric을 운영 closeout에 어떻게 반영할지”다. 남은 결정은 1) mainline closeout을 actionable subset만으로 선언할지, 2) local-profile-only shadow track을 별도 guard/report에 포함할지, 3) shadow track에 대해 judge/source-policy 실험을 연결할지 여부다.
  - 2026-03-09 추가 후속으로 metrics summary schema에 actionability/shadow reference를 넣어, mainline `claim_count_total = 0`이어도 `SEPARATED_TO_SHADOW`와 `NO_MAINLINE_CLAIMS`를 구분해 읽을 수 있게 했다.
- fresh shadow artifact(`verify/benchmarks/20260309T090831Z.json`)가 있는 현재 bench dir 기준 preview summary에서는 `DS-200.latest_actionability_status = SEPARATED_TO_SHADOW`로 판정된다.
- final gate preview(`verify/benchmarks/gate_report_ws4_actionability_preview_20260309.md`)에서도 같은 상태가 `pipeline_actionability_status = SEPARATED_TO_SHADOW`로 노출된다.
- 후속으로 cohort-tagged canonical rerun(`20260309T092830Z/092609Z/093357Z/093414Z`)을 찍고 `latest_metrics_summary.{json,md}`와 `gate_report_20260309T093500Z_with_soak.md`를 재생성했다.
- canonical summary 기준 현재 `DS-200/400.latest_actionability_status = MAINLINE_ALL_UNKNOWN`, `DS-800.latest_actionability_status = MAINLINE_ACTIVE`다.
- 2026-03-09 추가 후속으로 mainline sampling을 extractor-backed claim-positive doc selection으로 바꾼 ad hoc rerun(`20260309T124915Z`, `20260309T125807Z`)에서는 `DS-200.claim_count_total = 3`, `DS-400.claim_count_total = 12`, `DS-400.violate_count_total = 1`까지 회복됐다.
- 즉 coverage recovery 자체는 어느 정도 성공했지만, unknown reason은 여전히 거의 전부 `NO_EVIDENCE`다.
- claim span을 문장 단위로 넓힌 후속 rerun(`20260309T132315Z`)에서도 verdict text explainability는 좋아졌지만 unknown count는 줄지 않았다.
- 후속 extractor quality patch(`20260309T134325Z`)에서는 planning relation 1건이 실제로 제거되어 `DS-200.claim_count_total = 2`까지 정리됐다.
- 2026-03-10 후속 extractor patch로 quoted/unquoted self-intro relation(`오로트 왕 폼페의 딸, 루이사입니다.`, `오로트 왕 폼페의 딸 루이사입니다.`)는 rule-only extractor 기준에서 제거됐다.
- 같은 후속에서 narrative `implicit talent` claim(`그녀는 천재였다.`)도 extractor 기준에서 제거되어, talent 계열은 explicit `재능:` 라벨 쪽으로 정렬됐다.
- 2026-03-09 추가 후속으로 `modules/nf_consistency/engine.py`, `modules/nf_workers/runner.py`, `tools/bench/run_pipeline_bench.py`에 slot-level diagnostics를 추가했다.
  - `claim_slot_counts`
  - `unknown_slot_counts`
  - `no_evidence_slot_counts`
  - `retrieval_anchor_filtered_count`
  - `anchor_filtered_slot_counts`
- 해석:
  - 이제 remaining `NO_EVIDENCE`를 slot type별로 분해하고, retrieval anchor filter가 corroboration을 얼마나 깎는지 artifact 수준에서 직접 볼 수 있다.
  - 다만 fresh operational rerun은 아직 없으므로 현재 상태 표기는 `검증 완료(운영 미반영)`로 읽어야 한다.
- 2026-03-09 추가 후속으로 `modules/nf_schema/extraction.py`에 selective narrative schema extraction을 보강했다.
  - explicit line prefix가 없는 문장이라도 아래 고정형 identity phrase는 explicit schema fact로 승격 가능하게 했다.
    - relation: `...의 아들/딸/동생/형제/손녀딸/...`
    - affiliation: `... 소속의 ...`, `...의 제1황녀/황녀/왕자/왕녀/공주`
    - job: `... 소속의 시녀/기사/...`처럼 affiliation phrase에 종속된 경우만 제한적으로 허용
  - generic `그의 직업은 마법사다.` 같은 일반 서술은 계속 explicit schema fact에서 제외한다.
  - 관련 unit regression:
    - `tests/test_nf_schema_extraction.py`
    - `tests/test_nf_schema_registry.py`
    - `tests/test_nf_consistency_extractors.py`
  - 해석:
    - WS4의 남은 `relation/affiliation` 계열 `NO_EVIDENCE`에 대해, sampling이 아니라 cross-doc schema fact coverage를 늘리는 쪽의 보강이 들어갔다.
    - 아직 fresh operational rerun은 없으므로 판정은 `검증 완료(운영 미반영)`이다.
- 따라서 현재 WS4의 남은 실질 과제는 sampling이 아니라 corroboration quality다. 구체적으로는 남은 `epithet` 류 relation/affiliation claim과 still-`NO_EVIDENCE` explicit claim의 corroboration 가능성을 더 높이는 쪽이다.
- 즉 two-lane closeout rule은 정리됐지만, mainline quality 자체는 아직 WS4 완료 수준이 아니다.

우선순위:
- `P1`

### WS5. soak tail lock 제거 — “통과”에서 “장기 안정”으로 이동
목적:
- soak가 이미 통과한 상태를 유지하되, 남아 있는 SQLite tail risk를 실질적으로 줄인다.

상태:
- `완료 (2026-03-07, isolated baseline short/0.5h soak clean pass)`

현재 근거:
- `verify/benchmarks/soak_20260307T032658Z.json`
  - `jobs_failed = 1 / 7028`
  - `sample error = database is locked`
- `verify/benchmarks/soak_20260307T161437Z.json`
  - short soak
  - `jobs_failed = 0 / 2676`
  - `failure_breakdown = {}`
  - `failure_samples = []`
- `verify/benchmarks/soak_20260307T164722Z.json`
  - `0.5h soak`
  - `jobs_failed = 0 / 6448`
  - `failure_breakdown = {}`
  - `failure_samples = []`
- isolated baseline 기준으로는 retry/busy_timeout/slot 제한 이후 tail lock이 재현되지 않았다.

작업:
1. WS0/WS1 반영 상태로 soak 재평가
   - shared-storage failure family fix 이후 isolated stack에서 재측정
2. short soak 실행
   - `verify/benchmarks/soak_20260307T161437Z.json`
3. `0.5h soak` 실행
   - `verify/benchmarks/soak_20260307T164722Z.json`
4. 후속 원칙
   - 이후 overnight soak에서 tail이 재현될 때만 hotspot / retry outcome 전용 계측을 추가한다.

검증:
1. short soak에서 `jobs_failed = 0`, `failure_samples = []` 확인
2. `0.5h soak`에서 `jobs_failed = 0`, `failure_samples = []` 확인
3. final gate sidecar(`verify/benchmarks/gate_report_20260307T164722Z_with_soak.md`)에서 soak goal이 `PASS`인지 확인

완료 기준:
- 최소 0.5h soak에서 `database is locked`가 0건이거나,
- 0건이 되지 않더라도 retry/exhaust/hotspot 근거로 잔존 원인이 완전히 설명 가능하다.
- 운영 문서에 “잔존 리스크 수용” 또는 “완전 제거” 중 하나로 명시된다.

완료 메모:
- 현재는 `완전 제거` 쪽에 가깝게 판정한다. 다만 explicit shared legacy storage를 다시 강제로 쓰는 비표준 실행은 본 판정 범위 밖이다.

우선순위:
- `P1`

### WS6. 문서/운영 판독 정리 — 실행자 오해 방지
목적:
- 산출물 해석 순서와 각 gate의 의미를 문서상으로 완전히 정리한다.

상태:
- `진행중 (WS6 1차 반영 완료, DS-200/400/800 fresh operational rerun 반영)`

현재 근거:
- `verify/benchmark_runbook.md`
  - final gate / strict_core_gate / strict_layer3_gate / latest metrics summary / shadow lane 판독 순서를 고정했다.
- `tools/bench/summarize_latest_metrics.py`
  - latest successful row에 `dataset_generation_version`, `composite_source_policy`, `source_policy_registry_version`, `local_profile_only_record_count`, `consistency_corroboration_policy_counts`, `consistency_corroboration_filter`, `consistency_target_selection`, `corroboration_lane`를 함께 노출한다.
  - markdown에도 `Corroboration Lane` 섹션을 추가했다.
- `tools/bench/render_gate_report.py`
  - pipeline section에 `pipeline_dataset_generation_version`, `pipeline_composite_source_policy`, `pipeline_source_policy_registry_version`, `pipeline_local_profile_only_record_count`, `pipeline_corroboration_lane`, `pipeline_consistency_corroboration_filter`, `pipeline_consistency_target_selection`를 추가했다.
- `verify/benchmarks/latest_metrics_summary.json`
  - 운영 summary를 현재 코드 기준으로 재생성했다.
  - `DS-200.latest_successful_file = 20260308T122139Z.json`
  - `DS-200/400/800.latest_dataset_generation_version = 20260308-r6`
  - `DS-200/400/800.latest_corroboration_lane = mainline_excludes_local_profile_only`
- `verify/benchmarks/20260308T131114Z.json`
  - fresh `operational-main:DS-400` rerun이 `r6 + mainline_excludes_local_profile_only` 상태를 직접 남긴다.
- `verify/benchmarks/20260308T132814Z.json`
  - fresh `operational-main:DS-800` rerun이 `r6 + mainline_excludes_local_profile_only` 상태를 직접 남긴다.
- `verify/benchmarks/20260308T122139Z.json`
  - fresh `operational-main:DS-200` rerun에서 `dataset_generation_version = 20260308-r6`, `local_profile_only_docs_total = 1`, `skipped_local_profile_only_docs = 1`, `claim_count_total = 0`, `unknown_rate = 0.0`이 artifact에 직접 남는다.
- `verify/benchmarks/gate_report_20260308T132814Z_with_soak.md`
  - final gate markdown에도 `pipeline_dataset_generation_version`, `pipeline_corroboration_lane`, `pipeline_consistency_target_selection`가 함께 출력되고, latest chain 기준 `goal_achieved = PASS`가 다시 닫혔다.
- 검증:
  - `pytest -q tests/test_tools_bench_metrics_summary.py tests/test_tools_bench_metrics_summary_corroboration.py tests/test_tools_bench_render_gate_report.py`
  - 통과

해석:
- summary/final report schema 자체는 이제 `r6 + local_profile_only two-lane` 메타를 표현할 수 있다.
- canonical `latest_metrics_summary`도 이제 fresh `operational-main:DS-200/400/800` rerun을 통해 `r6 + mainline_excludes_local_profile_only` 상태를 직접 보여준다.
- 남은 WS6 잔여물은 wording/runbook cleanup 성격에 가깝고, 운영 artifact 체인 자체는 current code 기준으로 다시 맞춰졌다.

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

### WS7. dataset builder validity / provenance 정리 + developer-only judge generalization
목적:
- benchmark input 자체의 분할 품질과 재현성을 artifact 수준에서 설명 가능하게 만들고, developer-only judge 실험 경로를 deterministic primary path와 분리된 형태로 일반화한다.

상태:
- `진행중 (WS7-J1/J2 완료, WS7-J3/J4/J5 검증 완료, remote_api backend 검증 완료(운영 미반영))`

현재 근거:
- `verify/datasets/dataset_manifest.json`
  - `dataset_generation_version = 20260308-r6`
  - `source_policy_registry_version = 20260307-r1`
  - `fallback_files = 1`
  - `fallback_episode_share = 0.01174`
  - `fallback_source_files = ["SRC-2e0ba0a8ee12"]`
  - `manual_review_source_count = 1`
  - `judge_audit_policy_count = 0`
  - canonical dataset은 여전히 `judge_audit_enabled = false` 상태로 유지된다
- `verify/datasets/DS-INJECT-C.jsonl`
  - canonical dataset row의 judge metadata는 비어 있고, judge on/off만으로 canonical hash가 달라지지 않도록 유지된다
- `verify/datasets/DS-DIVERSE-INJECT-C.jsonl`
  - canonical dataset row의 judge metadata는 비어 있다
- `verify/datasets/DS-INJECT-C-STRUCTURED.jsonl`
  - structured subset은 typed judge benchmark가 아니라 deterministic keyword filter다
- `verify/judge_runs/codex-ws7j5-layer3-r1/comparison/bench_candidate_summary.json`
  - `source_policy.judged_rows = 11`
  - `source_policy_shadow_apply.applied_rows = 0`
  - `inject_quality.effective_backend_counts = {"heuristic": 50}`
  - `typed_inject_disagreement.clear_conflict_rows = 8`
- `tools/bench/build_novel_dataset.py`
  - common novel header 탐지와 provenance 필드는 보강됐지만, 일부 corpus는 여전히 fallback 또는 partial split 상태다
  - source policy judge는 low-confidence `profile_auto` source에서만 호출되며, latest judge run 기준 실제 judged rows는 생겼지만 shadow apply 성공 사례는 아직 없다
- 2026-03-09 추가 후속으로 `tools/bench/build_novel_dataset.py`에 manual-review diagnostics와 optional quality gate를 추가했다.
  - manual-review source별 `manual_review_diagnostics`
    - `front_matter_hits`
    - `blank_line_gate_filtered_candidates`
    - `unsupported_header_variant_hits`
    - `unsupported_header_variant_samples`
    - `reason_code`
  - optional builder gates:
    - `--max-manual-review-sources`
    - `--max-undersized-sources`
    - `--max-oversized-sources`
  - canonical `verify/datasets/dataset_manifest.json` 재생성 이후에도 `SRC-2e0ba0a8ee12`는 `front_matter_dominant`이면서 동시에 `unsupported_header_variant_hits = 52`가 남아, “front matter가 강하고 unsupported chapter-style header도 섞여 있는 source”로 더 구체적으로 분해된다.
  - canonical manifest `build_options`에도 `max_manual_review_sources`, `max_undersized_sources`, `max_oversized_sources`가 기록된다.
- `tools/bench/judge_audit.py`, `tools/bench/dev_judge_backends.py`
  - dataset judge path는 `enable_test_judge_local_nli`와 `enable_test_judge_remote_api`를 모두 지원한다
  - `remote_api` path는 provider-backed prompt/JSON parse 경로로 연결되어 `judge_effective_backend = remote_api`를 남길 수 있다
  - provider credential이 없으면 기존처럼 `unsupported`로 남겨 accidental remote drift를 막는다
- `modules/nf_model_gateway/local/text_pair_classifier.py`
  - 현재 `local_nli` path는 model absence 시 heuristic fallback score를 반환할 수 있다
- `modules/nf_model_gateway/remote/provider.py`, `modules/nf_model_gateway/remote/openai_client.py`, `modules/nf_model_gateway/remote/gemini_client.py`
  - remote judge path는 `provider:model` 형태의 `judge_model_id`를 남긴다
  - `test_judge_timeout_ms`가 실제 remote judge request timeout에 연결됐다
- judge on/off 비교 결과
  - inject dataset row에 judge metadata가 직접 들어가므로, semantic sampling이 같아도 judge on/off만으로 JSONL hash가 달라질 수 있다
  - 이 상태에서는 canonical benchmark comparability가 judge 구현 변화에 오염된다
- 2026-03-08 `WS7-J1` 1차 반영
  - `tools/bench/judge_audit.py`
    - `judge_requested_backend`
    - `judge_effective_backend`
    - `judge_model_id`
    - `judge_prompt_version`
    - `judge_fallback_used`
    - `judge_input_hash`
    - `remote_api` requested path는 현재 `unsupported`로 명시
  - `tools/bench/build_novel_dataset.py`
    - source policy stats / inject rows에 judge provenance 필드 연결
  - `tools/bench/run_pipeline_bench.py`
    - dataset profile에 `requested_backend_counts`, `effective_backend_counts`, `prompt_version_counts`, `fallback_used_count` 추가
  - 검증:
    - `pytest -q tests/test_tools_bench_judge_audit.py tests/test_tools_bench_build_novel_dataset.py tests/test_tools_bench_run_pipeline_bench.py`
    - 통과
- 2026-03-08 `WS7-J2` 1차 반영
  - 새 엔트리포인트:
    - `tools/bench/run_dev_judged_dataset_pipeline.py`
  - 새 보조 모듈:
    - `tools/bench/render_dev_judge_report.py`
  - 보호장치:
    - `--developer-mode` 없으면 실행 실패
    - `verify/datasets` 아래 overwrite 차단
  - 산출물 루트:
    - `verify/judge_runs/ws7j2-20260308T042500Z/`
    - `baseline_snapshot/`
    - `judge_run_manifest.json`
    - `source_policy_judgments.jsonl`
    - `inject_quality_judgments.jsonl`
    - `comparison/dataset_diff_summary.json`
    - `comparison/bench_candidate_summary.json`
    - `report.md`
  - 실제 실행 결과:
    - inject audit `rows_total = 100`
    - `effective_backend_counts = {"local_nli_fallback": 100}`
    - `label_counts = {"contextless_append": 100}`
    - source policy audit는 현재 corpus 기준 low-confidence profile source가 없어 `judged_rows = 0`
  - 검증:
    - `pytest -q tests/test_tools_bench_run_dev_judged_dataset_pipeline.py`
    - 통과
- 2026-03-08 `WS7-J3` 1차 반영
  - `tools/bench/run_dev_judged_dataset_pipeline.py`
    - `DS-INJECT-C-TYPED`
    - `DS-DIVERSE-INJECT-C-TYPED`
    - `typed_inject_usability.jsonl`
    - deterministic subject alias extraction + typed contradiction template 반영
  - `tools/bench/judge_audit.py`
    - `malformed_template` label 추가
  - smoke:
    - `verify/judge_runs/ws7j4-smoke/derived_datasets/DS-INJECT-C-TYPED.jsonl`
    - `verify/judge_runs/ws7j4-smoke/derived_datasets/DS-DIVERSE-INJECT-C-TYPED.jsonl`
  - 현재 해석:
    - backend disabled smoke 기준 label은 여전히 `contextless_append` 중심이라, 실제 분별력 평가는 local judge enabled run으로 별도 확인해야 한다
- 2026-03-08 `WS7-J4` 1차 반영
  - `tools/bench/run_dev_judged_dataset_pipeline.py`
    - source policy row에 `candidate_line_samples` / compact feature bundle 연결
    - `manual_review_required` provenance 연결
    - simulated segmentation validation 추가
    - run-scoped `derived_datasets/source_policy_applied/summary.json` 생성
  - 검증:
    - `pytest -q tests/test_tools_bench_judge_audit.py tests/test_tools_bench_run_dev_judged_dataset_pipeline.py`
    - 통과
  - smoke:
    - `verify/judge_runs/ws7j4-smoke/comparison/bench_candidate_summary.json`
    - `source_policy_shadow_apply.applied_rows = 0`
  - 현재 해석:
    - current corpus에서는 low-confidence judged source가 없어 실제 apply 사례는 아직 없고, validation/apply 경로만 코드와 테스트로 고정된 상태다
- 2026-03-08 `WS7-J5` 1차 반영
  - `tools/bench/run_dev_judged_dataset_pipeline.py`
    - optional strict artifact 입력 경로 추가
    - `strict_layer3_audit` sidecar summary 추가
    - control/inject false positive drift, typed inject disagreement sample, confidence band 집계 추가
  - `tools/bench/render_dev_judge_report.py`
    - strict/layer3 secondary audit section 추가
  - 검증:
    - `pytest -q tests/test_tools_bench_run_dev_judged_dataset_pipeline.py tests/test_tools_bench_judge_audit.py tests/test_tools_bench_strict_gate.py`
    - 통과
  - smoke:
    - `verify/judge_runs/ws7j5-smoke/comparison/bench_candidate_summary.json`
    - `verify/judge_runs/ws7j5-smoke/report.md`
  - 현재 해석:
    - strict/layer3 audit는 현재 `no_strict_artifacts` placeholder까지 연결된 상태이고, next step은 real strict control/inject artifact를 입력해 evaluated path를 실증하는 것이다
- 2026-03-08 `WS7-J5` 2차 반영
  - `tools/bench/run_dev_judged_dataset_pipeline.py`
    - `--strict-artifact-dir` auto discovery 추가
    - latest `operational-main:DS-200` / `operational-strict-main:DS-CONTROL-D` / `operational-strict-main:DS-INJECT-C`를 자동 해석
    - `strict_artifact_resolution`을 manifest / sidecar / report에 기록
  - `tools/bench/render_dev_judge_report.py`
    - strict artifact resolution / selected artifact path를 보고서에 표시
  - 검증:
    - `pytest -q tests/test_tools_bench_run_dev_judged_dataset_pipeline.py tests/test_tools_bench_judge_audit.py`
    - 통과
  - smoke:
    - `verify/judge_runs/codex-review-auto-strict/`
    - `verify/judge_runs/codex-review-heuristic-provenance/`
  - 현재 해석:
    - `WS7-J5`는 이제 manual path뿐 아니라 real benchmark artifact auto discovery 기준 evaluated path까지 열렸다
    - 다만 current strict artifact는 `strict_layer3_gate = SKIPPED`이므로, layer3-capable strict rerun이 있어야 `J5` closeout으로 올릴 수 있다
- 2026-03-09 `WS7-J5` 3차 실증 완료
  - layer3-enabled isolated stack(`http://127.0.0.1:8091`) 기준 latest strict artifact를 재생성했다.
    - `verify/benchmarks/20260309T080639Z.json`
    - `verify/benchmarks/20260309T080952Z.json`
    - `verify/benchmarks/consistency_strict_gate_20260309T081000Z_iter1.json`
  - `tools/bench/run_dev_judged_dataset_pipeline.py --strict-artifact-dir verify/benchmarks` 재실행:
    - `verify/judge_runs/codex-ws7j5-layer3-r1/comparison/strict_layer3_audit_summary.json`
    - `verify/judge_runs/codex-ws7j5-layer3-r1/report.md`
  - 현재 해석:
    - `strict_layer3_audit.status = evaluated`
    - `strict_layer3_gate.status = PASS`
    - `artifact_resolution.mode = auto_discovery`
    - `typed_inject_disagreement.clear_conflict_rows = 8`
    - strict artifact의 `layer3_model_fallback_count`가 남아 있어, actual model availability가 아니라 fallback-aware local_nli path 실증으로 해석해야 한다
  - 판정:
    - `WS7-J5`는 real strict artifact + layer3-capable gate 기준 closeout 가능 상태다

작업:
1. 남은 fallback source 원인 분해
   - 현재 기준 실제 대상은 `SRC-2e0ba0a8ee12` 단일 source다
   - 진짜 헤더 부재
   - unsupported header variant
   - false positive 방지 필터로 인한 누락
2. oversized / undersized segment quality gate 추가 검토
   - `max_content_chars` 상한
   - `min_content_chars` 하한
   - per-file warning 기준
3. `DS-GROWTH-*` shuffled progressive growth semantics를 artifact/runbook에 고정
   - historical artifact와 직접 비교 시 comparability warning 유지
4. inject/control dataset의 typed benchmark화 검토
   - target entity alias
   - expected outcome
   - inject strategy 소비 경로 연결
5. dataset generation epoch/version 도입 검토
   - `dataset_generation_version`
   - pre-fix / post-fix comparability 경고
   - growth semantics 변경 시 artifact 수준 표기
6. content-based registry coverage 확대
   - `tools/bench/build_novel_dataset.py`의 source governance는 이미 `content_sha256` 기반 `source_policy_registry`로 전환됐다
   - 남은 과제는 rename-safe registry 자체가 아니라 registry coverage 확대와 manual-review source 축소다
   - 우선 대상:
     - `SRC-2e0ba0a8ee12` fallback/manual-review 해소 가능성 재검토
     - source profile(feature) 기반 자동 정책과 registry override의 경계 정리
     - low-confidence source에 대한 judge 보조 판정은 developer-only shadow apply에만 한정
7. judge 일반화 기본 원칙 고정
   - 운영 mainline에 통합하지 않고 developer-only shadow pipeline으로만 실행한다
   - canonical `verify/datasets` / `dataset_manifest.json` / 운영 summary는 judge 실험으로 직접 덮어쓰지 않는다
   - judge는 segmentation generator가 아니라 policy selector / sample auditor 역할로 제한한다
   - primary deterministic gate 대체 금지
   - prompt / model / input hash / backend provenance 없는 black-box 판정 금지
8. `WS7-J1` judge provenance hardening
   - `완료 (2026-03-10, remote_api backend/timeout wiring 포함)`
   - `tools/bench/judge_audit.py` / dataset row / sidecar schema에 아래 필드를 추가한다
     - `judge_requested_backend`
     - `judge_effective_backend`
     - `judge_model_id`
     - `judge_prompt_version`
     - `judge_fallback_used`
     - `judge_input_hash`
   - `local_nli_model` / `local_nli_fallback` / `heuristic` / `remote_api` / `disabled`를 구분 가능한 effective backend 체계로 정리한다
   - `enable_test_judge_remote_api`는 provider credential이 있는 경우 developer-only judge path에서 실제 backend로 동작하고, 미설정 시에는 `unsupported`로 남긴다
   - `test_judge_timeout_ms`는 실제 remote judge 호출 경로에 연결됐다
   - `tools/bench/run_pipeline_bench.py` summary에도 `judge_backend` 단일 문자열 대신 `effective_backend_counts`, `fallback_used_count`, `prompt_version_counts` 같은 집계를 남긴다
9. `WS7-J2` developer-only audit pipeline 신설
   - `완료 (2026-03-08)`
   - 새 엔트리포인트:
     - `tools/bench/run_dev_judged_dataset_pipeline.py`
   - 권장 보조 모듈:
     - `tools/bench/dev_judge_backends.py`
     - `tools/bench/dev_judge_apply.py`
     - `tools/bench/dev_judge_prompts.py`
     - `tools/bench/render_dev_judge_report.py`
   - 실행 단계:
     - baseline deterministic build 실행 또는 snapshot 읽기
     - judge request generation
     - sidecar audit artifact 생성
     - 선택적으로 judged variant dataset 생성
   - 출력 루트:
     - `verify/judge_runs/{run_id}/`
   - 필수 산출물:
     - `baseline_snapshot/`
     - `judge_run_manifest.json`
     - `source_policy_judgments.jsonl`
     - `inject_quality_judgments.jsonl`
     - `derived_datasets/`
     - `comparison/dataset_diff_summary.json`
     - `comparison/bench_candidate_summary.json`
     - `report.md`
   - 실행 보호장치:
     - `--developer-mode` 없이 실행 금지
     - canonical output overwrite 금지
10. `WS7-J3` typed inject judged variant 설계
   - developer-only dataset variant를 별도 생성한다
     - `DS-INJECT-C-TYPED`
     - `DS-DIVERSE-INJECT-C-TYPED`
   - deterministic subject alias extraction + slot-targeted contradiction template를 사용한다
   - judge label은 최소 아래 5종으로 고정한다
     - `clear_conflict`
     - `ambiguous_subject`
     - `contextless_append`
     - `no_conflict`
     - `malformed_template`
   - row inline metadata 대신 sidecar usability tag를 사용한다
     - `usable_for_core`
     - `usable_for_strict`
     - `usable_for_layer3_audit`
   - 목표는 generic append 전체를 즉시 교체하는 것이 아니라, developer-only 실험셋에서 judge의 분별력을 먼저 확보하는 것이다
11. `WS7-J4` source policy shadow apply
   - 적용 대상은 low-confidence source로 제한한다
   - judge 입력은 full text가 아니라 compact feature bundle로 제한한다
     - `source_id`
     - `content_sha256`
     - `candidate_boundary_counts`
     - `candidate_line_samples`
     - `content_length_stats`
     - front matter / spacing / boundary density 관련 feature
   - judge 출력은 아래처럼 policy selector 역할만 수행한다
     - `segmentation_policy`
     - `accepted_pattern_family`
     - `confidence`
     - `reason`
     - `manual_review_required`
   - judge 적용 전 simulated segmentation validation을 통과해야 한다
     - accepted family의 candidate count 존재
     - split episode count 최소치 충족
     - `median_chars` / short-segment-share / oversized-share 허용 범위 충족
     - front matter dominance 과도 시 reject
   - 통과한 경우에만 run-scoped `derived_datasets/source_policy_applied/` 아래 파생 dataset을 만든다
12. `WS7-J5` strict/layer3 audit 연결
   - judge를 strict hard gate로 올리지 않고 secondary disagreement analysis artifact로만 사용한다
   - `strict_layer3_gate`와는 분리된 별도 report 또는 sidecar field로 관리한다
   - control/inject 기준 false positive drift, disagreement sample, confidence band를 기록한다
13. judge 검증 규칙 고정
   - judge pipeline 추가 전후 canonical deterministic dataset hash는 변하지 않아야 한다
   - `--developer-mode` 없이 judged pipeline 실행 시 실패해야 한다
   - `judge_requested_backend = local_nli`인데 model이 없으면 `judge_effective_backend = local_nli_fallback`, `judge_fallback_used = true`가 artifact에 남아야 한다
   - source policy judge는 validation 실패 시 apply되지 않아야 한다
   - typed inject variant는 current generic append보다 `clear_conflict` 비율이 유의미하게 높아야 한다
   - 모든 judged variant dataset은 run-scoped output 아래에만 생성되어야 한다

내부 순서:
1. `WS7-J1` judge provenance hardening
2. `WS7-J2` developer-only audit pipeline
3. `WS7-J3` typed inject judged variant
4. `WS7-J4` source policy shadow apply
5. `WS7-J5` strict/layer3 audit 연결

완료 기준:
- dataset manifest만 읽어도 source별 split quality를 설명할 수 있다.
- fallback/oversplit/undersplit이 남아 있으면 그 사실이 warning 또는 gate로 직접 드러난다.
- `DS-GROWTH-*`와 inject/control의 해석 한계가 문서와 artifact 둘 다에 남는다.
- 파일명 하드코딩이 제거되거나, 최소한 content-based registry로 치환된다.
- developer-only judge pipeline이 canonical builder를 오염시키지 않고 run-scoped output으로만 동작한다.
- source policy / inject quality / strict layer3 audit에서 judge provenance가 `requested/effective backend`, `model`, `prompt`, `input hash`, `fallback_used`까지 포함해 설명 가능해진다.
- `LLM as judge`를 쓰더라도 deterministic primary path와 secondary audit path가 분리된다.

우선순위:
- `P1`

## 6) 통합 실행 순서
1. `WS0A -> WS1 -> WS2 -> WS5 -> WS3 -> WS4`
   - 운영 closeout mainline
   - one-shot runtime smoke를 먼저 닫고, DS-800/front-door/heavy-job 기준선을 복구한 뒤 strict/soak/graph/unknown 순으로 진행한다.
2. `WS7-J1 -> WS7-J2`
   - `완료`
   - developer-only judge subtrack의 provenance hardening과 run-scoped shadow pipeline 골격은 확보됐다.
3. `WS7-J3 -> WS7-J4 -> WS7-J5`
   - `검증 완료`
   - typed inject judged variant, source policy shadow apply, strict/layer3 audit evaluated path까지 실증했다.
4. `WS6`
   - `완료`
   - 운영 mainline과 developer-only judge subtrack의 용어/판독 규칙을 문서에 고정했다.

## 7) 실행 시 고정 규칙
- summary는 반드시 운영 라벨 필터를 적용한 산출물로 본다.
- ad hoc artifact는 완료 판정의 보조 증거로만 사용한다.
- `validation:one-shot`은 `frontdoor_probe` 존재만으로 성공 처리하지 않고, live bench `guards` 4종이 모두 true일 때만 성공으로 본다.
- strict는 항상 `strict_core_gate`와 `strict_layer3_gate`를 구분해 해석한다.
- graph 개선은 applied rate와 latency를 동시에 본다.
- unknown 개선은 precision 손실 설명 없이 수치만 낮췄다고 완료 처리하지 않는다.
- soak는 `failed_ratio`만 보지 않고 failure sample과 retry outcome도 같이 본다.
- developer-only judge 실험은 canonical dataset/summary 경로를 덮어쓰지 않고, `verify/judge_runs/*` 아래 run-scoped output으로만 남긴다.

## 8) 완료 정의
- 코드 정확성 버그가 제거되고 테스트로 고정된다.
- one-shot live bench 성공이 provenance/schema smoke가 아니라 runtime guard success까지 포함한 의미로 고정된다.
- 운영 라벨 summary/final/strict 기준선이 현 코드 상태에 맞게 재생성된다.
- strict_core / strict_layer3 의미가 분리된다.
- graph는 재현 가능한 applied rate 목표를 충족한다.
- unknown 개선이 수치와 원인 모두 설명 가능해진다.
- soak tail lock이 제거되거나 명시적으로 수용 가능한 수준으로 문서화된다.
- developer-only judge pipeline이 canonical deterministic path와 분리된 채 재현 가능하게 동작한다.
- 본 문서 외에 별도 단발성 follow-up 계획문서가 더 필요하지 않다.

## 9) 문서 갱신 규칙
- 상태 갱신은 `완료/진행중/보류`만 적지 않고 반드시 근거 artifact를 함께 남긴다.
- “완료” 표기는 운영 라벨 artifact 또는 gate 갱신 후에만 사용한다.
- ad hoc 검증만 끝난 경우 표기는 `검증 완료(운영 미반영)`로 통일한다.
- 새로운 TODO가 생기면 먼저 본 문서에 추가하고, 별도 일회성 계획문서는 만들지 않는다.
## 10) 2026-03-09 late follow-up
- `tools/bench/run_pipeline_bench.py`
  - consistency runtime에 slot-diagnostic schema health를 추가했다.
  - 새 필드:
    - `jobs_with_claims_total`
    - `slot_diagnostics_schema_status`
    - `slot_diagnostics_present_jobs`
    - `slot_diagnostics_partial_jobs`
    - `slot_diagnostics_missing_jobs`
    - `slot_diagnostics_missing_with_claims_jobs`
    - `slot_diagnostics_complete_job_rate`
    - `slot_diagnostics_missing_with_claims_rate`
- `tools/bench/summarize_latest_metrics.py`
  - latest runtime summary/actionability markdown에 `slot_diag` 상태를 같이 노출한다.
- `tools/bench/render_gate_report.py`
  - gate markdown에 `pipeline_slot_diagnostics_schema_status`와 missing counters를 추가했다.
- `verify/benchmarks/20260309T153108Z.json`
  - contaminated `8095` shadow rerun
  - `slot_diagnostics_schema_status = MISSING`
  - `claim_count_total = 1`
  - old/new worker payload schema가 섞인 상태를 artifact에서 직접 판독 가능해졌다.
- `verify/benchmarks/20260309T163346Z.json`
  - clean `8096` DS-800 operational rerun
  - `claim_count_total = 56`
  - `unknown_count_total = 49`
  - `violate_count_total = 6`
  - `unknown_rate = 0.8750`
  - `slot_diagnostics_schema_status = COMPLETE`
  - `claim_slot_counts = {relation: 10, death: 21, job: 7, age: 11, time: 3, place: 2, affiliation: 1, talent: 1}`
  - clean stack에서 WS4 slot-level diagnostics가 정상적으로 수집됨을 확인했다.
- `verify/benchmarks/20260309T163357Z.json`
  - clean `8096` local-profile-only shadow rerun
  - `claim_count_total = 1`
  - `unknown_rate = 1.0000`
  - `slot_diagnostics_schema_status = COMPLETE`
  - `claim_slot_counts = {affiliation: 1}`
- `verify/benchmarks/gate_report_ws4_closeout_rerun_20260309.md`
  - latest clean DS-800 + clean shadow artifact 기준으로 재생성했다.
- next:
  - WS4는 이제 "counter가 비는지"가 아니라 `death/age/relation/time` 중심 `NO_EVIDENCE`를 어떻게 더 줄일지로 다시 좁혀 본다.
  - contaminated stack rerun은 closeout 근거에서 제외하고, clean-stack artifact만 운영 판단 근거로 사용한다.

## 11) 2026-03-11 late follow-up
- `modules/nf_consistency/engine.py`
  - schema fact가 비어도 retrieval top result snippet에서 같은 slot/value가 explicit하게 다시 추출되면 보수적 corroboration으로 `OK`를 줄 수 있는 snippet corroboration fallback을 추가했다.
  - 목적은 `WS4`의 남은 `NO_EVIDENCE` 중 cross-doc explicit corroboration이 이미 retrieval에는 잡히지만 schema fact coverage가 늦는 케이스를 줄이는 것이다.
- 관련 회귀:
  - `tests/test_nf_consistency_engine.py`
    - affiliation claim `사도련`이 retrieved snippet `그는 사도련의 백전귀였다.`로 corroborate되면 `OK`가 됨을 고정했다.
  - `pytest -q tests/test_nf_consistency_engine.py tests/test_nf_consistency_extractors.py tests/test_nf_schema_extraction.py tests/test_nf_schema_registry.py tests/consistency/test_engine_quality_core.py tests/test_tools_bench_run_pipeline_bench.py tests/test_nf_workers_consistency_payload.py`
  - 결과: 통과
- fresh isolated operational rerun:
  - isolated stack: `http://127.0.0.1:8097`
  - `verify/benchmarks/20260311T124616Z.json`
    - `operational-main:DS-200`
    - `claim_count_total = 247`
    - `unknown_count_total = 114`
    - `unknown_rate = 0.4615`
    - `latest_actionability_status = MAINLINE_ACTIVE`
  - `verify/benchmarks/20260311T125614Z.json`
    - `operational-main:DS-400`
    - `claim_count_total = 339`
    - `unknown_count_total = 157`
    - `unknown_rate = 0.4631`
    - `latest_actionability_status = MAINLINE_ACTIVE`
  - `verify/benchmarks/20260311T131336Z.json`
    - `operational-main:DS-800`
    - `claim_count_total = 377`
    - `unknown_count_total = 211`
    - `unknown_rate = 0.5597`
    - `violate_count_total = 165`
    - `slot_diagnostics_schema_status = COMPLETE`
    - `anchor_filtered_slot_counts = {affiliation: 3780, job: 48, relation: 48, talent: 11}`
- shadow lane:
  - `verify/benchmarks/failure_20260311T131336Z.json`
    - `operational-shadow:local-profile-only`
    - `error_message = dataset is empty after corroboration filter (only_local_profile_only): verify/datasets/DS-GROWTH-200.jsonl`
  - 해석:
    - current canonical `DS-GROWTH-200/400/800`는 `local_profile_only_record_count = 0`, `consistency_corroboration_policy_counts = {default: *}` 상태다.
    - 즉 shadow lane failure는 code regression이라기보다 current canonical dataset에 분리 대상 local-profile-only row가 없다는 뜻이다.
- summary / gate 재생성:
  - `verify/benchmarks/latest_metrics_summary.json`
    - `DS-200/400/800.latest_successful_file = 20260311T*.json`
    - 세 dataset 모두 `latest_actionability_status = MAINLINE_ACTIVE`
    - `overall_status = FAIL`
    - `absolute_goal_status = FAIL`
  - `verify/benchmarks/gate_report_ws4_closeout_rerun_20260311.md`
    - `pipeline_artifact = verify/benchmarks/20260311T131336Z.json`
    - `pipeline_goal_achieved = FAIL`
    - `pipeline_consistency_p95_ms = 2569.78`
    - `pipeline_unknown_rate = 0.5597`
- 해석:
  - coverage collapse 문제는 사실상 해소됐다. `DS-200/400/800` 모두 mainline에서 의미 있는 claim volume이 다시 잡힌다.
  - 다만 `WS4` closeout은 아직 아니다. 남은 병목은 `affiliation` 중심 corroboration quality와 DS-800 latency다.
  - 즉 다음 실질 과제는 "claim을 더 뽑을지"가 아니라, 이미 많이 잡히는 `affiliation/relation` claim에서 `NO_EVIDENCE`와 anchor-filter loss를 어떻게 더 줄일지로 좁혀진다.

### 11A) 2026-03-11 post-rerun follow-up
- `modules/nf_consistency/extractors/pipeline.py`
  - generic `조직명 + 칭호` affiliation은 기본 runtime extractor에서는 비활성화하고, schema extraction / snippet corroboration 경로에서만 opt-in 하도록 분리했다.
- `modules/nf_schema/extraction.py`
  - explicit schema extraction은 계속 `allow_generic_narrative_affiliation = true`로 동작해 cross-doc schema fact coverage는 유지한다.
- `modules/nf_consistency/engine.py`
  - snippet corroboration용 rule-only pipeline에도 같은 opt-in을 연결했다.
- 관련 회귀:
  - `tests/test_nf_consistency_extractors.py`
    - default runtime profile에서는 `그는 사도련의 백전귀였다.`를 affiliation claim으로 추출하지 않는다.
    - opt-in profile에서는 같은 문장을 affiliation corroboration용 signal로 읽을 수 있다.
  - `pytest -q tests/test_nf_consistency_extractors.py tests/test_nf_schema_extraction.py tests/test_nf_schema_registry.py tests/test_nf_consistency_engine.py tests/consistency/test_engine_quality_core.py tests/test_tools_bench_run_pipeline_bench.py tests/test_nf_workers_consistency_payload.py tests/test_tools_bench_metrics_summary.py tests/test_tools_bench_render_gate_report.py tests/test_tools_bench_build_novel_dataset.py`
  - 결과: 통과
- fresh isolated operational rerun r2:
  - isolated stack: `http://127.0.0.1:8098`
  - `verify/benchmarks/20260311T132559Z.json`
    - `operational-main:DS-200`
    - `claim_count_total = 196`
    - `unknown_count_total = 91`
    - `unknown_rate = 0.4643`
    - previous same-day rerun 대비 claim volume은 줄었지만 `MAINLINE_ACTIVE` 유지
  - `verify/benchmarks/20260311T133920Z.json`
    - `operational-main:DS-400`
    - `claim_count_total = 285`
    - `unknown_count_total = 134`
    - `unknown_rate = 0.4702`
  - `verify/benchmarks/20260311T135400Z.json`
    - `operational-main:DS-800`
    - `claim_count_total = 310`
    - `unknown_count_total = 177`
    - `unknown_rate = 0.5710`
    - `violate_count_total = 132`
    - `anchor_filtered_slot_counts = {affiliation: 3059, job: 36, relation: 48, talent: 11}`
    - `pipeline_consistency_p95_ms = 2568.30`
- latest attempt:
  - `verify/benchmarks/failure_20260311T135405Z.json`
    - `operational-main:DS-800`
    - `attempt_stage = ingest_jobs`
    - `error_class = URLError`
  - `verify/benchmarks/latest_metrics_summary.json`
    - `DS-800.latest_successful_file = 20260311T135400Z.json`
    - `DS-800.latest_attempt_file = failure_20260311T135405Z.json`
    - `overall_status = PASS`
    - `absolute_goal_status = FAIL`
  - `verify/benchmarks/gate_report_ws4_closeout_rerun_20260311_r2.md`
    - `pipeline_artifact = verify/benchmarks/20260311T135400Z.json`
    - `pipeline_goal_achieved = FAIL`
    - `pipeline_latest_attempt_file = failure_20260311T135405Z.json`
- 해석:
  - runtime에서 generic affiliation claim을 줄인 결과, `DS-800.claim_count_total`은 `377 -> 310`, `unknown_count_total`은 `211 -> 177`, `anchor_filtered_slot_counts.affiliation`은 `3780 -> 3059`로 감소했다.
  - 다만 `unknown_rate`는 `0.5597 -> 0.5710`으로 거의 개선되지 않았고, `consistency_p95_ms`도 `2569.78 -> 2568.30`으로 절대 gate 아래로 내려오지 못했다.
  - 따라서 다음 실질 과제는 generic claim volume 추가 축소가 아니라, 남아 있는 `affiliation` claim에서 `NO_EVIDENCE`/`CONFLICTING_EVIDENCE`를 더 직접 줄이는 corroboration quality 보강이다.

## 12) 2026-03-12 follow-up
- `WS4` corroboration / anchor-filter 보강
  - `modules/nf_consistency/extractors/rule_extractor.py`
    - `그녀는 라인시스의 제1황녀였다.` 같은 축약형 title phrase에서도 opt-in affiliation extraction이 가능하도록 affiliation rule의 주어 prefix 처리 범위를 정리했다.
  - `modules/nf_consistency/extractors/pipeline.py`
    - snippet corroboration / schema extraction opt-in 경로에서 `...의 제1황녀`류 title phrase는 affiliation suffix(`제국/연맹/...`)가 직접 없어도 keep할 수 있도록 sanitize guard를 완화했다.
  - `modules/nf_consistency/engine.py`
    - retrieval anchor filter에 snippet-side slot re-extraction rescue를 추가했다.
    - claim anchor 표면형이 snippet에 직접 없더라도, opt-in snippet extraction 결과가 slot compare상 `OK`면 retrieval hit를 유지한다.
    - affiliation slot compare에서 `라인시스 제국` vs `라인시스`처럼 조직 suffix를 포함한 value와 title-head 축약 value를 `OK`로 읽을 수 있는 head-token guard를 추가했다.
  - 관련 회귀:
    - `tests/test_nf_consistency_extractors.py`
      - `test_extraction_pipeline_keeps_non_suffix_affiliation_title_phrase_when_profile_opted_in`
    - `tests/test_nf_schema_extraction.py`
      - `test_extract_explicit_candidates_accepts_narrative_affiliation_title_phrase_without_suffix_entity`
    - `tests/consistency/test_engine_quality_core.py`
      - `test_filter_results_without_slot_anchor_keeps_extractable_title_affiliation_hit`
      - `test_compare_slot_allows_affiliation_prefix_entity_match`
    - `tests/test_nf_consistency_engine.py`
      - `test_consistency_engine_accepts_title_affiliation_corroboration_without_full_anchor_match`
  - 검증:
    - `pytest -q tests/test_nf_consistency_extractors.py tests/test_nf_schema_extraction.py tests/consistency/test_engine_quality_core.py tests/test_nf_consistency_engine.py`
    - `pytest -q tests/test_tools_bench_run_pipeline_bench.py tests/test_nf_workers_consistency_payload.py`
    - 결과: 통과
  - 해석:
    - 이번 보강은 `affiliation` anchor-filter loss를 줄이는 쪽의 WS4 세부 과제다.
    - 아직 fresh operational rerun은 없으므로 판정은 `검증 완료(운영 미반영)`으로 읽어야 한다.
- `WS7-J5` strict artifact auto-discovery 재현성 보강
  - `tools/bench/run_dev_judged_dataset_pipeline.py`
    - strict artifact auto discovery가 단순 latest file이 아니라 `layer3_effective_capable_jobs > 0`인 strict control/inject artifact를 우선 고르도록 조정했다.
  - 관련 회귀:
    - `tests/test_tools_bench_run_dev_judged_dataset_pipeline.py`
      - `test_resolve_strict_artifacts_prefers_layer3_capable_strict_artifacts`
      - `test_run_dev_judged_dataset_pipeline_auto_discovery_prefers_layer3_capable_strict_artifacts`
  - current bench dir 재실행:
    - run root: `C:\Users\USER\AppData\Local\Temp\nf_judge_review_postj5_20260312T010901\20260311T160901Z`
    - `report.md`
      - `artifact_resolution.artifacts.control_artifact = verify/benchmarks/20260309T080639Z.json`
      - `artifact_resolution.artifacts.inject_artifact = verify/benchmarks/20260309T080952Z.json`
      - `strict_layer3_gate.status = PASS`
  - 해석:
    - 기존 latest strict artifact auto discovery가 non-layer3 rerun에 끌려 `SKIPPED`로 퇴행하던 문제는 재현성 있게 해소됐다.
- `WS7-J3` typed inject judged variant 정리
  - `tools/bench/run_dev_judged_dataset_pipeline.py`
    - typed variant builder가 원문에서 target slot을 전혀 grounding하지 못한 row(`typed_original_value is None`)는 judged variant에서 제외하고 `skipped_reason_counts`로만 남기도록 조정했다.
  - 관련 회귀:
    - `tests/test_tools_bench_run_dev_judged_dataset_pipeline.py`
      - `test_build_typed_inject_variants_skips_rows_without_grounded_original_slot`
  - current bench dir 재실행:
    - run root: `C:\Users\USER\AppData\Local\Temp\nf_judge_review_postj4_20260312T011513\20260311T161513Z`
    - `report.md`
      - `typed_inject_disagreement.rows_total = 26`
      - `typed_inject_disagreement.clear_conflict_rows = 16`
      - `typed_inject_disagreement.disagreement_rows = 10`
  - 해석:
    - pre-fix shadow run의 `rows_total = 403`, `clear_conflict_rows = 16` 대비, missing-original-slot 잡음을 대량으로 제거해 typed variant의 usable density를 높였다.
    - 남은 disagreement는 주로 `affiliation`의 `typed_slot_uncomparable` / `typed_variant_subject_not_grounded`로 좁혀졌다.
- `WS7-J4` source policy shadow apply 실적용 보강
  - `tools/bench/run_dev_judged_dataset_pipeline.py`
    - source policy shadow apply validation의 `candidate_count_exists`를 accepted family 전부가 아니라 family 중 하나라도 실제 candidate count가 있으면 통과하는 의미로 완화했다.
    - `judge_confidence_below_threshold`로 manual review에 머무는 row 중, `profile_auto` + dominant pattern share가 높은 source는 run-scoped shadow apply에 한해 single-pattern fallback(`dominant_pattern_fallback`)을 허용하도록 추가했다.
  - 관련 회귀:
    - `tests/test_tools_bench_run_dev_judged_dataset_pipeline.py`
      - `test_build_source_policy_shadow_apply_accepts_family_when_any_member_is_present`
      - `test_build_source_policy_shadow_apply_uses_dominant_pattern_fallback_for_low_confidence_manual_review`
  - current bench dir 재실행:
    - run root: `C:\Users\USER\AppData\Local\Temp\nf_judge_review_postj4_20260312T011513\20260311T161513Z`
    - `report.md`
      - `source_policy.judged_rows = 11`
      - `source_policy_shadow_apply.applied_rows = 5`
      - `source_policy_shadow_apply.validation_failed_rows = 6`
    - `derived_datasets/source_policy_applied/summary.json`
      - applied:
        - `SRC-19654228e388 -> numbered_title`
        - `SRC-f59649dcf0b9 -> numbered_title`
        - `SRC-17e07a6f5628 -> standalone_number`
        - `SRC-8afdc504e100 -> numbered_title`
        - `SRC-8c0996765ece -> angle_title_paren`
      - skipped:
        - `SRC-a79bc34f05e9`: `oversized_share = 0.2424`
        - `SRC-067bb5c747ae`: `oversized_share = 0.7111`
        - `SRC-7acbd790b5b5`, `SRC-4986913f40bd`, `SRC-fc9e73604cbf`, `SRC-704104cbe43c`: accepted family 부재 또는 split quality 미달
  - 해석:
    - `WS7-J4`는 더 이상 validation-only 골격이 아니라 current corpus 기준 run-scoped apply 실적용이 나오는 상태로 올라왔다.
    - 다만 canonical dataset에는 반영하지 않았고, 계속 developer-only shadow apply로만 유지한다.
- 통합 검증:
  - `pytest -q tests/test_tools_bench_judge_audit.py tests/test_tools_bench_run_dev_judged_dataset_pipeline.py tests/test_tools_bench_strict_gate.py`
  - `pytest -q tests/test_nf_consistency_extractors.py tests/test_nf_schema_extraction.py tests/consistency/test_engine_quality_core.py tests/test_nf_consistency_engine.py tests/test_tools_bench_run_pipeline_bench.py tests/test_nf_workers_consistency_payload.py`
  - 결과:
    - `31 passed`
    - `131 passed`
- 현재 해석:
  - `WS7-J5` auto discovery는 current bench dir 기준으로도 재현 가능해졌다.
  - `WS7-J4`는 first apply 사례를 확보했고, `applied_rows = 5`로 `0` 상태를 벗어났다.
  - `WS7-J3`는 noisy typed rows를 줄여 disagreement set이 더 해석 가능해졌다.
  - 다음 실질 과제는 1) typed inject의 남은 `affiliation` uncomparable/ambiguous subject 비중 추가 축소, 2) actual local/remote model availability가 있는 환경에서 non-heuristic judge backend 재검증, 3) WS4 fresh operational rerun으로 corroboration 개선이 실제 mainline unknown/actionability에 미치는 영향 확인이다.

### 12A) 2026-03-12 operational rerun
- fresh isolated operational rerun:
  - isolated stack: `http://127.0.0.1:8099`
  - `verify/benchmarks/20260311T162910Z.json`
    - `operational-main:DS-200`
    - `claim_count_total = 196`
    - `unknown_count_total = 91`
    - `unknown_rate = 0.4643`
    - `pipeline_consistency_p95_ms = 1572.19`
    - `anchor_filtered_slot_counts = {affiliation: 1895, relation: 19}`
  - `verify/benchmarks/20260311T163914Z.json`
    - `operational-main:DS-400`
    - `claim_count_total = 285`
    - `unknown_count_total = 133`
    - `unknown_rate = 0.4667`
    - `pipeline_consistency_p95_ms = 2073.22`
    - `anchor_filtered_slot_counts = {affiliation: 2868, relation: 12, job: 23}`
  - `verify/benchmarks/20260311T165643Z.json`
    - `operational-main:DS-800`
    - `claim_count_total = 332`
    - `unknown_count_total = 187`
    - `unknown_rate = 0.5633`
    - `violate_count_total = 144`
    - `pipeline_consistency_p95_ms = 2087.76`
    - `slot_diagnostics_schema_status = COMPLETE`
    - `anchor_filtered_slot_counts = {affiliation: 3373, relation: 36, job: 36}`
- latest summary / gate 재생성:
  - `python tools/bench/summarize_latest_metrics.py --datasets DS-200,DS-400,DS-800 --label-mode operational`
  - `verify/benchmarks/latest_metrics_summary.json`
    - `DS-200.latest_successful_file = 20260311T162910Z.json`
    - `DS-400.latest_successful_file = 20260311T163914Z.json`
    - `DS-800.latest_successful_file = 20260311T165643Z.json`
    - `overall_status = WARN`
    - `absolute_goal_status = PASS`
  - `python tools/bench/render_gate_report.py --pipeline verify/benchmarks/20260311T165643Z.json --latest-summary verify/benchmarks/latest_metrics_summary.json --output verify/benchmarks/gate_report_ws4_closeout_rerun_20260312.md`
  - `verify/benchmarks/gate_report_ws4_closeout_rerun_20260312.md`
    - `pipeline_goal_achieved = PASS`
    - `pipeline_consistency_p95_ms = 2087.76`
    - `pipeline_unknown_rate = 0.5633`
- 해석:
  - `WS4` 보강 이후 fresh operational rerun에서 `DS-800.claim_count_total`은 `310 -> 332`로 증가했고, `unknown_rate`는 `0.5710 -> 0.5633`으로 소폭 개선됐다.
  - 가장 큰 변화는 latency다. `DS-800.pipeline_consistency_p95_ms`가 `2568.30 -> 2087.76`으로 내려오면서 absolute gate 아래로 들어왔다.
  - `DS-400`도 `unknown_count_total = 134 -> 133`, `unknown_rate = 0.4702 -> 0.4667`로 소폭 개선됐다.
  - 다만 `anchor_filtered_slot_counts.affiliation = 3373`가 여전히 크므로, WS4의 남은 미세 과제는 계속 `affiliation` corroboration/anchor-filter 품질 쪽이다.
  - current code 기준으로는 `gate_report_ws4_closeout_rerun_20260312.md`에서 operational closeout gate가 `PASS`로 재생성됐다.

### 12B) 2026-03-12 judge backend availability diagnostics
- `tools/bench/run_dev_judged_dataset_pipeline.py`
  - developer-only judged run manifest에 `judge_backend_availability`를 추가했다.
  - 필드:
    - `requested_backend`
    - `local_test_judge_enabled`
    - `local_model_id`
    - `local_model_present`
    - `local_model_path`
    - `remote_test_judge_enabled`
    - `remote_provider`
    - `remote_model_id`
    - `remote_credentials_configured`
    - `expected_execution_mode`
- `tools/bench/render_dev_judge_report.py`
  - `## Backend Availability` 섹션을 추가해 current environment가 왜 heuristic-only인지 report에서 직접 보이게 했다.
- 관련 회귀:
  - `tests/test_tools_bench_run_dev_judged_dataset_pipeline.py`
    - run-scoped manifest에 `judge_backend_availability`가 들어가고, `report.md`에 backend section이 렌더되는지 고정했다.
  - `pytest -q tests/test_tools_bench_run_dev_judged_dataset_pipeline.py tests/test_tools_bench_judge_audit.py tests/test_tools_bench_strict_gate.py`
  - 결과: `33 passed`
- current judged run:
  - run root: `C:\Users\USER\AppData\Local\Temp\nf_judge_review_backenddiag_20260312T015959\20260311T165959Z`
  - `judge_run_manifest.json`
    - `requested_backend = local_nli`
    - `local_model_present = false`
    - `remote_test_judge_enabled = false`
    - `remote_credentials_configured = false`
    - `expected_execution_mode = heuristic_only_local_model_missing`
  - `report.md`
    - same backend availability section이 그대로 노출된다
- 해석:
  - current environment에서 non-heuristic judge backend 검증이 왜 막히는지(로컬 judge model 부재 / remote credential 부재)를 artifact만 읽어도 판독 가능해졌다.
  - 즉 다음 TODO는 “왜 heuristic이었는지 조사”가 아니라, 실제 `data/models/nli-lite-v1` 배치 또는 remote credential 제공 후 rerun하는 것이다.

### 12C) 2026-03-12 judge backend override / fail-fast policy
- `tools/bench/run_dev_judged_dataset_pipeline.py`
  - developer-only CLI override를 추가했다.
    - `--judge-backend {config,disabled,local_nli,remote_api}`
    - `--judge-local-model-id`
    - `--require-real-judge-backend`
  - 구현:
    - process-scoped env override로 judge backend를 강제할 수 있다.
    - `--require-real-judge-backend`가 켜진 상태에서 `expected_execution_mode`가 `local_model_ready` / `remote_api_ready`가 아니면 baseline build 이전에 fail-fast 한다.
    - manifest에 `judge_backend_overrides`가 함께 남는다.
- 관련 회귀:
  - `tests/test_tools_bench_run_dev_judged_dataset_pipeline.py`
    - `test_run_dev_judged_dataset_pipeline_fails_fast_when_real_backend_is_required_but_unavailable`
    - `test_run_dev_judged_dataset_pipeline_persists_disabled_backend_override_in_manifest`
  - `pytest -q tests/test_tools_bench_run_dev_judged_dataset_pipeline.py tests/test_tools_bench_judge_audit.py tests/test_tools_bench_strict_gate.py`
  - 결과: `35 passed`
- current environment check:
  - command:
    - `python tools/bench/run_dev_judged_dataset_pipeline.py --developer-mode --input-dir test_files --baseline-snapshot-dir verify/datasets --output-root <temp> --judge-backend local_nli --require-real-judge-backend`
  - result:
    - `real judge backend is required but unavailable: expected_execution_mode=heuristic_only_local_model_missing`
- 해석:
  - 이제 developer-only judged pipeline은 “실수로 heuristic fallback으로 돌려 놓고 real backend 실증으로 오인”하는 경로를 CLI 수준에서 차단할 수 있다.
  - non-heuristic judge 재검증은 코드 준비가 아니라 environment 준비 문제로 분리됐다.

### 12D) 2026-03-12 canonical dataset r7 + final manual-review source closeout
- `tools/bench/build_novel_dataset.py`
  - 새 header family를 추가했다.
    - `prologue_header`
    - `chapter_jang`
  - 지원 예:
    - `프롤로그`
    - `제1장 무당파의 노인`
    - `제2장 강호초출`
  - `chapter_jang` / `prologue_header`를 high-confidence episode family로 편입했다.
  - `dataset_generation_version`를 `20260312-r7`로 올렸다.
- `tools/bench/source_policy_registry.json`
  - `SRC-2e0ba0a8ee12` registry override를 `manual_review`에서 `source_override_pattern`으로 승격했다.
  - `allowed_patterns = ["prologue_header", "chapter_jang"]`
  - `reason = validated_source_specific_pattern_override`
- 관련 회귀:
  - `tests/test_tools_bench_build_novel_dataset.py`
    - `test_split_episodes_supports_prologue_and_chapter_jang_headers`
    - 기존 version assertions를 `20260312-r7`로 갱신
  - `tests/test_tools_bench_metrics_summary_corroboration.py`
  - `tests/test_tools_bench_render_gate_report.py`
  - `tests/test_tools_bench_run_pipeline_bench.py`
  - `pytest -q tests/test_tools_bench_build_novel_dataset.py tests/test_tools_bench_metrics_summary_corroboration.py tests/test_tools_bench_render_gate_report.py tests/test_tools_bench_run_pipeline_bench.py tests/test_tools_bench_run_dev_judged_dataset_pipeline.py tests/test_tools_bench_judge_audit.py tests/test_tools_bench_strict_gate.py`
  - 결과: `92 passed`
- canonical dataset 재생성:
  - `python tools/bench/build_novel_dataset.py --input-dir test_files --output-dir verify/datasets --inject-sample-size 200 --seed 42 --diversity-profile max`
  - `verify/datasets/dataset_manifest.json`
    - `dataset_generation_version = 20260312-r7`
    - `fallback_files = 0`
    - `fallback_episode_share = 0.0`
    - `manual_review_source_count = 0`
    - `manual_review_reason_counts = {}`
  - `verify/datasets/manual_review_sources.json`
    - `[]`
  - `verify/datasets/dataset_manifest.json`
    - `SRC-2e0ba0a8ee12`
      - `source_segmentation_policy = source_override_pattern`
      - `selected_pattern_family = ["prologue_header", "chapter_jang"]`
      - `split_strategy = header_boundary`
      - `fallback_used = false`
      - `episodes = 52`
- 해석:
  - canonical dataset 기준으로 남아 있던 마지막 manual-review/fallback source가 해소됐다.
  - `WS7`의 dataset/source governance 축은 current corpus 기준 사실상 closeout 수준까지 올라왔다.
  - 다만 latest operational benchmark artifacts는 `20260308-r6` 세대에서 생성된 것이므로, future operational rerun부터 `20260312-r7`이 반영된다.

### 12E) 2026-03-12 WS4 perf hardening + r7 DS-800 rerun
- `modules/nf_consistency/engine.py`
  - snippet corroboration / retrieval anchor rescue가 같은 snippet을 claim마다 다시 추출하지 않도록 request-scoped snippet slot cache를 추가했다.
  - retrieval anchor rescue를 `affiliation` slot으로 제한했다. 이번 WS4 보강의 기능적 목적이 affiliation title/head corroboration이었고, relation/job/talent까지 동일 rescue를 태우는 것은 p95 비용만 키우는 경로로 정리했다.
  - 새 telemetry:
    - `snippet_slot_cache_hit_count`
    - `snippet_slot_cache_miss_count`
    - `anchor_rescue_attempt_count`
    - `anchor_rescue_ok_count`
    - `snippet_corroborated_count`
- `modules/nf_workers/runner.py`
  - 위 telemetry를 consistency complete payload에 포함했다.
- `tools/bench/run_pipeline_bench.py`
  - consistency runtime aggregate/finalize에 새 telemetry를 연결했다.
  - 파생 지표:
    - `snippet_slot_cache_hit_rate`
    - `anchor_rescue_ok_rate`
- 관련 회귀:
  - `tests/consistency/test_engine_quality_core.py`
    - `test_filter_results_without_slot_anchor_limits_rescue_to_affiliation`
    - `test_filter_results_without_slot_anchor_reuses_snippet_slot_cache`
  - `tests/test_nf_workers_consistency_payload.py`
  - `tests/test_tools_bench_run_pipeline_bench.py`
  - `pytest -q tests/test_nf_consistency_extractors.py tests/test_nf_schema_extraction.py tests/consistency/test_engine_quality_core.py tests/test_nf_consistency_engine.py tests/test_tools_bench_run_pipeline_bench.py tests/test_nf_workers_consistency_payload.py tests/test_tools_bench_build_novel_dataset.py tests/test_tools_bench_run_dev_judged_dataset_pipeline.py tests/test_tools_bench_judge_audit.py tests/test_tools_bench_strict_gate.py tests/test_tools_bench_render_gate_report.py tests/test_tools_bench_metrics_summary_corroboration.py`
  - 결과: `206 passed`
- fresh isolated operational rerun:
  - isolated stack: `http://127.0.0.1:8099`
  - command:
    - `python tools/bench/run_pipeline_bench.py --base-url http://127.0.0.1:8099 --dataset verify/datasets/DS-GROWTH-800.jsonl --bench-label operational-main:DS-800 --limit-docs 800 --consistency-samples 100 --profile throughput --consistency-level quick --output-dir verify/benchmarks`
  - `verify/benchmarks/20260312T113139Z.json`
    - `dataset_generation_version = 20260312-r7`
    - `manual_review_source_count = 0`
    - `claim_count_total = 313`
    - `unknown_count_total = 181`
    - `unknown_rate = 0.5783`
    - `pipeline_consistency_p95_ms = 2076.63`
    - `retrieval_anchor_filtered_count = 3116`
    - `anchor_filtered_slot_counts = {affiliation: 3036, job: 46, relation: 34}`
    - `snippet_slot_cache_hit_count = 274`
    - `snippet_slot_cache_miss_count = 2839`
    - `snippet_slot_cache_hit_rate = 0.0880`
    - `anchor_rescue_attempt_count = 3041`
    - `anchor_rescue_ok_count = 5`
    - `anchor_rescue_ok_rate = 0.00164`
    - `snippet_corroborated_count = 0`
  - `python tools/bench/render_gate_report.py --pipeline verify/benchmarks/20260312T113139Z.json --latest-summary verify/benchmarks/latest_metrics_summary.json --output verify/benchmarks/gate_report_ws4_perf_followup_20260312.md`
  - `verify/benchmarks/gate_report_ws4_perf_followup_20260312.md`
    - `pipeline_goal_achieved = PASS`
    - `pipeline_consistency_p95_ms = 2076.63`
- 해석:
  - r7 기준 DS-800 p95가 `2608.26 -> 2076.63`으로 내려오며 absolute gate 아래로 복구됐다.
  - claim volume/unknown volume은 `20260311T174108Z.json`과 사실상 동일하므로, 이번 조치는 precision/recall을 흔들지 않고 hot path 비용만 줄인 성격으로 읽는 것이 맞다.
  - telemetry상 request-scoped snippet cache는 실제로 hit를 만들었고(`274`), anchor rescue 성공은 `5`건에 불과했다. 즉 기존 full-slot rescue 경로는 운영 p95 대비 효익이 매우 낮았고, affiliation-only 축소가 타당했다.
  - 다만 `latest_metrics_summary.json`은 `label-mode operational`에서 `preferred_artifact_cohort = operational_closeout`를 우선하므로, 이번 perf validation artifact는 `latest_attempt_*`로만 보이고 `latest_successful_*` 승격은 보류된다. summary/latest chain을 완전히 교체하려면 동일 설정으로 `--artifact-cohort operational_closeout` rerun이 추가로 필요하다.

### 12F) 2026-03-12 WS7 typed inject phrase-conflict hardening
- `tools/bench/judge_audit.py`
  - typed inject audit에서 `affiliation` / `job` slot이 모두 추출되었지만 `_compare_slot()`이 `None`으로 남는 케이스에 대해 disjoint phrase conflict heuristic을 추가했다.
  - 의도:
    - `정무전 제삼대` vs `황실 기사단`
    - `이르멜가의 정원사` vs `9서클 마법사`
    같은 다단어 명사구 충돌을 `typed_slot_uncomparable`로 남기지 않고 `clear_conflict`로 승격한다.
- 관련 회귀:
  - `tests/test_tools_bench_judge_audit.py`
    - `test_typed_inject_quality_judge_marks_non_suffix_affiliation_phrase_conflict_as_clear_conflict`
    - `test_typed_inject_quality_judge_marks_job_phrase_conflict_as_clear_conflict`
- developer-only judged rerun:
  - command:
    - `python tools/bench/run_dev_judged_dataset_pipeline.py --developer-mode --input-dir test_files --baseline-snapshot-dir verify/datasets --output-root verify/judge_runs --run-id codex-ws7-postfix-r1 --strict-artifact-dir verify/benchmarks`
  - `verify/judge_runs/codex-ws7-postfix-r1/report.md`
    - `source_policy_shadow_apply.applied_rows = 5`
    - `strict_layer3_gate.status = PASS`
    - `typed_inject_disagreement.rows_total = 35`
    - `typed_inject_disagreement.clear_conflict_rows = 33`
    - `typed_inject_disagreement.disagreement_rows = 2`
    - `typed_inject_disagreement.usable_for_strict_rows = 33`
    - `typed_inject_disagreement.usable_for_layer3_audit_rows = 35`
- 해석:
  - 남아 있던 `affiliation` / `job` uncomparable disagreement 2건이 `clear_conflict`로 정리됐다.
  - 현재 disagreement는 `death=true`가 이미 원문과 동일한 `no_conflict` 2건만 남는다. 즉 WS7-J3의 남은 과제는 subject ambiguity가 아니라 “동일 truth-value typed row를 disagreement 집합에 계속 남길 것인지”에 대한 report semantics 결정 쪽으로 좁혀졌다.
  - backend availability는 여전히 `heuristic_only_local_model_missing` 상태이므로, real backend 검증 과제 자체는 unchanged다.

### 12G) 2026-03-12 operational closeout cohort rerun
- 배경:
  - `20260312T113139Z.json` perf validation run은 gate 자체는 `PASS`였지만 `artifact_cohort = ""`라서 `summarize_latest_metrics.py --label-mode operational`의 preferred cohort(`operational_closeout`)에 의해 `latest_attempt_*`로만 집계됐다.
  - 따라서 latest chain / gate closeout을 현재 코드 기준으로 교체하려면 동일 설정으로 `artifact_cohort = operational_closeout` rerun이 추가로 필요했다.
- fresh isolated operational closeout rerun:
  - isolated stack: `http://127.0.0.1:8099`
  - commands:
    - `python tools/bench/run_pipeline_bench.py --base-url http://127.0.0.1:8099 --dataset verify/datasets/DS-GROWTH-200.jsonl --bench-label operational-main:DS-200 --limit-docs 200 --consistency-samples 100 --profile throughput --consistency-level quick --artifact-cohort operational_closeout --output-dir verify/benchmarks`
    - `python tools/bench/run_pipeline_bench.py --base-url http://127.0.0.1:8099 --dataset verify/datasets/DS-GROWTH-400.jsonl --bench-label operational-main:DS-400 --limit-docs 400 --consistency-samples 100 --profile throughput --consistency-level quick --artifact-cohort operational_closeout --output-dir verify/benchmarks`
    - `python tools/bench/run_pipeline_bench.py --base-url http://127.0.0.1:8099 --dataset verify/datasets/DS-GROWTH-800.jsonl --bench-label operational-main:DS-800 --limit-docs 800 --consistency-samples 100 --profile throughput --consistency-level quick --artifact-cohort operational_closeout --output-dir verify/benchmarks`
  - artifacts:
    - `verify/benchmarks/20260312T114401Z.json`
      - `operational-main:DS-200`
      - `artifact_cohort = operational_closeout`
      - `dataset_generation_version = 20260312-r7`
      - `pipeline_consistency_p95_ms = 1552.71`
      - `unknown_rate = 0.3182`
    - `verify/benchmarks/20260312T115351Z.json`
      - `operational-main:DS-400`
      - `artifact_cohort = operational_closeout`
      - `dataset_generation_version = 20260312-r7`
      - `pipeline_consistency_p95_ms = 1608.03`
      - `unknown_rate = 0.4338`
    - `verify/benchmarks/20260312T121119Z.json`
      - `operational-main:DS-800`
      - `artifact_cohort = operational_closeout`
      - `dataset_generation_version = 20260312-r7`
      - `pipeline_consistency_p95_ms = 2096.86`
      - `unknown_rate = 0.5783`
      - `snippet_slot_cache_hit_count = 274`
      - `anchor_rescue_attempt_count = 3041`
      - `anchor_rescue_ok_count = 5`
- latest summary / gate 재생성:
  - `python tools/bench/summarize_latest_metrics.py --datasets DS-200,DS-400,DS-800 --label-mode operational`
  - `verify/benchmarks/latest_metrics_summary.json`
    - `DS-200.latest_successful_file = 20260312T114401Z.json`
    - `DS-400.latest_successful_file = 20260312T115351Z.json`
    - `DS-800.latest_successful_file = 20260312T121119Z.json`
    - `overall_status = PASS`
    - `absolute_goal_status = PASS`
  - `python tools/bench/render_gate_report.py --pipeline verify/benchmarks/20260312T121119Z.json --latest-summary verify/benchmarks/latest_metrics_summary.json --output verify/benchmarks/gate_report_ws4_closeout_rerun_20260312_r7_closeout.md`
  - `verify/benchmarks/gate_report_ws4_closeout_rerun_20260312_r7_closeout.md`
    - `pipeline_goal_achieved = PASS`
    - `pipeline_latest_successful_file = 20260312T121119Z.json`
    - `pipeline_consistency_p95_ms = 2096.86`
- 해석:
  - `WS4`는 current code + canonical `r7` dataset + preferred closeout cohort 기준으로도 다시 `PASS`로 닫혔다.
  - 이제 latest summary / final gate / closeout artifact chain이 모두 같은 세대를 가리킨다.
  - current code 기준 남은 실질 blocker는 운영 perf가 아니라 1) real judge backend 환경 준비, 2) typed inject disagreement 집합의 `no_conflict` semantics 정리 두 가지다.

### 12H) 2026-03-12 typed disagreement semantics closeout
- `tools/bench/run_dev_judged_dataset_pipeline.py`
  - strict/layer3 audit summary에서 `typed_inject_disagreement` 집합 정의를 조정했다.
  - 새 의미:
    - `clear_conflict_rows`: typed strict 후보로 바로 쓸 수 있는 충돌 row
    - `no_conflict_rows`: 원문과 동일 truth-value라 disagreement가 아닌 agreement/reference row
    - `disagreement_rows`: `clear_conflict`도 `no_conflict`도 아닌 residual row만 집계
  - 따라서 `no_conflict` typed rows는 더 이상 disagreement 집합과 sample을 오염시키지 않는다.
- 관련 회귀:
  - `tests/test_tools_bench_run_dev_judged_dataset_pipeline.py`
    - `test_build_strict_layer3_audit_excludes_no_conflict_rows_from_disagreement`
  - `pytest -q tests/test_tools_bench_run_dev_judged_dataset_pipeline.py tests/test_tools_bench_judge_audit.py`
  - 결과: `31 passed`
- developer-only judged rerun:
  - command:
    - `python tools/bench/run_dev_judged_dataset_pipeline.py --developer-mode --input-dir test_files --baseline-snapshot-dir verify/datasets --output-root verify/judge_runs --run-id codex-ws7-postfix-r2 --strict-artifact-dir verify/benchmarks`
  - `verify/judge_runs/codex-ws7-postfix-r2/report.md`
    - `source_policy_shadow_apply.applied_rows = 5`
    - `strict_layer3_gate.status = PASS`
    - `typed_inject_disagreement.rows_total = 35`
    - `typed_inject_disagreement.clear_conflict_rows = 33`
    - `typed_inject_disagreement.no_conflict_rows = 2`
    - `typed_inject_disagreement.disagreement_rows = 0`
    - `typed_inject_disagreement.disagreement_samples = []`
- 해석:
  - `WS7-J3`의 residual ambiguity는 current heuristic path 기준 사실상 정리됐다.
  - 남은 `no_conflict` 2건은 disagreement가 아니라 “typed variant가 원문 truth-value를 그대로 유지한 reference row”로 해석하면 된다.
  - 이 시점부터 current code 기준 남은 실질 blocker는 `real judge backend` 환경 준비 하나로 축소된다.

### 12I) 2026-03-12 real local judge backend activation + rerun
- `modules/nf_model_gateway/local/model_store.py`
  - local model directory 존재 여부만 보지 않고 manifest/backend/runtime readiness를 함께 판정하도록 보강했다.
  - 노출 필드:
    - `manifest_backend`
    - `runtime_ready`
    - `reason`
- `modules/nf_model_gateway/local/text_pair_classifier.py`
  - heuristic scorer fallback 위에 Hugging Face sequence-classification 기반 real local NLI inference 경로를 추가했다.
  - model dir에 `nf_model_manifest.json` + `config.json` + weights + tokenizer asset이 모두 있으면 `effective_backend = local_nli_model`로 동작한다.
  - runtime failure 시에만 heuristic fallback으로 되돌아간다.
- `tools/bench/run_dev_judged_dataset_pipeline.py`
  - backend availability 진단에 아래 필드를 추가했다.
    - `local_model_runtime_ready`
    - `local_model_manifest_backend`
    - `local_model_status_reason`
  - local model dir이 있지만 runtime-ready가 아니면 `expected_execution_mode = heuristic_only_local_model_unusable`로 분리한다.
- `tools/bench/render_dev_judge_report.py`
  - backend availability 섹션에 runtime-ready / manifest backend / status reason을 함께 렌더한다.
- 새 설치 스크립트:
  - `tools/bench/install_local_nli_model.py`
  - 기본 pinned source:
    - repo: `MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli`
    - revision: `acf08db83390e23428c560cb578a865b39196993`
  - 설치 위치:
    - `data/models/nli-lite-v1/`
  - 생성 manifest:
    - `data/models/nli-lite-v1/nf_model_manifest.json`
- 관련 회귀:
  - `tests/test_nf_model_gateway_selection.py`
    - real local backend path / model manifest readiness 회귀 추가
  - `tests/test_tools_bench_run_dev_judged_dataset_pipeline.py`
    - present-but-unusable local model availability 분기 회귀 추가
  - `pytest -q tests/test_nf_model_gateway_selection.py tests/test_tools_bench_run_dev_judged_dataset_pipeline.py tests/test_tools_bench_judge_audit.py tests/test_tools_bench_run_one_shot_validation.py tests/test_tools_bench_run_pipeline_bench.py tests/test_nf_workers_consistency_payload.py tests/consistency/test_engine_quality_core.py`
  - 결과: `98 passed`
- real backend 설치/검증:
  - install:
    - `python tools/bench/install_local_nli_model.py`
  - spot check:
    - `infer_nli_distribution(..., enabled=True, model_id="nli-lite-v1")`
    - `effective_backend = local_nli_model`
    - `fallback_used = false`
  - availability:
    - `_judge_backend_availability()`
    - `expected_execution_mode = local_model_ready`
    - `local_model_runtime_ready = true`
- developer-only judged rerun:
  - command:
    - `python tools/bench/run_dev_judged_dataset_pipeline.py --developer-mode --input-dir test_files --baseline-snapshot-dir verify/datasets --output-root verify/judge_runs --run-id codex-ws7-real-backend-r1 --strict-artifact-dir verify/benchmarks --judge-backend local_nli --require-real-judge-backend`
  - `verify/judge_runs/codex-ws7-real-backend-r1/report.md`
    - `requested_backend = local_nli`
    - `expected_execution_mode = local_model_ready`
    - `local_model_runtime_ready = True`
    - `effective_backend_counts = {local_nli_model: 11}` (source policy)
    - `effective_backend_counts = {local_nli_model: 498}` (inject quality)
    - `strict_layer3_gate.status = PASS`
    - `typed_inject_disagreement.disagreement_rows = 0`
- 해석:
  - `WS7` developer-only judged path는 더 이상 heuristic-only 환경에 묶여 있지 않고, current workspace 기준 real local backend로 실제 실행 가능해졌다.
  - `--require-real-judge-backend` guarded rerun이 통과했으므로, follow-up 문서 기준 마지막 blocker였던 “real judge backend 환경 준비”는 현재 환경에서 해소됐다.
  - 남는 후속은 blocker가 아니라 선택 과제다. 예를 들면 remote API backend까지 별도 실증할지, 혹은 local judge model 교체/재학습으로 품질을 더 올릴지 여부다.
