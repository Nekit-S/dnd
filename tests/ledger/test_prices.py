from decimal import Decimal
from pathlib import Path

import pytest

from aidm.ledger.prices import PriceFileError, TokenCounts, UnknownPriceError, load_prices

M = 1_000_000


def test_opus_direct_all_kinds() -> None:
    prices = load_prices()
    counts = TokenCounts(
        uncached_input=M, cache_write_5m=M, cache_write_1h=M, cache_read=M, output=M
    )
    # 4 + 5 + 8 + 0.20 + 20
    assert prices.cost("claude-opus-5-5", counts) == Decimal("37.200000")


def test_sonnet_cache_read_and_output() -> None:
    prices = load_prices()
    counts = TokenCounts(cache_read=2000, output=1500)
    # 2000*0.10/1M + 1500*10/1M = 0.0002 + 0.015
    assert prices.cost("claude-sonnet-5-5", counts) == Decimal("0.015200")


def test_batch_halves_cost() -> None:
    prices = load_prices()
    counts = TokenCounts(uncached_input=10_000, output=1000)
    # (10000*2 + 1000*10)/1M = 0.03; batch -> 0.015
    assert prices.cost("claude-sonnet-5-5", counts, batch=True) == Decimal("0.015000")


def test_haiku_tier_by_prompt_size() -> None:
    prices = load_prices()
    small = TokenCounts(uncached_input=100_000, output=M)
    assert prices.cost("claude-haiku-5-5", small) == Decimal("0.510000")
    # 60K uncached + 50K cache read = 110K prompt -> higher tier for all kinds
    big = TokenCounts(uncached_input=60_000, cache_read=50_000, output=M)
    assert prices.cost("claude-haiku-5-5", big) == Decimal("2.532500")


def test_quantized_half_up() -> None:
    prices = load_prices()
    # 1 cache read on haiku = 0.00000001 -> rounds to 0
    assert prices.cost("claude-haiku-5-5", TokenCounts(cache_read=1)) == Decimal("0.000000")
    # 5 output on haiku = 0.0000025 -> 0.000003
    assert prices.cost("claude-haiku-5-5", TokenCounts(output=5)) == Decimal("0.000003")


def test_unknown_model_rejected() -> None:
    with pytest.raises(UnknownPriceError):
        load_prices().cost("no-such-model", TokenCounts(output=1))


def test_local_is_free_even_without_price() -> None:
    assert load_prices().cost("llama-local", TokenCounts(output=M), is_local=True) == Decimal(0)


def test_as_of_is_known() -> None:
    assert load_prices().as_of("claude-opus-5-5") == "2026-11-08"


def test_negative_counts_rejected() -> None:
    with pytest.raises(ValueError):
        TokenCounts(output=-1)


def _write(directory: Path, text: str) -> Path:
    (directory / "p.yaml").write_text(text, encoding="utf-8")
    return directory


FAKE = """
as_of: "2026-01-01"
batch_multiplier: "0.5"
models:
  fake-model:
    - input: "1"
      cache_write_5m: "1"
      cache_write_1h: "1"
      cache_read: "1"
      output: "3"
"""


def test_custom_directory(tmp_path: Path) -> None:
    prices = load_prices(_write(tmp_path, FAKE))
    assert prices.cost("fake-model", TokenCounts(output=M)) == Decimal("3.000000")
    assert prices.as_of("fake-model") == "2026-01-01"
    with pytest.raises(UnknownPriceError):
        prices.cost("claude-opus-5-5", TokenCounts())


def test_float_price_rejected(tmp_path: Path) -> None:
    with pytest.raises(PriceFileError):
        load_prices(_write(tmp_path, FAKE.replace('output: "3"', "output: 3.5")))


def test_last_tier_must_be_open(tmp_path: Path) -> None:
    bad = FAKE.replace("    - input:", "    - max_prompt_tokens: 10\n      input:")
    with pytest.raises(PriceFileError):
        load_prices(_write(tmp_path, bad))


def test_results_are_decimal() -> None:
    result = load_prices().cost("claude-opus-5-5", TokenCounts(output=7))
    assert type(result) is Decimal
