# 파이프라인 운영 검증 분리 문서 (2026-02-28)

## 1) 목적
- claim 매핑 문서에서 파이프라인 운영 검증 항목만 분리해 관리한다.
- 대상 Claim: `Q1-C17` (최신 성능 수치 공백 해소)
- 실행 진입점: `tools/bench/run_user_delegated.cmd`, `tools/bench/run_user_delegated.ps1`

## 2) 운영 검증 실행 규격
1. 고정 벤치 3종 + strict 벤치 2종
- DS-200: `verify/datasets/DS-GROWTH-200.jsonl`, `profile=dual`
- DS-400: `verify/datasets/DS-GROWTH-400.jsonl`, `profile=throughput`
- DS-800: `verify/datasets/DS-GROWTH-800.jsonl`, `profile=throughput`
- DS-CONTROL-D(strict): `verify/datasets/DS-CONTROL-D.jsonl`, `profile=throughput`, `--consistency-level strict`
- DS-INJECT-C(strict): `verify/datasets/DS-INJECT-C.jsonl`, `profile=throughput`, `--consistency-level strict`

2. 공통 실행 기준
- 실행기: `tools/bench/run_pipeline_bench.py`
- 산출 경로: `verify/benchmarks`
- 배치 파라미터(`--consistency-evidence-link-policy`, `--consistency-evidence-link-cap`)는 위임 실행 인자를 그대로 사용
- strict 벤치는 `--consistency-level strict`를 고정 적용해 verifier/triage/verification loop 계측을 강제한다.

3. 요약 산출 생성
- 명령:
  - `python tools/bench/summarize_latest_metrics.py --bench-dir verify/benchmarks --output-json verify/benchmarks/latest_metrics_summary.json --output-md verify/benchmarks/latest_metrics_summary.md`

## 3) Summary Gate 규칙
1. 판정 입력
- `verify/benchmarks/latest_metrics_summary.json`
- 핵심 필드: `overall_status`

2. 고정 정책
- `overall_status == "FAIL"`: 즉시 배치 실패
- `overall_status == "WARN"`: 경고 로그 후 계속
- `overall_status == "PASS"`: 통과

3. 추세 기준
- Hard fail: 직전 대비 동일 지표 20% 초과 악화
- Soft warning: 5~20% 악화
- PASS: hard fail 없음

## 4) Strict Gate 규칙 (Hard Fail)
1. 판정 입력
- baseline artifact: DS-200 운영 벤치 결과
- strict artifacts: DS-CONTROL-D, DS-INJECT-C 운영 벤치 결과
- 평가기: `tools/bench/check_consistency_strict_gate.py`

2. 고정 정책
- 세 artifact 모두 index 성공 및 failure count 0이어야 한다.
- strict artifact의 `parallel.consistency_level`은 `strict`이어야 한다.
- strict artifact에 required runtime key가 모두 존재해야 한다.
- strict 성능 상한:
  - `consistency_p95 <= baseline_ds200_consistency_p95 * 1.8`
  - `retrieval_fts_p95 <= baseline_ds200_retrieval_fts_p95 * 1.5`
  - `verification_loop_timeout_count / max(1, verification_loop_rounds_total) <= 0.20`
- inject 경로 신호:
  - `unknown_reason_counts.CONFLICTING_EVIDENCE >= 1` 또는 `violate_count_total >= 1`

3. 실패 정책
- strict gate 하나라도 실패하면 즉시 배치 실패(non-zero exit)

## 5) 문서 반영 규칙
1. 최신 성능 기준 파일
- `verify/benchmarks/latest_metrics_summary.json`
- `verify/benchmarks/latest_metrics_summary.md`

2. 상태 문서 갱신
- `plan/IMPLEMENTATION_STATUS.md` 성능 섹션은 summary 산출물의 최신 UTC를 기준으로 갱신한다.

## 6) 실패 대응
1. 벤치 또는 summary gate 실패 시 즉시 중단
2. strict gate 실패 시 즉시 중단
3. 재개 시 `-StartStep` 옵션 사용
- 예: `tools\\bench\\run_user_delegated.cmd -RunRemainingMatrix -StartStep <failed_step>`

## 7) 운영 메모
- `RunGraphProbeOnly` 모드는 기존 단일 목적 유지 정책에 따라 운영 검증 phase를 실행하지 않는다.
- 일반 배치 경로에서는 운영 검증 phase가 기본 포함된다.
