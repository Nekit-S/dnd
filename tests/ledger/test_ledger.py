import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from aidm.config.settings import Settings
from aidm.ledger.ledger import Ledger, LedgerError
from aidm.ledger.prices import TokenCounts


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def ledger(tmp_path: Path, clock: Clock) -> Ledger:
    return Ledger(Settings(var_dir=tmp_path / "var").ledger_path, clock=clock)


def _start(ledger: Ledger, **kw: object) -> int:
    args: dict[str, object] = {
        "category": "generation/plot/secrets",
        "provider": "fake",
        "model": "fake-model",
        "effort": None,
        "budget_scope": "campaign",
        "campaign_id": "c1",
    }
    args.update(kw)
    return ledger.start_attempt(**args)  # type: ignore[arg-type]


def test_file_created_under_var_dir_with_wal(tmp_path: Path, clock: Clock) -> None:
    settings = Settings(var_dir=tmp_path / "var")
    Ledger(settings.ledger_path, clock=clock)
    assert settings.ledger_path.is_file()
    conn = sqlite3.connect(settings.ledger_path)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        conn.close()


def test_pending_then_finished_once(ledger: Ledger, clock: Clock) -> None:
    attempt = _start(ledger, place="step4/item3")
    assert ledger.rows(10)[0].status == "pending"
    clock.now += timedelta(milliseconds=1500)
    ledger.finish_attempt(attempt, TokenCounts(uncached_input=10, output=5), Decimal("0.25"), "ok")
    row = ledger.rows(10)[0]
    assert row.status == "ok"
    assert row.cost == Decimal("0.25")
    assert row.duration_ms == 1500
    assert row.uncached_input == 10 and row.output == 5
    assert row.place == "step4/item3"
    with pytest.raises(LedgerError):
        ledger.finish_attempt(attempt, TokenCounts(), Decimal(0), "ok")
    assert ledger.rows(10)[0].cost == Decimal("0.25")


def test_finish_cannot_set_pending(ledger: Ledger) -> None:
    attempt = _start(ledger)
    with pytest.raises(LedgerError):
        ledger.finish_attempt(attempt, TokenCounts(), Decimal(0), "pending")


def test_retry_links_parent(ledger: Ledger) -> None:
    first = _start(ledger)
    retry = _start(ledger, parent_id=first, attempt_kind="retry_network")
    row = next(r for r in ledger.rows(10) if r.id == retry)
    assert row.parent_id == first and row.attempt_kind == "retry_network"


def test_invalid_enum_rejected(ledger: Ledger) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _start(ledger, budget_scope="nope")


def test_rejection_row_has_zero_cost(ledger: Ledger) -> None:
    ledger.record_rejection(
        status="rejected_budget",
        category="generation/plot/secrets",
        provider="fake",
        model="fake-model",
        effort=None,
        budget_scope="campaign",
        campaign_id="c1",
    )
    row = ledger.rows(1)[0]
    assert row.status == "rejected_budget"
    assert row.cost == Decimal(0)
    assert row.finished_at is not None
    assert ledger.spend() == Decimal(0)


def test_rejection_needs_rejected_status(ledger: Ledger) -> None:
    with pytest.raises(LedgerError):
        ledger.record_rejection(
            status="ok",
            category="a/b",
            provider="fake",
            model="m",
            effort=None,
            budget_scope="app",
        )


def test_spend_filters(ledger: Ledger, clock: Clock) -> None:
    a = _start(ledger, campaign_id="c1")
    ledger.finish_attempt(a, TokenCounts(), Decimal("0.100000"), "ok")
    clock.now += timedelta(hours=1)
    since = clock.now
    b = _start(ledger, campaign_id="c2")
    ledger.finish_attempt(b, TokenCounts(), Decimal("0.020000"), "invalid_output")
    c = _start(ledger, campaign_id=None, budget_scope="test", category="test/live/smoke")
    ledger.finish_attempt(c, TokenCounts(), Decimal("0.003000"), "provider_error", "retryable")
    _start(ledger)  # pending, no cost yet

    assert ledger.spend() == Decimal("0.123")
    assert ledger.spend(campaign_id="c1") == Decimal("0.1")
    assert ledger.spend(scope="test") == Decimal("0.003")
    assert ledger.spend(since=since) == Decimal("0.023")
    assert type(ledger.spend()) is Decimal

    summary = ledger.summary_by_category()
    assert summary["generation/plot/secrets"].attempts == 2
    assert summary["generation/plot/secrets"].cost == Decimal("0.12")
    assert summary["test/live/smoke"].cost == Decimal("0.003")
    assert ledger.summary_by_category(scope="test").keys() == {"test/live/smoke"}


def test_rows_newest_first_and_limited(ledger: Ledger) -> None:
    ids = [_start(ledger) for _ in range(3)]
    assert [r.id for r in ledger.rows(2)] == [ids[2], ids[1]]
