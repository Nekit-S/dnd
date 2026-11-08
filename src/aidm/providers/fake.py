import json
from collections import deque
from collections.abc import Iterable
from typing import Literal

from aidm.providers.base import (
    ProviderError,
    ProviderRequest,
    ProviderResponse,
    ProviderUsage,
    StopReason,
)

Failure = Literal["retryable", "fatal", "truncated", "invalid_json"]


def _tokens(*texts: str) -> int:
    # Та же грубая оценка, что в шлюзе: половина байт UTF-8, вверх
    return (sum(len(t.encode()) for t in texts) + 1) // 2


class FakeProvider:
    name = "fake"
    is_local = False

    def __init__(
        self,
        script: dict[tuple[str, str], str] | None = None,
        failures: Iterable[Failure] = (),
    ) -> None:
        self.script = script or {}
        self.failures = deque(failures)
        self.calls: list[ProviderRequest] = []

    def _input_tokens(self, request: ProviderRequest) -> int:
        return _tokens(*request.system_prefix, *(m.content for m in request.messages))

    def count_tokens(self, request: ProviderRequest) -> int | None:
        return self._input_tokens(request)

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        self.calls.append(request)
        failure = self.failures.popleft() if self.failures else None
        if failure == "retryable":
            raise ProviderError("fake retryable failure", retryable=True)
        if failure == "fatal":
            raise ProviderError("fake fatal failure", retryable=False)
        text = self.script[(request.category, request.place)]
        if failure == "truncated":
            text = text[: len(text) // 2]
        if failure == "invalid_json":
            text = "not json {"
        parsed = None
        if request.json_schema is not None and failure != "invalid_json":
            parsed = json.loads(text) if failure != "truncated" else None
        usage = ProviderUsage(uncached_input=self._input_tokens(request), output=_tokens(text))
        stop: StopReason = "max_tokens" if failure == "truncated" else "end"
        return ProviderResponse(text, parsed, stop, usage)


def build(settings: object) -> FakeProvider:
    return FakeProvider()
