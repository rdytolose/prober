"""Parser for ``vmess://`` connection URLs.

The dominant form is V2RayN: ``vmess://BASE64(JSON)``.  Some clients emit a
URI form ``vmess://uuid@host:port?...`` — we accept that too as a fallback.
"""

from __future__ import annotations

from urllib.parse import unquote, urlparse

from ._util import b64decode_str, coerce_int, parse_qsd, safe_json_loads, split_fragment
from .base import ParsedLink, ParseError

_DEFAULT_NETWORK = "tcp"


def _build_transport(net: str, ws_path: str, ws_host: str, grpc_service: str, h2_path: str, h2_host: str) -> dict | None:
    net = (net or "tcp").lower()
    if net in ("tcp", ""):
        return None
    if net == "ws":
        t: dict = {"type": "ws"}
        if ws_path:
            t["path"] = ws_path
        if ws_host:
            t["headers"] = {"Host": ws_host}
        return t
    if net == "grpc":
        return {"type": "grpc", "service_name": grpc_service or ""}
    if net in ("h2", "http"):
        t = {"type": "http"}
        if h2_path:
            t["path"] = h2_path
        if h2_host:
            t["host"] = [h2_host]
        return t
    if net == "quic":
        return {"type": "quic"}
    if net == "httpupgrade":
        t = {"type": "httpupgrade"}
        if ws_path:
            t["path"] = ws_path
        if ws_host:
            t["host"] = ws_host
        return t
    # Unknown — leave it to sing-box to reject.
    return {"type": net}


def parse_vmess(url: str) -> ParsedLink:
    if not url.startswith("vmess://"):
        raise ParseError("not a vmess:// URL")
    body = url[len("vmess://") :]

    # Try JSON form first.
    try:
        decoded = b64decode_str(body.split("#", 1)[0])
        if decoded.lstrip().startswith("{"):
            data = safe_json_loads(decoded)
            return _from_json(data, url)
    except (ValueError, Exception):
        pass

    # URI form fallback: vmess://uuid@host:port?network=ws&...#remark
    url_no_frag, remark = split_fragment(url)
    parsed = urlparse(url_no_frag)
    uuid = parsed.username or ""
    host = parsed.hostname or ""
    port = parsed.port or 0
    if not (uuid and host and port):
        raise ParseError("vmess URL invalid: missing uuid/host/port")
    q = parse_qsd(parsed.query)
    net = q.get("type") or q.get("network") or _DEFAULT_NETWORK
    transport = _build_transport(
        net=net,
        ws_path=q.get("path", ""),
        ws_host=q.get("host", ""),
        grpc_service=q.get("serviceName", ""),
        h2_path=q.get("path", ""),
        h2_host=q.get("host", ""),
    )
    tls_on = q.get("security", "").lower() in ("tls", "reality") or q.get("tls", "").lower() in ("tls", "1")
    sni = q.get("sni") or q.get("host") or host

    outbound: dict = {
        "type": "vmess",
        "tag": "proxy",
        "server": host,
        "server_port": port,
        "uuid": uuid,
        "security": q.get("scy", "auto"),
        "alter_id": coerce_int(q.get("aid"), 0) or 0,
    }
    if transport:
        outbound["transport"] = transport
    if tls_on:
        outbound["tls"] = {"enabled": True, "server_name": sni, "insecure": False}
    return ParsedLink(
        protocol="vmess",
        remark=unquote(remark),
        raw=url,
        server=host,
        port=port,
        outbound=outbound,
        meta={"network": net, "tls": tls_on},
    )


def _from_json(d: dict, raw: str) -> ParsedLink:
    host = str(d.get("add", "")).strip()
    port = coerce_int(d.get("port"), 0) or 0
    uuid = str(d.get("id", "")).strip()
    if not (host and port and uuid):
        raise ParseError("vmess JSON missing add/port/id")
    net = str(d.get("net", "tcp")).lower()
    ws_path = str(d.get("path", ""))
    ws_host = str(d.get("host", ""))
    grpc_service = str(d.get("path", "")) if net == "grpc" else ""
    transport = _build_transport(net, ws_path, ws_host, grpc_service, ws_path, ws_host)
    tls_on = str(d.get("tls", "")).lower() in ("tls", "1", "true")
    sni = str(d.get("sni") or d.get("host") or host)
    aid = coerce_int(d.get("aid"), 0) or 0

    outbound: dict = {
        "type": "vmess",
        "tag": "proxy",
        "server": host,
        "server_port": port,
        "uuid": uuid,
        "security": str(d.get("scy", "auto") or "auto"),
        "alter_id": aid,
    }
    if transport:
        outbound["transport"] = transport
    if tls_on:
        outbound["tls"] = {
            "enabled": True,
            "server_name": sni,
            "insecure": bool(d.get("allowInsecure")) or bool(d.get("skip-cert-verify")),
        }
    return ParsedLink(
        protocol="vmess",
        remark=str(d.get("ps") or d.get("remarks") or ""),
        raw=raw,
        server=host,
        port=port,
        outbound=outbound,
        meta={"network": net, "tls": tls_on, "alter_id": aid},
    )
