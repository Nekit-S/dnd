import builtins

from aidm.store.campaign import CampaignStore, row_to_record
from aidm.store.records import Record


class NotFound(LookupError):
    pass


class PlayerView:
    """Единственный путь чтения для кода игроков; player_id=None — общий вид без личных записей."""

    def __init__(self, store: CampaignStore, player_id: str | None) -> None:
        self.__conn = store.conn
        self.__player_id = player_id

    def __visible(self, alias: str) -> tuple[str, tuple[str | None, ...]]:
        return (
            f"({alias}.visibility = 'all' OR ({alias}.visibility = 'player'"
            f" AND {alias}.player_id = ?))",
            (self.__player_id,),
        )

    def get(self, record_id: str) -> Record:
        where, params = self.__visible("r")
        row = self.__conn.execute(
            f"SELECT * FROM records r WHERE r.id = ? AND {where}", (record_id, *params)
        ).fetchone()
        if row is None:
            # одно сообщение без id: скрытую запись нельзя отличить от отсутствующей
            raise NotFound("record not found")
        return row_to_record(row)

    def list(self, kind: str) -> builtins.list[Record]:
        where, params = self.__visible("r")
        rows = self.__conn.execute(
            f"SELECT * FROM records r WHERE r.kind = ? AND {where} ORDER BY r.created_at, r.id",
            (kind, *params),
        )
        return [row_to_record(r) for r in rows]

    def links(self, record_id: str) -> builtins.list[tuple[str, str, str]]:
        self.get(record_id)
        src, src_params = self.__visible("a")
        dst, dst_params = self.__visible("b")
        rows = self.__conn.execute(
            "SELECT l.from_id, l.to_id, l.kind FROM links l"
            " JOIN records a ON a.id = l.from_id JOIN records b ON b.id = l.to_id"
            f" WHERE (l.from_id = ? OR l.to_id = ?) AND {src} AND {dst} ORDER BY l.rowid",
            (record_id, record_id, *src_params, *dst_params),
        )
        return [(r[0], r[1], r[2]) for r in rows]
