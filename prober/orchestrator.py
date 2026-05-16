"""Job execution: for each link in a job, parse, start engine, run tests,
return a result.  The HTTP layer / worker loop wraps this in delivery."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass
from typing import Any

from .engines.base import Engine, EngineUnsupported
from .engines.openvpn import OpenVPNEngine
from .engines.singbox import SingBoxEngine
from .parsers import ParsedLink, ParseError, parse
from .tester import TestResults, run_tests

log = logging.getLogger(__name__)


@dataclass
class LinkOutcome:
    link: str
    protocol: str | None
    remark: str
    server: str | None
    port: int | None
    ok: bool
    error: str | None
    engine_startup_ms: int | None
    tests: TestResults | None
    meta: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "link": self.link,
            "protocol": self.protocol,
            "remark": self.remark,
            "server": self.server,
            "port": self.port,
            "ok": self.ok,
            "error": self.error,
            "engine_startup_ms": self.engine_startup_ms,
            "meta": self.meta,
        }
        if self.tests is not None:
            d["tests"] = {
                "connectivity": asdict(self.tests.connectivity),
                "sites": [asdict(s) for s in self.tests.sites],
            }
        else:
            d["tests"] = None
        return d


class Orchestrator:
    """Runs a single job (list of links + list of test URLs).

    All engines listen on the same loopback port, so per-link execution is
    serialised behind a lock.  For higher throughput, run multiple prober
    workers (each gets its own port) rather than threading inside one.
    """

    def __init__(
        self,
        *,
        singbox_bin: str,
        openvpn_bin: str,
        local_socks_port: int,
        site_timeout_s: float,
        link_timeout_s: float,
    ) -> None:
        self.singbox = SingBoxEngine(binary=singbox_bin)
        self.openvpn = OpenVPNEngine(binary=openvpn_bin)
        self.local_socks_port = local_socks_port
        self.site_timeout_s = site_timeout_s
        self.link_timeout_s = link_timeout_s
        self._lock = asyncio.Lock()

    def _engine_for(self, link: ParsedLink) -> Engine:
        if self.openvpn.supports(link):
            return self.openvpn
        return self.singbox

    def _parse_failure(self, link_url: str, exc: ParseError) -> LinkOutcome:
        return LinkOutcome(
            link=link_url,
            protocol=None,
            remark="",
            server=None,
            port=None,
            ok=False,
            error=f"parse_error: {exc!s}",
            engine_startup_ms=None,
            tests=None,
            meta={},
        )

    async def process(self, link_url: str, test_urls: list[str]) -> LinkOutcome:
        """Parse → start engine → run tests → tear down → return outcome."""
        try:
            link = parse(link_url)
        except ParseError as exc:
            return self._parse_failure(link_url, exc)

        async with self._lock:
            return await self._process_locked(link, test_urls)

    async def _process_locked(self, link: ParsedLink, test_urls: list[str]) -> LinkOutcome:
        engine = self._engine_for(link)
        start = time.perf_counter()
        try:
            handle = await asyncio.wait_for(
                engine.start(
                    link,
                    local_socks_port=self.local_socks_port,
                    timeout_s=min(15.0, self.link_timeout_s),
                ),
                timeout=self.link_timeout_s,
            )
        except (EngineUnsupported, RuntimeError, TimeoutError, FileNotFoundError, asyncio.TimeoutError) as exc:
            return LinkOutcome(
                link=link.raw,
                protocol=link.protocol,
                remark=link.remark,
                server=link.server,
                port=link.port,
                ok=False,
                error=f"engine_error: {exc!s}",
                engine_startup_ms=int((time.perf_counter() - start) * 1000),
                tests=None,
                meta=link.meta,
            )

        startup_ms = int((time.perf_counter() - start) * 1000)
        tests: TestResults | None = None
        error: str | None = None
        try:
            tests = await asyncio.wait_for(
                run_tests(
                    local_socks_port=handle.local_socks_port,
                    urls=test_urls,
                    timeout_s=self.site_timeout_s,
                ),
                timeout=self.link_timeout_s,
            )
        except asyncio.TimeoutError:
            error = f"tester_timeout after {self.link_timeout_s}s"
        finally:
            try:
                await handle.stop()  # type: ignore[misc]
            except Exception:
                log.exception("engine stop failed")

        if tests is None:
            return LinkOutcome(
                link=link.raw,
                protocol=link.protocol,
                remark=link.remark,
                server=link.server,
                port=link.port,
                ok=False,
                error=error or "tester_unknown_error",
                engine_startup_ms=startup_ms,
                tests=None,
                meta=link.meta,
            )

        ok = any(s.ok for s in tests.sites) if tests.sites else (tests.connectivity.ip is not None)
        return LinkOutcome(
            link=link.raw,
            protocol=link.protocol,
            remark=link.remark,
            server=link.server,
            port=link.port,
            ok=ok,
            error=None if ok else "all_sites_failed",
            engine_startup_ms=startup_ms,
            tests=tests,
            meta=link.meta,
        )
