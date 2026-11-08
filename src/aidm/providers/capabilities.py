from dataclasses import dataclass


class UnknownModelError(LookupError):
    pass


@dataclass(frozen=True)
class Capability:
    provider: str
    context_tokens: int
    structured_output: bool
    batch: bool
    prompt_cache: bool
    min_cache_tokens: int
    vision: bool
    exact_token_count: bool


_ANTHROPIC_5_5 = Capability("anthropic", 1_000_000, True, True, True, 512, True, True)

CAPABILITIES: dict[str, Capability] = {
    "claude-opus-5-5": _ANTHROPIC_5_5,
    "claude-sonnet-5-5": _ANTHROPIC_5_5,
    "claude-haiku-5-5": _ANTHROPIC_5_5,
    "fake-model": Capability("fake", 100_000, True, False, True, 512, False, True),
}


def get_capability(model: str) -> Capability:
    try:
        return CAPABILITIES[model]
    except KeyError:
        raise UnknownModelError(f"no capabilities for model: {model!r}") from None
