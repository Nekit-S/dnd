import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from functools import cache
from typing import Literal

from pydantic import BaseModel, ValidationError

from aidm.config.models import (
    CategoryConfig,
    ModelsConfig,
    UnknownCategoryError,
    load_models_config,
)
from aidm.config.settings import Settings
from aidm.gateway.tokens import estimate_tokens
from aidm.ledger.ledger import AttemptKind, BudgetScope, Ledger, Status
from aidm.ledger.prices import Prices, TokenCounts, UnknownPriceError, load_prices
from aidm.providers import registry
from aidm.providers.base import (
    CacheTtl,
    Message,
    Provider,
    ProviderError,
    ProviderRequest,
    ProviderResponse,
)
from aidm.providers.capabilities import Capability, UnknownModelError, get_capability

_log = logging.getLogger(__name__)

Limit = Literal["campaign", "monthly", "test"]
ResultStatus = Literal["ok", "invalid_output", "truncated"]


class BudgetExceededError(Exception):
    def __init__(self, limit: Limit) -> None:
        super().__init__(f"{limit} budget limit reached")
        self.limit = limit


class InputCapError(Exception):
    pass


class ProviderFatalError(Exception):
    pass


@dataclass(frozen=True)
class LLMRequest:
    category: str
    budget_scope: BudgetScope
    messages: list[Message]
    prefix: list[str] = field(default_factory=list)
    place: str = ""
    campaign_id: str | None = None
    campaign_limit_usd: Decimal | None = None
    output_model: type[BaseModel] | None = None
    attempt_kind: AttemptKind = "first"
    parent_id: int | None = None
    mode: Literal["direct"] = "direct"

    def __post_init__(self) -> None:
        if self.campaign_limit_usd is not None and self.campaign_id is None:
            raise ValueError("campaign_limit_usd needs campaign_id")


@dataclass(frozen=True)
class GatewayResult:
    status: ResultStatus
    text: str
    parsed: BaseModel | None
    ledger_row_id: int
    usage: TokenCounts
    cost: Decimal


def _sleep_ms(ms: int) -> None:
    time.sleep(ms / 1000)


def _log_row(req: LLMRequest, model: str, status: str, counts: TokenCounts, cost: Decimal) -> None:
    # Только метаданные: текст запроса и ответа может раскрыть скрытое хосту
    _log.info(
        "llm category=%s place=%s model=%s status=%s %s cost=%s",
        req.category,
        req.place,
        model,
        status,
        counts,
        cost,
    )


class Gateway:
    def __init__(
        self,
        settings: Settings,
        models: ModelsConfig,
        ledger: Ledger,
        prices: Prices,
        providers: Callable[[str], Provider],
        sleep: Callable[[int], None] = _sleep_ms,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._settings = settings
        self._models = models
        self._ledger = ledger
        self._prices = prices
        self._providers = providers
        self._sleep = sleep
        self._clock = clock

    def spend(self, campaign_id: str) -> Decimal:
        return self._ledger.spend(campaign_id=campaign_id)

    def call(self, req: LLMRequest) -> GatewayResult:
        try:
            cfg = self._models.resolve(req.category)
        except UnknownCategoryError:
            self._reject(req, "rejected_category", None)
            raise
        try:
            capability = get_capability(cfg.model)
        except UnknownModelError:
            # Отдельного статуса нет: модель вне таблицы возможностей считаем моделью без цены
            self._reject(req, "rejected_price", cfg)
            raise
        provider = self._providers(cfg.provider)
        try:
            price_as_of = None if provider.is_local else self._prices.as_of(cfg.model)
        except UnknownPriceError:
            self._reject(req, "rejected_price", cfg)
            raise
        limit = self._limit_reached(req)
        if limit is not None:
            self._reject(req, "rejected_budget", cfg)
            raise BudgetExceededError(limit)
        preq = ProviderRequest(
            model=cfg.model,
            effort=cfg.effort,
            system_prefix=req.prefix,
            messages=req.messages,
            max_output_tokens=cfg.max_output_tokens,
            json_schema=req.output_model.model_json_schema() if req.output_model else None,
            cache_ttl=self._cache_ttl(req, cfg, capability),
            category=req.category,
            place=req.place,
        )
        if self._input_tokens(provider, preq, cfg.max_input_tokens) > cfg.max_input_tokens:
            self._reject(req, "rejected_input_cap", cfg)
            raise InputCapError(f"input over {cfg.max_input_tokens} tokens for {req.category}")
        return self._attempts(req, cfg, provider, preq, price_as_of)

    def _reject(self, req: LLMRequest, status: Status, cfg: CategoryConfig | None) -> None:
        self._ledger.record_rejection(
            status=status,
            category=req.category,
            provider=cfg.provider if cfg else "",
            model=cfg.model if cfg else "",
            effort=cfg.effort if cfg else None,
            budget_scope=req.budget_scope,
            campaign_id=req.campaign_id,
            place=req.place,
            attempt_kind=req.attempt_kind,
            mode=req.mode,
            parent_id=req.parent_id,
        )
        _log_row(req, cfg.model if cfg else "", status, TokenCounts(), Decimal(0))

    def _limit_reached(self, req: LLMRequest) -> Limit | None:
        month = (
            self._clock().astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        )
        if self._ledger.spend(since=month) >= self._settings.monthly_limit_usd:
            return "monthly"
        if (
            req.budget_scope == "test"
            and self._ledger.spend(scope="test") >= self._settings.live_test_limit_usd
        ):
            return "test"
        if (
            req.campaign_id is not None
            and req.campaign_limit_usd is not None
            and self.spend(req.campaign_id) >= req.campaign_limit_usd
        ):
            return "campaign"
        return None

    def _cache_ttl(
        self, req: LLMRequest, cfg: CategoryConfig, capability: Capability
    ) -> CacheTtl | None:
        if (
            not capability.prompt_cache
            or estimate_tokens(*req.prefix) < capability.min_cache_tokens
        ):
            return None
        # shortcut: только режим direct, ветка batch появится на этапе 1а
        return (cfg.cache_ttl or self._models.defaults.cache_ttl).direct

    def _input_tokens(self, provider: Provider, preq: ProviderRequest, cap: int) -> int:
        estimate = estimate_tokens(*preq.system_prefix, *(m.content for m in preq.messages))
        if estimate * 5 <= cap * 4:
            return estimate
        try:
            exact = provider.count_tokens(preq)
        except ProviderError as e:
            # Оценка с запасом безопасна: точный счёт лишь пропускает больше
            _log.warning("token count failed, using estimate: %s", e)
            return estimate
        return estimate if exact is None else exact

    def _attempts(
        self,
        req: LLMRequest,
        cfg: CategoryConfig,
        provider: Provider,
        preq: ProviderRequest,
        price_as_of: str | None,
    ) -> GatewayResult:
        defaults = self._models.defaults
        first_id: int | None = None
        retry = 0
        while True:
            row = self._ledger.start_attempt(
                category=req.category,
                provider=cfg.provider,
                model=cfg.model,
                effort=cfg.effort,
                budget_scope=req.budget_scope,
                campaign_id=req.campaign_id,
                place=req.place,
                attempt_kind=req.attempt_kind if first_id is None else "retry_network",
                mode=req.mode,
                parent_id=req.parent_id if first_id is None else first_id,
                price_as_of=price_as_of,
            )
            first_id = first_id or row
            try:
                response = provider.complete(preq)
            except ProviderError as e:
                error_class: Literal["retryable", "fatal"] = "retryable" if e.retryable else "fatal"
                self._ledger.finish_attempt(
                    row, TokenCounts(), Decimal(0), "provider_error", error_class
                )
                _log_row(req, cfg.model, f"provider_error/{error_class}", TokenCounts(), Decimal(0))
                if not e.retryable or retry == defaults.retries:
                    raise ProviderFatalError(f"{req.category}: {e}") from e
                self._sleep(defaults.backoff_base_ms * 2**retry)
                retry += 1
                continue
            except BaseException:
                self._fail_row(row)
                raise
            try:
                return self._finish(req, cfg, provider, row, response)
            except BaseException:
                self._fail_row(row)
                raise

    def _fail_row(self, row: int) -> None:
        # Строка не должна остаться pending: иначе её стоимость пропадёт из лимитов
        self._ledger.finish_attempt(row, TokenCounts(), Decimal(0), "provider_error", "fatal")

    def _finish(
        self,
        req: LLMRequest,
        cfg: CategoryConfig,
        provider: Provider,
        row: int,
        response: ProviderResponse,
    ) -> GatewayResult:
        counts = TokenCounts(**asdict(response.usage))
        cost = self._prices.cost(cfg.model, counts, is_local=provider.is_local)
        parsed: BaseModel | None = None
        status: ResultStatus = "ok"
        if response.stop_reason == "max_tokens":
            status = "truncated"
        elif req.output_model is not None:
            try:
                parsed = req.output_model.model_validate(response.parsed_json)
            except ValidationError:
                status = "invalid_output"
        self._ledger.finish_attempt(row, counts, cost, status)
        _log_row(req, cfg.model, status, counts, cost)
        return GatewayResult(status, response.text, parsed, row, counts, cost)


def build(settings: Settings) -> Gateway:
    return Gateway(
        settings,
        load_models_config(settings.models_config),
        Ledger(settings.ledger_path),
        load_prices(),
        cache(lambda name: registry.get(name, settings)),
    )
