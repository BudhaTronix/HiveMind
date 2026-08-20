"""Adapt the official asynchronous OpenAI Responses API to HiveMind.

The official SDK parses Pydantic structured outputs directly. HiveMind still validates the
returned object at its provider boundary and keeps API keys confined to client construction.
"""

from __future__ import annotations

from typing import TypeVar

from openai import (
    APIConnectionError,
    APIStatusError,
    AsyncOpenAI,
    AuthenticationError,
    RateLimitError,
)
from pydantic import BaseModel

from hivemind.providers.base import ProviderError, ProviderHealth, ValidatingProvider

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class OpenAIProvider(ValidatingProvider):
    """Generate text and parsed Pydantic results through the Responses API."""

    name = "openai"

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None,
        client: AsyncOpenAI | None = None,
    ) -> None:
        super().__init__()
        self.model = model
        self._has_api_key = bool(api_key)
        self.client = client or AsyncOpenAI(api_key=api_key or "missing")

    async def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        """Request text without enabling provider-side tools or storage."""

        self._require_key()
        try:
            response = await self.client.responses.create(
                model=self.model,
                instructions=system_prompt,
                input=user_prompt,
                store=False,
            )
            return response.output_text
        except Exception as exc:
            raise _translate_error(exc) from exc

    async def _request_structured(
        self,
        schema: type[SchemaT],
        system_prompt: str,
        user_prompt: str,
    ) -> BaseModel:
        self._require_key()
        try:
            response = await self.client.responses.parse(
                model=self.model,
                instructions=system_prompt,
                input=user_prompt,
                text_format=schema,
                store=False,
            )
        except Exception as exc:
            raise _translate_error(exc) from exc
        if response.output_parsed is None:
            raise ProviderError(
                "OpenAI returned no parsed structured output. The request may have been refused.",
                retryable=False,
            )
        return response.output_parsed

    async def check_health(self) -> ProviderHealth:
        """Check configuration without spending tokens on a model request."""

        if not self._has_api_key:
            return ProviderHealth(
                ok=False,
                message="OPENAI_API_KEY is not set. Add it to your environment or .env file.",
            )
        return ProviderHealth(
            ok=True,
            message=("OPENAI_API_KEY is configured. No billable request was made by this check."),
        )

    def _require_key(self) -> None:
        if not self._has_api_key:
            raise ProviderError(
                "OpenAI was selected but OPENAI_API_KEY is not set.", retryable=False
            )


def _translate_error(exc: Exception) -> ProviderError:
    """Map SDK failures to concise messages without including credentials or headers."""

    if isinstance(exc, AuthenticationError):
        return ProviderError("OpenAI authentication failed. Check OPENAI_API_KEY.", retryable=False)
    if isinstance(exc, RateLimitError):
        return ProviderError("OpenAI rate limit reached; try again shortly.")
    if isinstance(exc, APIConnectionError):
        return ProviderError("HiveMind could not connect to the OpenAI API.")
    if isinstance(exc, APIStatusError):
        retryable = exc.status_code >= 500 or exc.status_code == 429
        return ProviderError(
            f"OpenAI request failed with HTTP {exc.status_code}.", retryable=retryable
        )
    if isinstance(exc, ProviderError):
        return exc
    return ProviderError(f"OpenAI request failed: {type(exc).__name__}")
