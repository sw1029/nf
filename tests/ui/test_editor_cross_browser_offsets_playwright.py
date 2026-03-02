from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.mark.browser
def test_editor_cross_browser_offsets_roundtrip_and_highlight() -> None:
    if os.getenv("NF_RUN_BROWSER_TESTS") != "1":
        pytest.skip("set NF_RUN_BROWSER_TESTS=1 to run cross-browser playwright checks")

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - depends on local runtime
        pytest.skip(f"playwright unavailable: {exc}")

    fixture = (Path(__file__).parent / "fixtures" / "editor_harness.html").resolve()
    url = fixture.as_uri()
    paragraph = (
        "In the city archive, Mina logged every clue and crossed each witness statement "
        "with timeline tags so nothing drifted between chapters. "
    )
    long_text = (paragraph * 140).strip()

    page_counts: dict[str, int] = {}
    with sync_playwright() as playwright:
        browser_matrix = (
            ("chromium", playwright.chromium),
            ("firefox", playwright.firefox),
            ("webkit", playwright.webkit),
        )
        for browser_name, browser_type in browser_matrix:
            console_errors: list[str] = []
            browser = browser_type.launch(headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()
            page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda err: console_errors.append(str(err)))

            page.goto(url, wait_until="domcontentloaded")
            page.evaluate("(text) => window.__setText(text)", long_text)
            page.evaluate("(span) => window.__setSelectionOffsets(span[0], span[1])", [220, 280])
            first_roundtrip = page.evaluate("() => window.__getSelectionOffsets()")
            assert first_roundtrip == {"start": 220, "end": 280}

            for width, height in ((1200, 840), (980, 820), (1360, 920), (860, 780)):
                page.set_viewport_size({"width": width, "height": height})
                budget = max(500, round(width * 0.85))
                page.evaluate("(b) => window.__repaginateWithBudget(b)", budget)
                roundtrip = page.evaluate("() => window.__getSelectionOffsets()")
                assert roundtrip == {"start": 220, "end": 280}

            highlight_span = [430, 495]
            expected = long_text[highlight_span[0] : highlight_span[1]]
            actual = page.evaluate(
                "(span) => { window.__applyHighlight(span[0], span[1]); return window.__highlightedText(); }",
                highlight_span,
            )
            assert actual == expected

            page_counts[browser_name] = int(page.evaluate("() => window.__pageCount()"))
            assert not console_errors

            context.close()
            browser.close()

    assert set(page_counts.keys()) == {"chromium", "firefox", "webkit"}
    assert max(page_counts.values()) - min(page_counts.values()) <= 2, f"cross-browser page count drift: {page_counts}"
