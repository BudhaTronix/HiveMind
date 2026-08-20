"""Register and execute the small, transparent set of HiveMind research tools.

Workers never choose arbitrary functions. Python reads approved search queries, checks tool
metadata, performs bounded web operations, and passes the resulting evidence to the model.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from ddgs import DDGS

from hivemind.schemas import AgentKind, FetchedPage, SearchResult, ToolMetadata
from hivemind.security import Resolver, safe_excerpt, validate_public_url


class ToolError(RuntimeError):
    """A recoverable tool failure safe to record as a public event."""


ToolHandler = Callable[..., Awaitable[Any]]


@dataclass(slots=True)
class ApprovalGate:
    """Fail-closed approval extension point for future consequential tools."""

    async def request_approval(
        self, metadata: ToolMetadata, *, agent_kind: AgentKind, arguments: dict[str, Any]
    ) -> bool:
        """Reject by default; an interactive application may provide another gate."""

        return False


class ToolRegistry:
    """Store Python-owned tool metadata and handlers."""

    def __init__(self, *, approval_gate: ApprovalGate | None = None) -> None:
        self._metadata: dict[str, ToolMetadata] = {}
        self._handlers: dict[str, ToolHandler] = {}
        self.approval_gate = approval_gate

    def register(self, metadata: ToolMetadata, handler: ToolHandler) -> None:
        """Register one explicit tool; duplicate names replace development-time adapters."""

        self._metadata[metadata.name] = metadata
        self._handlers[metadata.name] = handler

    def metadata(self, name: str) -> ToolMetadata:
        try:
            return self._metadata[name]
        except KeyError as exc:
            raise ToolError(f"Unknown tool: {name}") from exc

    async def execute(self, name: str, *, agent_kind: AgentKind, **kwargs: Any) -> Any:
        """Check the role allow-list before invoking a registered handler."""

        metadata = self.metadata(name)
        if agent_kind not in metadata.allowed_agent_kinds:
            raise PermissionError(f"{agent_kind.value} agents may not use {name}.")
        if metadata.requires_approval and (
            self.approval_gate is None
            or not await self.approval_gate.request_approval(
                metadata, agent_kind=agent_kind, arguments=kwargs
            )
        ):
            raise PermissionError(f"{name} requires approval and was not approved.")
        return await self._handlers[name](**kwargs)


class WebSearchTool:
    """Normalize DDGS results while keeping its synchronous call off the event loop."""

    async def __call__(self, *, query: str, max_results: int = 3) -> list[SearchResult]:
        def search() -> list[dict[str, Any]]:
            return list(DDGS().text(query, max_results=max_results))

        try:
            raw = await asyncio.to_thread(search)
        except Exception as exc:  # noqa: BLE001 - third-party engines fail independently.
            raise ToolError(f"Web search failed: {type(exc).__name__}") from exc
        results = []
        for item in raw:
            url = str(item.get("href") or item.get("url") or "")
            if not url:
                continue
            results.append(
                SearchResult(
                    title=str(item.get("title") or url),
                    url=url,
                    snippet=str(item.get("body") or item.get("snippet") or ""),
                )
            )
        return results


class WebFetchTool:
    """Fetch small public text/HTML responses and revalidate every redirect target."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        resolver: Resolver | None = None,
        max_bytes: int = 1_000_000,
        max_characters: int = 12_000,
        max_redirects: int = 3,
        timeout_seconds: float = 12,
    ) -> None:
        self.client = client
        self.timeout_seconds = timeout_seconds
        self.resolver = resolver
        self.max_bytes = max_bytes
        self.max_characters = max_characters
        self.max_redirects = max_redirects

    async def __call__(self, *, url: str) -> FetchedPage:
        if self.client:
            return await self._fetch(self.client, url)
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=self.timeout_seconds,
            headers={"User-Agent": "HiveMind-Educational-Research/0.1"},
        ) as client:
            return await self._fetch(client, url)

    async def _fetch(self, client: httpx.AsyncClient, url: str) -> FetchedPage:
        """Perform a redirect-aware fetch with either an injected or temporary client."""

        current = url
        for redirect_number in range(self.max_redirects + 1):
            await validate_public_url(current, resolver=self.resolver)
            try:
                async with client.stream("GET", current) as response:
                    if response.is_redirect:
                        if redirect_number == self.max_redirects:
                            raise ToolError("Web fetch exceeded the redirect limit.")
                        location = response.headers.get("location")
                        if not location:
                            raise ToolError("Redirect response had no Location header.")
                        current = urljoin(current, location)
                        continue
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").split(";", 1)[0]
                    if content_type not in {
                        "text/html",
                        "text/plain",
                        "application/xhtml+xml",
                    }:
                        raise ToolError(f"Unsupported content type: {content_type or 'unknown'}")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > self.max_bytes:
                            raise ToolError("Web response exceeded the download-size limit.")
            except httpx.HTTPError as exc:
                raise ToolError(f"Web fetch failed: {type(exc).__name__}") from exc
            text = bytes(body).decode(response.encoding or "utf-8", errors="replace")
            if content_type in {"text/html", "application/xhtml+xml"}:
                soup = BeautifulSoup(text, "html.parser")
                for element in soup(["script", "style", "noscript"]):
                    element.decompose()
                title = soup.title.get_text(" ", strip=True) if soup.title else current
                text = soup.get_text(" ", strip=True)
            else:
                title = current
            return FetchedPage(
                url=current,
                title=title,
                content_type=content_type,
                excerpt=safe_excerpt(text, max_characters=self.max_characters),
            )
        raise ToolError("Web fetch could not resolve redirects.")


def build_default_tool_registry() -> ToolRegistry:
    """Create the safe research tools enabled in version 1."""

    registry = ToolRegistry()
    registry.register(
        ToolMetadata(
            name="web_search",
            description="Search the public web and return titles, URLs, and snippets.",
            allowed_agent_kinds={AgentKind.WORKER, AgentKind.VERIFIER},
        ),
        WebSearchTool(),
    )
    registry.register(
        ToolMetadata(
            name="web_fetch",
            description="Fetch a bounded excerpt from a public HTTP(S) page.",
            allowed_agent_kinds={AgentKind.WORKER, AgentKind.VERIFIER},
        ),
        WebFetchTool(),
    )
    return registry
