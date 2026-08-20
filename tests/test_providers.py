"""Provider tests use local stubs and never call a model service."""

from types import SimpleNamespace
from typing import Any, TypeVar

from pydantic import BaseModel

from hivemind.providers.base import ValidatingProvider
from hivemind.providers.ollama_provider import OllamaProvider
from hivemind.providers.openai_provider import OpenAIProvider

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class Answer(BaseModel):
    value: int


class BrokenThenValidProvider(ValidatingProvider):
    name = "test"
    model = "test"

    def __init__(self) -> None:
        super().__init__()
        self.prompts: list[str] = []

    async def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        return "text"

    async def _request_structured(
        self,
        schema: type[SchemaT],
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any]:
        self.prompts.append(system_prompt)
        return {"wrong": True} if len(self.prompts) == 1 else {"value": 42}


class StubOllamaClient:
    async def list(self) -> SimpleNamespace:
        return SimpleNamespace(models=[SimpleNamespace(model="qwen3:8b")])


async def test_invalid_structured_output_is_retried_once() -> None:
    provider = BrokenThenValidProvider()

    result = await provider.generate_structured(Answer, "System", "User")

    assert result.value == 42
    assert provider.validation_failures == 1
    assert "previous response was invalid" in provider.prompts[1]


async def test_ollama_health_checks_requested_model() -> None:
    provider = OllamaProvider(
        model="qwen3:8b",
        base_url="http://localhost:11434",
        client=StubOllamaClient(),  # type: ignore[arg-type]
    )

    health = await provider.check_health()

    assert health.ok
    assert "qwen3:8b" in health.message


async def test_openai_health_does_not_make_request_without_key() -> None:
    provider = OpenAIProvider(model="gpt-test", api_key=None)

    health = await provider.check_health()

    assert not health.ok
    assert "OPENAI_API_KEY" in health.message
