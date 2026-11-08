from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from hypothesis import given
from hypothesis import settings as hsettings
from hypothesis import strategies as st

from aidm.config.settings import Settings
from aidm.store.campaign import CampaignStore
from aidm.store.player_view import NotFound, PlayerView
from aidm.store.records import FactSource, Record, Visibility, VisibilityError


@pytest.fixture
def store(tmp_path: Path) -> Iterator[CampaignStore]:
    with CampaignStore.create(Settings(var_dir=tmp_path), "Долина", is_test=True) as s:
        yield s


def rec(vis: Visibility, player_id: str | None = None, kind: str = "npc") -> Record:
    return Record(kind=kind, visibility=vis, player_id=player_id)


def test_visibility_per_view(store: CampaignStore) -> None:
    dm = store.put(rec(Visibility.DM))
    all_ = store.put(rec(Visibility.ALL))
    p1 = store.put(rec(Visibility.PLAYER, "p1"))
    p2 = store.put(rec(Visibility.PLAYER, "p2"))
    shared, v1 = PlayerView(store, None), PlayerView(store, "p1")
    assert [r.id for r in shared.list("npc")] == [all_.id]
    assert {r.id for r in v1.list("npc")} == {all_.id, p1.id}
    assert v1.get(p1.id) == store.get(p1.id)
    assert shared.get(all_.id).id == all_.id
    for view, hidden in [(shared, dm), (shared, p1), (v1, dm), (v1, p2)]:
        with pytest.raises(NotFound):
            view.get(hidden.id)


def test_list_filters_kind(store: CampaignStore) -> None:
    store.put(rec(Visibility.ALL, kind="place"))
    assert PlayerView(store, None).list("npc") == []


def test_not_found_same_for_hidden_and_missing(store: CampaignStore) -> None:
    hidden = store.put(rec(Visibility.DM))
    view = PlayerView(store, "p1")
    errors = []
    for record_id in [hidden.id, "0" * 32]:
        with pytest.raises(NotFound) as info:
            view.get(record_id)
        errors.append(info.value)
    assert str(errors[0]).replace(hidden.id, "") == str(errors[1]).replace("0" * 32, "")
    assert hidden.id not in str(errors[0]) and "0" * 32 not in str(errors[1])
    with pytest.raises(NotFound):
        view.links(hidden.id)


def test_links_skip_hidden_ends(store: CampaignStore) -> None:
    secret = store.put(rec(Visibility.DM))
    town = store.put(rec(Visibility.ALL))
    p1 = store.put(rec(Visibility.PLAYER, "p1"))
    store.link(secret.id, town.id, "secret_of")
    store.link(town.id, p1.id, "home_of")
    assert PlayerView(store, None).links(town.id) == []
    assert PlayerView(store, "p1").links(town.id) == [(town.id, p1.id, "home_of")]
    assert PlayerView(store, "p2").links(town.id) == []


def test_fact_follows_target_visibility_change(store: CampaignStore) -> None:
    npc = store.put(rec(Visibility.ALL))
    store.add_fact("SECRET", [npc.id], FactSource.GAME, None)
    store.put(npc.model_copy(update={"visibility": Visibility.PLAYER, "player_id": "p1"}))
    assert [f.data["text"] for f in PlayerView(store, "p1").list("fact")] == ["SECRET"]
    assert PlayerView(store, "p2").list("fact") == []
    assert PlayerView(store, None).list("fact") == []
    store.put(npc.model_copy(update={"visibility": Visibility.PLAYER, "player_id": "p2"}))
    assert PlayerView(store, "p1").list("fact") == []
    assert len(PlayerView(store, "p2").list("fact")) == 1


def test_view_has_no_writes_or_store() -> None:
    public = {n for n in dir(PlayerView) if not n.startswith("_")}
    assert public == {"get", "list", "links"}


_VIS = st.sampled_from(list(Visibility))
_PLAYERS = st.sampled_from(["p1", "p2", "p3"])


@hsettings(max_examples=40, deadline=None)
@given(
    specs=st.lists(st.tuples(_VIS, _PLAYERS), min_size=1, max_size=8),
    links=st.lists(st.tuples(st.integers(0, 7), st.integers(0, 7)), max_size=12),
    facts=st.lists(st.lists(st.integers(0, 7), min_size=1, max_size=3), max_size=4),
)
def test_no_leaks(
    specs: list[tuple[Visibility, str]],
    links: list[tuple[int, int]],
    facts: list[list[int]],
) -> None:
    with (
        TemporaryDirectory() as tmp,
        CampaignStore.create(Settings(var_dir=Path(tmp)), "x", is_test=True) as store,
    ):
        ids = [store.put(rec(v, p if v is Visibility.PLAYER else None)).id for v, p in specs]
        for a, b in links:
            try:
                store.link(ids[a % len(ids)], ids[b % len(ids)], "rel")
            except VisibilityError:
                pass
        for targets in facts:
            ids.append(
                store.add_fact("f", [ids[t % len(ids)] for t in targets], FactSource.GAME, None).id
            )

        # Смена видимости после появления фактов: факты должны её догнать
        for (v, p), rid in zip(specs, ids, strict=False):
            new = Visibility.PLAYER if v is Visibility.ALL else Visibility.ALL
            try:
                store.put(
                    store.get(rid).model_copy(
                        update={
                            "visibility": new,
                            "player_id": p if new is Visibility.PLAYER else None,
                        }
                    )
                )
            except VisibilityError:
                pass

        for player in [None, "p1", "p2", "p3"]:
            view = PlayerView(store, player)

            def ok(r: Record, player: str | None = player) -> bool:
                return r.visibility is Visibility.ALL or (
                    r.visibility is Visibility.PLAYER and r.player_id == player
                )

            seen = view.list("npc") + view.list("fact")
            assert all(ok(r) for r in seen)
            assert {r.id for r in seen} == {i for i in ids if ok(store.get(i))}
            for i in ids:
                try:
                    assert ok(view.get(i))
                except NotFound:
                    assert not ok(store.get(i))
                    continue
                for src, dst, _ in view.links(i):
                    assert ok(store.get(src)) and ok(store.get(dst))
