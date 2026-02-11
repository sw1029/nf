from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from modules.nf_shared.protocol.dtos import (
    Evidence,
    EvidenceMatchType,
    EvidenceRole,
    ReliabilityBreakdown,
    Span,
    Verdict,
    VerdictEvidenceLink,
    VerdictLog,
)


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fingerprint(text: str) -> str:
    digest = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _row_to_evidence(row: Any) -> Evidence:
    return Evidence(
        eid=row["eid"],
        project_id=row["project_id"],
        doc_id=row["doc_id"],
        snapshot_id=row["snapshot_id"],
        chunk_id=row["chunk_id"],
        section_path=row["section_path"],
        tag_path=row["tag_path"],
        snippet_text=row["snippet_text"],
        span_start=row["span_start"],
        span_end=row["span_end"],
        fts_score=row["fts_score"],
        match_type=EvidenceMatchType(row["match_type"]),
        confirmed=bool(row["confirmed"]),
        created_at=row["created_at"],
    )


def _row_to_verdict(row: Any) -> VerdictLog:
    breakdown = json.loads(row["breakdown_json"])
    return VerdictLog(
        vid=row["vid"],
        project_id=row["project_id"],
        input_doc_id=row["input_doc_id"],
        input_snapshot_id=row["input_snapshot_id"],
        schema_ver=row["schema_ver"],
        segment_span=Span(start=row["segment_start"], end=row["segment_end"]),
        claim_text=row["claim_text"],
        verdict=Verdict(row["verdict"]),
        reliability_overall=row["reliability_overall"],
        breakdown=ReliabilityBreakdown(
            fts_strength=breakdown.get("fts_strength", 0.0),
            evidence_count=breakdown.get("evidence_count", 0),
            confirmed_evidence=breakdown.get("confirmed_evidence", 0),
            model_score=breakdown.get("model_score", 0.0),
        ),
        whitelist_applied=bool(row["whitelist_applied"]),
        created_at=row["created_at"],
    )


def create_evidence(conn, evidence: Evidence, *, commit: bool = True) -> Evidence:
    conn.execute(
        """
        INSERT INTO evidence (
            eid, project_id, doc_id, snapshot_id, chunk_id, section_path, tag_path,
            snippet_text, span_start, span_end, fts_score, match_type, confirmed, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            evidence.eid,
            evidence.project_id,
            evidence.doc_id,
            evidence.snapshot_id,
            evidence.chunk_id,
            evidence.section_path,
            evidence.tag_path,
            evidence.snippet_text,
            evidence.span_start,
            evidence.span_end,
            evidence.fts_score,
            evidence.match_type.value,
            1 if evidence.confirmed else 0,
            evidence.created_at,
        ),
    )
    if commit:
        conn.commit()
    return evidence


def new_evidence(
    *,
    project_id: str,
    doc_id: str,
    snapshot_id: str,
    chunk_id: str | None,
    section_path: str,
    tag_path: str,
    snippet_text: str,
    span_start: int,
    span_end: int,
    fts_score: float,
    match_type: EvidenceMatchType,
    confirmed: bool,
) -> Evidence:
    return Evidence(
        eid=str(uuid.uuid4()),
        project_id=project_id,
        doc_id=doc_id,
        snapshot_id=snapshot_id,
        chunk_id=chunk_id,
        section_path=section_path,
        tag_path=tag_path,
        snippet_text=snippet_text,
        span_start=span_start,
        span_end=span_end,
        fts_score=fts_score,
        match_type=match_type,
        confirmed=confirmed,
        created_at=_now_ts(),
    )


def get_evidence(conn, eid: str) -> Evidence | None:
    row = conn.execute("SELECT * FROM evidence WHERE eid = ?", (eid,)).fetchone()
    if row is None:
        return None
    return _row_to_evidence(row)


def list_evidence(
    conn,
    project_id: str,
    *,
    doc_id: str | None = None,
    snapshot_id: str | None = None,
) -> list[Evidence]:
    query = "SELECT * FROM evidence WHERE project_id = ?"
    params: list[Any] = [project_id]
    if doc_id is not None:
        query += " AND doc_id = ?"
        params.append(doc_id)
    if snapshot_id is not None:
        query += " AND snapshot_id = ?"
        params.append(snapshot_id)
    query += " ORDER BY created_at ASC"
    rows = conn.execute(query, params).fetchall()
    return [_row_to_evidence(row) for row in rows]


def create_verdict_log(conn, verdict: VerdictLog, *, commit: bool = True) -> VerdictLog:
    claim_fingerprint = _fingerprint(verdict.claim_text)
    try:
        conn.execute(
            """
            INSERT INTO verdict_log (
                vid, project_id, input_doc_id, input_snapshot_id, schema_ver,
                segment_start, segment_end, claim_text, claim_fingerprint, verdict, reliability_overall,
                breakdown_json, whitelist_applied, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                verdict.vid,
                verdict.project_id,
                verdict.input_doc_id,
                verdict.input_snapshot_id,
                verdict.schema_ver,
                verdict.segment_span.start,
                verdict.segment_span.end,
                verdict.claim_text,
                claim_fingerprint,
                verdict.verdict.value,
                verdict.reliability_overall,
                json.dumps(
                    {
                        "fts_strength": verdict.breakdown.fts_strength,
                        "evidence_count": verdict.breakdown.evidence_count,
                        "confirmed_evidence": verdict.breakdown.confirmed_evidence,
                        "model_score": verdict.breakdown.model_score,
                    }
                ),
                1 if verdict.whitelist_applied else 0,
                verdict.created_at,
            ),
        )
    except sqlite3.OperationalError:
        conn.execute(
            """
            INSERT INTO verdict_log (
                vid, project_id, input_doc_id, input_snapshot_id, schema_ver,
                segment_start, segment_end, claim_text, verdict, reliability_overall,
                breakdown_json, whitelist_applied, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                verdict.vid,
                verdict.project_id,
                verdict.input_doc_id,
                verdict.input_snapshot_id,
                verdict.schema_ver,
                verdict.segment_span.start,
                verdict.segment_span.end,
                verdict.claim_text,
                verdict.verdict.value,
                verdict.reliability_overall,
                json.dumps(
                    {
                        "fts_strength": verdict.breakdown.fts_strength,
                        "evidence_count": verdict.breakdown.evidence_count,
                        "confirmed_evidence": verdict.breakdown.confirmed_evidence,
                        "model_score": verdict.breakdown.model_score,
                    }
                ),
                1 if verdict.whitelist_applied else 0,
                verdict.created_at,
            ),
        )
    if commit:
        conn.commit()
    return verdict


def create_verdict_links(conn, links: list[VerdictEvidenceLink], *, commit: bool = True) -> None:
    for link in links:
        conn.execute(
            """
            INSERT OR IGNORE INTO verdict_evidence_link (vid, eid, role)
            VALUES (?, ?, ?)
            """,
            (link.vid, link.eid, link.role.value),
        )
    if commit:
        conn.commit()


def list_verdicts(conn, project_id: str, *, input_doc_id: str | None = None) -> list[VerdictLog]:
    query = "SELECT * FROM verdict_log WHERE project_id = ?"
    params: list[Any] = [project_id]
    if input_doc_id is not None:
        query += " AND input_doc_id = ?"
        params.append(input_doc_id)
    query += " ORDER BY created_at ASC"
    rows = conn.execute(query, params).fetchall()
    return [_row_to_verdict(row) for row in rows]


def list_verdict_links(conn, vid: str) -> list[VerdictEvidenceLink]:
    rows = conn.execute(
        "SELECT * FROM verdict_evidence_link WHERE vid = ?",
        (vid,),
    ).fetchall()
    return [
        VerdictEvidenceLink(vid=row["vid"], eid=row["eid"], role=EvidenceRole(row["role"]))
        for row in rows
    ]


def get_verdict(conn, vid: str) -> VerdictLog | None:
    row = conn.execute("SELECT * FROM verdict_log WHERE vid = ?", (vid,)).fetchone()
    if row is None:
        return None
    return _row_to_verdict(row)


def get_claim_fingerprint(conn, vid: str) -> str | None:
    try:
        row = conn.execute("SELECT claim_fingerprint FROM verdict_log WHERE vid = ?", (vid,)).fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None:
        return None
    fingerprint = row["claim_fingerprint"]
    return fingerprint if isinstance(fingerprint, str) and fingerprint else None


def list_verdict_evidence(conn, vid: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            l.role AS role,
            e.eid AS eid,
            e.project_id AS project_id,
            e.doc_id AS doc_id,
            e.snapshot_id AS snapshot_id,
            e.chunk_id AS chunk_id,
            e.section_path AS section_path,
            e.tag_path AS tag_path,
            e.snippet_text AS snippet_text,
            e.span_start AS span_start,
            e.span_end AS span_end,
            e.fts_score AS fts_score,
            e.match_type AS match_type,
            e.confirmed AS confirmed,
            e.created_at AS created_at
        FROM verdict_evidence_link l
        JOIN evidence e ON e.eid = l.eid
        WHERE l.vid = ?
        ORDER BY e.created_at ASC
        """,
        (vid,),
    ).fetchall()
    items: list[dict[str, Any]] = []
    for row in rows:
        items.append({"role": row["role"], "evidence": _row_to_evidence(row)})
    return items
