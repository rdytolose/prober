"""Coordinator settings."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class CoordinatorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    coordinator_host: str = "0.0.0.0"
    coordinator_port: int = 8080
    coordinator_db_url: str = "sqlite+aiosqlite:///./data/coordinator.db"

    # Comma-separated allow list.
    coordinator_api_tokens: str = ""
    coordinator_admin_token: str = ""

    @property
    def prober_tokens(self) -> set[str]:
        return {t.strip() for t in self.coordinator_api_tokens.split(",") if t.strip()}


def load_settings() -> CoordinatorSettings:
    return CoordinatorSettings()
