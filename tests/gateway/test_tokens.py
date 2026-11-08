from hypothesis import given
from hypothesis import strategies as st

from aidm.gateway.tokens import estimate_tokens


def test_examples() -> None:
    assert estimate_tokens() == 0
    assert estimate_tokens("") == 0
    assert estimate_tokens("a") == 1
    assert estimate_tokens("ab") == 1
    assert estimate_tokens("абв") == 3
    assert estimate_tokens("a", "a") == 1


@given(st.lists(st.text()))
def test_half_of_utf8_bytes_rounded_up(texts: list[str]) -> None:
    size = sum(len(t.encode()) for t in texts)
    assert 2 * estimate_tokens(*texts) - size in (0, 1)
