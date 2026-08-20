"""Keep durable memory outside model weights behind one small interface.

The default store ranks scoped SQLite records using keyword overlap, confidence, and recency.
The optional Mem0 adapter mirrors approved records into Mem0 while preserving SQLite state
for HiveMind's CLI. Retrieval is context injection, not training or model-weight changes.
"""

from __future__ import annotations

import asyncio
import importlib
import math
from datetime import UTC, datetime
from typing import Any, Protocol

from hivemind.config import Settings
from hivemind.persistence import HiveMindRepository
from hivemind.schemas import MemoryRecord, MemoryScope


class MemoryStore(Protocol):
    """The retrieval and write operations needed by orchestration."""

    async def search(
        self,
        query: str,
        scopes: list[tuple[MemoryScope, str]],
        *,
        limit: int = 5,
    ) -> list[MemoryRecord]: ...

    async def save(self, memory: MemoryRecord) -> None: ...


class SimpleSQLiteMemoryStore:
    """Rank a small scoped candidate set without requiring embeddings or a service."""

    def __init__(self, repository: HiveMindRepository) -> None:
        self.repository = repository

    async def search(
        self,
        query: str,
        scopes: list[tuple[MemoryScope, str]],
        *,
        limit: int = 5,
    ) -> list[MemoryRecord]:
        candidates = await self.repository.search_memory_text(
            query, scopes, limit=max(50, limit * 5)
        )
        query_words = _words(query)
        return sorted(
            candidates,
            key=lambda item: _score(item, query_words),
            reverse=True,
        )[:limit]

    async def save(self, memory: MemoryRecord) -> None:
        await self.repository.save_memory(memory)


class Mem0MemoryStore:
    """Isolate the optional Mem0 OSS API and mirror approved metadata to SQLite."""

    def __init__(
        self,
        repository: HiveMindRepository,
        *,
        client: Any,
    ) -> None:
        self.repository = repository
        self.client = client

    @classmethod
    def from_settings(cls, settings: Settings, repository: HiveMindRepository) -> Mem0MemoryStore:
        """Create the documented Mem0 OSS ``Memory.from_config`` local adapter."""

        try:
            module = importlib.import_module("mem0")
        except ImportError as exc:
            raise RuntimeError(
                "Mem0 was selected but is not installed. Install it with: pip install -e '.[mem0]'"
            ) from exc
        config = {
            "llm": {
                "provider": "ollama",
                "config": {
                    "model": settings.ollama_model,
                    "ollama_base_url": settings.ollama_base_url,
                    "temperature": 0.1,
                },
            },
            "embedder": {
                "provider": "ollama",
                "config": {
                    "model": settings.mem0_embed_model,
                    "ollama_base_url": settings.ollama_base_url,
                },
            },
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "path": str(settings.db_path.parent / "mem0-qdrant"),
                    "collection_name": "hivemind_memories",
                },
            },
        }
        return cls(repository, client=module.Memory.from_config(config))

    async def save(self, memory: MemoryRecord) -> None:
        await self.repository.save_memory(memory)
        metadata = {
            "hivemind_memory_id": memory.memory_id,
            "scope": memory.scope.value,
            "scope_id": memory.scope_id,
            "memory_type": memory.memory_type.value,
            "confidence": memory.confidence,
        }
        await asyncio.to_thread(
            self.client.add,
            memory.text,
            user_id=_mem0_user(memory.scope, memory.scope_id),
            metadata=metadata,
            infer=False,
        )

    async def search(
        self,
        query: str,
        scopes: list[tuple[MemoryScope, str]],
        *,
        limit: int = 5,
    ) -> list[MemoryRecord]:
        ids: list[str] = []
        for scope, scope_id in scopes:
            raw = await asyncio.to_thread(
                self.client.search,
                query,
                filters={"user_id": _mem0_user(scope, scope_id)},
                limit=limit,
            )
            rows = raw.get("results", raw if isinstance(raw, list) else [])
            for row in rows:
                memory_id = row.get("metadata", {}).get("hivemind_memory_id")
                if memory_id:
                    ids.append(str(memory_id))
        records = [await self.repository.get_memory(item) for item in dict.fromkeys(ids)]
        available = [item for item in records if item is not None]
        if available:
            return available[:limit]
        # If Mem0 has no matching mirrored IDs, the simple scoped backend remains useful.
        return await SimpleSQLiteMemoryStore(self.repository).search(query, scopes, limit=limit)


def create_memory_store(
    settings: Settings, repository: HiveMindRepository | None
) -> MemoryStore | None:
    """Build the selected backend only when persistence is available."""

    if repository is None:
        return None
    if settings.memory_backend == "mem0":
        return Mem0MemoryStore.from_settings(settings, repository)
    return SimpleSQLiteMemoryStore(repository)


def _score(memory: MemoryRecord, query_words: set[str]) -> float:
    memory_words = _words(memory.text)
    keyword_score = len(query_words & memory_words) / max(1, len(query_words))
    age_days = max(0.0, (datetime.now(UTC) - memory.updated_at).total_seconds() / 86_400)
    recency_score = 1 / (1 + math.log1p(age_days))
    return keyword_score * 4 + memory.confidence * 2 + recency_score


def _words(text: str) -> set[str]:
    return {
        cleaned
        for word in text.split()
        if (cleaned := "".join(character for character in word.lower() if character.isalnum()))
    }


def _mem0_user(scope: MemoryScope, scope_id: str) -> str:
    return f"hivemind:{scope.value}:{scope_id}"
