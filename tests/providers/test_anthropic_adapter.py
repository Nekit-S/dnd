import json
from pathlib import Path
from typing import Any

import httpx2
import pytest

from aidm.config.settings import Settings
from aidm.providers.anthropic import AnthropicProvider, build
from aidm.providers.base import CacheTtl, Message, ProviderError, ProviderRequest, ProviderUsage

FIXTURES = Path(__file__).parent / "fixtures" / "anthropic"


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def mock_provider(handler: Any) -> AnthropicProvider:
    client = httpx2.Client(transport=httpx2.MockTransport(handler))
    return build(Settings(ANTHROPIC_API_KEY="test-key"), http_client=client)


class Server:
    """Отвечает фикстурой и запоминает тела запросов."""

    def __init__(self, name: str, status: int = 200) -> None:
        self.name, self.status = name, status
        self.bodies: list[dict[str, Any]] = []
        self.paths: list[str] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.bodies.append(json.loads(request.content))
        self.paths.append(request.url.path)
        return httpx2.Response(self.status, json=fixture(self.name))

    def provider(self) -> AnthropicProvider:
        return mock_provider(self)


def req(
    schema: dict[str, Any] | None = None,
    ttl: CacheTtl | None = None,
    effort: str | None = None,
) -> ProviderRequest:
    return ProviderRequest(
        model="claude-haiku-5-5",
        effort=effort,
        system_prefix=["rules", "canon"],
        messages=[Message("user", "hello")],
        max_output_tokens=64,
        json_schema=schema,
        cache_ttl=ttl,
    )


SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string"}},
    "required": ["name"],
    "additionalProperties": False,
}


def test_plain_reply() -> None:
    s = Server("plain.json")
    r = s.provider().complete(req(effort="low"))
    assert r.text == "Привет, путник."
    assert r.parsed_json is None
    assert r.stop_reason == "end"
    assert r.usage == ProviderUsage(uncached_input=10, output=5)
    body = s.bodies[0]
    assert body["model"] == "claude-haiku-5-5"
    assert body["max_tokens"] == 64
    assert body["output_config"] == {"effort": "low"}
    assert body["messages"] == [{"role": "user", "content": "hello"}]
    assert body["system"] == [{"type": "text", "text": "rules"}, {"type": "text", "text": "canon"}]
    assert "thinking" not in body


def test_structured_reply() -> None:
    s = Server("structured.json")
    r = s.provider().complete(req(schema=SCHEMA))
    assert r.parsed_json == {"name": "Борин"}
    assert s.bodies[0]["output_config"] == {"format": {"type": "json_schema", "schema": SCHEMA}}


@pytest.mark.parametrize(
    ("name", "ttl", "usage"),
    [
        ("cache_write_5m.json", "5m", ProviderUsage(12, 600, 0, 0, 5)),
        ("cache_write_1h.json", "1h", ProviderUsage(12, 0, 700, 0, 5)),
        ("cache_read.json", "5m", ProviderUsage(12, 0, 0, 600, 5)),
    ],
)
def test_cache_marker_and_usage(name: str, ttl: CacheTtl, usage: ProviderUsage) -> None:
    s = Server(name)
    r = s.provider().complete(req(ttl=ttl))
    assert r.usage == usage
    system = s.bodies[0]["system"]
    assert "cache_control" not in system[0]
    assert system[-1]["cache_control"] == {"type": "ephemeral", "ttl": ttl}


def test_max_tokens_stop() -> None:
    r = Server("max_tokens.json").provider().complete(req(schema=SCHEMA))
    assert r.stop_reason == "max_tokens"
    assert r.parsed_json is None


def test_count_tokens_uses_count_endpoint() -> None:
    s = Server("count_tokens.json")
    assert s.provider().count_tokens(req(schema=SCHEMA, ttl="5m")) == 42
    assert s.paths == ["/v1/messages/count_tokens"]
    assert "max_tokens" not in s.bodies[0]
    assert s.bodies[0]["output_config"]["format"]["schema"] == SCHEMA


@pytest.mark.parametrize(
    ("status", "name", "retryable"),
    [
        (429, "error_429.json", True),
        (529, "error_529.json", True),
        (401, "error_401.json", False),
        (400, "error_400.json", False),
    ],
)
def test_error_classification(status: int, name: str, retryable: bool) -> None:
    with pytest.raises(ProviderError) as e:
        Server(name, status).provider().complete(req())
    assert e.value.retryable is retryable
    assert "hello" not in str(e.value) and "rules" not in str(e.value)


def test_network_error_is_retryable() -> None:
    def fail(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("down")

    with pytest.raises(ProviderError) as e:
        mock_provider(fail).complete(req())
    assert e.value.retryable is True


def test_build_disables_sdk_retries() -> None:
    assert build(Settings(ANTHROPIC_API_KEY="k")).client.max_retries == 0
