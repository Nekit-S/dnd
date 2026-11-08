import pytest

from aidm.providers.capabilities import UnknownModelError, get_capability


@pytest.mark.parametrize("model", ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"])
def test_anthropic_models(model: str) -> None:
    cap = get_capability(model)
    assert cap.provider == "anthropic"
    assert cap.context_tokens == 1_000_000
    assert cap.min_cache_tokens == 512
    assert cap.batch and cap.prompt_cache and cap.structured_output


def test_fake_model() -> None:
    assert get_capability("fake-model").provider == "fake"


def test_unknown_model() -> None:
    with pytest.raises(UnknownModelError):
        get_capability("gpt-nope")
