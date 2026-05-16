"""Prober HTTP API.

Two roles:
1. Local-only endpoint to submit ad-hoc jobs (useful in dev / when running
   without a coordinator).
2. ``/health`` and ``/info`` endpoints for the coordinator's monitoring.

The worker loop in ``worker.py`` runs in the background and pulls jobs from
the coordinator when ``COORDINATOR_URL`` is set.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from .config import ProberSettings, load_settings
from .orchestrator import Orchestrator
from .parsers import SUPPORTED_PREFIXES
from .worker import WorkerLoop

log = logging.getLogger(__name__)


class AdHocJob(BaseModel):
    links: list[str] = Field(default_factory=list)
    test_urls: list[str] = Field(default_factory=list)


def create_app(settings: ProberSettings | None = None) -> FastAPI:
    settings = settings or load_settings()
    orchestrator = Orchestrator(
        singbox_bin=settings.singbox_bin,
        openvpn_bin=settings.openvpn_bin,
        local_socks_port=settings.prober_local_socks_port,
        site_timeout_s=settings.prober_site_timeout,
        link_timeout_s=settings.prober_link_timeout,
    )
    worker = WorkerLoop(settings, orchestrator)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await worker.start()
        try:
            yield
        finally:
            await worker.stop()

    app = FastAPI(title="VPN Prober", lifespan=lifespan)
    app.state.settings = settings
    app.state.orchestrator = orchestrator
    app.state.worker = worker

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "name": settings.prober_name}

    @app.get("/info")
    async def info() -> dict[str, Any]:
        return {
            "name": settings.prober_name,
            "supported_prefixes": list(SUPPORTED_PREFIXES),
            "coordinator_url": settings.coordinator_url or None,
            "concurrency": settings.prober_concurrency,
        }

    @app.post("/run")
    async def run_adhoc(job: AdHocJob, request: Request) -> dict[str, Any]:
        # Optional simple token guard for ad-hoc submissions on the prober.
        token = settings.prober_api_token
        if token:
            auth = request.headers.get("authorization", "")
            if auth != f"Bearer {token}":
                raise HTTPException(status_code=401, detail="invalid prober token")
        if not job.links:
            raise HTTPException(status_code=400, detail="no links provided")
        outcomes = []
        for link in job.links:
            outcome = await orchestrator.process(link, job.test_urls)
            outcomes.append(outcome.to_dict())
        return {"prober_name": settings.prober_name, "outcomes": outcomes}

    return app
