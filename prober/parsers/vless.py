"""Parser for ``vless://`` URLs, including XTLS-Vision and Reality variants."""

from __future__ import annotations

from urllib.parse import unquote, urlparse

from ._util import coerce_bool, parse_qsd, split_fragment
from .base import ParsedLink, ParseError


def _build_transport(q: dict[str, str]) -> dict | None:
    net = (q.get("type") or "tcp").lower()
    if net in ("tcp", ""):
        # In Xray-style URIs an "http header type" can still be present on
        # tcp transport for fake-http obfuscation; sing-box has no exact
        # equivalent so we ignore that detail.
        return None
    if net == "ws":
        t: dict = {"type": "ws"}
        if q.get("path"):
            t["path"] = unquote(q["path"])
        host = q.get("host", "")
        if host:
            t["headers"] = {"Host": host}
        return t
    if net == "grpc":
        return {"type": "grpc", "service_name": unquote(q.get("serviceName", ""))}
    if net == "http" or net == "h2":
        t = {"type": "http"}
        if q.get("path"):
            t["path"] = unquote(q["path"])
        if q.get("host"):
            t["host"] = [q["host"]]
        return t
    if net == "quic":
        return {"type": "quic"}
    if net == "httpupgrade":
        t = {"type": "httpupgrade"}
        if q.get("path"):
            t["path"] = unquote(q["path"])
        if q.get("host"):
            t["host"] = q["host"]
        return t
    return {"type": net}


def parse_vless(url: str) -> ParsedLink:
    if not url.startswith("vless://"):
        raise ParseError("not a vless:// URL")
    url_no_frag, remark = split_fragment(url)
    parsed = urlparse(url_no_frag)
    uuid = parsed.username or ""
    host = parsed.hostname or ""
    port = parsed.port or 0
    if not (uuid and host and port):
        raise ParseError("vless URL missing uuid/host/port")
    q = parse_qsd(parsed.query)

    security = (q.get("security") or "none").lower()
    flow = q.get("flow", "")
    sni = q.get("sni") or q.get("host") or host
    fp = q.get("fp", "")

    outbound: dict = {
        "type": "vless",
        "tag": "proxy",
        "server": host,
        "server_port": port,
        "uuid": uuid,
        "flow": flow,
    }
    transport = _build_transport(q)
    if transport:
        outbound["transport"] = transport

    if security == "tls":
        outbound["tls"] = {
            "enabled": True,
            "server_name": sni,
            "insecure": coerce_bool(q.get("allowInsecure"), False),
        }
        if q.get("alpn"):
            outbound["tls"]["alpn"] = [a.strip() for a in q["alpn"].split(",") if a.strip()]
        if fp:
            outbound["tls"]["utls"] = {"enabled": True, "fingerprint": fp}
    elif security == "reality":
        outbound["tls"] = {
            "enabled": True,
            "server_name": sni,
            "utls": {"enabled": True, "fingerprint": fp or "chrome"},
            "reality": {
                "enabled": True,
                "public_key": q.get("pbk", ""),
                "short_id": q.get("sid", ""),
            },
        }
    elif security == "xtls":
        # Legacy XTLS — sing-box maps via flow on plain TLS.
        outbound["tls"] = {
            "enabled": True,
            "server_name": sni,
            "insecure": coerce_bool(q.get("allowInsecure"), False),
        }

    return ParsedLink(
        protocol="vless",
        remark=unquote(remark),
        raw=url,
        server=host,
        port=port,
        outbound=outbound,
        meta={
            "network": q.get("type", "tcp"),
            "security": security,
            "flow": flow,
            "fingerprint": fp,
        },
    )
