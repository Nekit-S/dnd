import random

import pytest
from hypothesis import given
from hypothesis import strategies as st

from aidm.rules.dice import Dice, DiceSyntaxError, parse, roll


def test_examples() -> None:
    assert parse("4d6kh3") == Dice(4, 6, "kh", 3, 0)
    assert parse(" D20 + 5 ") == Dice(1, 20, None, None, 5)
    assert parse("2d20kl1-1") == Dice(2, 20, "kl", 1, -1)


@pytest.mark.parametrize(
    "bad",
    ["0d6", "1d1", "101d6", "3d6kh4", "3d6kh0", "1d6+", "abc", "", "1d1001", "1d6+1001", "1d6kh"],
)
def test_rejects(bad: str) -> None:
    with pytest.raises(DiceSyntaxError):
        parse(bad)


def test_keep_highest_lowest() -> None:
    class R(random.Random):
        vals = iter([1, 5, 3])

        def randint(self, a: int, b: int) -> int:
            return next(self.vals)

    r = roll(parse("3d6kh2"), R())
    assert (r.rolls, sorted(r.kept), r.total) == ((1, 5, 3), [3, 5], 8)
    low = roll(parse("3d6kl1"), random.Random(1))
    assert low.total == min(low.rolls)


@st.composite
def dice(draw: st.DrawFn) -> Dice:
    n = draw(st.integers(1, 100))
    keep = draw(st.sampled_from([None, "kh", "kl"]))
    k = draw(st.integers(1, n)) if keep else None
    return Dice(n, draw(st.integers(2, 1000)), keep, k, draw(st.integers(-1000, 1000)))


@given(dice(), st.integers())
def test_roll_properties(d: Dice, seed: int) -> None:
    r = roll(d, random.Random(seed))
    assert len(r.rolls) == d.count
    assert len(r.kept) == (d.keep_n or d.count)
    assert r.total == sum(r.kept) + d.bonus
    assert all(1 <= x <= d.sides for x in r.rolls)
    assert r == roll(d, random.Random(seed))


@given(dice())
def test_roundtrip(d: Dice) -> None:
    assert parse(str(d)) == d


@given(st.integers(1, 100), st.integers(2, 1000), st.integers(-1000, 1000), st.integers())
def test_total_bounds(n: int, m: int, c: int, seed: int) -> None:
    t = roll(Dice(n, m, None, None, c), random.Random(seed)).total
    assert n + c <= t <= n * m + c
