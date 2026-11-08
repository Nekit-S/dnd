from importlib import import_module

from aidm.config.settings import Settings
from aidm.providers.base import Provider

# Адаптер отдаёт build(settings); импорт ленивый, SDK грузится только при выборе
_MODULES = {
    "anthropic": "aidm.providers.anthropic",
    "openai": "aidm.providers.openai",
    "ollama": "aidm.providers.ollama",
    "fake": "aidm.providers.fake",
}


class UnknownProviderError(LookupError):
    pass


def get(name: str, settings: Settings) -> Provider:
    if name not in _MODULES:
        raise UnknownProviderError(f"unknown provider: {name!r}")
    provider: Provider = import_module(_MODULES[name]).build(settings)
    return provider
