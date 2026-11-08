import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE meta (
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    is_test INTEGER NOT NULL,
    status TEXT NOT NULL
);
CREATE TABLE records (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    visibility TEXT NOT NULL CHECK (visibility IN ('dm', 'all', 'player')),
    player_id TEXT,
    version INTEGER NOT NULL,
    provenance TEXT,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK ((visibility = 'player') = (player_id IS NOT NULL))
);
CREATE INDEX records_kind ON records (kind);
CREATE TABLE links (
    from_id TEXT NOT NULL REFERENCES records (id),
    to_id TEXT NOT NULL REFERENCES records (id),
    kind TEXT NOT NULL,
    PRIMARY KEY (from_id, to_id, kind)
);
CREATE INDEX links_to ON links (to_id);
"""


class SchemaVersionError(RuntimeError):
    pass


def _connect(path: Path) -> sqlite3.Connection:
    # autocommit: транзакции открывает CampaignStore.transaction явно
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_db(path: Path) -> sqlite3.Connection:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = _connect(path)
    conn.executescript(f"BEGIN; {_SCHEMA} PRAGMA user_version = {SCHEMA_VERSION}; COMMIT;")
    return conn


def open_db(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise FileNotFoundError(path)
    conn = _connect(path)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version != SCHEMA_VERSION:
        conn.close()
        raise SchemaVersionError(
            f"{path.name}: schema version {version}, expected {SCHEMA_VERSION}"
        )
    return conn
