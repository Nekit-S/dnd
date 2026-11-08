import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from aidm.config.settings import Settings
from aidm.store.campaign import CampaignStore
from aidm.store.db import SchemaVersionError
from aidm.store.records import FactSource, Provenance, Record, Visibility, VisibilityError


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(var_dir=tmp_path)


@pytest.fixture
def store(settings: Settings) -> Iterator[CampaignStore]:
    with CampaignStore.create(settings, "Туманная долина", is_test=True) as s:
        yield s


def rec(vis: Visibility, player_id: str | None = None) -> Record:
    return Record(kind="npc", visibility=vis, player_id=player_id, data={"name": "Ольгерд"})


def test_create_open_list(settings: Settings) -> None:
    with CampaignStore.create(settings, "Первая", is_test=False) as a:
        r = a.put(rec(Visibility.ALL))
    with CampaignStore.create(settings, "Вторая", is_test=True) as b:
        pass
    with CampaignStore.open(settings, a.campaign_id) as again:
        assert again.get(r.id).data == {"name": "Ольгерд"}
    infos = {c.id: c for c in CampaignStore.list_campaigns(settings)}
    assert {i.title for i in infos.values()} == {"Первая", "Вторая"}
    assert infos[a.campaign_id].is_test is False
    assert infos[b.campaign_id].is_test is True


def test_list_without_dir_is_empty(settings: Settings) -> None:
    assert CampaignStore.list_campaigns(settings) == []


def test_open_missing_campaign(settings: Settings) -> None:
    with pytest.raises(FileNotFoundError):
        CampaignStore.open(settings, "0" * 32)


def test_unknown_schema_version_rejected(settings: Settings) -> None:
    with CampaignStore.create(settings, "Старая", is_test=True) as s:
        pass
    conn = sqlite3.connect(settings.campaigns_dir / f"{s.campaign_id}.sqlite")
    conn.execute("PRAGMA user_version = 99")
    conn.close()
    with pytest.raises(SchemaVersionError):
        CampaignStore.open(settings, s.campaign_id)


def test_version_increments(store: CampaignStore) -> None:
    r = store.put(rec(Visibility.DM))
    assert r.version == 1
    r2 = store.put(r.model_copy(update={"data": {"name": "Ольгерд Рыжий"}}))
    assert r2.version == 2
    assert store.get(r.id).version == 2
    assert store.get(r.id).data == {"name": "Ольгерд Рыжий"}


def test_provenance_round_trip(store: CampaignStore) -> None:
    prov = Provenance(step="world", model="m", attempt_id=7)
    r = store.put(rec(Visibility.DM).model_copy(update={"provenance": prov}))
    assert store.get(r.id).provenance == prov


def test_player_visibility_requires_player_id() -> None:
    with pytest.raises(ValueError):
        rec(Visibility.PLAYER)
    with pytest.raises(ValueError):
        rec(Visibility.ALL, player_id="p1")


def test_transaction_rollback_leaves_nothing(store: CampaignStore) -> None:
    kept = store.put(rec(Visibility.DM))
    with pytest.raises(RuntimeError), store.transaction():
        a = store.put(rec(Visibility.DM))
        store.put(kept.model_copy(update={"data": {"x": 1}}))
        store.link(a.id, kept.id, "knows")
        raise RuntimeError("step failed")
    with pytest.raises(KeyError):
        store.get(a.id)
    assert store.get(kept.id).version == 1
    assert store.links(kept.id) == []


def test_link_from_open_to_hidden_rejected(store: CampaignStore) -> None:
    open_ = store.put(rec(Visibility.ALL))
    hidden = store.put(rec(Visibility.DM))
    with pytest.raises(VisibilityError):
        store.link(open_.id, hidden.id, "secret")
    store.link(hidden.id, open_.id, "secret_of")
    assert store.links(hidden.id) == [(hidden.id, open_.id, "secret_of")]


def test_cannot_hide_record_linked_from_open(store: CampaignStore) -> None:
    open_ = store.put(rec(Visibility.ALL))
    target = store.put(rec(Visibility.ALL))
    store.link(open_.id, target.id, "near")
    with pytest.raises(VisibilityError):
        store.put(target.model_copy(update={"visibility": Visibility.DM}))


def test_cannot_open_record_linking_to_hidden(store: CampaignStore) -> None:
    src = store.put(rec(Visibility.DM))
    hidden = store.put(rec(Visibility.DM))
    store.link(src.id, hidden.id, "knows")
    with pytest.raises(VisibilityError):
        store.put(src.model_copy(update={"visibility": Visibility.ALL}))


def test_link_to_missing_record(store: CampaignStore) -> None:
    a = store.put(rec(Visibility.DM))
    with pytest.raises(KeyError):
        store.link(a.id, "missing", "knows")


def test_fact_visibility_dm_if_any_hidden(store: CampaignStore) -> None:
    ids = [store.put(rec(Visibility.ALL)).id, store.put(rec(Visibility.DM)).id]
    f = store.add_fact("Мэр — брат контрабандиста", ids, FactSource.GENERATION, None)
    assert (f.visibility, f.player_id) == (Visibility.DM, None)


def test_fact_visibility_dm_if_two_players(store: CampaignStore) -> None:
    ids = [store.put(rec(Visibility.PLAYER, "p1")).id, store.put(rec(Visibility.PLAYER, "p2")).id]
    f = store.add_fact("Они кузены", ids, FactSource.BACKSTORY, None)
    assert (f.visibility, f.player_id) == (Visibility.DM, None)


def test_fact_visibility_one_player(store: CampaignStore) -> None:
    ids = [store.put(rec(Visibility.PLAYER, "p1")).id, store.put(rec(Visibility.ALL)).id]
    f = store.add_fact("Её наставник — мэр", ids, FactSource.BACKSTORY, None)
    assert (f.visibility, f.player_id) == (Visibility.PLAYER, "p1")
    assert {to for _, to, _ in store.links(f.id)} == set(ids)


def test_fact_visibility_all(store: CampaignStore) -> None:
    ids = [store.put(rec(Visibility.ALL)).id, store.put(rec(Visibility.ALL)).id]
    prov = Provenance(step="plot", model="m", attempt_id=1)
    f = store.add_fact("Таверна стоит у моста", ids, FactSource.GENERATION, prov)
    assert (f.visibility, f.player_id) == (Visibility.ALL, None)
    stored = store.get(f.id)
    assert stored.data == {"text": "Таверна стоит у моста", "source": "generation"}
    assert stored.provenance == prov


def test_put_rejects_facts(store: CampaignStore) -> None:
    f = store.add_fact("x", [store.put(rec(Visibility.ALL)).id], FactSource.GENERATION, None)
    with pytest.raises(ValueError):
        store.put(store.get(f.id).model_copy(update={"visibility": Visibility.ALL}))


@pytest.mark.parametrize("bad", ["../x", "abc", "", "A" * 32])
def test_bad_campaign_id_rejected(settings: Settings, bad: str) -> None:
    with pytest.raises(ValueError):
        CampaignStore.open(settings, bad)
