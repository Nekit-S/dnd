from decimal import Decimal

import pytest

from aidm.config.settings import Settings
from aidm.gateway.gateway import LLMRequest, build
from aidm.ledger.ledger import Ledger
from aidm.ledger.prices import load_prices
from aidm.providers.base import Message


@pytest.mark.live
def test_anthropic_smoke() -> None:
    # Настоящий .env и общий журнал: траты тестов должны попасть в лимит тестов
    settings = Settings(_env_file=".env")
    result = build(settings).call(
        LLMRequest(
            category="dev/smoke",
            budget_scope="test",
            place="smoke",
            messages=[Message(role="user", content="Ответь одним словом: да.")],
        )
    )
    assert result.status == "ok"
    assert result.text.strip()
    assert result.usage.uncached_input > 0 and result.usage.output > 0
    assert result.cost > Decimal(0)

    row = Ledger(settings.ledger_path).rows(1)[0]
    assert row.id == result.ledger_row_id
    assert row.status == "ok"
    assert row.budget_scope == "test"
    assert row.cost == result.cost
    assert row.price_as_of == load_prices().as_of(row.model)
