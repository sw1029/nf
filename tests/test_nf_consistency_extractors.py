from __future__ import annotations

import pytest

from modules.nf_consistency.extractors.contracts import ExtractionMapping
from modules.nf_consistency.extractors.pipeline import ExtractionPipeline
from modules.nf_consistency.extractors.rule_extractor import validate_regex_pattern


class _FakeGateway:
    def nli_score(self, bundle):  # pragma: no cover - not used in these tests
        return 0.5

    def propose_text(self, bundle):  # pragma: no cover - not used in these tests
        return {"text": "", "citations": []}

    def extract_slots_local(self, bundle):
        return [
            {
                "slot_key": "age",
                "value": 99,
                "confidence": 0.99,
                "span_start": 0,
                "span_end": 0,
                "matched_text": "99",
            }
        ]

    def extract_slots_remote(self, bundle):
        return []


@pytest.mark.unit
def test_validate_regex_pattern_rejects_unsafe_nested_quantifier() -> None:
    with pytest.raises(ValueError):
        validate_regex_pattern("(.*)+")


@pytest.mark.unit
def test_extraction_pipeline_user_mapping_extracts_non_builtin_pattern() -> None:
    mapping = ExtractionMapping(
        mapping_id="m1",
        project_id="p1",
        slot_key="job",
        pattern=r"class:\s*([^\n,.]+)",
        flags="I",
        transform="strip",
        priority=999,
        enabled=True,
        created_by="USER",
        created_at="2026-02-11T00:00:00Z",
    )
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[mapping], gateway=None)
    result = pipeline.extract("Class: Arcane Engineer")

    assert result.slots.get("job") == "Arcane Engineer"
    assert any(c.source == "user_mapping" and c.slot_key == "job" for c in result.candidates)


@pytest.mark.unit
def test_extraction_pipeline_hybrid_local_does_not_override_rule_result() -> None:
    pipeline = ExtractionPipeline(
        profile={"mode": "hybrid_local", "model_slots": ["age"], "model_timeout_ms": 500},
        mappings=[],
        gateway=_FakeGateway(),
    )
    result = pipeline.extract("주인공은 14세였다.")

    # Rule extractor already filled age, so local model output must not override it.
    assert result.slots.get("age") == 14
    assert not any(c.source == "local_model" and c.slot_key == "age" for c in result.candidates)

