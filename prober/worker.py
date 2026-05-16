"""Background loop: poll the coordinator for jobs, run them, report incrementally."""

from __future__ import annotations

import asyncio
import logging
import time

from .config import ProberSettings
from .orchestrator import Orchestrator
from .reporter import CoordinatorClient

log = logging.getLogger(__name__)


def _fail_outcome(link: str, reason: str) -> dict:
    return {
        "link": link,
        "ok": False,
        "error": reason,
        "protocol": None,
        "remark": "",
        "server": None,
        "port": None,
        "engine_startup_ms": None,
        "tests": None,
        "meta": {},
    }


class WorkerLoop:
    def __init__(self, settings: ProberSettings, orchestrator: Orchestrator) -> None:
        self.settings = settings
        self.orchestrator = orchestrator
        self.client = CoordinatorClient(
            base_url=settings.coordinator_url,
            token=settings.prober_api_token,
            prober_name=settings.prober_name,
        )
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        if self.client.configured:
            try:
                await self.client.register()
                log.info("registered with coordinator at %s", self.settings.coordinator_url)
            except Exception as exc:
                log.warning("could not register with coordinator: %s", exc)
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None
        await self.client.aclose()

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                job = await self.client.next_job()
            except Exception:
                log.exception("polling loop error")
                job = None
            if job is None:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.settings.prober_poll_interval)
                except asyncio.TimeoutError:
                    pass
                continue
            await self._handle_job(job)

    async def _handle_job(self, job: dict) -> None:
        job_id = str(job.get("id"))
        links = list(job.get("links") or [])
        urls = list(job.get("test_urls") or [])
        total = len(links)
        log.info("claimed job %s · %d links · %d test urls", job_id, total, len(urls))

        pending: list[dict] = []
        last_flush = time.monotonic()
        cancelled = False
        processed = 0
        flush_n = max(1, int(self.settings.prober_flush_every_n))
        flush_t = max(1.0, float(self.settings.prober_flush_every_seconds))
        cancel_check_n = max(1, int(self.settings.prober_cancel_check_every_n))

        for i, link in enumerate(links, start=1):
            processed = i
            if self._stop.is_set():
                log.info("worker stopping mid-job; flushing partial results")
                break
            t0 = time.monotonic()
            try:
                outcome = await self.orchestrator.process(link, urls)
                outcome_dict = outcome.to_dict()
            except Exception:
                log.exception("link %s crashed", link)
                outcome_dict = _fail_outcome(link, "internal_error")
            took_ms = int((time.monotonic() - t0) * 1000)
            proto = outcome_dict.get("protocol") or "?"
            ok = "ok" if outcome_dict.get("ok") else "FAIL"
            log.info(
                "[%d/%d] %s · %s · %sms · %s",
                i, total, proto, ok, took_ms,
                (outcome_dict.get("server") or "")[:40],
            )
            pending.append(outcome_dict)

            should_flush_size = len(pending) >= flush_n
            should_flush_time = (time.monotonic() - last_flush) >= flush_t
            if should_flush_size or should_flush_time:
                await self._flush(job_id, pending, final=False)
                pending = []
                last_flush = time.monotonic()

            if i % cancel_check_n == 0:
                status = await self.client.job_status(job_id)
                if status == "cancelled":
                    log.warning("job %s was cancelled by admin; stopping after link %d/%d", job_id, i, total)
                    cancelled = True
                    break
                if status in ("done", "failed"):
                    log.warning("job %s has status=%s on coordinator; stopping", job_id, status)
                    break

        # Final flush: marks job done unless it was cancelled.
        await self._flush(job_id, pending, final=not cancelled and not self._stop.is_set())
        log.info("finished job %s · processed %d/%d · cancelled=%s",
                 job_id, processed, total, cancelled)

    async def _flush(self, job_id: str, outcomes: list[dict], *, final: bool) -> None:
        if not outcomes and not final:
            return
        try:
            await self.client.post_results(job_id, outcomes, final=final)
            log.info("flushed %d outcome(s) for job %s%s", len(outcomes), job_id, " (final)" if final else "")
        except Exception:
            log.exception("failed to post %d outcome(s) for job %s (final=%s)", len(outcomes), job_id, final)
