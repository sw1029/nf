# Integrated Review: `test_files` Dataset, Consistency Engine, Bench Quality (2026-03-07)

기준일: 2026-03-07

검토 범위:
- `tools/bench/build_novel_dataset.py`
- `modules/nf_consistency/*`
- `modules/nf_workers/runner.py`
- `tools/bench/summarize_latest_metrics.py`
- `tools/bench/check_consistency_strict_gate.py`
- `verify/benchmarks/*`
- `verify/datasets/*`
- `plan/consistency_benchmark_followup_2026-03-07.md`

## Update After Implementation

2026-03-07 추가 보완 반영 결과:
- `tools/bench/build_novel_dataset.py`
  - common novel header 탐지(`1화`, `0화 프롤로그`, `001. ...`, `1. ...`, `<1화>`, `작품명 1화`, `< 챕터 제목(1) >`, `EP.0 ...`, `【1. ...】`, `제1조. ...`, `작품명 (1)`) 추가
  - content SHA-256 provenance, `segmentation_summary`, `quality_warnings`, `sampling_strategy`, `source_order`, `candidate_boundary_counts`, `fallback_source_files`, boundary/content length 진단 필드 추가
  - inject record에 `inject_subject_text`, `inject_expected_signal` 추가
  - composite dataset policy를 `exclude_fallback_sources_unless_empty`로 전환하고, `DS-GROWTH-*`를 deterministic shuffled prefix로 재구성
  - `source-01`에 source-specific `standalone_number` override 적용
  - file-name keyed exception 대신 `source_policy_registry.json` + `source_id` 중심 구조로 전환
  - `source_segmentation_policy`로 auto / source_override_pattern / manual_review를 구분
  - `dataset_generation_version = 20260307-r5` 추가
  - structured inject subset(`DS-INJECT-C-STRUCTURED`, `DS-DIVERSE-INJECT-C-STRUCTURED`) 추가
- `tools/bench/summarize_latest_metrics.py`
  - dataset row에 `latest_successful_*`, `latest_attempt_*`, `latest_attempt_status`, `latest_attempt_succeeded` 추가
- `tools/bench/check_consistency_strict_gate.py`
  - `strict_core_gate` / `strict_layer3_gate` 분리
- `tools/bench/run_pipeline_bench.py`
  - future bench artifact에 `semantic.dataset_profile` 추가
  - source segmentation / inject strategy / growth prefix bias metadata가 future artifact에 보존되도록 보강
- `tools/bench/http_client.py` / `tools/bench/run_pipeline_bench.py`
  - transport/front-door 실패 시 structured `failure_*.json/.md` artifact를 남기도록 보강
  - GET 및 safe POST(`/projects`, `/query/retrieval`)에 transient retry 추가
  - `request_body_shape`, `retry_count`, `retryable`, `backoff_total_sec`, `frontdoor_probe` 추가
- `tools/quality/check_source_filename_governance.py`
  - tracked text file 전체에 대해 real corpus filename denylist 검증 추가
- `tools/bench/judge_audit.py`
  - `source_policy_judge`
  - `judge_inject_quality`
  - test-only local-first judge scaffold 추가
- `modules/nf_shared/config.py`
  - UTF-8 BOM이 있는 `nf_config.toml`도 정상 로드하도록 보강
- `tools/bench/run_one_shot_validation.ps1`
  - TOML write 없이 env override만으로 dataset rebuild를 수행
  - intentional failure probe를 expected failure로 처리하고 `failure_*.json` telemetry를 직접 검증
  - delegated long-run 명령을 PowerShell one-liner로 출력

실제 실행 결과:
- `verify/datasets/dataset_manifest.json`
  - `files_total = 36`
  - `dataset_generation_version = 20260307-r5`
  - `source_policy_registry_version = 20260307-r1`
  - `fallback_files = 1`
  - `episodes_total = 8433`
  - `fallback_episodes = 99`
  - `fallback_episode_share = 0.01174`
  - `fallback_source_files = ["SRC-2e0ba0a8ee12"]`
  - `manual_review_source_count = 1`
  - `manual_review_reason_counts = {"unsupported_or_ambiguous_source_structure": 1}`
  - `composite_source_policy = exclude_fallback_sources_unless_empty`
  - `eligible_source_ids = 35`
  - `excluded_source_ids = 1`
  - `DS-GROWTH-*`는 이제 deterministic shuffled prefix semantics를 사용하므로, pre-fix artifact와 직접 비교할 때 dataset comparability를 별도 경고해야 한다
  - `quality_warnings`에 아래 3개가 직접 기록됨
    - `FALLBACK_SOURCES_PRESENT`
    - `GROWTH_DATASET_PREFIX_BIAS`
    - `GENERIC_APPEND_INJECT_DATASET`
    - `COMPOSITE_DATASETS_EXCLUDE_FALLBACK_SOURCES`
    - `MANUAL_REVIEW_SOURCE_POLICY`
- `verify/benchmarks/latest_metrics_summary.json`
  - DS-800:
    - `latest_successful_file = 20260306T153832Z.json`
    - `latest_attempt_file = 20260307T073717Z.json`
    - `latest_attempt_status = index_fts:FAILED`
- `verify/benchmarks/consistency_strict_gate_20260307T103600Z_iter1.json`
  - `strict_core_gate.passed = true`
  - `strict_layer3_gate.status = SKIPPED`
- `verify/benchmarks/20260307T110330Z.json`
  - local stack(`http://127.0.0.1:8085`) 기준 소형 live bench 실행으로 `semantic.dataset_profile` 필드가 실제 artifact에 기록됨을 확인
  - `DS-INJECT-C` 2문서 기준:
    - `injected_kind_counts = {"age": 1, "job": 1}`
    - `inject_strategy_counts = {"append_marker_statement": 2}`
    - `generic_append_inject_present = true`
- `verify/benchmarks/20260307T113957Z.json`
  - local stack 기준 throughput live bench 실행으로 `semantic.dataset_profile.dataset_manifest_entry`가 실제 artifact에 기록됨을 확인
  - `dataset_generation_version = 20260307-r5`
  - `composite_source_policy = exclude_fallback_sources_unless_empty`
- `verify/benchmarks/20260307T120903Z.json`
  - source-id 전환 이후 live throughput run으로 `dataset_manifest_entry.top_source_distribution[*].source_id` 저장 확인
- `verify/benchmarks/20260307T133528Z.json`
  - source-id / registry / structured inject / frontdoor probe 반영 이후 live throughput run
  - `frontdoor_probe` top-level 저장 확인
- `verify/benchmarks/failure_20260307T111803Z.json`
  - intentionally failing base URL(`http://127.0.0.1:9`)로 소형 bench를 실행해 structured transport failure artifact를 생성
  - 확인값:
    - `attempt_stage = project_create`
    - `request_path = /projects`
    - `error_class = URLError`
    - `base_url = http://127.0.0.1:9`
  - 최신 검증 artifact:
    - `verify/benchmarks/failure_20260307T135330Z.json`
    - `attempt_stage = frontdoor_probe`
    - `request_method = GET`
    - `request_path = /health`
    - `retry_count = 1`
    - `retryable = true`
    - `backoff_total_sec = 0.25`

회귀 검증:
- `pytest -q tests/test_tools_quality_source_filename_governance.py tests/test_nf_shared_protocol.py tests/test_tools_bench_http_client.py tests/test_tools_bench_build_novel_dataset.py tests/test_tools_bench_run_pipeline_bench.py tests/test_tools_bench_run_one_shot_validation.py tests/test_tools_bench_judge_audit.py tests/test_tools_bench_shared_utils.py tests/test_nf_consistency_filters.py tests/test_tools_bench_metrics_summary.py tests/test_tools_bench_strict_gate.py tests/test_nf_consistency_engine.py tests/test_nf_consistency_slot_equivalence.py tests/consistency/test_engine_quality_core.py tests/consistency/test_engine_quality_graph.py tests/consistency/test_engine_quality_layer3.py`
  - 결과: `106 passed`
- one-shot script 검증:
  - `powershell -ExecutionPolicy Bypass -File tools/bench/run_one_shot_validation.ps1 -BaseUrl http://127.0.0.1:8085 -DatasetInputDir test_files -DatasetOutputDir verify/datasets -BenchOutputDir verify/benchmarks -DiversityProfile max`
  - 결과:
    - dataset rebuild / governance / regression / live bench / expected failure probe 통과
    - failure probe는 non-zero exit code 자체가 아니라 generated artifact와 telemetry 필드 존재로 판정
    - live bench artifact: `verify/benchmarks/20260307T135325Z.json`
    - failure probe artifact: `verify/benchmarks/failure_20260307T135330Z.json`
- governance 검증:
  - `python tools/quality/check_source_filename_governance.py --repo-root . --source-dir test_files`
  - 결과: `ok = true`

현재 잔여 결손:
- dataset builder는 pre-fix 대비 크게 개선됐지만 `SRC-2e0ba0a8ee12` 한 개 source는 여전히 manual-review 대상이다.
- `DS-GROWTH-*`의 raw file-prefix bias는 제거됐지만, 이제 shuffled progressive growth semantics로 바뀌었으므로 historical artifact와의 직접 비교 해석은 별도 주의가 필요하다.
- inject dataset의 generic append 설계는 structured subset이 추가됐지만, typed benchmark 전환 자체는 아직 남아 있다.
- strict output은 분리됐지만 layer3 capability 자체는 여전히 inactive라 `SKIPPED` 상태다.
- transport/front-door failure는 이제 structured artifact로 남지만, `RemoteDisconnected`의 근본 원인 제거는 아직 남아 있다.

## LLM-as-Judge 검토

현재 repo 기준 판정:
- 타당성은 있다. 다만 primary consistency gate로 바로 올리기보다 test-only secondary audit로 붙이는 것이 맞다.
- 근거:
  - 현재 코드에는 layer3 / conservative NLI / remote API 경로가 이미 있다.
  - 하지만 현재 설정 로드 결과는 `enable_layer3_model=False`, `enable_local_nli=False`, `enable_remote_api=False`다.
  - 즉 현재는 judge capability 경로가 “구현은 존재하지만 운영 비활성” 상태다.

권장 적용 방식:
- `LLM as judge`는 strict core를 대체하지 않는다.
- test dataset 한정으로만 쓴다.
- 추천 위치:
  - `strict_layer3_gate`의 보조 평가
  - 또는 별도 `judge_audit` artifact
- 추천 입력:
  - `DS-CONTROL-D`
  - `DS-INJECT-C`
  - 가능하면 typed inject benchmark로 재구성된 후
- 추천 출력:
  - `judge_model`
  - `judge_prompt_version`
  - `judge_verdict`
  - `judge_confidence`
  - `judge_agrees_with_core`
  - disagreement sample 목록

주의점:
- 지금의 inject dataset은 generic append 문장 중심이라, LLM-as-judge를 붙여도 ground truth가 정교해지지는 않는다.
- 따라서 typed inject benchmark 또는 manually curated judge-set 없이 judge 점수만 올리면 과신 위험이 있다.
- 이 repo에서는 LLM-as-judge를 “검사기”가 아니라 “감사기”로 두는 것이 안전하다.

## 파일명 하드코딩 배제 관점의 일반화 검토

현재 상태:
- runtime segmentation policy는 [build_novel_dataset.py](/c:/Users/USER/nf/tools/bench/build_novel_dataset.py)의 `_SOURCE_OVERRIDE_PATTERNS`, `_SOURCE_MANUAL_REVIEW`에 file-name key를 사용한다.
- 지금은 남은 예외 source가 1개라 운영상 관리 가능하지만, 데이터 거버넌스 관점에서는 좋은 종착점이 아니다.

문제:
- 파일명 rename 시 정책이 깨진다.
- 동일 원문을 다른 이름으로 복제하면 policy가 누락된다.
- 같은 이름의 다른 파일이 들어오면 잘못된 policy가 적용될 수 있다.
- source identity가 파일명이 아니라 content여야 provenance와 일치한다.

추가 일반화 방안:

1. content-hash 기반 source policy registry
- 가장 현실적인 1순위 대안이다.
- 이미 manifest에 `content_sha256`가 있으므로, file-name key 대신 `content_sha256` key를 쓰는 것이 자연스럽다.
- 예시 구조:
```json
{
  "version": "20260307-r6",
  "sources": [
    {
      "content_sha256": "...",
      "segmentation_policy": "manual_review",
      "allowed_patterns": [],
      "reason": "unsupported_or_ambiguous_source_structure"
    }
  ]
}
```
- 장점:
  - rename에 안전
  - provenance와 직접 연결
  - dataset_generation_version과 함께 관리 가능
- 한계:
  - 여전히 curated exception registry다
  - 완전한 일반화는 아니다

2. source profile 기반 자동 정책
- file-name이 아니라 source layout feature로 정책을 결정한다.
- 현재 코드와 잘 맞는다. 이미 `candidate_boundary_counts`, `boundary_counts`, `content_length_stats`를 계산하고 있기 때문이다.
- 추천 feature:
  - `episode_hwa`, `ep_prefix`, `bracketed_numbered_title`, `section_jo`, `plain_title_paren`, `standalone_number` 반복 수
  - blank-line spacing pattern
  - short-line density
  - isolated-number density
  - front matter density
  - max/min/median segment length
- 추천 output:
  - `segmentation_policy = auto | source_override_pattern | manual_review`
  - `selected_pattern_family`
  - `profile_confidence`
- 장점:
  - 이름 의존 제거
  - 새로운 source에도 일반화 가능
- 한계:
  - 애매한 source는 여전히 남는다

3. hash registry + profile classifier 혼합
- 실무적으로 가장 타당한 형태다.
- 기본은 profile classifier로 자동 결정
- classifier confidence가 낮은 source만 content-hash registry로 고정
- file-name 하드코딩은 제거 가능

4. `LLM as judge`를 source policy fallback으로 사용
- 이 경우에도 1차 분할기는 deterministic이어야 한다.
- 추천 구조:
  - Step 1: deterministic candidate extraction
  - Step 2: source profile confidence 계산
  - Step 3: confidence 낮은 source만 judge 호출
  - Step 4: judge는 “full segmentation 생성기”가 아니라 “policy selector” 역할만 수행
- judge가 결정할 것:
  - `accepted_pattern_family`
  - `manual_review_required`
  - `reason`
- 장점:
  - file-name 예외를 줄일 수 있다
  - 새로운 형식의 source를 더 빨리 수용 가능
- 한계:
  - 판정 drift
  - remote API 사용 시 데이터 전송 이슈
  - reproducibility 관리 필요

## `LLM as judge`를 우선 고려할 때의 적용 상세 검토

추천 적용 우선순위:

1. source segmentation judge
- 가장 타당하다.
- 이유:
  - 현재 남은 manual-review source는 소수
  - deterministic candidate set과 profile을 입력으로 줄 수 있어 prompt가 짧다
  - full novel 원문 전체를 보내지 않아도 된다
- 입력 예:
  - short-line candidates 30개
  - candidate pattern counts
  - blank-line spacing stats
  - source content hash
- 출력 예:
```json
{
  "segmentation_policy": "manual_review",
  "accepted_pattern_family": [],
  "manual_review_required": true,
  "confidence": 0.92,
  "reason": "No reliable repeated chapter markers; front matter and prose dominate."
}
```

2. inject sample quality judge
- 현재 inject dataset의 generic append 설계를 보조 평가하는 데 유용하다.
- judge가 볼 것:
  - appended statement가 동일 entity에 자연스럽게 귀속되는지
  - clear conflict인지, ambiguous인지
  - malformed sample인지
- 출력 예:
  - `clear_conflict`
  - `ambiguous_subject`
  - `contextless_append`
  - `no_conflict`
- 이 라벨을 붙이면 기존 inject dataset도 부분적으로 usable subset을 만들 수 있다.

3. strict layer3 audit
- 지금은 `enable_layer3_model=False`, `enable_local_nli=False`, `enable_remote_api=False`라 운영 judge는 꺼져 있다.
- 따라서 바로 운영 gate로 쓰기보다, test-only strict audit artifact로 두는 것이 맞다.
- 추천 출력:
  - `judge_verdict`
  - `judge_confidence`
  - `judge_agrees_with_core`
  - disagreement sample

비추천 적용:
- full dataset 전체를 LLM이 직접 segmentation하는 방식
- 이유:
  - cost 과다
  - drift 크다
  - rerun reproducibility가 낮다
  - long source 전체를 prompt로 넣는 거버넌스 부담이 크다

## 권장 아키텍처

단기:
- file-name key를 `content_sha256` key로 치환
- source profile confidence를 먼저 계산
- confidence가 낮은 source만 manual review 또는 judge 대상으로 보낸다

중기:
- `source_policy_registry.json` 도입
- `judge_audit` artifact 도입
- `inject_quality_label` 도입

장기:
- typed inject benchmark로 전환
- `strict_layer3_gate`와 judge audit disagreement 분석을 결합

권장 결론:
- file-name 하드코딩 제거는 `content_sha256 registry + source profile classifier` 조합이 최선이다.
- `LLM as judge`는 우선 적용 가능하지만, primary deterministic path를 대체하지 말고
  source policy fallback과 inject quality audit부터 붙이는 것이 가장 안전하다.

아래 본문은 pre-fix 진단과 구조적 리스크 설명을 포함하며, 위 구현 결과가 최신 상태를 우선한다.

## 0. 결론

현재 미비점 존재 여부: **예**.

핵심 결론:
- `test_files` 기반 dataset builder는 현재 벤치 입력의 대표성과 재현성을 충분히 보장하지 못한다.
- 정합성 엔진 자체는 이전보다 명확히 보강되었지만, quick 운영 경로의 높은 `unknown_rate`와 rule-first extractor 한계 때문에 정합성 품질은 아직 완성 단계가 아니다.
- 운영 benchmark summary는 2026-03-07 시점 기준으로 DS-200/400은 회복했지만, DS-800 최신 실패 시도 노출성이 부족하고 strict gate는 아직 “정답성 게이트”라기보다 “신호 존재 게이트”에 가깝다.
- `plan/consistency_benchmark_followup_2026-03-07.md`의 active workstream은 대체로 유효하지만, dataset builder 품질/재현성 문제는 계획 문서에 빠져 있다.

## 1. 실행 및 검증

재실행한 테스트:
- `pytest -q tests/test_tools_bench_build_novel_dataset.py tests/test_nf_consistency_filters.py tests/test_tools_bench_metrics_summary.py tests/test_tools_bench_strict_gate.py`
  - 결과: `13 passed`
- `pytest -q tests/test_nf_consistency_engine.py tests/test_nf_consistency_slot_equivalence.py tests/consistency/test_engine_quality_core.py tests/consistency/test_engine_quality_graph.py tests/consistency/test_engine_quality_layer3.py`
  - 결과: `46 passed`

추가 분석:
- `python tools/bench/summarize_latest_metrics.py --bench-dir verify/benchmarks --datasets "DS-200,DS-400,DS-800,DS-DIVERSE-200,DS-DIVERSE-400,DS-DIVERSE-800" --label-mode operational ...`
  - temp summary 재생성 후 repo 산출물과 의미 재확인
- `test_files/*.txt` 전수 분석
  - boundary 검출 수, 추출 episode 수, fallback 여부, 길이 분포 재집계
- `verify/datasets/*.jsonl` 분석
  - `DS-GROWTH-*`, `DS-DIVERSE-*`, `DS-INJECT-C`, `DS-CONTROL-D` source distribution 산출
- `DS-INJECT-C` 샘플 확인
  - injected 문장이 원문 말미에 generic append 방식으로 붙는지 확인

## 2. Dataset Builder 감사

관련 코드:
- `tools/bench/build_novel_dataset.py:35`
- `tools/bench/build_novel_dataset.py:85`
- `tools/bench/build_novel_dataset.py:98`
- `tools/bench/build_novel_dataset.py:132`
- `tools/bench/build_novel_dataset.py:147`

### 2.1 확인된 사실

- 이 문서에서 `source-##`는 내부 corpus source의 안정적 익명 별칭이다.
- 전체 `test_files`는 36개였다.
- 전체 추출 episode는 5,721개였다.
- 이 중 32개 파일이 fallback 12k chunking을 사용했다.
- fallback episode는 4,718개였다.
- fallback 비중은 전체 episode 기준 `82.47%`였다.
- primary boundary를 실제로 많이 잡은 파일은 극소수였다.
  - `source-02`: `10`개
  - `source-03`: `15`개
  - `source-04`: `799`개 + secondary `1`개
  - `source-05`: primary `131`, secondary `47`

### 2.2 구조적 결함

#### P0. episode segmentation이 대부분 실패하고 있다

현재 `split_episodes()`는 사실상 아래 두 패턴에만 의존한다.
- bracket header: `^\[(\d{1,5})\]\s*(.*)$`
- trailing hyphen number: `^.*?-(\d{1,5})\s*$`

실제 원본 샘플에서 확인된 누락 패턴:
- `1화`
- `0화 프롤로그`
- `001. 프롤로그`
- `1. 서걱`

대표 사례:
- `source-06`
  - 실제 본문은 `0화 프롤로그` 형식인데 boundary `0`, fallback chunking `true`
- `source-02`
  - 파일명상 120화 계열인데 추출 episode는 `10`
  - `max_content_chars = 271151`, `min_content_chars = 21`
  - 즉 일부만 episode로 잡히고 큰 덩어리가 남았다
- `source-03`
  - 샘플 본문은 `001. 프롤로그` 형식인데 추출 episode는 `15`
  - `min_content_chars = 35`, `median_content_chars = 1124`
  - 우연한 숫자/대괄호가 false positive로 잡혔을 가능성이 높다
- `source-05`
  - episode는 `178`개만 생성됐고 `max_content_chars = 866433`
  - 일부는 잡고 일부는 놓치는 partial segmentation 상태다

판정:
- 현재 builder는 “episode dataset builder”라기보다 “부분적으로 episode를 잡고, 대부분은 12k raw chunk로 대체하는 builder”에 가깝다.
- 따라서 `verify/datasets/*.jsonl`의 `episode_no`와 `header`는 데이터셋 전체에서 신뢰 가능한 ground truth로 보기 어렵다.

#### P0. fallback 12k chunking이 조용히 dataset 의미를 바꾼다

`split_episodes()`는 boundary가 2개 미만이면 12,000자 고정 chunk로 fallback한다.

영향:
- chapter/scene 경계와 무관한 인위적 절단이 발생한다.
- 한 record 안에 여러 화/여러 scene이 섞일 수 있다.
- strict/control/inject dataset에서도 동일 왜곡이 상속된다.
- retrieval/consistency 성능은 episode segmentation 품질이 아니라 raw chunk 길이와 우연한 scene 혼합에 영향을 받는다.

현재 state:
- 전체 episode의 `82.47%`가 이 fallback 산출물이다.

#### P0. `DS-GROWTH-*`는 scale benchmark이 아니라 “파일 정렬 prefix benchmark”다

생성 방식:
- `all_base_episodes[:cut]`

관측된 분포:
- `DS-GROWTH-200`: source 2개
  - `7회차 회귀자는 해피엔딩을 찾는다...`: 106
  - `[경우勁雨]블랙 게이트의 민속학자...`: 94
- `DS-GROWTH-400`: source 6개
- `DS-GROWTH-800`: source 10개

영향:
- doc 수가 증가할수록 corpus composition도 같이 바뀐다.
- 따라서 `DS-GROWTH-200 -> 400 -> 800` 비교는 pure scale test가 아니다.
- 현재 수치는 “규모 증가”와 “다른 작품/다른 segmentation 품질 유입”이 결합된 결과다.

#### P0. `DS-INJECT-C`/`DS-CONTROL-D`는 ground-truth calibrated strict dataset이 아니다

생성 방식:
- `uniform_sample()`로 flatten된 전체 episode를 순서 기반 균등 추출
- `inject_conflict_text()`로 원문 말미에 generic 문장을 append
- `injected_kind`는 record에 저장되지만 현재 레포에서 builder 외 소비 경로가 없다

샘플 확인:
- `[INJECT]\n주인공의 나이는 50세였다.`
- `[INJECT]\n주인공은 9서클 마법사였다.`
- `[INJECT]\n주인공은 천재였다.`

문제:
- injected 문장은 실제 entity alias가 아닌 `주인공` 고정 문구다.
- append 위치가 원문 말미 고정이라 scene/context와 분리된다.
- `injected_kind`는 strict gate, benchmark summary, consistency runtime 어디에서도 사용되지 않는다.
- 즉 strict dataset은 “정해진 유형의 위배를 얼마나 정확히 잡았는지”보다 “generic conflict signal이 최소 1회 이상 생겼는지”에 더 가깝다.

#### P1. `DS-DIVERSE-*`는 source balance는 좋아졌지만 split failure를 상속한다

관측:
- `DS-DIVERSE-200`: source 36개, 상위 source count 6 수준
- `DS-DIVERSE-800`: source 36개, 상위 source count 23 수준

장점:
- source 편중은 `DS-GROWTH-*`보다 훨씬 낫다.

한계:
- 입력 pool 자체가 fallback chunk에 오염되어 있다.
- 즉 diversity는 좋아졌지만 segmentation validity는 개선되지 않는다.

#### P1. manifest가 provenance를 충분히 보존하지 않는다

현재 `dataset_manifest.json`이 보존하는 것:
- file name
- encoding
- size
- mtime
- episode count
- top distribution
- build options

현재 보존하지 않는 것:
- split strategy
- fallback 여부
- boundary counts
- per-source segmentation quality
- sampling strategy detail
- source order
- record-level provenance
- content hash

추가 결함:
- `source_snapshot_hash`는 현재 file name + size + mtime 기반이다.
- 실제 content hash가 아니므로 재현성 fingerprint로 약하다.

#### P1. encoding fallback이 조용히 내용을 손상시킬 수 있다

`read_text_auto()`는 여러 encoding을 시도한 뒤 실패하면 `errors="ignore"`로 읽는다.

영향:
- 문자 손실이 조용히 발생할 수 있다.
- manifest에는 `"encoding": "unknown"`만 남고, 어느 정도 손상이 있었는지는 남지 않는다.

#### P1. 현재 테스트가 dataset validity를 거의 고정하지 못한다

관련 테스트:
- `tests/test_tools_bench_build_novel_dataset.py`

현재 보장하는 것:
- diverse set과 manifest field 존재 여부

현재 보장하지 않는 것:
- `1화`, `0화`, `001.`, `1.` 패턴 인식
- fallback 비율 상한
- non-fallback segmentation 품질
- `source_snapshot_hash`의 content-based reproducibility
- inject/control dataset의 의미적 유효성

### 2.3 데이터 거버넌스 / 재현성 리스크

#### P1. mutable local corpus 의존

- 현재 benchmark는 local `test_files/*.txt`에 직접 의존한다.
- corpus는 repo 안에 있지만 관리 기준이 “고정된 공개 benchmark asset”이 아니다.
- 원문 변경, 파일 추가/삭제, 이름 변경만으로 dataset 의미가 바뀔 수 있다.

#### P1. benchmark portability 부족

- 외부 환경에서 동일 `test_files`를 보장할 수 없다.
- `source_snapshot_hash`가 content hash가 아니므로 동일성 확인도 약하다.
- 결과적으로 benchmark artifact는 같은 레포라도 다른 머신/다른 시점에서 의미가 달라질 수 있다.

판정:
- 법률 자문 수준은 아니지만, 운영 benchmark의 재현 가능성과 배포 가능성은 현재 부족하다.

## 3. 정합성 로직 감사

관련 코드:
- `modules/nf_consistency/engine.py:509`
- `modules/nf_consistency/engine.py:727`
- `modules/nf_consistency/engine.py:817`
- `modules/nf_consistency/engine.py:959`
- `modules/nf_consistency/engine.py:1694`
- `modules/nf_workers/runner.py:1371`
- `modules/nf_workers/runner.py:1488`
- `modules/nf_workers/runner.py:1517`
- `modules/nf_workers/runner.py:1652`

### 3.1 이미 보강된 항목

다음 항목은 “미구현”으로 분류하면 안 된다.

- entity-unresolved 시 entity-bound slot 비교 차단
  - `_judge_with_fact_index()`가 entity-bound slot에서 global compare를 멈추고 `ENTITY_UNRESOLVED`로 보낸다
  - 관련 테스트:
    - `tests/test_nf_consistency_engine.py`
    - `tests/consistency/test_engine_quality_core.py`
- auto entity/time metadata filter 주입
  - `_resolve_auto_metadata_filters()`가 claim span overlap으로 `entity_id`, `time_key`, `timeline_idx`를 주입한다
  - 관련 테스트:
    - `tests/test_nf_consistency_filters.py`
- numeric conflict를 `UNKNOWN` 사유로 분리
  - `_has_string_slot_numeric_conflict()` + `_judge_with_fact_index()` 경로
  - 관련 테스트:
    - `tests/test_nf_consistency_engine.py`
    - `tests/consistency/test_engine_quality_core.py`
- confirmed evidence overlap ratio 강화
  - `_promote_confirmed_evidence()`가 최소 overlap chars/ratio를 요구한다
  - 관련 테스트:
    - `tests/consistency/test_engine_quality_core.py`
- metadata grouping preflight 플래그 분리
  - `runner.py`에서 `metadata_grouping_enabled`가 graph와 분리된 별도 preflight input으로 들어간다
  - 관련 테스트:
    - `tests/test_nf_workers_consistency_payload.py`

판정:
- 이 영역의 로직은 “설계상 없음”이 아니라 “이미 1차 보강됨”으로 분류하는 것이 맞다.

### 3.2 미해결 항목

#### P1. extractor는 여전히 rule-first이고 natural language recall ceiling이 낮다

관련 코드:
- `modules/nf_consistency/extractors/rule_extractor.py`
- `modules/nf_consistency/extractors/pipeline.py`

현재 default behavior:
- builtin rule은 `나이`, `시간`, `장소/위치`, `관계`, `소속`, `직업/클래스`, `재능`, `사망/생존` 중심
- 자연 서술형 문장 회수력은 제한적이다
- model path는 profile과 gateway가 있어야 작동하고, quick 운영 artifact는 사실상 rule-first 해석이 맞다

영향:
- “검사 대상 claim 자체”가 적게 잡힌다.
- precision 보호에는 유리하지만 recall ceiling이 낮다.

#### P1. metadata filter가 걸리면 vector refill이 차단된다

관련 코드:
- `modules/nf_consistency/engine.py:727`
- `modules/nf_consistency/engine.py:2243`
- `modules/nf_consistency/engine.py:2629`

현재 동작:
- `entity_id`, `time_key`, `timeline_idx` 중 하나라도 있으면 metadata filter requested로 간주
- 이 경우 FTS 결과 부족 시 vector refill을 하지 않는다

영향:
- metadata scope를 좁힐수록 recall이 더 떨어질 수 있다.
- entity/time 분해를 정교하게 한 대가로 retrieval recall 손실이 생긴다.

#### P1. quick 운영 경로는 구조적으로 `unknown`이 높다

관련 artifact:
- `verify/benchmarks/20260307T064648Z.json`
  - `unknown_rate = 0.8267`
  - `unknown_reason_counts = {CONFLICTING_EVIDENCE: 51, NUMERIC_CONFLICT: 12, SLOT_UNCOMPARABLE: 12}`
- `verify/benchmarks/20260307T061120Z.json`
  - `unknown_rate = 0.9118`
  - `unknown_reason_counts = {CONFLICTING_EVIDENCE: 121, NUMERIC_CONFLICT: 5, SLOT_UNCOMPARABLE: 5}`

해석:
- quick 운영 경로는 `graph_mode = off`
- `layer3_* = 0`
- `verification_loop_* = 0`
- 따라서 quick artifact의 `unknown_rate`는 일시적 이상치가 아니라 현재 운영 정책의 구조적 결과다

#### P1. strict gate는 correctness gate보다 signal-presence gate에 가깝다

관련 코드:
- `tools/bench/check_consistency_strict_gate.py:85`
- `tools/bench/check_consistency_strict_gate.py:141`
- `tools/bench/check_consistency_strict_gate.py:187`

현재 strict gate 핵심:
- runtime key 존재
- strict level 여부
- 성능 비율
- loop timeout rate
- inject 쪽에서 `CONFLICTING_EVIDENCE >= 1` 또는 `violate_count_total >= 1`

한계:
- expected injection count 대비 recall을 측정하지 않는다
- `injected_kind`별 분리 측정이 없다
- layer3 capability/정답성 자체를 pass condition으로 강하게 다루지 않는다

판정:
- “strict PASS”는 현재도 useful한 운영 신호다
- 그러나 “strict correctness fully verified”로 읽으면 과대해석이다

### 3.3 정합성 로직 완성도 평가

강점:
- claim-evidence-verdict 구조는 존재한다
- unknown reason taxonomy가 비교적 잘 정리돼 있다
- entity/time metadata scope, overlap safety, numeric conflict handling 같은 오탐 억제 장치가 있다
- 해당 장치들은 테스트로 고정돼 있다

약점:
- extractor recall이 낮다
- quick mainline actionability가 낮다
- strict gate semantics가 아직 느슨하다
- benchmark dataset 자체가 왜곡되어 엔진 품질 해석도 오염된다

판정:
- 엔진 “코어 로직”은 B급 이상이지만, 운영 품질을 대표하는 end-to-end 정합성 품질은 dataset/benchmark 정책까지 합치면 아직 C+ 수준이 맞다

## 4. 운영 Artifact 기준 레포 완성도/품질 평가

기준 artifact:
- `verify/benchmarks/latest_metrics_summary.json`
- `verify/benchmarks/20260307T064648Z.json`
- `verify/benchmarks/20260307T061120Z.json`
- `verify/benchmarks/20260307T071917Z.json`
- `verify/benchmarks/20260307T073717Z.json`
- `verify/benchmarks/soak_20260307T032658Z.json`

### 4.1 현재 상태 요약

- DS-200 운영 artifact는 회복
  - `consistency_p95 = 1615.80ms`
  - `retrieval_fts_p95 = 27.93ms`
- DS-400 운영 artifact는 회복
  - `consistency_p95 = 2067.48ms`
  - `retrieval_fts_p95 = 28.26ms`
- DS-800은 운영 rerun 2회가 모두 실패
  - `20260307T071917Z.json`: `index_fts = FAILED`
  - `20260307T073717Z.json`: `index_fts = FAILED`
- summary는 실패 artifact를 제외하므로 DS-800은 현재 latest successful만 보인다
  - `latest_metrics_summary.json` 기준 `DS-800.status = NO_BASELINE`
  - 동시에 `DS-800.absolute_status = PASS`
- diversity mainline은 아직 절대 성능 FAIL
  - `DS-DIVERSE-200 consistency_p95 = 3151.30ms`
  - `DS-DIVERSE-400 consistency_p95 = 9054.23ms`
  - `DS-DIVERSE-800 consistency_p95 = 11796.49ms`
- soak는 0이 아닌 tail failure sample이 남아 있다
  - `failure_breakdown.by_stage.CONSISTENCY = 1`

### 4.2 5개 축 등급

| 축 | 등급 | 판정 근거 |
|---|---|---|
| 구현 완성도 | `B+` | core consistency, retrieval, unknown reason, graph/layer3 hook, summary/gate 체계가 모두 존재하고 주요 보강이 이미 반영되어 있음 |
| 테스트 완성도 | `B-` | consistency 핵심 회귀는 비교적 좋지만 dataset builder validity, strict correctness, benchmark corpus integrity를 고정하는 테스트가 약함 |
| 운영 완성도 | `B-` | DS-200/400 운영 회복은 확인됐지만 DS-800 운영 baseline 미복구, latest attempt 노출 부족, soak tail risk가 남음 |
| 절대 성능 품질 | `B-` | mainline DS-200/400은 목표 내 회복했지만 diversity는 여전히 절대 FAIL이고 DS-800 최신 성공 재확인이 없음 |
| 정합성 품질 | `C+` | quick 운영 artifact의 `unknown_rate`가 매우 높고 strict gate가 correctness보다는 signal-presence에 가까우며 dataset 자체도 품질 해석을 오염시킴 |

## 5. `consistency_benchmark_followup_2026-03-07.md` 타당성 감사

검토 대상:
- `plan/consistency_benchmark_followup_2026-03-07.md`

### 5.1 active workstream 재분류

| Workstream | 재분류 | 판단 |
|---|---|---|
| WS1 운영 기준선 정렬 | `valid / partially stale` | DS-800 front-door, summary semantics, latest attempt 노출은 여전히 유효. 다만 earlier subissues 일부는 이미 코드에 반영됨 |
| WS2 strict 의미 분리 | `valid` | 현재 strict gate는 core/layer3 분리 필요성이 여전히 큼 |
| WS3 graph 실효성 | `valid` | graph path 존재만으로는 부족하고 applied-rate 관리가 아직 필요함 |
| WS4 unknown/actionability | `valid` | quick mainline unknown 비율이 여전히 높아 최우선 품질 개선 축으로 유지 타당 |
| WS5 soak tail lock | `valid` | soak pass에도 tail failure sample이 남아 있으므로 유지 타당 |
| WS6 문서/판독 정리 | `valid` | summary/final/strict 해석 경계가 여전히 사용자 오해를 유발할 수 있음 |

### 5.2 stale 또는 재서술 필요 항목

다음 류의 표현은 “미구현”처럼 읽히지 않게 바꾸는 편이 맞다.
- entity unresolved 처리
- numeric conflict unknown 분리
- confirmed overlap 강화
- metadata grouping preflight 분리

이 항목들은 현재 코드와 테스트 기준으로 이미 1차 구현/회귀 고정이 끝난 상태다.

### 5.3 문서의 명확한 누락

현재 follow-up 문서에는 아래 축이 빠져 있다.
- dataset builder 품질 자체
- benchmark corpus validity
- `test_files` 기반 재현성/배포성 리스크
- `DS-GROWTH-*`가 pure scale benchmark가 아니라 order-biased corpus prefix라는 문제
- `DS-INJECT-C`/`DS-CONTROL-D`가 ground-truth calibrated strict benchmark가 아니라는 문제

판정:
- follow-up 문서는 benchmark/runtime remediation 문서로는 유효하다
- 그러나 benchmark input validity 문서가 아니므로, 현 시점에서는 dataset builder 품질 항목을 추가하지 않으면 “운영 수치 해석”이 과신될 위험이 있다

## 6. 개선 권고

## 6.1 즉시 수정 권고

### P0

1. `tools/bench/build_novel_dataset.py`
   - `split_episodes()`에 실제 corpus header 패턴을 추가한다
   - 최소 지원:
     - `^\d+\s*화`
     - `^\d+\.\s+`
     - `^\[(\d+)\]`
     - 필요 시 `프롤로그`, `에필로그`, `외전` 보조 규칙
   - fallback은 조용히 수행하지 말고 manifest에 강하게 기록하거나 threshold 초과 시 build fail/warn로 올린다

2. `tools/bench/build_novel_dataset.py`
   - `source_snapshot_hash`를 size/mtime 기반이 아니라 content hash 기반으로 바꾼다
   - `dataset_manifest.json`에 아래를 추가한다
     - `split_strategy`
     - `fallback_used`
     - `boundary_counts`
     - `content_length_stats`
     - `sampling_strategy`
     - `source_order`
     - `build_input_hash_policy`

3. `tools/bench/summarize_latest_metrics.py`
   - dataset별 `latest_successful_*`와 별개로 `latest_attempt_*`, `latest_attempt_status`를 노출한다
   - 현재는 unsuccessful artifact를 summary 후보에서 제거하기 때문에 최신 실패 시도가 dataset row에 드러나지 않는다

4. `tests/test_tools_bench_build_novel_dataset.py`
   - corpus 대표 패턴 regression fixture를 추가한다
   - 최소 fixture:
     - `1화`
     - `0화 프롤로그`
     - `001. 프롤로그`
     - `1. 단편 제목`
   - fallback 비율/episode 수 sanity check도 넣는다

### P1

5. `tools/bench/check_consistency_strict_gate.py`
   - `strict_core_gate`와 `strict_layer3_gate`를 분리하거나 동등한 필드를 추가한다
   - 현재 `inject_conflict_signal_present`는 ground-truth calibrated gate로는 약하다

6. `tools/bench/build_novel_dataset.py`
   - inject dataset을 generic append에서 typed benchmark로 바꾼다
   - 최소한 아래를 추가한다
     - target entity alias
     - expected outcome
     - inject position
     - inject strategy
   - `injected_kind`는 실제 게이트/리포트에서 소비되도록 연결한다

## 6.2 구조 개선 권고

### P1

1. `modules/nf_consistency/extractors/pipeline.py`
   - quick 운영 경로와 별도 실험 profile을 두고 hybrid extraction recall을 계측한다
   - builder/benchmark 품질 개선 없이 이 작업만 먼저 하면 원인 분리가 흐려지므로 순서를 builder 이후로 둔다

2. `modules/nf_consistency/engine.py`
   - metadata filter active 시 vector refill 차단 정책을 재검토한다
   - 최소 실험:
     - metadata + vector refill off
     - metadata + vector refill on
   - 측정 지표:
     - `unknown_rate`
     - `CONFLICTING_EVIDENCE`
     - `SLOT_UNCOMPARABLE`
     - false positive 증가 여부

3. benchmark integrity gate 추가
   - dataset build 단계에서 아래를 fail/warn 기준으로 둔다
     - fallback episode share
     - giant episode 존재 여부
     - tiny episode 존재 여부
     - source distribution imbalance

### P2

4. benchmark corpus 거버넌스 정리
   - frozen benchmark snapshot 또는 public/synthetic 대체 benchmark를 분리한다
   - 운영 benchmark와 개발용 local corpus를 분리 관리한다

## 7. 요약

최종 판정:
- dataset builder는 **즉시 보완 필요** 상태다.
- consistency engine core는 **부분적으로 성숙**했지만, quick 운영 품질과 strict correctness semantics는 아직 미완이다.
- benchmark summary와 strict gate는 **운영 판단 도구로는 유효**하지만, 현재 dataset validity 문제를 덮을 수는 없다.
- `plan/consistency_benchmark_followup_2026-03-07.md`는 **runtime remediation 계획으로는 타당**하나, dataset validity 축이 빠져 있어 본 문서 수준의 보완이 필요하다.
