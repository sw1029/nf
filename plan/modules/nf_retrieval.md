# nf-retrieval (FTS/벡터) — MoSCoW 구현 계획

nf-retrieval은 “정확 인용(FTS)”과 “의미 확장(벡터 샤드)”를 제공한다.

> 표기 규칙: ☐ TODO / ☑ Done / ◐ Partial(스텁/의도 미적용)

중요 정책(D5):

- UI 동기 쿼리는 **FTS-only**
- 벡터 검색은 **RETRIEVE_VEC 잡**으로 실행하고 결과를 스트리밍한다

참조:

- `plan/contracts.md`
- `plan/architecture_2.md` (fts_docs, vector_manifest, chunk_map)

구현 순서(Phase, 전체 로드맵: `plan/IMPLEMENTATION_CHECKLIST.md`):

테스트는 conda의 `nf` 환경에서 수행한다.

- Phase 30: FTS 인덱스 + 동기 검색(FTS-only) (제품/디버그 UI 공통 전제)
- Phase 70: 벡터 샤드 + `RETRIEVE_VEC` 잡 결과 스트리밍(D5)

---

# [M] 필수 — 1차 배포(MVP+안정화)

## 0) 패키지/폴더 구조(플레이스홀더 기준)

```text
modules/nf_retrieval/
  __init__.py
  fts/
    fts_index.py
    query_builder.py
    snippet.py
  vector/
    embedder.py
    manifest.py
    shard_store.py
  contracts.py
```

## 1) FTS (동기, 인용 우선)

* ◐ SQLite FTS5 인덱스 생성/갱신
  - 저장 필드: `chunk_id`, `doc_id`, `snapshot_id`, `section_path`, `tag_path`, `episode_id`, `span_start/span_end`
  - (현재) `tag_path`/`episode_id` 전파가 미완이라 필터/인용 품질이 부족함
* ◐ `query_builder`: claim 텍스트 + 슬롯 기반(예: 나이/시간/장소) 질의 생성 (현재는 공백 정규화 수준)
* ◐ `snippet`: Evidence 스니펫 생성(길이 제한) (현재는 텍스트 일부 발췌; tag_path/section_path 메타 전파는 별도)
* ☑ API: `fts_search(request: RetrievalRequest) -> RetrievalResult[]`
* ☐ fts_meta(체크섬 기반 증분 인덱싱)
* ☐ tag_path 전파: tag_assignment(span overlap) 기반으로 retrieval evidence의 tag_path를 채우기(FTS/CONSISTENCY/SUGGEST 공통)
* ◐ (추가 요구) filters 확장: `entity_id/time_key/timeline_idx`로 chunk group 필터링 지원
  - 1차: `entity_mention_span/time_anchor`의 span overlap 기반 필터(사용자 요청 시 생성된 메타)
  - 2차: `chunk ↔ entity/time` 역인덱스(옵션)로 최적화

## 2) 벡터 (비동기 잡)

* ◐ shard 기반 저장/로드/언로드 (현재는 저장/로드 위주; LRU/언로드는 미구현)
* ◐ `vector_manifest.json` + `chunk_map_path`로 chunk_id ↔ 벡터 row 매핑 (현재는 manifest/shard만 존재)
* ☑ API(워커용): `vector_search(request) -> RetrievalResult[]`
* ☑ 잡 타입: `RETRIEVE_VEC`에서만 외부 노출(D5)
* ◐ (추가 요구) filters.entity_id/time_key/timeline_idx 적용(워커 post-filter 또는 샤드 메타데이터 기반)
* ☐ vector shard에 tag_path/episode_id 등 메타 포함(또는 post-filter 보강)하여 “근거 인용” 품질 보장

## 3) RetrievalResult 계약

* ◐ 최소 필드:
  - `evidence`: `doc_id/snapshot_id/chunk_id/section_path/tag_path/snippet/fts_score/match_type/confirmed`
  - `score`(fts_score 또는 벡터 점수), `source`(fts|vector)
  - (현재) tag_path가 비어 있는 경로가 있어 “태그 경로 인용” 의도는 미반영

## 4) 테스트(pytest)

* ☑ `tests/test_nf_retrieval_contracts.py`: RetrievalRequest/Result 계약(TypedDict) + Searcher 프로토콜 스모크
* ☐ (차순위) FTS 인덱스 구축/검색 스모크(임시 SQLite)
* ☐ (차순위) snippet 길이/메타 포함 테스트
* ☐ (차순위) manifest/chunk_map 구조 검증 테스트

---

# [S] 권장 — 권장

* ☐ 벡터 재랭크(경량) 옵션(워커 내부)
* ☐ 샤드 선택 로직 고도화(에피소드 중첩 + 최근 사용 + doc_type)
* ☐ RETRIEVE_VEC 결과 캐시(프리징 방지 범위 내)

---

# [C] 선택 — 여유 시

* ☐ semantic chunking 고도화(문서 타입별)

---

# [W] 현재 제외

* ☐ GraphRAG/RAPTOR를 기본 경로에 강제

---

## 계약 인터페이스(요약)

- Inputs: `RetrievalRequest(project_id, query, filters, k)`
- Outputs: `RetrievalResult[]` (Evidence 포함)
- Sync path: FTS-only
- Async path: `RETRIEVE_VEC` job + `JobEvent.payload.results[]`

---

## 계약 인터페이스(상세; 구현 기준)

```python
from typing import Protocol, TypedDict


class RetrievalRequest(TypedDict):
    project_id: str
    query: str
    filters: dict  # tag_path/section/episode/entity_id/time_key/timeline_idx 등
    k: int

class RetrievalResult(TypedDict):
    source: str  # "fts" | "vector"
    score: float
    evidence: dict  # Evidence DTO subset

class FTSSearcher(Protocol):
    def search(self, req: RetrievalRequest) -> list[RetrievalResult]: ...

class VectorSearcher(Protocol):
    def search(self, req: RetrievalRequest) -> list[RetrievalResult]: ...
```

Sync query는 `FTSSearcher`만 사용하고, vector는 `RETRIEVE_VEC` job에서만 외부로 노출한다.
