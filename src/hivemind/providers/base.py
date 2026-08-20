"""Define the provider boundary used by all HiveMind agents.

An agent function depends on this protocol rather than Ollama or OpenAI. That keeps tests
offline and demonstrates a basic dependency-inversion pattern without a framework.
"""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class ProviderError(RuntimeError):
    """A model-provider failure safe to show as a concise setup/runtime message."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class LLMProvider(Protocol):
    """The small interface that orchestration code uses for every model provider."""

    name: str
    model: str

    async def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        """Generate ordinary text for the rare case where a schema is unnecessary."""

    async def generate_structured(
        self,
        schema: type[SchemaT],
        system_prompt: str,
        user_prompt: str,
    ) -> SchemaT:
        """Generate and validate one of HiveMind's Pydantic contracts."""
