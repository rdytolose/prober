"""Common types and base classes for connection URL parsers.

Every parser converts a single connection URL into a normalised
``ParsedLink`` object.  The engine (sing-box / openvpn) then turns that
into a runtime config.

A parser is allowed to raise ``ParseError`` for malformed input; the
orchestrator records this as a failure for that link rather than crashing
the whole worker.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class ParseError(ValueError):
    """Raised when a connection URL cannot be parsed."""


@dataclass
class ParsedLink:
    """Normalised representation of one connection URL.

    ``outbound`` is a dict in sing-box outbound JSON schema (or
    ``{"type": "openvpn", ...}`` for the OpenVPN engine).  The engine
    layer is responsible for wrapping this in a full sing-box config.
    """

    protocol: str
    remark: str
    raw: str
    server: str
    port: int
    outbound: dict[str, Any]
    # Free-form metadata: transport, tls, etc.  Used by the dashboard.
    meta: dict[str, Any] = field(default_factory=dict)

    def short(self) -> str:
        return f"{self.protocol}://{self.server}:{self.port} ({self.remark or '-'})"
