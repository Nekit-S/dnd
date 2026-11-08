import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict

_CATEGORY = re.compile(r"[a-z0-9_]+(/[a-z0-9_]+)+")


class UnknownCategoryError(LookupError):
    pass


class CacheTtl(BaseModel):
    model_config = ConfigDict(extra="forbid")
    direct: Literal["5m", "1h"]
    batch: Literal["5m", "1h"]


class Defaults(BaseModel):
    model_config = ConfigDict(extra="forbid")
    retries: int
    backoff_base_ms: int
    cache_ttl: CacheTtl


class CategoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str
    model: str
    effort: str | None
    max_input_tokens: int
    max_output_tokens: int
    repair_model: str | None = None
    cache_ttl: CacheTtl | None = None


class ModelsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    defaults: Defaults
    categories: dict[str, CategoryConfig]

    def resolve(self, category: str) -> CategoryConfig:
        """Запись с самым длинным совпавшим префиксом пути."""
        if not _CATEGORY.fullmatch(category):
            raise UnknownCategoryError(f"bad category path: {category!r}")
        parts = category.split("/")
        for n in range(len(parts), 0, -1):
            entry = self.categories.get("/".join(parts[:n]))
            if entry is not None:
                return entry
        raise UnknownCategoryError(f"no config for category: {category!r}")


def _reject_floats(node: Any, path: str = "") -> None:
    if isinstance(node, float):
        raise ValueError(f"float in models config at {path or '<root>'}")
    if isinstance(node, dict):
        for k, v in node.items():
            _reject_floats(v, f"{path}/{k}")


def load_models_config(path: Path) -> ModelsConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    _reject_floats(raw)
    return ModelsConfig.model_validate(raw)
