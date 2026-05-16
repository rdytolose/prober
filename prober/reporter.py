"""Coordinator client: register, pull jobs, push results."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)


class CoordinatorClient:
    def __init__(self, base_url: str, token: str, prober_name: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.prober_name = prober_name
        self._client = httpx.AsyncClient(
            timeout=15.0,
            headers={"Authorization": f"Bearer {token}", "X-Prober-Name": prober_name},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.token)

    async def register(self) -> dict[str, Any]:
        if not self.configured:
            return {}
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(5),
            wait=wait_exponential(multiplier=0.5, max=10),
            retry=retry_if_exception_type(httpx.HTTPError),
        ):
            with attempt:
                r = await self._client.post(
                    f"{self.base_url}/api/v1/probers/register",
                    json={"name": self.prober_name},
                )
                r.raise_for_status()
                return r.json()
        return {}

    async def next_job(self) -> dict[str, Any] | None:
        if not self.configured:
            return None
        try:
            r = await self._client.get(f"{self.base_url}/api/v1/jobs/next")
        except httpx.HTTPError as exc:
            log.warning("next_job failed: %s", exc)
            return None
        if r.status_code == 204:
            return None
        if r.status_code >= 400:
            log.warning("next_job HTTP %s: %s", r.status_code, r.text[:200])
            return None
        return r.json()

    async def post_results(
        self,
        job_id: str,
        outcomes: list[dict[str, Any]],
        *,
        final: bool = False,
    ) -> None:
        """Push a batch of outcomes. ``final=True`` marks the job done on the coordinator."""
        if not self.configured:
            return
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(5),
            wait=wait_exponential(multiplier=0.5, max=10),
            retry=retry_if_exception_type(httpx.HTTPError),
        ):
            with attempt:
                r = await self._client.post(
                    f"{self.base_url}/api/v1/results",
                    json={
                        "job_id": job_id,
                        "prober_name": self.prober_name,
                        "outcomes": outcomes,
                        "final": final,
                    },
                )
                r.raise_for_status()
                return

    async def job_status(self, job_id: str) -> str | None:
        """Return the coordinator's view of the job status, or None on error."""
        if not self.configured:
            return None
        try:
            r = await self._client.get(f"{self.base_url}/api/v1/jobs/{job_id}/status")
        except httpx.HTTPError as exc:
            log.warning("job_status failed: %s", exc)
            return None
        if r.status_code >= 400:
            return None
        return (r.json() or {}).get("status")
