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


@pytest.mark.unit
def test_user_ui_exposes_advanced_consistency_controls() -> None:
    html = Path("modules/nf_orchestrator/user_ui.html").read_text(encoding="utf-8")
    assert "consistency-filter-entity" in html
    assert "consistency-filter-time" in html
    assert "consistency-filter-timeline" in html
    assert "consistency-graph-mode" in html
    assert "consistency-layer3-promotion" in html
    assert "consistency-verifier-mode" in html
    assert "consistency-triage-mode" in html
    assert "consistency-loop-enabled" in html


@pytest.mark.unit
def test_user_ui_consistency_mode_contract_values_and_checkbox_sync() -> None:
    html = Path("modules/nf_orchestrator/user_ui.html").read_text(encoding="utf-8")
    assert '<option value="auto">' in html
    assert '<option value="manual">' in html
    assert '<option value="conservative_nli">' in html
    assert '<option value="embedding_anomaly">' in html
    assert "layer3Input.checked" in html
    assert "loopInput.checked" in html
    assert "value === 'on'" not in html


@pytest.mark.unit
def test_user_ui_supports_whitelist_ignore_and_inline_highlight() -> None:
    html = Path("modules/nf_orchestrator/user_ui.html").read_text(encoding="utf-8")
    assert "markVerdictAsWhitelisted" in html
    assert "markVerdictAsIgnored" in html
    assert "renderInlineVerdictHighlights" in html
    assert "::highlight(nf-violate)" in html
    assert "::highlight(nf-unknown)" in html


@pytest.mark.unit
def test_user_ui_verdict_detail_renders_fact_paths() -> None:
    html = Path("modules/nf_orchestrator/user_ui.html").read_text(encoding="utf-8")
    assert "fact_paths" in html
    assert "CONTRADICT" in html
    assert "CONTRADICT evidence link missing" not in html


@pytest.mark.unit
def test_user_ui_wait_for_job_prefers_sse_and_falls_back_to_polling() -> None:
    html = Path("modules/nf_orchestrator/user_ui.html").read_text(encoding="utf-8")
    assert "_waitForJobViaSse" in html
    assert "_waitForJobByPolling" in html
    assert "EventSource" in html
    assert "/jobs/${encodeURIComponent(jobId)}/events" in html
