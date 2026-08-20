"""Load HiveMind configuration from defaults, ``.env``, and environment variables.

Configuration is centralized here so model adapters and orchestration code do not read
environment variables directly. CLI commands may create a copied settings object with a
few explicit overrides, making the precedence visible and easy to test.
"""

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings with safe, local-first defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    provider: Literal["ollama", "openai", "fake"] = Field(
        default="ollama", alias="HIVEMIND_PROVIDER"
    )
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="qwen3:8b", alias="OLLAMA_MODEL")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4.1-mini", alias="OPENAI_MODEL")

    db_path: Path = Field(default=Path("data/hivemind.db"), alias="HIVEMIND_DB_PATH")
    runs_dir: Path = Field(default=Path("runs"), alias="HIVEMIND_RUNS_DIR")
    memory_backend: Literal["simple", "mem0"] = Field(
        default="simple", alias="HIVEMIND_MEMORY_BACKEND"
    )
    mem0_embed_model: str = Field(default="nomic-embed-text", alias="HIVEMIND_MEM0_EMBED_MODEL")
    enable_web: bool = Field(default=True, alias="HIVEMIND_ENABLE_WEB")

    max_managers: int = Field(default=3, ge=1, le=10, alias="HIVEMIND_MAX_MANAGERS")
    max_workers_per_manager: int = Field(
        default=3, ge=1, le=10, alias="HIVEMIND_MAX_WORKERS_PER_MANAGER"
    )
    max_total_agents: int = Field(default=15, ge=4, le=100, alias="HIVEMIND_MAX_TOTAL_AGENTS")
    max_concurrent_llm_calls: int = Field(
        default=3, ge=1, le=20, alias="HIVEMIND_MAX_CONCURRENT_LLM_CALLS"
    )
    max_concurrent_web_requests: int = Field(
        default=4, ge=1, le=20, alias="HIVEMIND_MAX_CONCURRENT_WEB_REQUESTS"
    )
    max_research_rounds: int = Field(default=2, ge=1, le=5, alias="HIVEMIND_MAX_RESEARCH_ROUNDS")
    max_search_queries_per_worker: int = Field(
        default=2, ge=0, le=5, alias="HIVEMIND_MAX_SEARCH_QUERIES_PER_WORKER"
    )
    max_retries: int = Field(default=2, ge=0, le=5, alias="HIVEMIND_MAX_RETRIES")
    max_runtime_seconds: int = Field(
        default=900, ge=10, le=86400, alias="HIVEMIND_MAX_RUNTIME_SECONDS"
    )
    log_level: str = Field(default="INFO", alias="HIVEMIND_LOG_LEVEL")

    model_ceo: str | None = Field(default=None, alias="HIVEMIND_MODEL_CEO")
    model_manager: str | None = Field(default=None, alias="HIVEMIND_MODEL_MANAGER")
    model_worker: str | None = Field(default=None, alias="HIVEMIND_MODEL_WORKER")
    model_verifier: str | None = Field(default=None, alias="HIVEMIND_MODEL_VERIFIER")
    model_qa: str | None = Field(default=None, alias="HIVEMIND_MODEL_QA")
    model_memory: str | None = Field(default=None, alias="HIVEMIND_MODEL_MEMORY")

    def model_for(self, role: str) -> str:
        """Return a role override or the provider's main model."""

        override = getattr(self, f"model_{role}", None)
        if override:
            return override
        return self.openai_model if self.provider == "openai" else self.ollama_model

    def ensure_directories(self) -> None:
        """Create only the local directories needed for database and run artifacts."""

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)


def load_settings(**overrides: object) -> Settings:
    """Load settings and apply non-``None`` CLI overrides last."""

    settings = Settings()
    clean = {key: value for key, value in overrides.items() if value is not None}
    return settings.model_copy(update=clean)
