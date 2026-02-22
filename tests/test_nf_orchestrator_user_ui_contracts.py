from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.unit
def test_user_ui_search_renderer_uses_retrieval_evidence_shape() -> None:
    html = Path("modules/nf_orchestrator/user_ui.html").read_text(encoding="utf-8")
    assert "evidence.snippet_text" in html
    assert "r.text.substring" not in html


@pytest.mark.unit
def test_user_ui_verdict_renderer_uses_current_api_fields() -> None:
    html = Path("modules/nf_orchestrator/user_ui.html").read_text(encoding="utf-8")
    assert "claim_text" in html
    assert "reliability_overall" in html
    assert "unknown_reasons" in html
    assert "analysis-card.unknown" in html
    assert "v.claim ||" not in html


@pytest.mark.unit
def test_user_ui_fetches_verdict_detail_endpoint() -> None:
    html = Path("modules/nf_orchestrator/user_ui.html").read_text(encoding="utf-8")
    assert "/query/verdicts/${encodeURIComponent(vid)}?project_id=${encodeURIComponent(state.projectId)}" in html


@pytest.mark.unit
def test_user_ui_export_formats_match_backend_contract() -> None:
    html = Path("modules/nf_orchestrator/user_ui.html").read_text(encoding="utf-8")
    assert 'name="export-fmt" value="txt"' in html
    assert 'name="export-fmt" value="docx"' in html
    assert 'name="export-fmt" value="json"' not in html


@pytest.mark.unit
def test_user_ui_has_background_consistency_hooks() -> None:
    html = Path("modules/nf_orchestrator/user_ui.html").read_text(encoding="utf-8")
    assert "_segmentTextForConsistency" in html
    assert "pendingConsistencySegments" in html
    assert "scheduleBackgroundConsistencyCheck" in html
    assert "runBackgroundConsistencyCheck" in html
    assert "toggle-show-ok" in html
