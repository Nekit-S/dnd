import json
from typing import Any

import anthropic
import httpx2

from aidm.config.settings import Settings
from aidm.providers.base import (
    ProviderError,
    ProviderRequest,
    ProviderResponse,
    ProviderUsage,
    StopReason,
)

_STOP: dict[str | None, StopReason] = {"end_turn": "end", "max_tokens": "max_tokens"}


def _classify(e: anthropic.APIError) -> ProviderError:
    status = e.status_code if isinstance(e, anthropic.APIStatusError) else None
    retryable = status is None or status in (408, 409, 429) or status >= 500
    return ProviderError(f"anthropic {type(e).__name__} status={status}", retryable)


class AnthropicProvider:
    name = "anthropic"
    is_local = False

    def __init__(self, client: anthropic.Anthropic) -> None:
        self.client = client

    def _params(self, request: ProviderRequest) -> dict[str, Any]:
        system: list[dict[str, Any]] = [{"type": "text", "text": t} for t in request.system_prefix]
        if system and request.cache_ttl:
            system[-1]["cache_control"] = {"type": "ephemeral", "ttl": request.cache_ttl}
        output_config: dict[str, Any] = {}
        if request.effort:
            output_config["effort"] = request.effort
        if request.json_schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": request.json_schema}
        params: dict[str, Any] = {
            "model": request.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        }
        if system:
            params["system"] = system
        if output_config:
            params["output_config"] = output_config
        return params

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        try:
            # shortcut: без stream SDK не пускает max_tokens > ~21k; для больших нужен stream
            msg = self.client.messages.create(
                max_tokens=request.max_output_tokens, **self._params(request)
            )
        except anthropic.APIError as e:
            raise _classify(e) from e
        text = "".join(b.text for b in msg.content if b.type == "text")
        stop = _STOP.get(msg.stop_reason, "other")
        parsed = None
        if request.json_schema is not None and stop == "end":
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                pass  # шлюз увидит parsed_json=None и запустит цикл починки
        u = msg.usage
        cc = u.cache_creation
        # Без разбивки по TTL вся запись в кэш считается 5-минутной
        w5 = cc.ephemeral_5m_input_tokens if cc else u.cache_creation_input_tokens or 0
        w1 = cc.ephemeral_1h_input_tokens if cc else 0
        usage = ProviderUsage(
            uncached_input=u.input_tokens,
            cache_write_5m=w5,
            cache_write_1h=w1,
            cache_read=u.cache_read_input_tokens or 0,
            output=u.output_tokens,
        )
        return ProviderResponse(text, parsed, stop, usage)

    def count_tokens(self, request: ProviderRequest) -> int | None:
        try:
            return self.client.messages.count_tokens(**self._params(request)).input_tokens
        except anthropic.APIError as e:
            raise _classify(e) from e


def build(settings: Settings, http_client: httpx2.Client | None = None) -> AnthropicProvider:
    key = settings.anthropic_api_key
    # Повторы делает шлюз: одна строка журнала на попытку
    client = anthropic.Anthropic(
        api_key=key.get_secret_value() if key else None, max_retries=0, http_client=http_client
    )
    return AnthropicProvider(client)
