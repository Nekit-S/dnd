import json
import re
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Self
from uuid import uuid4

from aidm.config.settings import Settings
from aidm.store.db import create_db, open_db
from aidm.store.records import (
    FACT_KIND,
    CampaignInfo,
    FactSource,
    Provenance,
    Record,
    Visibility,
    VisibilityError,
)


def row_to_record(row: sqlite3.Row) -> Record:
    return Record(
        id=row["id"],
        kind=row["kind"],
        visibility=row["visibility"],
        player_id=row["player_id"],
        version=row["version"],
        provenance=json.loads(row["provenance"]) if row["provenance"] else None,
        data=json.loads(row["data"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


_ID = re.compile(r"[0-9a-f]{32}")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _fact_visibility(targets: Sequence[Record]) -> tuple[Visibility, str | None]:
    players = {t.player_id for t in targets if t.visibility is Visibility.PLAYER}
    if any(t.visibility is Visibility.DM for t in targets) or len(players) > 1:
        return Visibility.DM, None
    if players:
        return Visibility.PLAYER, players.pop()
    return Visibility.ALL, None


class CampaignStore:
    def __init__(self, conn: sqlite3.Connection, campaign_id: str) -> None:
        self.conn = conn
        self.campaign_id = campaign_id

    @staticmethod
    def _path(settings: Settings, campaign_id: str) -> Path:
        if not _ID.fullmatch(campaign_id):
            raise ValueError(f"bad campaign id: {campaign_id!r}")
        return settings.campaigns_dir / f"{campaign_id}.sqlite"

    @classmethod
    def create(cls, settings: Settings, title: str, is_test: bool) -> Self:
        campaign_id = uuid4().hex
        conn = create_db(cls._path(settings, campaign_id))
        conn.execute(
            "INSERT INTO meta (title, created_at, is_test, status) VALUES (?, ?, ?, 'draft')",
            (title, _now(), is_test),
        )
        return cls(conn, campaign_id)

    @classmethod
    def open(cls, settings: Settings, campaign_id: str) -> Self:
        return cls(open_db(cls._path(settings, campaign_id)), campaign_id)

    @classmethod
    def list_campaigns(cls, settings: Settings) -> list[CampaignInfo]:
        if not settings.campaigns_dir.is_dir():
            return []
        infos = []
        for path in sorted(settings.campaigns_dir.glob("*.sqlite")):
            with cls.open(settings, path.stem) as store:
                row = store.conn.execute("SELECT * FROM meta").fetchone()
                infos.append(CampaignInfo(id=path.stem, **dict(row)))
        return infos

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Все записи внутри коммитятся вместе; вложенный вызов входит во внешнюю транзакцию."""
        if self.conn.in_transaction:
            yield
            return
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    def get(self, record_id: str) -> Record:
        row = self.conn.execute("SELECT * FROM records WHERE id = ?", (record_id,)).fetchone()
        if row is None:
            raise KeyError(record_id)
        return row_to_record(row)

    def all_records(self) -> list[Record]:
        rows = self.conn.execute("SELECT * FROM records ORDER BY kind, id")
        return [row_to_record(r) for r in rows]

    def links(self, record_id: str) -> list[tuple[str, str, str]]:
        rows = self.conn.execute(
            "SELECT from_id, to_id, kind FROM links WHERE from_id = ? OR to_id = ? ORDER BY rowid",
            (record_id, record_id),
        )
        return [tuple(r) for r in rows]

    def put(self, record: Record) -> Record:
        if record.kind == FACT_KIND:
            raise ValueError("facts are written only through add_fact")
        return self._put(record)

    def _put(self, record: Record) -> Record:
        with self.transaction():
            old = self.conn.execute(
                "SELECT version, created_at FROM records WHERE id = ?", (record.id,)
            ).fetchone()
            now = datetime.now(UTC)
            # model_copy не валидирует, поэтому собираем запись заново через model_validate
            stored = Record.model_validate(
                record.model_dump()
                | {
                    "version": old["version"] + 1 if old else 1,
                    "created_at": old["created_at"] if old else now,
                    "updated_at": now,
                }
            )
            if old is not None:
                self._check_visibility_change(stored)
            self.conn.execute(
                "INSERT OR REPLACE INTO records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    stored.id,
                    stored.kind,
                    stored.visibility,
                    stored.player_id,
                    stored.version,
                    stored.provenance.model_dump_json() if stored.provenance else None,
                    json.dumps(stored.data, ensure_ascii=False),
                    stored.created_at.isoformat() if stored.created_at else None,
                    now.isoformat(),
                ),
            )
            if old is not None:
                self._refresh_facts(stored.id)
        return stored

    def _refresh_facts(self, record_id: str) -> None:
        """Видимость факта следует за целями «about», правило то же, что в add_fact."""
        fact_ids = self.conn.execute(
            "SELECT from_id FROM links WHERE to_id = ? AND kind = 'about'", (record_id,)
        ).fetchall()
        for (fact_id,) in fact_ids:
            target_ids = self.conn.execute(
                "SELECT to_id FROM links WHERE from_id = ? AND kind = 'about'", (fact_id,)
            ).fetchall()
            visibility, player_id = _fact_visibility([self.get(t) for (t,) in target_ids])
            self.conn.execute(
                "UPDATE records SET visibility = ?, player_id = ? WHERE id = ?",
                (visibility, player_id, fact_id),
            )

    def _check_visibility_change(self, record: Record) -> None:
        if record.visibility is Visibility.DM:
            bad = self.conn.execute(
                "SELECT 1 FROM links JOIN records r ON r.id = links.from_id"
                " WHERE links.to_id = ? AND r.visibility != 'dm'",
                (record.id,),
            ).fetchone()
        else:
            bad = self.conn.execute(
                "SELECT 1 FROM links JOIN records r ON r.id = links.to_id"
                " WHERE links.from_id = ? AND r.visibility = 'dm'",
                (record.id,),
            ).fetchone()
        if bad is not None:
            raise VisibilityError(f"record {record.id}: open records may link only to open ones")

    def link(self, from_id: str, to_id: str, kind: str) -> None:
        with self.transaction():
            src, dst = self.get(from_id), self.get(to_id)
            if src.visibility is not Visibility.DM and dst.visibility is Visibility.DM:
                raise VisibilityError(f"open record {from_id} cannot link to hidden {to_id}")
            self.conn.execute(
                "INSERT OR IGNORE INTO links (from_id, to_id, kind) VALUES (?, ?, ?)",
                (from_id, to_id, kind),
            )

    def add_fact(
        self,
        text: str,
        links: Sequence[str],
        source: FactSource,
        provenance: Provenance | None,
    ) -> Record:
        with self.transaction():
            targets = [self.get(i) for i in links]
            visibility, player_id = _fact_visibility(targets)
            fact = self._put(
                Record(
                    kind=FACT_KIND,
                    visibility=visibility,
                    player_id=player_id,
                    provenance=provenance,
                    data={"text": text, "source": source.value},
                )
            )
            for target in targets:
                self.link(fact.id, target.id, "about")
        return fact
