from fractions import Fraction

import pytest

from aidm.rules.rounding import round_value


@pytest.mark.parametrize(
    ("value", "mode", "expected"),
    [
        (Fraction(-1, 2), "down", -1),
        (Fraction(-1, 2), "up", 0),
        (Fraction(7, 2), "down", 3),
        (Fraction(7, 2), "up", 4),
        (Fraction(3), "down", 3),
        (Fraction(3), "up", 3),
    ],
)
def test_round_value(value: Fraction, mode: str, expected: int) -> None:
    assert round_value(value, mode) == expected  # type: ignore[arg-type]
