# nf-graphrag (옵션형 그래프 하이브리드) — MoSCoW 구현 계획

nf-graphrag는 전역정보(entity/time/timeline/facts)를 프로젝트 단위 그래프로 물질화하고,
`RETRIEVE_VEC` 경로에서 옵션형 rerank를 수행한다.

> 표기 규칙: ☐ TODO / ☑ Done / ◐ Partial(스텁/의도 미적용)

중요 정책:

- 기본 경로는 유지: sync retrieval은 FTS-only, vector는 async job
- GraphRAG는 옵션형(additive) 경로로만 동작
- 기본값은 `graph.enabled=false`

참조:

- `plan/contracts.md`
- `plan/architecture_2.md`
- `plan/DECISIONS_PENDING.md` (D7)

구현 순서(Phase, 전체 로드맵: `plan/IMPLEMENTATION_CHECKLIST.md`):

테스트는 conda의 `nf` 환경에서 수행한다.

- Phase 72: graph materialize + rerank 옵션 경로 도입

---

# [M] 필수 — 1차 배포(MVP+안정화)

## 0) 패키지/폴더 구조(플레이스홀더 기준)

```text
modules/nf_retrieval/graph/
  __init__.py
  materialized.py
  rerank.py
```

## 1) graph source 정규화

* ☑ 소스 범위(프로젝트 단위):
  - `entity_mention_span`
  - `time_anchor`
  - `timeline_event`
  - `schema_facts(status=APPROVED)`
* ☑ edge/node 중복 제거 + 최소 정규화
* ☑ materialized graph 저장(`.../vector/graph/<project_id>.json`)

## 2) graph materialize 트리거

* ☑ `INDEX_FTS.params.grouping.graph_extract=true`일 때만 graph 추출 수행
* ☑ 기본값은 off(`false`), 기존 INDEX_FTS 계약과 충돌 없음
* ☑ 실패 시 인덱싱 전체를 중단하지 않고 graph 블록만 경고/축소

## 3) graph rerank 실행 경로

* ☑ `RETRIEVE_VEC.params.graph.enabled=true`일 때만 rerank 수행
* ☑ 파라미터:
  - `max_hops` (1|2, 기본 1)
  - `rerank_weight` (0.0~0.5, 기본 0.25)
* ☑ fallback:
  - graph 로드 실패/seed 없음이면 기존 vector 결과 유지
* ☑ payload에 graph 메타(`applied`, `seed_docs`, `expanded_docs`) 포함

## 4) 테스트(pytest)

* ☑ `tests/test_nf_retrieval_graph_rerank.py`:
  - seeded doc boost 동작
  - seed 없음 시 no-op 동작
* ◐ graph on/off A/B 성능 회귀(DS-200/800)는 벤치 스크립트 기반 수동 게이트

---

# [S] 권장 — 권장

* ☐ graph seed 품질 개선(질의/alias/time_key 혼합 전략)
* ☐ graph edge 신뢰도 가중치 학습/튜닝
* ☐ project graph warmup/캐시 도입

---

# [C] 선택 — 여유 시

* ◐ RAPTOR experimental skeleton(플러그인 스켈레톤, 기본 경로 미연결)
* ☐ graph + rule + vector 결합 점수 자동 튜닝

---

# [W] 현재 제외

* ☑ GraphRAG를 기본 경로에 강제
* ☑ RAPTOR/SELF-RAG를 기본 경로에 강제
* ☑ sync retrieval 경로에 graph 연산 삽입

---

## 계약 인터페이스(요약)

- `INDEX_FTS.params.grouping.graph_extract: bool` (기본 `false`)
- `RETRIEVE_VEC.params.graph`:
  - `enabled: bool` (기본 `false`)
  - `max_hops: int` (기본 `1`)
  - `rerank_weight: float` (기본 `0.25`)
- 기존 `RetrievalResult` 스키마는 유지, graph 관련 메타는 additive

