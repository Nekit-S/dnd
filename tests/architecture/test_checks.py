from checks import (
    attr_uses,
    model_ids,
    rules_float_math,
    sqlite3_imports,
    sqlite_connect_args,
    web_store_imports,
)


def test_rules_float_math() -> None:
    assert rules_float_math("x = 1.5") == ["line 1: float literal"]
    assert rules_float_math("x = a / b") == ["line 1: true division"]
    assert rules_float_math("f = path / 'x'") == []
    assert rules_float_math("x /= 2") == ["line 1: true division"]
    assert rules_float_math("x = a // b + Fraction(1, 2)") == []


def test_model_ids() -> None:
    assert model_ids('m = "claude-opus-5-5"', set()) == ["claude-opus-5-5"]
    assert model_ids("m = 'gpt-5'", set()) == ["gpt-5"]
    assert model_ids("m = 'llama3'", {"llama3"}) == ["llama3"]
    assert model_ids("m = 'claude'  # nothing", set()) == []


def test_sqlite3_imports() -> None:
    assert sqlite3_imports("import sqlite3")
    assert sqlite3_imports("from sqlite3 import Row")
    assert sqlite3_imports("import json") == []


def test_sqlite_connect_args() -> None:
    assert sqlite_connect_args("sqlite3.connect('x.db')", "ledger_path")
    assert sqlite_connect_args("sqlite3.connect(settings.var_dir)", "ledger_path")
    assert sqlite_connect_args("sqlite3.connect(settings.ledger_path)", "ledger_path") == []
    assert sqlite_connect_args("sqlite3.connect(path, timeout=1)", "ledger_path") == []


def test_attr_uses() -> None:
    assert attr_uses("s.campaigns_dir", "campaigns_dir")
    assert attr_uses("s.other", "campaigns_dir") == []


def test_web_store_imports() -> None:
    assert web_store_imports("from aidm.store.campaign import CampaignStore")
    assert web_store_imports("from aidm.store import campaign")
    assert web_store_imports("import aidm.store.db")
    assert web_store_imports("from aidm.store.player_view import PlayerView") == []
    assert web_store_imports("from aidm.config.settings import Settings") == []
