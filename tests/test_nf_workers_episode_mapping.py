from __future__ import annotations

import pytest

from modules.nf_shared.protocol.dtos import Document, DocumentType, Episode
from modules.nf_workers import runner


def _build_doc(*, title: str, metadata: dict | None = None) -> Document:
    return Document(
        doc_id="doc-1",
        project_id="project-1",
        title=title,
        type=DocumentType.EPISODE,
        path="/tmp/doc.txt",
        head_snapshot_id="snap-1",
        checksum="sha256:test",
        version=1,
        created_at="2026-02-23T00:00:00Z",
        updated_at="2026-02-23T00:00:00Z",
        metadata=metadata or {},
    )


@pytest.mark.unit
def test_extract_episode_number_prefers_metadata_episode_no() -> None:
    doc = _build_doc(title="에피소드 99", metadata={"episode_no": "12"})
    assert runner._extract_episode_number(doc) == 12


@pytest.mark.unit
def test_extract_episode_number_falls_back_to_title_digits() -> None:
    doc = _build_doc(title="EP 07 - 시작", metadata={})
    assert runner._extract_episode_number(doc) == 7


@pytest.mark.unit
def test_extract_episode_number_non_episode_returns_none() -> None:
    doc = Document(
        doc_id="setting-1",
        project_id="project-1",
        title="설정집",
        type=DocumentType.SETTING,
        path="/tmp/setting.txt",
        head_snapshot_id="snap-s",
        checksum="sha256:test",
        version=1,
        created_at="2026-02-23T00:00:00Z",
        updated_at="2026-02-23T00:00:00Z",
        metadata={"episode_no": "5"},
    )
    assert runner._extract_episode_number(doc) is None


@pytest.mark.unit
def test_resolve_episode_id_uses_extracted_episode_number() -> None:
    doc = _build_doc(title="에피소드 100", metadata={"episode_no": 8})
    episodes = [
        Episode(
            episode_id="ep-1-5",
            project_id="project-1",
            start_n=1,
            end_m=5,
            label="초반",
            created_at="2026-02-23T00:00:00Z",
        ),
        Episode(
            episode_id="ep-6-10",
            project_id="project-1",
            start_n=6,
            end_m=10,
            label="중반",
            created_at="2026-02-23T00:00:00Z",
        ),
    ]
    assert runner._resolve_episode_id(None, "project-1", doc, episodes=episodes) == "ep-6-10"
