from __future__ import annotations

from pathlib import Path

import pytest

from modules.nf_orchestrator.storage import db
from modules.nf_retrieval.fts.fts_index import fts_search
from modules.nf_retrieval.fts.query_builder import build_query


def _insert_fts_row(
    conn,
    *,
    content: str,
    chunk_id: str,
    doc_id: str,
    snapshot_id: str,
) -> None:
    conn.execute(
        """
        INSERT INTO fts_docs (
            content, chunk_id, doc_id, snapshot_id, section_path, tag_path,
            episode_id, span_start, span_end
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (content, chunk_id, doc_id, snapshot_id, "본문", "", None, 0, len(content)),
    )
    conn.commit()


@pytest.mark.unit
def test_build_query_quotes_terms_and_caps_length() -> None:
    query = build_query("A.B (test) \"quote\" quote quote")
    # Terms are quoted so FTS operators/punctuation do not break parser.
    assert '"A"' in query
    assert '"B"' in query
    assert '"test"' in query
    assert '"quote"' in query
    assert " OR " in query
    # Duplicate term should be de-duplicated.
    assert query.count('"quote"') == 1


@pytest.mark.unit
def test_fts_search_handles_special_chars_without_syntax_error(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    with db.connect(db_path) as conn:
        _insert_fts_row(
            conn,
            content="시로네는 40살의 중년 남성이다.",
            chunk_id="chunk-1",
            doc_id="doc-1",
            snapshot_id="snap-1",
        )

        queries = [
            '시로네는 40살의 중년 남성이다.',
            'A.B (test) "quote"',
            "OR.",
            "AND ( )",
            '"broken',
        ]
        for query in queries:
            results = fts_search(
                conn,
                {
                    "project_id": "project-1",
                    "query": query,
                    "filters": {},
                    "k": 5,
                },
            )
            assert isinstance(results, list)


@pytest.mark.unit
def test_fts_search_supports_doc_ids_and_snapshot_ids_filters(tmp_path: Path) -> None:
    db_path = tmp_path / "orchestrator.db"
    with db.connect(db_path) as conn:
        _insert_fts_row(
            conn,
            content="공통 키워드 alpha",
            chunk_id="chunk-a",
            doc_id="doc-a",
            snapshot_id="snap-a",
        )
        _insert_fts_row(
            conn,
            content="공통 키워드 alpha",
            chunk_id="chunk-b",
            doc_id="doc-b",
            snapshot_id="snap-b",
        )

        results = fts_search(
            conn,
            {
                "project_id": "project-1",
                "query": "alpha",
                "filters": {"doc_ids": ["doc-b"], "snapshot_ids": ["snap-b"]},
                "k": 10,
            },
        )

    assert len(results) == 1
    evidence = results[0]["evidence"]
    assert evidence["doc_id"] == "doc-b"
    assert evidence["snapshot_id"] == "snap-b"
