"""Define the provider boundary used by all HiveMind agents.

An agent function depends on this protocol rather than Ollama or OpenAI. That keeps tests
offline and demonstrates a basic dependency-inversion pattern without a framework.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel
from pydantic_core import ValidationError

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class ProviderError(RuntimeError):
    """A model-provider failure safe to show as a concise setup/runtime message."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    """A safe health-check result that can be shown by ``hivemind doctor``."""

    ok: bool
    message: str


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

    async def check_health(self) -> ProviderHealth:
        """Check provider configuration/connectivity without generating research."""


class ValidatingProvider(ABC):
    """Share structured validation and one bounded repair attempt across real providers."""

    name: str
    model: str

    def __init__(self) -> None:
        self.validation_failures = 0

    @abstractmethod
    async def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        """Generate ordinary text through the provider API."""

    @abstractmethod
    async def _request_structured(
        self,
        schema: type[SchemaT],
        system_prompt: str,
        user_prompt: str,
    ) -> BaseModel | dict[str, Any] | str:
        """Ask the provider for a schema-shaped payload."""

    async def generate_structured(
        self,
        schema: type[SchemaT],
        system_prompt: str,
        user_prompt: str,
    ) -> SchemaT:
        """Validate provider output and retry once with a concise repair instruction."""

        last_error: Exception | None = None
        current_system = system_prompt
        for attempt in range(2):
            candidate = await self._request_structured(schema, current_system, user_prompt)
            try:
                if isinstance(candidate, schema):
                    return candidate
                if isinstance(candidate, str):
                    return schema.model_validate_json(candidate)
                return schema.model_validate(candidate)
            except (ValidationError, ValueError) as exc:
                self.validation_failures += 1
                last_error = exc
                if attempt == 0:
                    current_system = (
                        f"{system_prompt}\n\nYour previous response was invalid for "
                        f"{schema.__name__}. Return one corrected response matching the schema."
                    )
        raise ProviderError(
            f"The model returned invalid {schema.__name__} data after one repair attempt.",
            retryable=False,
        ) from last_error
