"""Parser for ``trojan://`` and ``trojan-go://`` URLs.

URL form: ``trojan://password@host:port?sni=...&type=ws&path=...#remark``
"""

from __future__ import annotations

from urllib.parse import unquote, urlparse

from ._util import coerce_bool, parse_qsd, split_fragment
from .base import ParsedLink, ParseError


def parse_trojan(url: str) -> ParsedLink:
    if not (url.startswith("trojan://") or url.startswith("trojan-go://")):
        raise ParseError("not a trojan URL")
    url_no_frag, remark = split_fragment(url)
    parsed = urlparse(url_no_frag)
    password = unquote(parsed.username or "")
    host = parsed.hostname or ""
    port = parsed.port or 0
    if not (password and host and port):
        raise ParseError("trojan URL missing password/host/port")
    q = parse_qsd(parsed.query)
    sni = q.get("sni") or q.get("peer") or host
    network = (q.get("type") or "tcp").lower()

    outbound: dict = {
        "type": "trojan",
        "tag": "proxy",
        "server": host,
        "server_port": port,
        "password": password,
        "tls": {
            "enabled": True,
            "server_name": sni,
            "insecure": coerce_bool(q.get("allowInsecure"), False),
        },
    }
    if q.get("alpn"):
        outbound["tls"]["alpn"] = [a.strip() for a in q["alpn"].split(",") if a.strip()]
    fp = q.get("fp", "")
    if fp:
        outbound["tls"]["utls"] = {"enabled": True, "fingerprint": fp}

    if network == "ws":
        transport: dict = {"type": "ws"}
        if q.get("path"):
            transport["path"] = unquote(q["path"])
        if q.get("host"):
            transport["headers"] = {"Host": q["host"]}
        outbound["transport"] = transport
    elif network == "grpc":
        outbound["transport"] = {"type": "grpc", "service_name": unquote(q.get("serviceName", ""))}
    elif network in ("h2", "http"):
        t: dict = {"type": "http"}
        if q.get("path"):
            t["path"] = unquote(q["path"])
        if q.get("host"):
            t["host"] = [q["host"]]
        outbound["transport"] = t

    return ParsedLink(
        protocol="trojan",
        remark=unquote(remark),
        raw=url,
        server=host,
        port=port,
        outbound=outbound,
        meta={"network": network, "fingerprint": fp},
    )
