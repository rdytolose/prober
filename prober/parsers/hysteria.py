"""Parser for ``hysteria://`` (v1) URLs."""

from __future__ import annotations

from urllib.parse import unquote, urlparse

from ._util import coerce_bool, coerce_int, parse_qsd, split_fragment
from .base import ParsedLink, ParseError


def parse_hysteria(url: str) -> ParsedLink:
    if not url.startswith("hysteria://"):
        raise ParseError("not a hysteria:// URL")
    url_no_frag, remark = split_fragment(url)
    parsed = urlparse(url_no_frag)
    host = parsed.hostname or ""
    port = parsed.port or 0
    if not (host and port):
        raise ParseError("hysteria URL missing host/port")
    q = parse_qsd(parsed.query)

    outbound: dict = {
        "type": "hysteria",
        "tag": "proxy",
        "server": host,
        "server_port": port,
        "up_mbps": coerce_int(q.get("upmbps") or q.get("up"), 50) or 50,
        "down_mbps": coerce_int(q.get("downmbps") or q.get("down"), 100) or 100,
        "auth_str": unquote(q.get("auth", "") or q.get("authStr", "") or q.get("auth_str", "")),
        "tls": {
            "enabled": True,
            "server_name": q.get("peer") or q.get("sni") or host,
            "insecure": coerce_bool(q.get("insecure"), False),
        },
    }
    obfs = q.get("obfs", "")
    if obfs:
        outbound["obfs"] = obfs
    if q.get("alpn"):
        outbound["tls"]["alpn"] = [a.strip() for a in q["alpn"].split(",") if a.strip()]
    return ParsedLink(
        protocol="hysteria",
        remark=unquote(remark),
        raw=url,
        server=host,
        port=port,
        outbound=outbound,
        meta={"obfs": obfs},
    )
