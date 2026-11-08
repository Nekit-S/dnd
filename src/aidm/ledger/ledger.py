import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from aidm.ledger.db import connect, init_db
from aidm.ledger.prices import TokenCounts

BudgetScope = Literal["campaign", "test", "app"]
AttemptKind = Literal[
    "first", "retry_network", "repair_schema", "repair_check", "escalation", "creative_revision"
]
Mode = Literal["direct", "batch"]
Status = Literal[
    "pending",
    "ok",
    "invalid_output",
    "truncated",
    "provider_error",
    "rejected_category",
    "rejected_budget",
    "rejected_input_cap",
    "rejected_price",
]
ErrorClass = Literal["retryable", "fatal", ""]
_MS = timedelta(milliseconds=1)
_COUNTS = ("uncached_input", "cache_write_5m", "cache_write_1h", "cache_read", "output")


class LedgerError(Exception):
    pass


class LedgerRow(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: int
    parent_id: int | None
    created_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    campaign_id: str | None
    session_id: str | None
    budget_scope: BudgetScope
    category: str
    place: str
    attempt_kind: AttemptKind
    provider: str
    model: str
    effort: str | None
    mode: Mode
    batch_id: str | None
    uncached_input: int
    cache_write_5m: int
    cache_write_1h: int
    cache_read: int
    output: int
    cost: Decimal | None
    price_as_of: str | None
    status: Status
    error_class: ErrorClass


class CategorySummary(BaseModel):
    model_config = ConfigDict(frozen=True)
    attempts: int
    cost: Decimal


class Ledger:
    def __init__(self, path: Path, clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self._path = path
        self._clock = clock
        init_db(path)

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        # Соединение на операцию: журнал пишут из разных потоков веб-сервера
        with closing(connect(self._path)) as conn, conn:
            yield conn

    def _now(self) -> str:
        return self._clock().astimezone(UTC).isoformat(timespec="microseconds")

    def _insert(self, values: dict[str, object]) -> int:
        columns = ", ".join(values)
        marks = ", ".join("?" * len(values))
        with self._db() as conn:
            cur = conn.execute(
                f"INSERT INTO attempts ({columns}) VALUES ({marks})", tuple(values.values())
            )
            assert cur.lastrowid is not None
            return cur.lastrowid

    def start_attempt(
        self,
        *,
        category: str,
        provider: str,
        model: str,
        effort: str | None,
        budget_scope: BudgetScope,
        campaign_id: str | None = None,
        session_id: str | None = None,
        place: str = "",
        attempt_kind: AttemptKind = "first",
        mode: Mode = "direct",
        batch_id: str | None = None,
        parent_id: int | None = None,
        price_as_of: str | None = None,
    ) -> int:
        return self._insert(
            {
                "parent_id": parent_id,
                "created_at": self._now(),
                "campaign_id": campaign_id,
                "session_id": session_id,
                "budget_scope": budget_scope,
                "category": category,
                "place": place,
                "attempt_kind": attempt_kind,
                "provider": provider,
                "model": model,
                "effort": effort,
                "mode": mode,
                "batch_id": batch_id,
                "price_as_of": price_as_of,
                "status": "pending",
            }
        )

    def finish_attempt(
        self,
        attempt_id: int,
        counts: TokenCounts,
        cost: Decimal,
        status: Status,
        error_class: ErrorClass = "",
    ) -> None:
        if status == "pending":
            raise LedgerError("finish status cannot be pending")
        now = self._clock()
        with self._db() as conn:
            row = conn.execute(
                "SELECT created_at FROM attempts WHERE id = ? AND status = 'pending'",
                (attempt_id,),
            ).fetchone()
            if row is None:
                raise LedgerError(f"attempt {attempt_id} is not pending")
            elapsed = now - datetime.fromisoformat(row["created_at"])
            conn.execute(
                "UPDATE attempts SET finished_at = ?, duration_ms = ?, cost = ?, status = ?,"
                " error_class = ?, " + ", ".join(f"{c} = ?" for c in _COUNTS) + " WHERE id = ?",
                (
                    now.astimezone(UTC).isoformat(timespec="microseconds"),
                    elapsed // _MS,
                    str(cost),
                    status,
                    error_class,
                    *(getattr(counts, c) for c in _COUNTS),
                    attempt_id,
                ),
            )

    def record_rejection(
        self,
        *,
        status: Status,
        category: str,
        provider: str,
        model: str,
        effort: str | None,
        budget_scope: BudgetScope,
        campaign_id: str | None = None,
        session_id: str | None = None,
        place: str = "",
        attempt_kind: AttemptKind = "first",
        mode: Mode = "direct",
        parent_id: int | None = None,
    ) -> int:
        if not status.startswith("rejected_"):
            raise LedgerError(f"not a rejection status: {status}")
        now = self._now()
        return self._insert(
            {
                "parent_id": parent_id,
                "created_at": now,
                "finished_at": now,
                "duration_ms": 0,
                "campaign_id": campaign_id,
                "session_id": session_id,
                "budget_scope": budget_scope,
                "category": category,
                "place": place,
                "attempt_kind": attempt_kind,
                "provider": provider,
                "model": model,
                "effort": effort,
                "mode": mode,
                "cost": "0",
                "status": status,
            }
        )

    def _costs(
        self, campaign_id: str | None, scope: BudgetScope | None, since: datetime | None
    ) -> list[sqlite3.Row]:
        where, params = ["cost IS NOT NULL"], []
        if campaign_id is not None:
            where.append("campaign_id = ?")
            params.append(campaign_id)
        if scope is not None:
            where.append("budget_scope = ?")
            params.append(scope)
        if since is not None:
            where.append("created_at >= ?")
            params.append(since.astimezone(UTC).isoformat(timespec="microseconds"))
        with self._db() as conn:
            # Суммируем в Python: SUM в SQLite перевёл бы TEXT-деньги во float
            return conn.execute(
                "SELECT category, cost FROM attempts WHERE " + " AND ".join(where), params
            ).fetchall()

    def spend(
        self,
        campaign_id: str | None = None,
        scope: BudgetScope | None = None,
        since: datetime | None = None,
    ) -> Decimal:
        return sum((Decimal(r["cost"]) for r in self._costs(campaign_id, scope, since)), Decimal(0))

    def summary_by_category(
        self,
        campaign_id: str | None = None,
        scope: BudgetScope | None = None,
        since: datetime | None = None,
    ) -> dict[str, CategorySummary]:
        totals: dict[str, tuple[int, Decimal]] = {}
        for r in self._costs(campaign_id, scope, since):
            attempts, cost = totals.get(r["category"], (0, Decimal(0)))
            totals[r["category"]] = (attempts + 1, cost + Decimal(r["cost"]))
        return {k: CategorySummary(attempts=a, cost=c) for k, (a, c) in sorted(totals.items())}

    def rows(self, limit: int) -> list[LedgerRow]:
        with self._db() as conn:
            found = conn.execute(
                "SELECT * FROM attempts ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [LedgerRow.model_validate(dict(r)) for r in found]
