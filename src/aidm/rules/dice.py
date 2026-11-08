import random
import re
from dataclasses import dataclass
from typing import Literal

_RE = re.compile(r"(\d*)d(\d+)(?:(kh|kl)(\d+))?(?:([+-])(\d+))?")


class DiceSyntaxError(ValueError):
    pass


@dataclass(frozen=True)
class Dice:
    count: int
    sides: int
    keep: Literal["kh", "kl"] | None
    keep_n: int | None
    bonus: int

    def __str__(self) -> str:
        keep = f"{self.keep}{self.keep_n}" if self.keep else ""
        return (
            f"{self.count}d{self.sides}{keep}{self.bonus:+d}"
            if self.bonus
            else f"{self.count}d{self.sides}{keep}"
        )


@dataclass(frozen=True)
class RollResult:
    rolls: tuple[int, ...]
    kept: tuple[int, ...]
    total: int


def parse(text: str) -> Dice:
    m = _RE.fullmatch("".join(text.split()).lower())
    if not m:
        raise DiceSyntaxError(f"bad dice expression: {text!r}")
    count_s, sides_s, keep, keep_s, sign, bonus_s = m.groups()
    count, sides = int(count_s or 1), int(sides_s)
    keep_n = int(keep_s) if keep_s else None
    bonus = int(bonus_s) * (-1 if sign == "-" else 1) if bonus_s else 0
    if not (1 <= count <= 100 and 2 <= sides <= 1000 and abs(bonus) <= 1000):
        raise DiceSyntaxError(f"dice out of range: {text!r}")
    if keep_n is not None and not 1 <= keep_n <= count:
        raise DiceSyntaxError(f"bad keep count: {text!r}")
    return Dice(count, sides, keep, keep_n, bonus)  # type: ignore[arg-type]


def roll(expr: Dice, rng: random.Random) -> RollResult:
    rolls = tuple(rng.randint(1, expr.sides) for _ in range(expr.count))
    ordered = sorted(rolls, reverse=expr.keep == "kh")
    kept = tuple(ordered[: expr.keep_n]) if expr.keep else rolls
    return RollResult(rolls, kept, sum(kept) + expr.bonus)
