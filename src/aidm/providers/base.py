from dataclasses import dataclass
from typing import Any, Literal, Protocol

CacheTtl = Literal["5m", "1h"]
StopReason = Literal["end", "max_tokens", "other"]


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class ProviderRequest:
    model: str
    effort: str | None
    system_prefix: list[str]  # шлюз ставит кэш-маркер на последний блок
    messages: list[Message]
    max_output_tokens: int
    json_schema: dict[str, Any] | None = None
    cache_ttl: CacheTtl | None = None
    # Только для фейка и логов шлюза: адаптеры реальных провайдеров их не читают
    category: str = ""
    place: str = ""


@dataclass(frozen=True)
class ProviderUsage:
    """Рассуждения считаются в output."""

    uncached_input: int = 0
    cache_write_5m: int = 0
    cache_write_1h: int = 0
    cache_read: int = 0
    output: int = 0


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    parsed_json: Any | None
    stop_reason: StopReason
    usage: ProviderUsage
    latency_ms: int


class ProviderError(Exception):
    """Сообщение никогда не содержит текст запроса."""

    def __init__(self, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class Provider(Protocol):
    name: str
    is_local: bool

    def complete(self, request: ProviderRequest) -> ProviderResponse: ...

    def count_tokens(self, request: ProviderRequest) -> int | None:
        """None: провайдер не умеет считать."""
        ...
