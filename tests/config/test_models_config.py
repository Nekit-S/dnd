from pathlib import Path

import pytest

from aidm.config.models import ModelsConfig, UnknownCategoryError, load_models_config

YAML = """
defaults:
  retries: 3
  backoff_base_ms: 500
  cache_ttl: {direct: 5m, batch: 1h}
categories:
  generation:
    {provider: anthropic, model: m-a, effort: null, max_input_tokens: 10, max_output_tokens: 5}
  generation/plot:
    {provider: anthropic, model: m-b, effort: high, max_input_tokens: 20, max_output_tokens: 6}
"""


def _load(tmp_path: Path, text: str = YAML) -> ModelsConfig:
    p = tmp_path / "models.yaml"
    p.write_text(text)
    return load_models_config(p)


def test_resolve_longest_prefix(tmp_path: Path) -> None:
    cfg = _load(tmp_path)
    assert cfg.resolve("generation/plot/secrets").model == "m-b"
    assert cfg.resolve("generation/npc").model == "m-a"


@pytest.mark.parametrize(
    "bad", ["", "generation", "Generation/plot", "other/x", "a//b", "generation/"]
)
def test_reject_missing_or_malformed_category(tmp_path: Path, bad: str) -> None:
    with pytest.raises(UnknownCategoryError):
        _load(tmp_path).resolve(bad)


def test_float_in_yaml_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="float"):
        _load(tmp_path, YAML.replace("max_input_tokens: 10", "max_input_tokens: 10.5"))


def test_repo_models_yaml_loads() -> None:
    cfg = load_models_config(Path("config/models.yaml"))
    assert cfg.resolve("dev/smoke").max_output_tokens == 64
