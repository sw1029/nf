from __future__ import annotations

import hashlib
from pathlib import Path
from modules.nf_orchestrator.storage import db
from modules.nf_orchestrator.storage.repos import evidence_repo, ignore_repo, whitelist_repo
from modules.nf_retrieval.contracts import RetrievalRequest, RetrievalResult
from modules.nf_retrieval.fts.fts_index import fts_search
from modules.nf_shared.protocol.dtos import Evidence, EvidenceMatchType, VerdictLog


class QueryServiceImpl:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path

    def retrieval_fts(self, req: RetrievalRequest) -> list[RetrievalResult]:
        with db.connect(self._db_path) as conn:
            results = fts_search(conn, req)
            return results

    def store_evidence_from_results(self, project_id: str, results: list[RetrievalResult]) -> list[Evidence]:
        stored: list[Evidence] = []
        with db.connect(self._db_path) as conn:
            for result in results:
                evidence_raw = result.get("evidence") or {}
                evidence = evidence_repo.new_evidence(
                    project_id=project_id,
                    doc_id=evidence_raw.get("doc_id", ""),
                    snapshot_id=evidence_raw.get("snapshot_id", ""),
                    chunk_id=evidence_raw.get("chunk_id"),
                    section_path=evidence_raw.get("section_path", ""),
                    tag_path=evidence_raw.get("tag_path", ""),
                    snippet_text=evidence_raw.get("snippet_text", ""),
                    span_start=int(evidence_raw.get("span_start", 0)),
                    span_end=int(evidence_raw.get("span_end", 0)),
                    fts_score=float(evidence_raw.get("fts_score", 0.0)),
                    match_type=EvidenceMatchType(evidence_raw.get("match_type", EvidenceMatchType.EXACT.value)),
                    confirmed=bool(evidence_raw.get("confirmed", False)),
                )
                evidence_repo.create_evidence(conn, evidence)
                stored.append(evidence)
        return stored

    def get_evidence(self, eid: str) -> Evidence | None:
        with db.connect(self._db_path) as conn:
            return evidence_repo.get_evidence(conn, eid)

    def list_verdicts(self, project_id: str, *, input_doc_id: str | None = None) -> list[VerdictLog]:
        with db.connect(self._db_path) as conn:
            verdicts = evidence_repo.list_verdicts(conn, project_id, input_doc_id=input_doc_id)
            return [v for v in verdicts]

    def get_verdict_detail(self, project_id: str, vid: str) -> dict[str, object] | None:
        with db.connect(self._db_path) as conn:
            verdict = evidence_repo.get_verdict(conn, vid)
            if verdict is None or verdict.project_id != project_id:
                return None
            evidence_items = evidence_repo.list_verdict_evidence(conn, vid)
            fingerprint = evidence_repo.get_claim_fingerprint(conn, vid)
            if not fingerprint:
                digest = hashlib.sha256(verdict.claim_text.strip().encode("utf-8")).hexdigest()
                fingerprint = f"sha256:{digest}"
            scope = verdict.input_doc_id
            whitelisted = whitelist_repo.is_whitelisted(conn, project_id, fingerprint, scope=scope)
            ignored = ignore_repo.is_ignored(conn, project_id, fingerprint, scope=scope, kind="CONSISTENCY")
            return {
                "verdict": verdict,
                "evidence": evidence_items,
                "claim_fingerprint": fingerprint,
                "whitelisted": whitelisted,
                "ignored": ignored,
            }
