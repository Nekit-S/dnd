import os

import pytest

from aidm.config.settings import Settings


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Тесты не читают .env разработчика и не зависят от его AIDM_* переменных
    for name in [n for n in os.environ if n.startswith("AIDM_")]:
        monkeypatch.delenv(name)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
