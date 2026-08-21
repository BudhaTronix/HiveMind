"""Adapt the official asynchronous Ollama client to HiveMind's provider contract.

Ollama is the default because it can keep model inference local. Connection and missing
model errors become beginner-friendly ``ProviderError`` messages rather than SDK traces.
"""

from __future__ import annotations

from typing import Any, TypeVar

import httpx
from ollama import AsyncClient, ResponseError
from pydantic import BaseModel

from hivemind.providers.base import ProviderError, ProviderHealth, ValidatingProvider

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class OllamaProvider(ValidatingProvider):
    """Generate local text and Pydantic-compatible JSON through Ollama."""

    name = "ollama"

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        think: bool = False,
        timeout_seconds: float = 300,
        client: AsyncClient | None = None,
    ) -> None:
        super().__init__()
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.think = think
        self.timeout_seconds = timeout_seconds
        self.client = client or AsyncClient(host=self.base_url, timeout=timeout_seconds)

    async def generate_text(self, system_prompt: str, user_prompt: str) -> str:
        """Request a normal non-streaming chat response."""

        response = await self._chat(
            messages=_messages(system_prompt, user_prompt),
            think=self.think,
        )
        return response.message.content or ""

    async def _request_structured(
        self,
        schema: type[SchemaT],
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        response = await self._chat(
            messages=_messages(system_prompt, user_prompt),
            format=schema.model_json_schema(),
            think=self.think,
            options={"temperature": 0},
        )
        return response.message.content or ""

    async def _chat(self, **kwargs: Any) -> Any:
        try:
            return await self.client.chat(model=self.model, stream=False, **kwargs)
        except ResponseError as exc:
            missing = exc.status_code == 404 or "not found" in str(exc).lower()
            if missing:
                raise ProviderError(
                    f"Ollama model '{self.model}' is not installed.\n"
                    f"Pull it with: ollama pull {self.model}",
                    retryable=False,
                ) from exc
            raise ProviderError(f"Ollama rejected the request: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise ProviderError(
                (
                    f"Ollama model '{self.model}' did not finish within "
                    f"{self.timeout_seconds:g} seconds. The server was reachable, but "
                    "generation was too slow. Keep OLLAMA_THINK=false, try "
                    "--max-concurrent 1 or a smaller model, or increase "
                    "HIVEMIND_LLM_CALL_TIMEOUT_SECONDS."
                ),
                retryable=False,
            ) from exc
        except (httpx.ConnectError, OSError) as exc:
            raise ProviderError(self.connection_help) from exc

    async def check_health(self) -> ProviderHealth:
        """Check server connectivity and model availability without generating text."""

        try:
            response = await self.client.list()
        except (httpx.HTTPError, OSError) as exc:
            return ProviderHealth(ok=False, message=f"{self.connection_help}\nCause: {exc}")
        models = {item.model for item in response.models}
        if self.model not in models:
            return ProviderHealth(
                ok=False,
                message=(
                    f"Ollama is running, but '{self.model}' is not installed. "
                    f"Run: ollama pull {self.model}"
                ),
            )
        return ProviderHealth(ok=True, message=f"Ollama is ready with {self.model}.")

    @property
    def connection_help(self) -> str:
        """Return the actionable setup guidance used for ordinary connection failures."""

        return (
            f"HiveMind could not connect to Ollama at {self.base_url}.\n\n"
            "1. Install Ollama.\n"
            "2. Start it with: ollama serve\n"
            f"3. Pull the model with: ollama pull {self.model}\n"
            "4. Run: hivemind doctor"
        )


def _messages(system_prompt: str, user_prompt: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
