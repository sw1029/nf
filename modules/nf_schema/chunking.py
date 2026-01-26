from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from modules.nf_shared.protocol.dtos import Chunk, FactSource


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_chunks(
    *,
    project_id: str,
    doc_id: str,
    snapshot_id: str,
    text: str,
    max_chars: int = 800,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    section_index = 0
    for match in re.finditer(r".+?(?:\n\n|$)", text, flags=re.S):
        block = match.group(0)
        if not block.strip():
            continue
        block_start = match.start()
        block_end = match.end()
        if len(block) <= max_chars:
            chunks.append(
                Chunk(
                    chunk_id=str(uuid.uuid4()),
                    project_id=project_id,
                    doc_id=doc_id,
                    snapshot_id=snapshot_id,
                    section_path=f"section/{section_index}",
                    episode_id=None,
                    span_start=block_start,
                    span_end=block_end,
                    token_count_est=None,
                    created_by=FactSource.AUTO,
                    created_at=_now_ts(),
                )
            )
        else:
            start = block_start
            sub_index = 0
            while start < block_end:
                end = min(start + max_chars, block_end)
                chunks.append(
                    Chunk(
                        chunk_id=str(uuid.uuid4()),
                        project_id=project_id,
                        doc_id=doc_id,
                        snapshot_id=snapshot_id,
                        section_path=f"section/{section_index}/{sub_index}",
                        episode_id=None,
                        span_start=start,
                        span_end=end,
                        token_count_est=None,
                        created_by=FactSource.AUTO,
                        created_at=_now_ts(),
                    )
                )
                start = end
                sub_index += 1
        section_index += 1
    if not chunks:
        chunks.append(
            Chunk(
                chunk_id=str(uuid.uuid4()),
                project_id=project_id,
                doc_id=doc_id,
                snapshot_id=snapshot_id,
                section_path="section/0",
                episode_id=None,
                span_start=0,
                span_end=len(text),
                token_count_est=None,
                created_by=FactSource.AUTO,
                created_at=_now_ts(),
            )
        )
    return chunks
