import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY,
    parent_id INTEGER REFERENCES attempts(id),
    created_at TEXT NOT NULL,
    finished_at TEXT,
    duration_ms INTEGER,
    campaign_id TEXT,
    session_id TEXT,
    budget_scope TEXT NOT NULL CHECK (budget_scope IN ('campaign', 'test', 'app')),
    category TEXT NOT NULL,
    place TEXT NOT NULL DEFAULT '',
    attempt_kind TEXT NOT NULL CHECK (attempt_kind IN ('first', 'retry_network',
        'repair_schema', 'repair_check', 'escalation', 'creative_revision')),
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    effort TEXT,
    mode TEXT NOT NULL CHECK (mode IN ('direct', 'batch')),
    batch_id TEXT,
    uncached_input INTEGER NOT NULL DEFAULT 0,
    cache_write_5m INTEGER NOT NULL DEFAULT 0,
    cache_write_1h INTEGER NOT NULL DEFAULT 0,
    cache_read INTEGER NOT NULL DEFAULT 0,
    output INTEGER NOT NULL DEFAULT 0,
    cost TEXT,
    price_as_of TEXT,
    status TEXT NOT NULL CHECK (status IN ('pending', 'ok', 'invalid_output', 'truncated',
        'provider_error', 'rejected_category', 'rejected_budget', 'rejected_input_cap',
        'rejected_price')),
    error_class TEXT NOT NULL DEFAULT '' CHECK (error_class IN ('retryable', 'fatal', ''))
);
CREATE INDEX IF NOT EXISTS attempts_campaign ON attempts(campaign_id, created_at);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: Path) -> None:
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
    finally:
        conn.close()
