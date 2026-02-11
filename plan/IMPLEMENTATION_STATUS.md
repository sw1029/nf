> 구현 순서(Phase) 통제: `plan/IMPLEMENTATION_CHECKLIST.md`

# 구현/보완 현황 및 잔여 TODO (기준일: 2026-02-08)

## 1) 문서 목적
- 본 문서는 아래 3개 기준 문서의 요구사항/의도 대비, 현재 레포 구현 상태를 정량/정성으로 정리한다.
- 장시간 소크(8시간)와 초대형(800화) 벤치는 사용자 위임 범위로 분리하고, 즉시 실행 가능한 단기/중기 검증 결과를 반영한다.
- 잔여 TODO를 우선순위와 완료 기준(DoD)까지 포함해 통합 관리한다.

## 2) 기준 문서 및 전역 정보
- 기준 요구 문서:
  - `plan/user_request.md`
  - `plan/architecture_1.md`
  - `plan/architecture_2.md`
- 기준 실행 환경:
  - OS: Windows 11 (로컬)
  - Python: 3.11.0rc2
  - Orchestrator URL: `http://127.0.0.1:8085`
  - 기본 DB: `nf_orchestrator.sqlite3`
  - 벤치 데이터셋:
    - `verify/datasets/DS-GROWTH-50.jsonl`
    - `verify/datasets/DS-GROWTH-200.jsonl`
    - `verify/datasets/DS-GROWTH-800.jsonl` (사용자 위임)
- 공통 검증 키:
  - `job_events.payload` 메트릭:
    - `elapsed_ms`, `rss_mb_peak`, `claims_processed`, `chunks_processed`, `rows_scanned`, `shards_loaded`
  - pytest 마커:
    - `perf`, `soak`, `e2e_large`

## 3) 전체 반영도 요약
- `user_request.md` 반영도: 약 75%
- `architecture_1.md` 반영도: 약 85%
- `architecture_2.md` 반영도: 약 80%

요약 판단:
- 핵심 파이프라인(문서-스키마-검색-정합성-근거 저장)은 실동작 수준으로 확보.
- 대규모 확장 시 핵심 병목은 `CONSISTENCY` 지연(p95)으로 수렴.
- 고급 모델 품질(Layer3/NLI)과 일부 UI 연동(요청형 grouping 제어)은 추가 보완 필요.

## 4) `user_request.md` 요구사항 반영도

| ID | 요구사항 요약 | 반영도 | 현재 상태 | 근거(대표) |
|---|---|---|---|---|
| 1 | 설정/플롯/등장인물 문서화 및 분류 | 충족 | 프로젝트/문서/에피소드/태그/엔티티 관리 가능 | `modules/nf_orchestrator/main.py` |
| 2 | 인덱싱/임베딩(RAG) | 충족 | FTS + Vector 인덱싱/조회 경로 운영 | `modules/nf_workers/runner.py` |
| 3 | 정합성 위배 탐지/세그멘테이션/근거/신뢰성/예외 | 부분 충족 | 핵심은 동작, 고도 신뢰성 모델은 미완 | `modules/nf_consistency/engine.py` |
| 4 | 문법 교정 | 충족(규칙 기반) | Proofread job 존재 | `modules/nf_workers/runner.py` |
| 5 | 에디터 자간/줄간격/폰트 | 충족 | UI 설정/저장/반영 제공 | `modules/nf_orchestrator/user_ui.html` |
| 6 | 개선 제안 + 근거 인용 + 신뢰성 점수 | 부분 충족 | Suggest + citation 동작, 모델 품질 고도화 필요 | `modules/nf_workers/runner.py` |
| 7 | txt/docx export | 충족 | export job 제공 | `modules/nf_workers/runner.py` |
| 8 | n~m episode chunk 구성 | 부분 충족 | episode 연계 chunking 지원, UX 고도화 여지 | `modules/nf_workers/runner.py` |
| 8-1 | time_key/entity_id 기준 group/filter | 부분 충족 | entity/time anchor 생성/필터 경로 존재 | `modules/nf_workers/runner.py` |
| 9 | DB 설계 + 룰 기반 우선 + 확장 고려 | 충족 | 조회 인덱스/룰 기반 확대 반영 | `modules/nf_orchestrator/storage/db.py` |
| 10 | 고비용 모델 선택적 사용 | 충족 | 설정 기반 opt-in 구조 | `modules/nf_model_gateway/gateway.py` |
| 11 | 정합성 모델 vs 생성 모델 분리 | 부분 충족 | 목적별 분기 존재, 게이트웨이 세분화 여지 | `modules/nf_model_gateway/gateway.py` |
| 12 | 3단 검증 + unknown 처리 | 부분 충족 | unknown 강등/근거 강제 적용, Layer3 실효성 미완 | `modules/nf_consistency/engine.py` |

## 5) `architecture_1.md`, `architecture_2.md` 의도 반영도

### 5.1 구조/프로세스 분리
- 충족:
  - Orchestrator + Worker 분리
  - Queue lease/heartbeat/cancel 구조
  - FTS/Vector 검색 계층 분리
- 근거:
  - `modules/nf_orchestrator/main.py`
  - `modules/nf_workers/runner.py`
  - `modules/nf_orchestrator/storage/repos/job_repo.py`

### 5.2 운영 정책(세마포어/루프백/SSE)
- 충족:
  - heavy job semaphore
  - loopback 제약
  - SSE 이벤트 스트리밍
- 근거:
  - `modules/nf_orchestrator/main.py`

### 5.3 스토리지/인덱싱
- 충족:
  - SQLite + docstore + vector shard manifest
  - DB 인덱스 보강
  - vector shard cache(LRU) 도입
- 근거:
  - `modules/nf_orchestrator/storage/db.py`
  - `modules/nf_retrieval/vector/manifest.py`

### 5.4 미반영/부분
- 부분:
  - 데스크톱(PySide6) 제품 UI 전면 전환
  - 모델 게이트웨이 고도 분리(정합성/생성 각기 품질 강화)

## 6) 이번 보완 태스크 주요 개선 사항

### 6.1 정합성 정확도 및 근거 강제
- 반영:
  - `세/살`, `직업/클래스`, `재능` 추출/비교 확장
  - `explicit_only` 스코프 추가
  - `VIOLATE` 시 `CONTRADICT` 근거 누락 방지
- 근거:
  - `modules/nf_consistency/engine.py`
  - `modules/nf_schema/extraction.py`
  - `modules/nf_schema/registry.py`

### 6.2 전역정보 누락 방지(preflight)
- 반영:
  - `POST /jobs` `CONSISTENCY` 입력에 `preflight`, `schema_scope` 검증 추가
  - consistency 전 preflight로 전역 ingest/index_fts 수행
  - UI 저장 후 post-save pipeline(ingest/index_fts) 연동
- 근거:
  - `modules/nf_orchestrator/main.py`
  - `modules/nf_workers/runner.py`
  - `modules/nf_orchestrator/user_ui.html`

### 6.3 성능 기반 보강
- 반영:
  - FTS query 안전화/필터 확장/통계 수집
  - vector shard/manifest cache + query stats 수집
  - chunk 과분할 완화(min chunk merge)
  - DB 보조 인덱스 추가
- 근거:
  - `modules/nf_retrieval/fts/query_builder.py`
  - `modules/nf_retrieval/fts/fts_index.py`
  - `modules/nf_retrieval/vector/manifest.py`
  - `modules/nf_schema/chunking.py`
  - `modules/nf_orchestrator/storage/db.py`

### 6.4 테스트/벤치 체계
- 반영:
  - e2e/perf 테스트 추가
  - 벤치 스크립트(데이터셋/파이프라인/소크) 추가
  - 런북 추가
- 근거:
  - `tests/e2e/test_global_context_detection.py`
  - `tests/perf/test_large_novel_pipeline.py`
  - `tests/test_nf_consistency_scope_and_slots.py`
  - `tools/bench/build_novel_dataset.py`
  - `tools/bench/run_pipeline_bench.py`
  - `tools/bench/run_soak.py`
  - `verify/benchmark_runbook.md`

## 7) 테스트 실행 현황 및 결과 (장시간 제외)

### 7.1 테스트 실행 결과
- `pytest -q -m "not perf and not soak"`: 통과
- `pytest -q tests/e2e/test_global_context_detection.py`: 통과
- `NF_RUN_PERF_TESTS=1; pytest -q -m perf`: 통과

### 7.2 파이프라인 벤치 결과
- 결과 파일:
  - `verify/benchmarks/20260207T170707Z.json` (50화)
  - `verify/benchmarks/20260207T172225Z.json` (200화)
  - `verify/benchmarks/comparison_50_vs_200.md` (비교 요약)
- 핵심 수치:
  - FTS p95: 약 104ms 수준(양호)
  - 실패 카운트: 0건
  - Consistency p95:
    - 50화: 2739ms
    - 200화: 7573ms
- 판정:
  - 검색(FTS) 경로는 안정적
  - 정합성 경로는 대규모에서 지연 증가가 뚜렷(우선 병목)

## 8) 잔여 TODO (우선순위/완료 기준)

### P0 (즉시)
- [ ] Consistency 병목 계측 세분화
  - 작업:
    - claim 수, claim당 retrieval 시간, DB 조회 시간 분리 계측
    - job_events payload에 단계별 timing 추가(내부 분석용)
  - DoD:
    - 200화 케이스에서 병목 상위 2개 구간 식별 가능
- [ ] 200화 벤치 2회 재측정(분산 확인)
  - 작업:
    - 동일 조건 2회 재실행
  - DoD:
    - p95 편차 범위 문서화(평균/표준편차)

### P1 (단기)
- [ ] Layer3 모델 실효성 보강
  - 작업:
    - `nli_score` 고정값(0.5) 탈피
    - evidence_required 정책 유지한 상태에서 최소 분류기/룰 점수 연결
  - DoD:
    - UNKNOWN/VIOLATE 경계에서 재현 가능한 개선 지표 확보
- [ ] explicit_only/approved 혼용 정책 정리
  - 작업:
    - 사실 레이어 우선순위/버전 선택 규칙 문서화 및 테스트 추가
  - DoD:
    - 스키마 스코프별 기대 동작이 테스트로 고정

### P2 (중기)
- [ ] 요청형 grouping UX 노출 강화(entity/time_key/timeline_idx)
  - 작업:
    - UI에서 grouping 옵션 토글/요청형 실행 경로 추가
  - DoD:
    - 사용자 조작만으로 entity/time filter retrieval 재현 가능
- [ ] Suggest 품질 고도화
  - 작업:
    - citation 품질 규칙 강화(문서/섹션/tag_path 일관성)
  - DoD:
    - 제안 결과에 근거 누락률 0% 유지

### 사용자 위임(장시간)
- [ ] 800화 벤치
  - `python tools/bench/run_pipeline_bench.py --base-url http://127.0.0.1:8085 --dataset verify/datasets/DS-GROWTH-800.jsonl --limit-docs 800 --consistency-samples 100 --output-dir verify/benchmarks`
- [ ] 8시간 소크
  - `python tools/bench/run_soak.py --base-url http://127.0.0.1:8085 --db-path nf_orchestrator.sqlite3 --hours 8 --output-dir verify/benchmarks`
- [ ] 최종 게이트 확인
  - `failed_ratio < 1%`
  - `orchestrator_crashes == 0`
  - `rss_drift_pct < 15`
  - `queue_lag_p95_ms < 60000`

## 9) 리스크 및 관리 방안
- 리스크:
  - Consistency 지연이 문서 수 증가와 함께 비선형 상승 가능
  - Layer3 품질 미완으로 UNKNOWN 과다 가능
- 관리:
  - 단계별 계측 고정 + benchmark 회귀 자동화
  - 모델 의존 경로는 opt-in 유지, 근거 강제 정책 유지

## 10) 다음 업데이트 규칙
- 본 문서는 기능/성능 변화가 발생할 때마다 갱신한다.
- 갱신 시 최소 포함 항목:
  - 테스트 통과/실패 요약
  - 벤치 파일 경로
  - TODO 상태 변경(완료/보류/신규)
