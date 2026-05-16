"""Engine that drives a per-link ``sing-box`` subprocess.

For each ``ParsedLink`` we:

1. Build a minimal sing-box JSON config with two inbounds (mixed/socks on a
   loopback port) and one outbound (the parsed proxy).
2. Spawn ``sing-box run -c <config.json>`` in a temp directory.
3. Wait until the SOCKS port is accepting connections (or timeout).
4. Return an ``EngineHandle`` whose ``stop`` coroutine kills the process and
   cleans up the temp dir.

We deliberately use a fresh process per link so that a hung or crashed
sing-box only affects that one link's result.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import tempfile
from collections.abc import Awaitable, Callable
from typing import Any

from ..parsers.base import ParsedLink
from .base import Engine, EngineHandle, EngineUnsupported

log = logging.getLogger(__name__)


_UNSUPPORTED = {"openvpn"}


def build_config(link: ParsedLink, *, local_socks_port: int) -> dict[str, Any]:
    """Return a sing-box config that routes everything through ``link``."""

    outbound = dict(link.outbound)
    outbound.setdefault("tag", "proxy")

    config: dict[str, Any] = {
        "log": {"level": "warn", "timestamp": True},
        "dns": {
            "servers": [
                {"tag": "system", "address": "local", "detour": "direct"},
            ],
        },
        "inbounds": [
            {
                "type": "mixed",
                "tag": "mixed-in",
                "listen": "127.0.0.1",
                "listen_port": local_socks_port,
                "sniff": True,
            }
        ],
        "outbounds": [
            outbound,
            {"type": "direct", "tag": "direct"},
            {"type": "block", "tag": "block"},
        ],
        "route": {
            "rules": [
                {"inbound": ["mixed-in"], "outbound": "proxy"},
            ],
            "final": "proxy",
        },
    }
    return config


class SingBoxEngine(Engine):
    name = "singbox"

    def __init__(self, binary: str = "sing-box") -> None:
        self.binary = binary

    def supports(self, link: ParsedLink) -> bool:
        return link.outbound.get("type") not in _UNSUPPORTED

    async def start(
        self,
        link: ParsedLink,
        *,
        local_socks_port: int,
        timeout_s: float,
    ) -> EngineHandle:
        if not self.supports(link):
            raise EngineUnsupported(f"sing-box does not handle outbound type {link.outbound.get('type')!r}")

        tmpdir = tempfile.mkdtemp(prefix="prober-singbox-")
        config_path = os.path.join(tmpdir, "config.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(build_config(link, local_socks_port=local_socks_port), f, indent=2)

        # Resolve binary; allow ``./sing-box`` style paths.
        binary = shutil.which(self.binary) or self.binary

        log.debug("starting sing-box for %s on port %d (cfg=%s)", link.short(), local_socks_port, config_path)
        proc = await asyncio.create_subprocess_exec(
            binary,
            "run",
            "-c",
            config_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=tmpdir,
        )

        stop_fn: Callable[[], Awaitable[None]] = _make_stopper(proc, tmpdir)

        # Wait for the SOCKS port to start accepting connections.
        deadline = asyncio.get_event_loop().time() + timeout_s
        while True:
            if proc.returncode is not None:
                stderr = await _read_stderr(proc)
                await stop_fn()
                raise RuntimeError(
                    f"sing-box exited before listening (rc={proc.returncode}): {stderr[:400]}"
                )
            if await _port_open("127.0.0.1", local_socks_port):
                break
            if asyncio.get_event_loop().time() > deadline:
                stderr = await _read_stderr(proc)
                await stop_fn()
                raise TimeoutError(f"sing-box did not open socks port {local_socks_port}: {stderr[:400]}")
            await asyncio.sleep(0.1)

        return EngineHandle(local_socks_port=local_socks_port, stop=stop_fn)


def _make_stopper(proc: asyncio.subprocess.Process, tmpdir: str) -> Callable[[], Awaitable[None]]:
    async def stop() -> None:
        with contextlib.suppress(ProcessLookupError):
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=3.0)
                except asyncio.TimeoutError:
                    proc.kill()
                    with contextlib.suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(proc.wait(), timeout=2.0)
        shutil.rmtree(tmpdir, ignore_errors=True)

    return stop


async def _port_open(host: str, port: int) -> bool:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=0.5
        )
    except (OSError, asyncio.TimeoutError):
        return False
    writer.close()
    with contextlib.suppress(Exception):
        await writer.wait_closed()
    _ = reader  # silence unused
    return True


async def _read_stderr(proc: asyncio.subprocess.Process, limit: int = 4096) -> str:
    if proc.stderr is None:
        return ""
    try:
        data = await asyncio.wait_for(proc.stderr.read(limit), timeout=0.5)
    except asyncio.TimeoutError:
        return ""
    return data.decode("utf-8", errors="replace")
