import json
import time
from typing import Any

import httpx
import ollama

from aidm.config.settings import Settings
from aidm.providers.base import (
    ProviderError,
    ProviderRequest,
    ProviderResponse,
    ProviderUsage,
    StopReason,
)
from aidm.providers.capabilities import CAPABILITIES

_STOP: dict[str, StopReason] = {"stop": "end", "length": "max_tokens"}


def _classify(exc: Exception) -> ProviderError:
    # Текст исключения не берём: в нём может оказаться кусок запроса
    if isinstance(exc, ollama.ResponseError):
        code = exc.status_code
        return ProviderError(f"ollama status {code}", code in (408, 429) or code >= 500)
    # сервер не запущен, обрыв или таймаут
    return ProviderError(f"ollama {type(exc).__name__}", True)


class OllamaProvider:
    name = "ollama"
    is_local = True

    def __init__(self, client: ollama.Client) -> None:
        self.client = client

    def count_tokens(self, request: ProviderRequest) -> int | None:
        return None

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        messages: list[dict[str, str]] = []
        if request.system_prefix:
            messages.append({"role": "system", "content": "\n\n".join(request.system_prefix)})
        messages += [{"role": m.role, "content": m.content} for m in request.messages]
        options: dict[str, Any] = {"num_predict": request.max_output_tokens}
        # Без num_ctx Ollama режет контекст до маленького значения по умолчанию
        cap = CAPABILITIES.get(request.model)
        if cap is not None:
            options["num_ctx"] = cap.context_tokens
        started = time.monotonic()
        try:
            resp = self.client.chat(
                model=request.model,
                messages=messages,
                format=request.json_schema,
                options=options,
            )
        except (ollama.ResponseError, ConnectionError, httpx.TransportError) as exc:
            raise _classify(exc) from None
        latency_ms = int((time.monotonic() - started) * 1000)

        text = resp.message.content or ""
        parsed = None
        if request.json_schema is not None:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                pass  # невалидный JSON отдаём шлюзу: он запустит цикл починки
        stop = _STOP.get(resp.done_reason or "", "other")
        usage = ProviderUsage(
            uncached_input=resp.prompt_eval_count or 0, output=resp.eval_count or 0
        )
        return ProviderResponse(text, parsed, stop, usage, latency_ms)


def build(settings: Settings) -> OllamaProvider:
    return OllamaProvider(ollama.Client(host=settings.ollama_host))
