"""Архитектурные проверки по реальному дереву."""

from pathlib import Path

import yaml
from checks import (
    attr_uses,
    model_ids,
    rules_float_math,
    sqlite3_imports,
    sqlite_connect_args,
    web_store_imports,
)

from aidm.providers.capabilities import CAPABILITIES

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "aidm"


def py(pkg: str) -> list[Path]:
    return sorted((SRC / pkg).rglob("*.py"))


def violations(paths: list[Path], check) -> list[str]:  # type: ignore[no-untyped-def]
    return [f"{p.relative_to(ROOT)}: {v}" for p in paths for v in check(p.read_text())]


def test_rules_have_no_floats_or_division() -> None:
    assert violations(py("rules"), rules_float_math) == []


def test_model_ids_only_in_config_and_capabilities() -> None:
    cfg = yaml.safe_load((ROOT / "config" / "models.yaml").read_text())
    known = {c["model"] for c in cfg["categories"].values()} | set(CAPABILITIES)
    allowed = {
        ROOT / "config" / "models.yaml",
        SRC / "providers" / "capabilities.py",
    }
    scanned = [
        p
        for p in [*(ROOT / "src").rglob("*"), *(ROOT / "config").rglob("*")]
        if p.is_file()
        and p.suffix in {".py", ".yaml", ".yml", ".html", ".css", ".js", ".json"}
        and p not in allowed
        and (SRC / "resources" / "prices") not in p.parents
    ]
    assert violations(scanned, lambda text: model_ids(text, known)) == []


def test_sqlite3_only_in_store_and_ledger() -> None:
    others = [p for p in SRC.rglob("*.py") if p.parent.name not in {"store", "ledger"}]
    assert violations(others, sqlite3_imports) == []


def test_sqlite_connect_arguments() -> None:
    assert violations(py("ledger"), lambda s: sqlite_connect_args(s, "ledger_path")) == []
    assert violations(py("store"), lambda s: sqlite_connect_args(s, "campaigns_dir")) == []


def test_campaigns_dir_only_in_store() -> None:
    # config объявляет свойство, store единственный его читает
    others = [p for p in SRC.rglob("*.py") if p.parent.name not in {"store", "config"}]
    assert violations(others, lambda s: attr_uses(s, "campaigns_dir")) == []


def test_web_reads_store_only_through_player_view() -> None:
    others = [p for p in py("web") if p.name != "dev.py"]
    assert violations(others, web_store_imports) == []


def test_no_raw_store_connection_outside_store() -> None:
    others = [p for p in SRC.rglob("*.py") if p.parent.name != "store"]
    assert violations(others, lambda s: attr_uses(s, "conn")) == []
