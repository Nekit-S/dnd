from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError, model_validator

DEFAULT_DIR = Path(__file__).resolve().parents[1] / "resources" / "prices"
_QUANTUM = Decimal("0.000001")
_MTOK = Decimal(1_000_000)


class UnknownPriceError(LookupError):
    pass


class PriceFileError(ValueError):
    pass


def _require_str(value: Any) -> Any:
    # Цены только строками: YAML-число стало бы float и потеряло бы точность
    if not isinstance(value, str):
        raise ValueError("price must be a string")
    return value


Price = Annotated[Decimal, BeforeValidator(_require_str), Field(ge=0)]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TokenCounts(_Frozen):
    uncached_input: int = Field(0, ge=0)
    cache_write_5m: int = Field(0, ge=0)
    cache_write_1h: int = Field(0, ge=0)
    cache_read: int = Field(0, ge=0)
    output: int = Field(0, ge=0)

    @property
    def prompt(self) -> int:
        return self.uncached_input + self.cache_write_5m + self.cache_write_1h + self.cache_read


class Tier(_Frozen):
    max_prompt_tokens: int | None = Field(None, gt=0)
    input: Price
    cache_write_5m: Price
    cache_write_1h: Price
    cache_read: Price
    output: Price


class PriceFile(_Frozen):
    as_of: str
    batch_multiplier: Price
    models: dict[str, list[Tier]]

    @model_validator(mode="after")
    def _tiers_ordered(self) -> "PriceFile":
        for model, tiers in self.models.items():
            limits = [t.max_prompt_tokens for t in tiers]
            bounded = [n for n in limits if n is not None]
            if not limits or limits[-1] is not None or limits[:-1] != sorted(bounded):
                raise ValueError(f"{model}: tiers must ascend and end with an open tier")
        return self


@dataclass(frozen=True)
class _ModelPrice:
    tiers: list[Tier]
    batch_multiplier: Decimal
    as_of: str


class Prices:
    def __init__(self, models: dict[str, _ModelPrice]) -> None:
        self._models = models

    def _get(self, model: str) -> _ModelPrice:
        try:
            return self._models[model]
        except KeyError:
            raise UnknownPriceError(model) from None

    def as_of(self, model: str) -> str:
        return self._get(model).as_of

    def cost(
        self, model: str, counts: TokenCounts, batch: bool = False, is_local: bool = False
    ) -> Decimal:
        if is_local:
            return Decimal(0)
        price = self._get(model)
        prompt = counts.prompt
        tier = next(
            t for t in price.tiers if t.max_prompt_tokens is None or prompt <= t.max_prompt_tokens
        )
        total = (
            counts.uncached_input * tier.input
            + counts.cache_write_5m * tier.cache_write_5m
            + counts.cache_write_1h * tier.cache_write_1h
            + counts.cache_read * tier.cache_read
            + counts.output * tier.output
        ) / _MTOK
        if batch:
            total *= price.batch_multiplier
        return total.quantize(_QUANTUM, rounding=ROUND_HALF_UP)


def load_prices(directory: Path = DEFAULT_DIR) -> Prices:
    models: dict[str, _ModelPrice] = {}
    for path in sorted(directory.glob("*.yaml")):
        try:
            data = PriceFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        except ValidationError as e:
            raise PriceFileError(f"{path}: {e}") from e
        for model, tiers in data.models.items():
            if model in models:
                raise PriceFileError(f"{path}: duplicate price for {model}")
            models[model] = _ModelPrice(tiers, data.batch_multiplier, data.as_of)
    return Prices(models)
