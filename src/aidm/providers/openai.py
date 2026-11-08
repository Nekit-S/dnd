import json
from typing import Any

import openai
from openai.types.chat import ChatCompletion

from aidm.config.settings import Settings
from aidm.providers.base import (
    ProviderError,
    ProviderRequest,
    ProviderResponse,
    ProviderUsage,
    StopReason,
)

_STOP: dict[str, StopReason] = {"stop": "end", "length": "max_tokens"}


def _classify(exc: openai.OpenAIError) -> ProviderError:
    # Текст исключения не берём: в нём может оказаться кусок запроса
    if isinstance(exc, openai.APIStatusError):
        code = exc.status_code
        # 429 insufficient_quota — это биллинг, повтор не поможет
        quota = isinstance(exc, openai.RateLimitError) and exc.code == "insufficient_quota"
        retryable = not quota and (code in (408, 409, 429) or code >= 500)
        return ProviderError(f"openai status {code}", retryable)
    if isinstance(exc, openai.APIConnectionError):  # включая таймаут
        return ProviderError(f"openai {type(exc).__name__}", True)
    return ProviderError(f"openai {type(exc).__name__}", False)


class OpenAIProvider:
    name = "openai"
    is_local = False

    def __init__(self, client: openai.OpenAI) -> None:
        self.client = client

    def count_tokens(self, request: ProviderRequest) -> int | None:
        return None

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        messages: list[dict[str, Any]] = []
        if request.system_prefix:
            messages.append({"role": "system", "content": "\n\n".join(request.system_prefix)})
        messages += [{"role": m.role, "content": m.content} for m in request.messages]
        extra: dict[str, Any] = {}
        if request.effort is not None:
            extra["reasoning_effort"] = request.effort
        if request.json_schema is not None:
            extra["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "result", "schema": request.json_schema, "strict": True},
            }
        try:
            resp: ChatCompletion = self.client.chat.completions.create(
                model=request.model,
                messages=messages,  # type: ignore[arg-type]
                max_completion_tokens=request.max_output_tokens,
                **extra,
            )
        except openai.OpenAIError as exc:
            raise _classify(exc) from None

        choice = resp.choices[0]
        text = choice.message.content or ""
        parsed = None
        if request.json_schema is not None:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                pass  # невалидный JSON отдаём шлюзу: он запустит цикл починки
        stop = _STOP.get(choice.finish_reason, "other")
        usage = ProviderUsage()
        if resp.usage is not None:
            cached = getattr(resp.usage.prompt_tokens_details, "cached_tokens", None) or 0
            usage = ProviderUsage(
                uncached_input=resp.usage.prompt_tokens - cached,
                cache_read=cached,
                output=resp.usage.completion_tokens,
            )
        return ProviderResponse(text, parsed, stop, usage)


def build(settings: Settings) -> OpenAIProvider:
    key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
    # LM Studio и подобные не проверяют ключ, но клиент требует непустой
    client = openai.OpenAI(
        api_key=key or "not-needed", base_url=settings.openai_base_url, max_retries=0
    )
    return OpenAIProvider(client)
