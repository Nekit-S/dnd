from decimal import Decimal
from pathlib import Path

import pytest

from aidm.config.settings import Settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AIDM_VAR_DIR", "AIDM_PORT"):
        monkeypatch.delenv(name, raising=False)


def test_secret_not_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret-value")
    s = Settings(_env_file=None)
    assert "sk-secret-value" not in repr(s)
    assert "sk-secret-value" not in str(s)
    assert s.anthropic_api_key is not None
    assert s.anthropic_api_key.get_secret_value() == "sk-secret-value"


def test_defaults() -> None:
    s = Settings(_env_file=None)
    assert s.monthly_limit_usd == Decimal(100)
    assert s.live_test_limit_usd == Decimal(20)
    assert isinstance(s.monthly_limit_usd, Decimal)
    assert s.ledger_path == Path("var/ledger.sqlite")
    assert s.campaigns_dir == Path("var/campaigns")
    assert (s.bind_host, s.port, s.log_level, s.dev_page) == ("127.0.0.1", 8000, "INFO", False)


def test_aidm_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AIDM_VAR_DIR", "/x")
    monkeypatch.setenv("AIDM_PORT", "9000")
    s = Settings(_env_file=None)
    assert s.campaigns_dir == Path("/x/campaigns")
    assert s.port == 9000


def test_empty_env_values_use_defaults(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("AIDM_PORT=\nAIDM_DEV_PAGE=\nAIDM_MONTHLY_LIMIT_USD=\n", encoding="utf-8")
    s = Settings(_env_file=env)
    assert (s.port, s.dev_page, s.monthly_limit_usd) == (8000, False, Decimal(100))
