"""Parser for ``hysteria2://`` / ``hy2://`` URLs."""

from __future__ import annotations

from urllib.parse import unquote, urlparse

from ._util import coerce_bool, parse_qsd, split_fragment
from .base import ParsedLink, ParseError


def parse_hysteria2(url: str) -> ParsedLink:
    if not (url.startswith("hysteria2://") or url.startswith("hy2://")):
        raise ParseError("not a hysteria2 URL")
    url_no_frag, remark = split_fragment(url)
    parsed = urlparse(url_no_frag)
    password = unquote(parsed.username or "")
    host = parsed.hostname or ""
    port = parsed.port or 0
    if not (host and port):
        raise ParseError("hysteria2 URL missing host/port")
    q = parse_qsd(parsed.query)

    outbound: dict = {
        "type": "hysteria2",
        "tag": "proxy",
        "server": host,
        "server_port": port,
        "password": password,
        "tls": {
            "enabled": True,
            "server_name": q.get("sni") or q.get("peer") or host,
            "insecure": coerce_bool(q.get("insecure"), False),
        },
    }
    if q.get("alpn"):
        outbound["tls"]["alpn"] = [a.strip() for a in q["alpn"].split(",") if a.strip()]
    obfs_type = q.get("obfs", "")
    obfs_pwd = q.get("obfs-password", "") or q.get("obfsParam", "")
    if obfs_type:
        outbound["obfs"] = {"type": obfs_type, "password": obfs_pwd}
    return ParsedLink(
        protocol="hysteria2",
        remark=unquote(remark),
        raw=url,
        server=host,
        port=port,
        outbound=outbound,
        meta={"obfs": obfs_type},
    )
