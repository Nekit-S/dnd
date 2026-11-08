import json
from pathlib import Path
from typing import Any

import httpx2
import openai  # noqa: TID251
import pytest

from aidm.providers.base import Message, ProviderError, ProviderRequest
from aidm.providers.openai import OpenAIProvider

FIXTURE = Path(__file__).parent / "fixtures/openai/completion.json"
SCHEMA = {"type": "object", "properties": {"a": {"type": "integer"}}}


def provider(handler: Any) -> OpenAIProvider:
    client = openai.OpenAI(
        api_key="k",
        base_url="http://test/v1",
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
    )
    return OpenAIProvider(client)


def req(schema: dict[str, Any] | None = None) -> ProviderRequest:
    return ProviderRequest(
        model="gpt-x",
        effort="low",
        system_prefix=["s1", "s2"],
        messages=[Message("user", "hi")],
        max_output_tokens=50,
        json_schema=schema,
    )


def reply(**patch: Any):  # type: ignore[no-untyped-def]
    body = json.loads(FIXTURE.read_text())
    body["choices"][0].update(patch)

    def handler(request: httpx2.Request) -> httpx2.Response:
        handler.sent = json.loads(request.content)  # type: ignore[attr-defined]
        return httpx2.Response(200, json=body)

    return handler


def test_request_shape_and_usage() -> None:
    h = reply()
    resp = provider(h).complete(req(SCHEMA))
    sent = h.sent  # type: ignore[attr-defined]
    assert sent["messages"][0] == {"role": "system", "content": "s1\n\ns2"}
    assert sent["max_completion_tokens"] == 50
    assert sent["reasoning_effort"] == "low"
    assert sent["response_format"]["json_schema"]["schema"] == SCHEMA
    assert resp.text == "Hello!"
    assert resp.parsed_json is None  # не JSON: решает шлюз
    assert resp.stop_reason == "end"
    u = resp.usage
    assert (u.uncached_input, u.cache_read, u.cache_write_5m, u.cache_write_1h, u.output) == (
        400, 600, 0, 0, 20,
    )  # fmt: skip


def test_parsed_json_and_length_stop() -> None:
    h = reply(message={"role": "assistant", "content": '{"a": 1}'}, finish_reason="length")
    resp = provider(h).complete(req(SCHEMA))
    assert resp.parsed_json == {"a": 1}
    assert resp.stop_reason == "max_tokens"


def test_count_tokens_none() -> None:
    assert provider(reply()).count_tokens(req()) is None


@pytest.mark.parametrize(
    ("status", "body", "retryable"),
    [
        (429, {"error": {"message": "slow", "code": "rate_limit_exceeded"}}, True),
        (429, {"error": {"message": "pay", "code": "insufficient_quota"}}, False),
        (500, {"error": {"message": "boom"}}, True),
        (503, {"error": {"message": "overloaded"}}, True),
        (401, {"error": {"message": "bad key"}}, False),
        (400, {"error": {"message": "too long SECRET-PROMPT"}}, False),
    ],
)
def test_errors(status: int, body: dict[str, Any], retryable: bool) -> None:
    p = provider(lambda r: httpx2.Response(status, json=body))
    with pytest.raises(ProviderError) as ei:
        p.complete(req())
    assert ei.value.retryable is retryable
    assert "SECRET-PROMPT" not in str(ei.value)


def test_connection_error_retryable() -> None:
    def boom(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("down")

    with pytest.raises(ProviderError) as ei:
        provider(boom).complete(req())
    assert ei.value.retryable
