# nf-retrieval (FTS/Vector) — MoSCoW 구현 계획

nf-retrieval은 “정확 인용(FTS)”과 “의미 확장(Vector shards)”를 제공한다.

중요 정책(D5):

- UI sync query는 **FTS-only**
- Vector retrieval은 **RETRIEVE_VEC job**으로 실행하고 결과를 스트리밍한다

참조:

- `plan/contracts.md`
- `plan/architecture_2.md` (fts_docs, vector_manifest, chunk_map)

---

# [M] Must — 1차 배포(MVP+안정화)

## 0) 패키지/폴더 구조(placeholder 기준)

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

## 1) FTS (sync, 인용 우선)

* ☐ SQLite FTS5 인덱스 생성/갱신
  - 저장 필드: `chunk_id`, `doc_id`, `snapshot_id`, `section_path`, `tag_path`, `span_start/span_end`
* ☐ `query_builder`: claim 텍스트 + 슬롯 기반(예: 나이/시간/장소) 질의 생성
* ☐ `snippet`: Evidence 스니펫 생성(길이 제한, tag_path/section_path 포함)
* ☐ API: `fts_search(request: RetrievalRequest) -> RetrievalResult[]`

## 2) Vector (비동기 job)

* ☐ shard 기반 저장/로드/언로드
* ☐ `vector_manifest.json` + `chunk_map_path`로 chunk_id ↔ 벡터 row 매핑
* ☐ API(워커용): `vector_search(request) -> RetrievalResult[]`
* ☐ job 타입: `RETRIEVE_VEC`에서만 외부 노출(D5)

## 3) RetrievalResult 계약

* ☐ 최소 필드:
  - `evidence`: `doc_id/snapshot_id/chunk_id/section_path/tag_path/snippet/fts_score/match_type/confirmed`
  - `score`(fts_score 또는 vector score), `source`(fts|vector)

## 4) 테스트(pytest)

* ☐ `tests/test_nf_retrieval_contracts.py`: RetrievalRequest/Result 계약(TypedDict) + Searcher Protocol 스모크
* ☐ (차순위) FTS 인덱스 구축/검색 스모크(임시 SQLite)
* ☐ (차순위) snippet 길이/메타 포함 테스트
* ☐ (차순위) manifest/chunk_map 구조 validation 테스트

---

# [S] Should — 권장

* ☐ Vector rerank(경량) 옵션(워커 내부)
* ☐ shard 선택 로직 고도화(episode overlap + 최근 사용 + doc_type)
* ☐ RETRIEVE_VEC 결과 캐시(프리징 방지 범위 내)

---

# [C] Could — 여유 시

* ☐ semantic chunking 고도화(문서 타입별)

---

# [W] Won’t (now)

* ☐ GraphRAG/RAPTOR를 기본 경로에 강제

---

## 계약 인터페이스(요약)

- Inputs: `RetrievalRequest(pid, query, filters, k)`
- Outputs: `RetrievalResult[]` (Evidence 포함)
- Sync path: FTS-only
- Async path: `RETRIEVE_VEC` job + `JobEvent.payload.results[]`

---

## 계약 인터페이스(상세; 구현 기준)

```python
from typing import Protocol, TypedDict


class RetrievalRequest(TypedDict):
    pid: str
    query: str
    filters: dict  # tag_path/section/episode 등
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
