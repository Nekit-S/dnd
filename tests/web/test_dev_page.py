from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aidm.config.settings import Settings
from aidm.ledger.ledger import Ledger
from aidm.ledger.prices import TokenCounts
from aidm.store.campaign import CampaignStore
from aidm.store.records import Record, Visibility
from aidm.web.app import create_app

CANARY = "СЕКРЕТ-КАНАРЕЙКА"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(var_dir=tmp_path, dev_page=True)


def client(settings: Settings, host: str = "127.0.0.1") -> TestClient:
    return TestClient(create_app(settings), client=(host, 50000))


def secret_record() -> Record:
    return Record(kind="npc", visibility=Visibility.DM, data={"name": CANARY})


def test_dev_off_is_404(settings: Settings) -> None:
    off = settings.model_copy(update={"dev_page": False})
    assert client(off).get("/dev/ledger").status_code == 404


def test_remote_client_is_403(settings: Settings) -> None:
    assert client(settings, "192.168.1.5").get("/dev/ledger").status_code == 403


def test_ledger_page_lists_rows_and_totals(settings: Settings) -> None:
    ledger = Ledger(settings.ledger_path)
    attempt = ledger.start_attempt(
        category="generation/plot/secrets", provider="fake", model="m", effort=None,
        budget_scope="test",
    )  # fmt: skip
    ledger.finish_attempt(attempt, TokenCounts(uncached_input=10, output=5), Decimal("0.25"), "ok")
    html = client(settings).get("/dev/ledger").text
    assert "generation/plot/secrets" in html
    assert "generation/plot<" in html
    assert "0.25" in html


def test_test_campaign_shows_records(settings: Settings) -> None:
    with CampaignStore.create(settings, "Тест", is_test=True) as store:
        store.put(secret_record())
    page = client(settings).get(f"/dev/campaigns/{store.campaign_id}")
    assert page.status_code == 200
    assert CANARY in page.text


def test_real_campaign_is_403_without_leak(settings: Settings) -> None:
    with CampaignStore.create(settings, "Настоящая", is_test=False) as store:
        store.put(secret_record())
    c = client(settings)
    page = c.get(f"/dev/campaigns/{store.campaign_id}")
    assert page.status_code == 403
    assert CANARY not in page.text
    assert "Настоящая" not in c.get("/dev/campaigns").text
