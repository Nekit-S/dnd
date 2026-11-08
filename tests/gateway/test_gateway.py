import logging
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from aidm.config.models import ModelsConfig, UnknownCategoryError
from aidm.config.settings import Settings
from aidm.gateway.gateway import (
    BudgetExceededError,
    Gateway,
    InputCapError,
    LLMRequest,
    ProviderFatalError,
)
from aidm.ledger.ledger import Ledger, LedgerRow
from aidm.ledger.prices import Prices, TokenCounts, UnknownPriceError, load_prices
from aidm.providers.base import Message, ProviderError, ProviderRequest
from aidm.providers.capabilities import UnknownModelError
from aidm.providers.fake import Failure, FakeProvider

PRICES = """\
as_of: "2026-11-01"
batch_multiplier: "0.5"
models:
  fake-model:
    - input: "1"
      cache_write_5m: "1.25"
      cache_write_1h: "2"
      cache_read: "0.1"
      output: "5"
"""
REPLY = '{"a": 1}'
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class CountingFake(FakeProvider):
    def __init__(self, exact: int | None = None, **kw: Any) -> None:
        super().__init__(**kw)
        self.exact = exact
        self.counts = 0

    def count_tokens(self, request: ProviderRequest) -> int | None:
        self.counts += 1
        if self.exact == -1:
            raise ProviderError("count failed", retryable=True)
        return self.exact if self.exact is not None else super().count_tokens(request)


class Env:
    def __init__(self, tmp_path: Path, **settings: Any) -> None:
        self.clock = Clock()
        self.sleeps: list[int] = []
        self.settings = Settings(var_dir=tmp_path / "var", **settings)
        self.ledger = Ledger(self.settings.ledger_path, clock=self.clock)
        prices_dir = tmp_path / "prices"
        prices_dir.mkdir(exist_ok=True)
        (prices_dir / "fake.yaml").write_text(PRICES, encoding="utf-8")
        self.prices = load_prices(prices_dir)
        self.models = ModelsConfig.model_validate(
            {
                "defaults": {
                    "retries": 3,
                    "backoff_base_ms": 500,
                    "cache_ttl": {"direct": "5m", "batch": "1h"},
                },
                "categories": {
                    "dev/smoke": {
                        "provider": "fake",
                        "model": "fake-model",
                        "effort": None,
                        "max_input_tokens": 100,
                        "max_output_tokens": 64,
                    }
                },
            }
        )
        self.fake = CountingFake(script={("dev/smoke", "p1"): REPLY})

    def gateway(self, prices: Prices | None = None) -> Gateway:
        return Gateway(
            self.settings,
            self.models,
            self.ledger,
            prices or self.prices,
            {"fake": self.fake}.__getitem__,
            sleep=self.sleeps.append,
            clock=self.clock,
        )

    def call(self, text: str = "hello", **kw: Any) -> Any:
        args: dict[str, Any] = {
            "category": "dev/smoke",
            "place": "p1",
            "budget_scope": "app",
            "prefix": ["sys"],
            "messages": [Message("user", text)],
        }
        args.update(kw)
        return self.gateway().call(LLMRequest(**args))

    def rows(self) -> list[LedgerRow]:
        return list(reversed(self.ledger.rows(100)))

    def spent(self, cost: str, **kw: Any) -> None:
        args: dict[str, Any] = {
            "category": "dev/smoke",
            "provider": "fake",
            "model": "fake-model",
            "effort": None,
            "budget_scope": "app",
        }
        args.update(kw)
        row = self.ledger.start_attempt(**args)
        self.ledger.finish_attempt(row, TokenCounts(), Decimal(cost), "ok")


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


def test_ok_call_cost_and_row(env: Env) -> None:
    r = env.call(attempt_kind="repair_schema", parent_id=None, campaign_id="c1")
    # вход: "sys"+"hello" = 8 байт -> 4; выход: REPLY 8 байт -> 4; 4*1 + 4*5 за миллион
    assert r.status == "ok"
    assert r.text == REPLY
    assert r.usage == TokenCounts(uncached_input=4, output=4)
    assert r.cost == Decimal("0.000024")
    (row,) = env.rows()
    assert row.id == r.ledger_row_id
    assert (row.status, row.cost, row.price_as_of) == ("ok", Decimal("0.000024"), "2026-11-01")
    assert (row.attempt_kind, row.campaign_id, row.place) == ("repair_schema", "c1", "p1")
    assert (row.uncached_input, row.output) == (4, 4)
    assert env.gateway().spend("c1") == Decimal("0.000024")
    sent = env.fake.calls[0]
    assert (sent.category, sent.place, sent.model, sent.max_output_tokens) == (
        "dev/smoke",
        "p1",
        "fake-model",
        64,
    )


@pytest.mark.parametrize("category", ["", "Plot", "generation", "unknown/cat"])
def test_bad_category_rejected(env: Env, category: str) -> None:
    with pytest.raises(UnknownCategoryError):
        env.call(category=category)
    (row,) = env.rows()
    assert (row.status, row.cost, row.category) == ("rejected_category", Decimal(0), category)
    assert env.fake.calls == []


def test_unknown_price_rejected(env: Env) -> None:
    with pytest.raises(UnknownPriceError):
        env.gateway(Prices({})).call(
            LLMRequest(category="dev/smoke", budget_scope="app", messages=[Message("user", "x")])
        )
    (row,) = env.rows()
    assert (row.status, row.cost, row.model) == ("rejected_price", Decimal(0), "fake-model")
    assert env.fake.calls == []


def test_local_provider_needs_no_price(env: Env) -> None:
    env.fake.is_local = True
    r = env.gateway(Prices({})).call(
        LLMRequest(
            category="dev/smoke", place="p1", budget_scope="app", messages=[Message("user", "x")]
        )
    )
    assert (r.status, r.cost) == ("ok", Decimal(0))
    assert env.rows()[0].price_as_of is None


def test_over_cap_rejected_without_call(env: Env) -> None:
    with pytest.raises(InputCapError):
        env.call("x" * 400)
    (row,) = env.rows()
    assert (row.status, row.cost) == ("rejected_input_cap", Decimal(0))
    assert env.fake.calls == []
    assert env.fake.counts == 1


def test_exact_count_only_near_cap(env: Env) -> None:
    env.call("x" * 100)  # оценка 52 из 100: далеко от потолка
    assert env.fake.counts == 0
    env.fake.exact = 90
    env.call("x" * 300)  # оценка 152 > 100, точный счёт 90 пропускает
    assert env.fake.counts == 1
    assert len(env.fake.calls) == 2


def test_exact_count_failure_keeps_estimate(env: Env) -> None:
    env.fake.exact = -1
    with pytest.raises(InputCapError):
        env.call("x" * 300)
    env.call("x" * 158)  # оценка 81: у потолка, счёт упал, оценка проходит
    assert env.fake.counts == 2


@pytest.mark.parametrize(
    ("limit", "settings", "spent", "request_kw"),
    [
        ("monthly", {"monthly_limit_usd": Decimal(5)}, {"cost": "5"}, {}),
        (
            "test",
            {"live_test_limit_usd": Decimal(2)},
            {"cost": "2", "budget_scope": "test"},
            {"budget_scope": "test"},
        ),
        (
            "campaign",
            {},
            {"cost": "1", "campaign_id": "c1", "budget_scope": "campaign"},
            {"campaign_id": "c1", "budget_scope": "campaign", "campaign_limit_usd": Decimal(1)},
        ),
    ],
)
def test_budget_limits(
    tmp_path: Path,
    limit: str,
    settings: dict[str, Any],
    spent: dict[str, Any],
    request_kw: dict[str, Any],
) -> None:
    env = Env(tmp_path, **settings)
    env.spent(**spent)
    with pytest.raises(BudgetExceededError) as e:
        env.call(**request_kw)
    assert e.value.limit == limit
    assert env.rows()[-1].status == "rejected_budget"
    assert env.fake.calls == []


def test_budget_below_limit_and_last_month_ignored(tmp_path: Path) -> None:
    env = Env(tmp_path, monthly_limit_usd=Decimal(5))
    env.clock.now = datetime(2026, 10, 31, 23, 0, tzinfo=UTC)
    env.spent("10")
    env.clock.now = NOW
    env.spent("4.99", campaign_id="c2")
    assert env.call(campaign_id="c1", campaign_limit_usd=Decimal(1)).status == "ok"
    with pytest.raises(BudgetExceededError):
        env.call(campaign_id="c2", campaign_limit_usd=Decimal(1))


def test_campaign_limit_needs_campaign_id() -> None:
    with pytest.raises(ValueError):
        LLMRequest(
            category="dev/smoke", budget_scope="app", messages=[], campaign_limit_usd=Decimal(1)
        )


def _with_failures(env: Env, failures: list[Failure]) -> None:
    env.fake.failures.extend(failures)


def test_retryable_retried_with_linked_rows(env: Env) -> None:
    _with_failures(env, ["retryable", "retryable"])
    r = env.call()
    assert r.status == "ok"
    first, second, third = env.rows()
    assert (first.attempt_kind, first.parent_id) == ("first", None)
    assert [(x.attempt_kind, x.parent_id) for x in (second, third)] == [
        ("retry_network", first.id)
    ] * 2
    assert [(x.status, x.error_class) for x in (first, second)] == [
        ("provider_error", "retryable")
    ] * 2
    assert (third.status, third.id) == ("ok", r.ledger_row_id)
    assert env.sleeps == [500, 1000]


def test_retries_capped(env: Env) -> None:
    _with_failures(env, ["retryable"] * 5)
    with pytest.raises(ProviderFatalError):
        env.call()
    assert len(env.fake.calls) == 4
    assert [x.status for x in env.rows()] == ["provider_error"] * 4
    assert env.sleeps == [500, 1000, 2000]


def test_fatal_not_retried(env: Env) -> None:
    _with_failures(env, ["fatal"])
    with pytest.raises(ProviderFatalError):
        env.call()
    (row,) = env.rows()
    assert (row.status, row.error_class, row.cost) == ("provider_error", "fatal", Decimal(0))
    assert len(env.fake.calls) == 1
    assert env.sleeps == []


class Out(BaseModel):
    a: int


class Other(BaseModel):
    b: str


def test_truncated(env: Env) -> None:
    _with_failures(env, ["truncated"])
    r = env.call(output_model=Out)
    assert (r.status, r.parsed) == ("truncated", None)
    assert env.rows()[0].status == "truncated"


def test_invalid_json(env: Env) -> None:
    _with_failures(env, ["invalid_json"])
    r = env.call(output_model=Out)
    assert (r.status, r.parsed) == ("invalid_output", None)
    assert env.rows()[0].status == "invalid_output"
    assert env.fake.calls[0].json_schema == Out.model_json_schema()


def test_schema_mismatch_and_valid(env: Env) -> None:
    assert env.call(output_model=Other).status == "invalid_output"
    r = env.call(output_model=Out)
    assert (r.status, r.parsed) == ("ok", Out(a=1))


def test_cache_marker_only_above_minimum(env: Env) -> None:
    env.models.categories["dev/smoke"].max_input_tokens = 10_000
    env.call(prefix=["s" * 1022])  # 511 < 512
    env.call(prefix=["s" * 1000, "t" * 24])  # 512
    assert [c.cache_ttl for c in env.fake.calls] == [None, "5m"]


def test_logs_have_no_prompt_or_reply(env: Env, caplog: pytest.LogCaptureFixture) -> None:
    env.fake.script[("dev/smoke", "p1")] = "REPLY-CANARY"
    caplog.set_level(logging.INFO, logger="aidm")
    env.call("PROMPT-CANARY", prefix=["PREFIX-CANARY"])
    _with_failures(env, ["fatal"])
    with pytest.raises(ProviderFatalError):
        env.call("PROMPT-CANARY")
    assert "dev/smoke" in caplog.text
    assert "CANARY" not in caplog.text


def test_unexpected_error_closes_ledger_row(env: Env) -> None:
    def boom(request: ProviderRequest) -> Any:
        raise RuntimeError("adapter bug")

    env.fake.complete = boom  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        env.call()
    (row,) = env.rows()
    assert (row.status, row.error_class) == ("provider_error", "fatal")


def test_unknown_model_rejected_with_row(env: Env) -> None:
    env.models.categories["dev/smoke"].model = "no-such-model"
    with pytest.raises(UnknownModelError):
        env.call()
    (row,) = env.rows()
    assert row.status == "rejected_price"
    assert env.fake.calls == []
