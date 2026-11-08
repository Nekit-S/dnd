from fractions import Fraction
from typing import Literal

RoundMode = Literal["down", "up"]


def round_value(value: Fraction, mode: RoundMode) -> int:
    # Fraction.__floor__/__ceil__ точные, без float
    return value.__floor__() if mode == "down" else value.__ceil__()
