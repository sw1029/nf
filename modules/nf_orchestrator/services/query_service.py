from __future__ import annotations

import hashlib
from pathlib import Path
from modules.nf_orchestrator.storage import db
from modules.nf_orchestrator.storage.repos import evidence_repo, ignore_repo, schema_repo, whitelist_repo
from modules.nf_retrieval.contracts import RetrievalRequest, RetrievalResult
from modules.nf_retrieval.fts.fts_index import fts_search
from modules.nf_shared.protocol.dtos import Evidence, EvidenceMatchType, FactStatus, VerdictLog


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
                evidence_repo.create_evidence(conn, evidence, commit=False)
                stored.append(evidence)
            conn.commit()
        return stored

    def get_evidence(self, eid: str) -> Evidence | None:
        with db.connect(self._db_path) as conn:
            return evidence_repo.get_evidence(conn, eid)

    def list_verdicts(self, project_id: str, *, input_doc_id: str | None = None) -> list[VerdictLog]:
        with db.connect(self._db_path) as conn:
            verdicts = evidence_repo.list_verdicts(conn, project_id, input_doc_id=input_doc_id)
            return [v for v in verdicts]

    def build_tag_path_preview_by_vid(
        self,
        project_id: str,
        vids: list[str],
        *,
        limit_per_verdict: int = 2,
    ) -> dict[str, list[str]]:
        unique_vids = [item for item in vids if isinstance(item, str) and item]
        if not unique_vids or limit_per_verdict <= 0:
            return {}
        with db.connect(self._db_path) as conn:
            placeholders = ",".join(["?"] * len(unique_vids))
            rows = conn.execute(
                f"""
                SELECT
                    l.vid AS vid,
                    l.role AS role,
                    e.tag_path AS tag_path
                FROM verdict_evidence_link l
                JOIN evidence e ON e.eid = l.eid
                JOIN verdict_log v ON v.vid = l.vid
                WHERE v.project_id = ? AND l.vid IN ({placeholders})
                ORDER BY
                    l.vid ASC,
                    CASE WHEN l.role = 'CONTRADICT' THEN 0 ELSE 1 END ASC,
                    e.created_at ASC
                """,
                [project_id, *unique_vids],
            ).fetchall()

        previews: dict[str, list[str]] = {}
        seen: dict[str, set[str]] = {}
        cap = max(1, int(limit_per_verdict))
        for row in rows:
            vid = row["vid"]
            tag_path = row["tag_path"] or ""
            if not isinstance(vid, str) or not vid:
                continue
            if not isinstance(tag_path, str) or not tag_path:
                continue
            bucket = previews.setdefault(vid, [])
            if len(bucket) >= cap:
                continue
            dedup = seen.setdefault(vid, set())
            if tag_path in dedup:
                continue
            dedup.add(tag_path)
            bucket.append(tag_path)
        return previews

    def get_verdict_detail(self, project_id: str, vid: str) -> dict[str, object] | None:
        with db.connect(self._db_path) as conn:
            verdict = evidence_repo.get_verdict(conn, vid)
            if verdict is None or verdict.project_id != project_id:
                return None
            evidence_items = evidence_repo.list_verdict_evidence(conn, vid)
            links = evidence_repo.list_verdict_links(conn, vid)
            eids: list[str] = []
            eid_roles: dict[str, list[str]] = {}
            for link in links:
                eid = str(link.eid or "").strip()
                if not eid:
                    continue
                eids.append(eid)
                roles = eid_roles.setdefault(eid, [])
                role_value = link.role.value
                if role_value not in roles:
                    roles.append(role_value)
            fact_paths: list[dict[str, object]] = []
            if eids:
                schema_facts = schema_repo.list_schema_facts_by_evidence_ids(
                    conn,
                    project_id,
                    eids,
                    status=FactStatus.APPROVED,
                )
                dedup: set[tuple[str, str, str | None]] = set()
                for fact in schema_facts:
                    roles = eid_roles.get(fact.evidence_eid, [])
                    for role in roles:
                        key = (role, fact.tag_path, fact.entity_id)
                        if key in dedup:
                            continue
                        dedup.add(key)
                        fact_paths.append(
                            {
                                "role": role,
                                "tag_path": fact.tag_path,
                                "entity_id": fact.entity_id,
                                "source": "schema_fact",
                            }
                        )
                fact_paths.sort(key=lambda item: (str(item.get("role", "")), str(item.get("tag_path", ""))))
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
                "unknown_reasons": list(verdict.unknown_reasons),
                "fact_paths": fact_paths,
            }
