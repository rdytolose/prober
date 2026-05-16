"""Engine for ``openvpn://`` links.

OpenVPN sets up a system-wide tunnel (TUN/TAP) — it does not expose a SOCKS
port natively.  To stay compatible with the rest of the prober (which talks
SOCKS5) we run a tiny local HTTP/SOCKS hop via ``microsocks`` when present,
and otherwise we treat OpenVPN as a "system route" mode where the prober
talks directly via the default interface once the tunnel is up.

This module is opt-in: if ``openvpn`` is not installed or the link doesn't
provide a config, the engine reports the link as ``error="openvpn not
configured on this prober"``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import tempfile

import httpx

from ..parsers.base import ParsedLink
from .base import Engine, EngineHandle, EngineUnsupported

log = logging.getLogger(__name__)


class OpenVPNEngine(Engine):
    name = "openvpn"

    def __init__(self, binary: str = "openvpn", microsocks_binary: str = "microsocks") -> None:
        self.binary = binary
        self.microsocks_binary = microsocks_binary

    def supports(self, link: ParsedLink) -> bool:
        return link.outbound.get("type") == "openvpn"

    async def start(
        self,
        link: ParsedLink,
        *,
        local_socks_port: int,
        timeout_s: float,
    ) -> EngineHandle:
        if not self.supports(link):
            raise EngineUnsupported("not an openvpn link")
        ovpn = shutil.which(self.binary)
        if not ovpn:
            raise EngineUnsupported(
                f"{self.binary} binary not found on PATH; install OpenVPN to test openvpn:// links"
            )

        cfg_text = link.outbound.get("config_text")
        cfg_url = link.outbound.get("config_url")
        if not cfg_text and cfg_url:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(cfg_url)
                resp.raise_for_status()
                cfg_text = resp.text
        if not cfg_text:
            raise EngineUnsupported("openvpn link has no inline config and no fetchable URL")

        tmpdir = tempfile.mkdtemp(prefix="prober-openvpn-")
        cfg_path = os.path.join(tmpdir, "client.ovpn")
        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write(cfg_text)

        log_path = os.path.join(tmpdir, "openvpn.log")
        # Note: in production OpenVPN typically needs root or CAP_NET_ADMIN.
        proc = await asyncio.create_subprocess_exec(
            ovpn,
            "--config",
            cfg_path,
            "--log",
            log_path,
            "--script-security",
            "0",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            cwd=tmpdir,
        )

        # Wait until the tunnel is up by polling the log for "Initialization Sequence Completed".
        ready = False
        deadline = asyncio.get_event_loop().time() + timeout_s
        while asyncio.get_event_loop().time() < deadline:
            if proc.returncode is not None:
                break
            if os.path.exists(log_path):
                try:
                    with open(log_path, errors="replace") as f:
                        contents = f.read()
                except OSError:
                    contents = ""
                if "Initialization Sequence Completed" in contents:
                    ready = True
                    break
                if "AUTH_FAILED" in contents or "Exiting due to fatal error" in contents:
                    break
            await asyncio.sleep(0.5)

        async def stop() -> None:
            with contextlib.suppress(ProcessLookupError):
                if proc.returncode is None:
                    proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        proc.kill()
            shutil.rmtree(tmpdir, ignore_errors=True)

        if not ready:
            await stop()
            raise TimeoutError("openvpn tunnel did not come up in time")

        # If microsocks is available, run it bound to the new default route so
        # that the rest of the prober can keep using SOCKS5.  Otherwise return
        # a "system route" handle with port=0, which the tester treats as
        # direct (no SOCKS).
        microsocks = shutil.which(self.microsocks_binary)
        microsocks_proc: asyncio.subprocess.Process | None = None
        if microsocks:
            microsocks_proc = await asyncio.create_subprocess_exec(
                microsocks,
                "-i",
                "127.0.0.1",
                "-p",
                str(local_socks_port),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            # microsocks is up almost instantly; small grace period.
            await asyncio.sleep(0.2)
            effective_port = local_socks_port
        else:
            log.warning("microsocks not found; openvpn engine will use system route")
            effective_port = 0

        async def stop_full() -> None:
            if microsocks_proc is not None:
                with contextlib.suppress(ProcessLookupError):
                    if microsocks_proc.returncode is None:
                        microsocks_proc.terminate()
                        try:
                            await asyncio.wait_for(microsocks_proc.wait(), timeout=3.0)
                        except asyncio.TimeoutError:
                            microsocks_proc.kill()
            await stop()

        return EngineHandle(local_socks_port=effective_port, stop=stop_full)
