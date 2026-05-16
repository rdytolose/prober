"""Site tester: given a SOCKS5 port (or direct route), fetch each URL and
report whether it loaded, how fast, and what the apparent egress IP is.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import httpx

log = logging.getLogger(__name__)


@dataclass
class SiteResult:
    url: str
    ok: bool
    status: int | None = None
    latency_ms: int | None = None
    size_bytes: int | None = None
    error: str | None = None


@dataclass
class ConnectivityResult:
    ip: str | None = None
    country: str | None = None
    error: str | None = None


@dataclass
class TestResults:
    sites: list[SiteResult] = field(default_factory=list)
    connectivity: ConnectivityResult = field(default_factory=ConnectivityResult)


def _fmt(exc: BaseException) -> str:
    """Format an exception with its class name so empty-message errors are still informative."""
    msg = str(exc).strip()
    cls = type(exc).__name__
    return f"{cls}: {msg}" if msg else cls


def _proxy_for_port(local_socks_port: int) -> str | None:
    if local_socks_port <= 0:
        return None
    return f"socks5://127.0.0.1:{local_socks_port}"


async def _detect_ip(client: httpx.AsyncClient) -> ConnectivityResult:
    out = ConnectivityResult()
    try:
        r = await client.get("https://ipinfo.io/json", timeout=8.0)
        if r.status_code == 200:
            d = r.json()
            out.ip = d.get("ip")
            out.country = d.get("country")
            return out
    except Exception as exc:
        out.error = f"ipinfo: {exc!s}"
    # Fallback
    try:
        r = await client.get("https://api.ipify.org?format=json", timeout=8.0)
        if r.status_code == 200:
            out.ip = r.json().get("ip")
            out.error = None
    except Exception as exc:
        if not out.ip:
            out.error = f"ipify: {exc!s}"
    return out


async def _test_one(client: httpx.AsyncClient, url: str, timeout_s: float) -> SiteResult:
    start = time.perf_counter()
    try:
        # Use GET so we actually pull bytes (HEAD is often blocked or misleading).
        resp = await client.get(url, timeout=timeout_s, follow_redirects=True)
        latency = int((time.perf_counter() - start) * 1000)
        size = len(resp.content) if resp.content is not None else 0
        ok = 200 <= resp.status_code < 400
        return SiteResult(
            url=url,
            ok=ok,
            status=resp.status_code,
            latency_ms=latency,
            size_bytes=size,
            error=None if ok else f"HTTP {resp.status_code}",
        )
    except httpx.TimeoutException as exc:
        return SiteResult(url=url, ok=False, error=f"timeout: {_fmt(exc)}")
    except httpx.ProxyError as exc:
        return SiteResult(url=url, ok=False, error=f"proxy_error: {_fmt(exc)}")
    except httpx.HTTPError as exc:
        return SiteResult(url=url, ok=False, error=f"http_error: {_fmt(exc)}")
    except Exception as exc:  # pragma: no cover - defensive
        return SiteResult(url=url, ok=False, error=f"unexpected: {_fmt(exc)}")


async def run_tests(
    local_socks_port: int,
    urls: list[str],
    *,
    timeout_s: float = 10.0,
    detect_ip: bool = True,
    user_agent: str = "vpn-prober/0.1",
) -> TestResults:
    proxy = _proxy_for_port(local_socks_port)
    transport_kwargs: dict = {"proxy": proxy} if proxy else {}
    async with httpx.AsyncClient(
        headers={"User-Agent": user_agent},
        verify=True,
        **transport_kwargs,
    ) as client:
        connectivity = await _detect_ip(client) if detect_ip else ConnectivityResult()
        results: list[SiteResult] = []
        for url in urls:
            r = await _test_one(client, url, timeout_s=timeout_s)
            results.append(r)
            log.debug("tested %s -> ok=%s status=%s", url, r.ok, r.status)
        return TestResults(sites=results, connectivity=connectivity)
