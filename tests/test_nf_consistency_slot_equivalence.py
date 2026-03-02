from __future__ import annotations

import pytest

from modules.nf_consistency import engine as consistency_engine
from modules.nf_shared.protocol.dtos import Verdict


@pytest.mark.unit
def test_compare_slot_place_equivalent_with_admin_suffix_and_particle() -> None:
    verdict = consistency_engine._compare_slot("place", "서울특별시에서", "서울시")
    assert verdict is Verdict.OK


@pytest.mark.unit
def test_compare_slot_relation_equivalent_with_postposition() -> None:
    verdict = consistency_engine._compare_slot("relation", "동생은", "동생")
    assert verdict is Verdict.OK


@pytest.mark.unit
def test_compare_slot_low_similarity_single_token_is_violate() -> None:
    verdict = consistency_engine._compare_slot("job", "검사", "마법사")
    assert verdict is Verdict.VIOLATE


@pytest.mark.unit
def test_compare_slot_mid_similarity_stays_unknown() -> None:
    verdict = consistency_engine._compare_slot("job", "12기 마법사", "13기 마법사")
    assert verdict is None


@pytest.mark.unit
def test_compare_slot_time_contains_with_numeric_conflict_stays_unknown() -> None:
    verdict = consistency_engine._compare_slot("time", "3일 후", "3일 후 4시간")
    assert verdict is None


@pytest.mark.unit
def test_compare_slot_low_similarity_single_vs_multi_is_violate() -> None:
    verdict = consistency_engine._compare_slot("talent", "genius", "no talent")
    assert verdict is Verdict.VIOLATE
