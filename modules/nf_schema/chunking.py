from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from modules.nf_shared.protocol.dtos import Chunk, FactSource


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iter_blocks(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for match in re.finditer(r".+?(?:\n\s*\n|$)", text, flags=re.S):
        start = match.start()
        end = match.end()
        if start >= end:
            continue
        if not text[start:end].strip():
            continue
        spans.append((start, end))
    return spans


def _split_block(text: str, *, start: int, end: int, max_chars: int) -> list[tuple[int, int]]:
    if end - start <= max_chars:
        return [(start, end)]

    spans: list[tuple[int, int]] = []
    cursor = start
    while cursor < end:
        hard_end = min(cursor + max_chars, end)
        if hard_end >= end:
            spans.append((cursor, end))
            break

        segment = text[cursor:hard_end]
        split_points = [m.end() for m in re.finditer(r"[.!?。！？]\s+|\n", segment)]
        if split_points:
            rel = split_points[-1]
            next_end = cursor + rel
            if next_end <= cursor:
                next_end = hard_end
        else:
            next_end = hard_end

        spans.append((cursor, next_end))
        cursor = next_end
    return spans


def _merge_small_spans(
    spans: list[tuple[int, int]],
    *,
    min_chunk_chars: int,
    max_merge_chars: int,
) -> list[tuple[int, int]]:
    if not spans:
        return spans
    merged: list[tuple[int, int]] = [spans[0]]
    for start, end in spans[1:]:
        prev_start, prev_end = merged[-1]
        current_len = end - start
        prev_len = prev_end - prev_start
        if (current_len < min_chunk_chars or prev_len < min_chunk_chars) and (end - prev_start) <= max_merge_chars:
            merged[-1] = (prev_start, end)
            continue
        merged.append((start, end))
    return merged


def build_chunks(
    *,
    project_id: str,
    doc_id: str,
    snapshot_id: str,
    text: str,
    max_chars: int = 1200,
    min_chunk_chars: int = 240,
) -> list[Chunk]:
    spans: list[tuple[int, int]] = []
    for block_start, block_end in _iter_blocks(text):
        spans.extend(_split_block(text, start=block_start, end=block_end, max_chars=max_chars))
    if not spans:
        spans = [(0, len(text))]

    merged_spans = _merge_small_spans(
        spans,
        min_chunk_chars=max(80, min_chunk_chars),
        max_merge_chars=max_chars + max(200, max_chars // 3),
    )

    chunks: list[Chunk] = []
    for idx, (span_start, span_end) in enumerate(merged_spans):
        chunks.append(
            Chunk(
                chunk_id=str(uuid.uuid4()),
                project_id=project_id,
                doc_id=doc_id,
                snapshot_id=snapshot_id,
                section_path=f"section/{idx}",
                episode_id=None,
                span_start=span_start,
                span_end=span_end,
                token_count_est=None,
                created_by=FactSource.AUTO,
                created_at=_now_ts(),
            )
        )
    return chunks
