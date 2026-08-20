"""Provider adapters isolate model-specific APIs from the HiveMind runtime."""

from hivemind.config import Settings
from hivemind.providers.base import LLMProvider, ProviderError
from hivemind.providers.fake_provider import FakeLLMProvider
from hivemind.providers.ollama_provider import OllamaProvider
from hivemind.providers.openai_provider import OpenAIProvider


def create_provider(settings: Settings) -> LLMProvider:
    """Create only the provider selected by validated configuration."""

    if settings.provider == "fake":
        return FakeLLMProvider()
    if settings.provider == "openai":
        return OpenAIProvider(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
        )
    return OllamaProvider(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
    )


__all__ = [
    "FakeLLMProvider",
    "LLMProvider",
    "OllamaProvider",
    "OpenAIProvider",
    "ProviderError",
    "create_provider",
]
