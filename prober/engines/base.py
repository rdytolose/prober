"""Abstract base for proxy engines.

An engine takes a ``ParsedLink`` and stands up a local SOCKS5 proxy that
forwards traffic through the link.  Implementations live in ``singbox.py``,
``openvpn.py``, etc.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass

from ..parsers.base import ParsedLink


@dataclass
class EngineHandle:
    """A running engine instance.  ``local_socks_port`` is what the site
    tester should send traffic through."""

    local_socks_port: int
    # An async coroutine the caller can await to gracefully shut it down.
    stop: object  # Callable[[], Awaitable[None]] (cannot import here without circular)


class EngineUnsupported(RuntimeError):
    """Raised when an engine can't handle the parsed link."""


class Engine(abc.ABC):
    name: str

    @abc.abstractmethod
    async def start(self, link: ParsedLink, *, local_socks_port: int, timeout_s: float) -> EngineHandle:
        ...

    @abc.abstractmethod
    def supports(self, link: ParsedLink) -> bool:
        ...
