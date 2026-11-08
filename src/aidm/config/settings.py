from decimal import Decimal
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="AIDM_", extra="ignore")

    # Ключи провайдеров читаются под стандартными именами, без префикса
    anthropic_api_key: SecretStr | None = Field(None, validation_alias="ANTHROPIC_API_KEY")
    openai_api_key: SecretStr | None = Field(None, validation_alias="OPENAI_API_KEY")
    openai_base_url: str | None = Field(None, validation_alias="OPENAI_BASE_URL")
    ollama_host: str | None = Field(None, validation_alias="OLLAMA_HOST")

    var_dir: Path = Path("var")
    models_config: Path = Path("config/models.yaml")
    dev_page: bool = False
    monthly_limit_usd: Decimal = Decimal(100)
    live_test_limit_usd: Decimal = Decimal(20)
    bind_host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"

    @property
    def ledger_path(self) -> Path:
        return self.var_dir / "ledger.sqlite"

    @property
    def campaigns_dir(self) -> Path:
        return self.var_dir / "campaigns"
