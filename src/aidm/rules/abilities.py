from fractions import Fraction

from aidm.rules.rounding import RoundMode, round_value


def ability_modifier(score: int, mode: RoundMode) -> int:
    return round_value(Fraction(score - 10, 2), mode)
