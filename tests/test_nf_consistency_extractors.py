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


@pytest.mark.unit
def test_extraction_pipeline_rejects_clause_like_talent_value() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("기감에 대한 재능은 꽤 뛰어난 편이라고 볼 수 있겠다.")

    assert result.slots == {}


@pytest.mark.unit
def test_extraction_pipeline_rejects_clause_like_place_value() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("개인마다 위치는 다르지만 결국 같은 방향으로 향했다.")

    assert result.slots == {}


@pytest.mark.unit
def test_extraction_pipeline_rejects_place_value_with_trailing_clause_tail() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("장소는 당연히 침대 위고, 방법은…")

    assert "place" not in result.slots


@pytest.mark.unit
def test_extraction_pipeline_extracts_job_value_without_terminal_copula() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("그의 직업은 마법사다.")

    assert result.slots.get("job") == "마법사"


@pytest.mark.unit
def test_extraction_pipeline_rejects_quantified_job_taxonomy_summary() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("세상에 알려진 헌터의 직업은 크게 네 가지다.")

    assert "job" not in result.slots


@pytest.mark.unit
def test_extraction_pipeline_extracts_class_based_job_value() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("이 사람. 요리사 클래스였구나.")

    assert result.slots.get("job") == "요리사"


@pytest.mark.unit
def test_extraction_pipeline_extracts_affiliation_and_job_from_affiliation_phrase() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("저는 황궁 소속의 시녀입니다.")

    assert result.slots.get("affiliation") == "황궁"
    assert result.slots.get("job") == "시녀"


@pytest.mark.unit
def test_extraction_pipeline_extracts_genitive_title_affiliation_and_job() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("라인시스 제국의 제1황녀이자, 제국의 유일한 희망이었던 자.")

    assert result.slots.get("affiliation") == "라인시스 제국"
    assert "job" not in result.slots


@pytest.mark.unit
def test_extraction_pipeline_extracts_appositive_title_affiliation_and_job() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("라인시스 제국의 제1황녀 아리아 라인시스의 이름으로 그대를 임명합니다.")

    assert result.slots.get("affiliation") == "라인시스 제국"
    assert "job" not in result.slots


@pytest.mark.unit
def test_extraction_pipeline_keeps_non_suffix_affiliation_title_phrase_when_profile_opted_in() -> None:
    default_pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)
    opt_in_pipeline = ExtractionPipeline(
        profile={"mode": "rule_only", "allow_generic_narrative_affiliation": True},
        mappings=[],
        gateway=None,
    )

    default_result = default_pipeline.extract("그녀는 라인시스의 제1황녀였다.")
    opt_in_result = opt_in_pipeline.extract("그녀는 라인시스의 제1황녀였다.")

    assert "affiliation" not in default_result.slots
    assert opt_in_result.slots.get("affiliation") == "라인시스"


@pytest.mark.unit
def test_extraction_pipeline_rejects_generic_org_title_affiliation_in_default_runtime_profile() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("그는 사도련의 백전귀였다.")

    assert "affiliation" not in result.slots


@pytest.mark.unit
def test_extraction_pipeline_allows_generic_org_title_affiliation_when_profile_opted_in() -> None:
    pipeline = ExtractionPipeline(
        profile={"mode": "rule_only", "allow_generic_narrative_affiliation": True},
        mappings=[],
        gateway=None,
    )

    result = pipeline.extract("그는 사도련의 백전귀였다.")

    assert result.slots.get("affiliation") == "사도련"
    assert "job" not in result.slots


@pytest.mark.unit
def test_extraction_pipeline_extracts_relation_from_identity_phrase() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("그녀의 정체는 고 유명찬 공의 손녀딸이었다.")

    assert result.slots.get("relation") == "고 유명찬 공의 손녀딸"
    assert "affiliation" not in result.slots


@pytest.mark.unit
def test_extraction_pipeline_does_not_extract_affiliation_from_family_relation_phrase() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("고 유명찬 공의 손녀딸이었다.")

    assert "affiliation" not in result.slots


@pytest.mark.unit
def test_extraction_pipeline_extracts_relation_from_appositive_family_phrase() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("포키온의 아들 포코스가 군세를 이끌고 도달했소이다!")

    assert result.slots.get("relation") == "포키온의 아들"


@pytest.mark.unit
def test_extraction_pipeline_normalizes_affiliation_value_to_org_prefix() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("소속: 사도련 백전귀(百戰鬼)")

    assert result.slots.get("affiliation") == "사도련"


@pytest.mark.unit
def test_extraction_pipeline_rejects_leading_noise_relation_phrase() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("저놈이 황제의 아들이다!")

    assert "relation" not in result.slots


@pytest.mark.unit
def test_extraction_pipeline_rejects_relation_problem_phrase_in_planning_context() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("신기원요와, 걸신들린 김 진사의 딸 문제를 처리하고 난 뒤 공양왕을 만나보는 걸로 하자.")

    assert "relation" not in result.slots


@pytest.mark.unit
def test_extraction_pipeline_rejects_reported_self_intro_relation_phrase() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("오로트 왕 폼페의 딸, 루이사입니다.")

    assert "relation" not in result.slots


@pytest.mark.unit
def test_extraction_pipeline_rejects_reported_self_intro_relation_phrase_without_comma() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("오로트 왕 폼페의 딸 루이사입니다.")

    assert "relation" not in result.slots


@pytest.mark.unit
def test_extraction_pipeline_does_not_extract_generic_royal_title_as_job() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("공주 전하께서도...")

    assert "job" not in result.slots


@pytest.mark.unit
def test_extraction_pipeline_extracts_time_from_bracketed_timeline_line() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("[13:45경. 클로뎃 아르르크, 인질을 데리고 9층으로 도주.]")

    assert result.slots.get("time") == "13:45"


@pytest.mark.unit
def test_extraction_pipeline_does_not_treat_century_as_age() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("그는 17세기로 가는 길을 떠났다.")

    assert "age" not in result.slots


@pytest.mark.unit
def test_extraction_pipeline_does_not_treat_incidental_death_noun_as_death_claim() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("극락도 쪽을 통해 확인해본 바로는 사망자 명단에는 없다고 했다.")

    assert "death" not in result.slots


@pytest.mark.unit
def test_extraction_pipeline_does_not_treat_living_disaster_phrase_as_alive_claim() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("살아있는 재난이 말을 아낀다는 것은 드문 일이었다.")

    assert "death" not in result.slots


@pytest.mark.unit
def test_extraction_pipeline_does_not_treat_genius_compound_as_talent_claim() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("장대한 거룡의 숨결은 극한의 천재지변 같았다.")

    assert "talent" not in result.slots


@pytest.mark.unit
def test_extraction_pipeline_does_not_treat_subjectless_death_quote_as_claim() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("죽었어.")

    assert "death" not in result.slots


@pytest.mark.unit
def test_extraction_pipeline_extracts_subject_scoped_death_claim() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("그는 이미 사망했다.")

    assert result.slots.get("death") is True


@pytest.mark.unit
def test_extraction_pipeline_extracts_age_from_explicit_age_context() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("그의 나이는 14세였다.")

    assert result.slots.get("age") == 14


@pytest.mark.unit
def test_extraction_pipeline_does_not_treat_reported_death_clause_as_claim() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("예전에 1호와 가면으로 대화를 할 때 시드는 죽었다고 알렸다.")

    assert "death" not in result.slots


@pytest.mark.unit
def test_extraction_pipeline_does_not_treat_reported_alive_clause_as_claim() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("시온이 살아있다는 걸 직접 두 눈으로 확인하니 너무나도 안도했다.")

    assert "death" not in result.slots


@pytest.mark.unit
def test_extraction_pipeline_does_not_extract_bare_quoted_age_without_subject_or_age_prefix() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("“448살입니다.”")

    assert "age" not in result.slots


@pytest.mark.unit
def test_extraction_pipeline_extracts_subject_scoped_age_statement() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("주인공은 14세였다.")

    assert result.slots.get("age") == 14


@pytest.mark.unit
def test_extraction_pipeline_extracts_subject_scoped_age_statement_with_olhae_modifier() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("시로네는 올해 50세가 되었다.")

    assert result.slots.get("age") == 50


@pytest.mark.unit
def test_extraction_pipeline_does_not_treat_reported_genius_quote_as_talent_claim() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("너희 같은 것들이 천재라고?")

    assert "talent" not in result.slots


@pytest.mark.unit
def test_extraction_pipeline_does_not_extract_implicit_subject_scoped_talent_claim() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("그녀는 천재였다.")

    assert "talent" not in result.slots


@pytest.mark.unit
def test_extraction_pipeline_requires_explicit_leading_place_label() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("현재 자리한 장소는 사천성 남단 덕창(德昌)이었다.")

    assert "place" not in result.slots


@pytest.mark.unit
def test_extraction_pipeline_extracts_explicit_leading_place_label() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("장소는 사천성 남단 덕창(德昌)이었다.")

    assert result.slots.get("place") == "사천성 남단 덕창(德昌)"


@pytest.mark.unit
def test_extraction_pipeline_does_not_treat_narrative_date_reference_as_time_claim() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("생각해 보니까 1월 1일은 이미 지났지?")

    assert "time" not in result.slots


@pytest.mark.unit
def test_extraction_pipeline_rejects_standalone_bracketed_time_marker() -> None:
    pipeline = ExtractionPipeline(profile={"mode": "rule_only"}, mappings=[], gateway=None)

    result = pipeline.extract("[PM 5:31]")

    assert "time" not in result.slots
