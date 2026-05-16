"""Parser for ``anytls://`` URLs (anytls-go / sing-box >= 1.10)."""

from __future__ import annotations

from urllib.parse import unquote, urlparse

from ._util import coerce_bool, parse_qsd, split_fragment
from .base import ParsedLink, ParseError


def parse_anytls(url: str) -> ParsedLink:
    if not url.startswith("anytls://"):
        raise ParseError("not an anytls URL")
    url_no_frag, remark = split_fragment(url)
    parsed = urlparse(url_no_frag)
    password = unquote(parsed.username or "")
    host = parsed.hostname or ""
    port = parsed.port or 0
    if not (password and host and port):
        raise ParseError("anytls URL missing password/host/port")
    q = parse_qsd(parsed.query)
    outbound: dict = {
        "type": "anytls",
        "tag": "proxy",
        "server": host,
        "server_port": port,
        "password": password,
        "tls": {
            "enabled": True,
            "server_name": q.get("sni") or host,
            "insecure": coerce_bool(q.get("insecure"), False),
        },
    }
    return ParsedLink(
        protocol="anytls",
        remark=unquote(remark),
        raw=url,
        server=host,
        port=port,
        outbound=outbound,
        meta={},
    )
