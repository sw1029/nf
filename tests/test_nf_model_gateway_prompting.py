from __future__ import annotations

import json

import pytest

from modules.nf_model_gateway.prompting import build_remote_prompt


def _extract_json(prompt: str) -> dict:
    begin = "<BEGIN_INPUT_JSON>"
    end = "<END_INPUT_JSON>"
    start = prompt.index(begin) + len(begin)
    stop = prompt.index(end)
    return json.loads(prompt[start:stop].strip())


@pytest.mark.unit
def test_build_remote_prompt_wraps_json_payload() -> None:
    prompt = build_remote_prompt({"claim_text": "hello", "evidence": [{"k": "v"}]})
    payload = _extract_json(prompt)

    assert payload["claim_text"] == "hello"
    assert payload["evidence"] == [{"k": "v"}]
    assert payload["evidence_total"] == 1
    assert payload["evidence_included"] == 1


@pytest.mark.unit
def test_build_remote_prompt_truncates_and_limits_evidence() -> None:
    evidence = [{"text": "x" * 50} for _ in range(5)]
    prompt = build_remote_prompt(
        {"claim_text": "y" * 50, "evidence": evidence},
        max_claim_chars=10,
        max_evidence_items=2,
        max_value_chars=10,
    )
    payload = _extract_json(prompt)

    assert payload["claim_text"].endswith("…")
    assert payload["evidence_total"] == 5
    assert payload["evidence_included"] == 2
    assert payload["evidence"][0]["text"].endswith("…")

