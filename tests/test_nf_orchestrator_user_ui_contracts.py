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
    assert "v.claim || '내용 없음'" not in html


@pytest.mark.unit
def test_user_ui_fetches_verdict_detail_endpoint() -> None:
    html = Path("modules/nf_orchestrator/user_ui.html").read_text(encoding="utf-8")
    assert "/query/verdicts/${encodeURIComponent(vid)}?project_id=${encodeURIComponent(state.projectId)}" in html
