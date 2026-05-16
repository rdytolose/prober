"""Runtime settings for the prober worker (read from env + .env)."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class ProberSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    prober_name: str = "prober-1"
    prober_host: str = "0.0.0.0"
    prober_port: int = 8090

    coordinator_url: str = ""
    prober_api_token: str = ""

    prober_local_socks_port: int = 10808
    prober_concurrency: int = 1

    singbox_bin: str = "sing-box"
    openvpn_bin: str = "openvpn"

    prober_site_timeout: float = 10.0
    prober_link_timeout: float = 45.0

    # Polling interval for the worker loop when no coordinator job is ready.
    prober_poll_interval: float = 3.0

    # Incremental reporting: flush after N processed links *or* T seconds, whichever first.
    prober_flush_every_n: int = 10
    prober_flush_every_seconds: float = 20.0

    # While processing a job, re-check job status every N links (to detect cancel).
    prober_cancel_check_every_n: int = 5


def load_settings() -> ProberSettings:
    return ProberSettings()
