import json
from pathlib import Path
from typing import Any

import httpx
import ollama  # noqa: TID251
import pytest

from aidm.providers import capabilities
from aidm.providers.base import Message, ProviderError, ProviderRequest
from aidm.providers.capabilities import Capability
from aidm.providers.ollama import OllamaProvider

FIXTURE = Path(__file__).parent / "fixtures/ollama/chat.json"
SCHEMA = {"type": "object", "properties": {"a": {"type": "integer"}}}


def provider(handler: Any) -> OllamaProvider:
    client = ollama.Client(host="http://test", transport=httpx.MockTransport(handler))
    return OllamaProvider(client)


def req(schema: dict[str, Any] | None = None) -> ProviderRequest:
    return ProviderRequest(
        model="local-x",
        effort=None,
        system_prefix=["s1"],
        messages=[Message("user", "hi")],
        max_output_tokens=50,
        json_schema=schema,
    )


def test_request_shape_and_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        capabilities.CAPABILITIES,
        "local-x",
        Capability("ollama", 8192, True, False, False, 0, False, False),
    )
    sent: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.update(json.loads(request.content))
        return httpx.Response(200, json=json.loads(FIXTURE.read_text()))

    p = provider(handler)
    resp = p.complete(req(SCHEMA))
    assert sent["messages"][0] == {"role": "system", "content": "s1"}
    assert sent["format"] == SCHEMA
    assert sent["options"] == {"num_predict": 50, "num_ctx": 8192}
    assert sent["stream"] is False
    assert (resp.text, resp.stop_reason) == ("Hello!", "end")
    assert resp.parsed_json is None
    assert (resp.usage.uncached_input, resp.usage.output) == (26, 298)
    assert p.is_local
    assert p.count_tokens(req()) is None


def test_length_stop_and_json() -> None:
    body = json.loads(FIXTURE.read_text())
    body["message"]["content"] = '{"a": 1}'
    body["done_reason"] = "length"
    resp = provider(lambda r: httpx.Response(200, json=body)).complete(req(SCHEMA))
    assert resp.parsed_json == {"a": 1}
    assert resp.stop_reason == "max_tokens"


@pytest.mark.parametrize(
    ("status", "retryable"), [(500, True), (503, True), (429, True), (404, False), (400, False)]
)
def test_status_errors(status: int, retryable: bool) -> None:
    p = provider(lambda r: httpx.Response(status, json={"error": "model SECRET-PROMPT"}))
    with pytest.raises(ProviderError) as ei:
        p.complete(req())
    assert ei.value.retryable is retryable
    assert "SECRET-PROMPT" not in str(ei.value)


def test_server_down_retryable() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(ProviderError) as ei:
        provider(boom).complete(req())
    assert ei.value.retryable
