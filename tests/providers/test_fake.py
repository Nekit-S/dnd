import pytest

from aidm.config.settings import Settings
from aidm.providers import registry
from aidm.providers.base import Message, ProviderError, ProviderRequest
from aidm.providers.fake import FakeProvider


def req(schema: dict[str, object] | None = None) -> ProviderRequest:
    return ProviderRequest(
        model="fake-model",
        effort=None,
        system_prefix=["abcd"],
        messages=[Message("user", "efgh")],
        max_output_tokens=100,
        json_schema=schema,
        category="dev/smoke",
        place="p1",
    )


SCRIPT = {("dev/smoke", "p1"): '{"a": 1}'}


def test_scripted_text_and_usage() -> None:
    p = FakeProvider(SCRIPT)
    r = p.complete(req())
    assert r.text == '{"a": 1}'
    assert r.stop_reason == "end"
    assert (r.usage.uncached_input, r.usage.output) == (4, 4)
    assert p.complete(req()).usage == r.usage
    assert p.count_tokens(req()) == 4


def test_parsed_json_with_schema() -> None:
    assert FakeProvider(SCRIPT).complete(req({"type": "object"})).parsed_json == {"a": 1}


def test_retryable_then_fatal_then_normal() -> None:
    p = FakeProvider(SCRIPT, ["retryable", "fatal"])
    with pytest.raises(ProviderError) as e1:
        p.complete(req())
    assert e1.value.retryable
    with pytest.raises(ProviderError) as e2:
        p.complete(req())
    assert not e2.value.retryable
    assert p.complete(req()).text == '{"a": 1}'


def test_truncated_fires_once() -> None:
    p = FakeProvider(SCRIPT, ["truncated"])
    r = p.complete(req({"type": "object"}))
    assert r.stop_reason == "max_tokens" and r.parsed_json is None
    assert p.complete(req()).stop_reason == "end"


def test_invalid_json_fires_once() -> None:
    p = FakeProvider(SCRIPT, ["invalid_json"])
    r = p.complete(req({"type": "object"}))
    assert r.parsed_json is None and r.stop_reason == "end"
    assert p.complete(req({"type": "object"})).parsed_json == {"a": 1}


def test_registry() -> None:
    assert registry.get("fake", Settings()).name == "fake"
    with pytest.raises(registry.UnknownProviderError):
        registry.get("nope", Settings())
