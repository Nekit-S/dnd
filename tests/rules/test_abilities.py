import pytest
from hypothesis import given
from hypothesis import strategies as st

from aidm.rules.abilities import ability_modifier


@pytest.mark.parametrize(("score", "mod"), [(9, -1), (10, 0), (1, -5), (30, 10), (11, 0), (12, 1)])
def test_down(score: int, mod: int) -> None:
    assert ability_modifier(score, "down") == mod


@given(st.integers(1, 30))
def test_down_matches_floor(score: int) -> None:
    assert ability_modifier(score, "down") == (score - 10) // 2
