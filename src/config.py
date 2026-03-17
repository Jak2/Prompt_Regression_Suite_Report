"""Central configuration — single source of truth, loaded once at startup."""

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── LLM providers ─────────────────────────────────────────────────────────
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"

    # ── Model selection ───────────────────────────────────────────────────────
    # Model under test and judge must differ to avoid self-scoring bias
    test_model: str = "claude-haiku-4-5-20251001"
    judge_model: str = "gpt-4o-mini"

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = "sqlite:///./regression_suite.db"

    # ── Runner behaviour ──────────────────────────────────────────────────────
    run_count: int = 3
    regression_delta_threshold: float = 0.05
    flakiness_std_threshold: float = 0.05
    max_concurrent_workers: int = 10
    llm_timeout_seconds: int = 60
    llm_max_retries: int = 3

    # ── Paths ─────────────────────────────────────────────────────────────────
    tests_dir: Path = Path("tests")
    prompts_dir: Path = Path("prompts")

    # ── Notifications ─────────────────────────────────────────────────────────
    slack_webhook_url: str = ""

    # ── GitHub CI ─────────────────────────────────────────────────────────────
    github_token: str = ""
    github_repo: str = ""

    @field_validator("tests_dir", "prompts_dir", mode="before")
    @classmethod
    def coerce_path(cls, v: object) -> Path:
        return Path(str(v))

    @property
    def using_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()
