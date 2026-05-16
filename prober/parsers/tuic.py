"""Parser for ``tuic://`` URLs (v4 and v5 share the same surface shape).

Form (v5):  ``tuic://uuid:password@host:port?congestion_control=bbr&alpn=h3&sni=...#remark``
"""

from __future__ import annotations

from urllib.parse import unquote, urlparse

from ._util import coerce_bool, parse_qsd, split_fragment
from .base import ParsedLink, ParseError


def parse_tuic(url: str) -> ParsedLink:
    if not url.startswith("tuic://"):
        raise ParseError("not a tuic:// URL")
    url_no_frag, remark = split_fragment(url)
    parsed = urlparse(url_no_frag)
    user = unquote(parsed.username or "")
    password = unquote(parsed.password or "") if parsed.password is not None else ""
    host = parsed.hostname or ""
    port = parsed.port or 0
    if not (host and port and user):
        raise ParseError("tuic URL missing uuid/host/port")
    q = parse_qsd(parsed.query)

    outbound: dict = {
        "type": "tuic",
        "tag": "proxy",
        "server": host,
        "server_port": port,
        "uuid": user,
        "password": password,
        "congestion_control": q.get("congestion_control", "bbr"),
        "udp_relay_mode": q.get("udp_relay_mode", "native"),
        "zero_rtt_handshake": coerce_bool(q.get("zero_rtt"), False),
        "tls": {
            "enabled": True,
            "server_name": q.get("sni") or host,
            "insecure": coerce_bool(q.get("allow_insecure"), False),
            "alpn": [a.strip() for a in (q.get("alpn", "h3").split(",")) if a.strip()],
        },
    }
    return ParsedLink(
        protocol="tuic",
        remark=unquote(remark),
        raw=url,
        server=host,
        port=port,
        outbound=outbound,
        meta={"congestion_control": outbound["congestion_control"]},
    )
