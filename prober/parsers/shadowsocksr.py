"""Parser for ``ssr://`` (ShadowsocksR) connection URLs.

Form:  ``ssr://BASE64( host:port:protocol:method:obfs:BASE64(password)/?params )``

Note: sing-box does NOT natively support SSR (it's a separate protocol from
Shadowsocks).  We still parse it so the dashboard can show it and so users
get a clear "unsupported protocol" error rather than a parser crash.  When
``shadowsocksr-libev`` (``ssr-local``) is available on the host it can be
launched by the SSR engine — see ``engines/ssr.py``.
"""

from __future__ import annotations

from urllib.parse import unquote

from ._util import b64decode_str, parse_qsd
from .base import ParsedLink, ParseError


def parse_ssr(url: str) -> ParsedLink:
    if not url.startswith("ssr://"):
        raise ParseError("not a ssr:// URL")
    body = url[len("ssr://") :]
    try:
        decoded = b64decode_str(body)
    except Exception as exc:
        raise ParseError(f"failed to base64-decode ssr URL: {exc!s}") from exc

    # decoded looks like:
    #   host:port:protocol:method:obfs:base64(password)/?obfsparam=...&protoparam=...&remarks=...&group=...
    if "/?" in decoded:
        main, query = decoded.split("/?", 1)
    else:
        main, query = decoded, ""
    parts = main.split(":")
    if len(parts) < 6:
        raise ParseError(f"ssr URL has {len(parts)} parts, expected 6")
    host, port_s, proto, method, obfs, pwd_b64 = parts[:6]
    try:
        port = int(port_s)
    except ValueError as exc:
        raise ParseError(f"ssr invalid port: {port_s!r}") from exc
    try:
        password = b64decode_str(pwd_b64)
    except Exception as exc:
        raise ParseError(f"ssr password base64 invalid: {exc!s}") from exc

    qs = parse_qsd(query)
    remark = ""
    if "remarks" in qs:
        try:
            remark = b64decode_str(qs["remarks"])
        except Exception:
            remark = unquote(qs["remarks"])
    obfs_param = ""
    if "obfsparam" in qs:
        try:
            obfs_param = b64decode_str(qs["obfsparam"])
        except Exception:
            obfs_param = qs["obfsparam"]
    proto_param = ""
    if "protoparam" in qs:
        try:
            proto_param = b64decode_str(qs["protoparam"])
        except Exception:
            proto_param = qs["protoparam"]

    outbound: dict = {
        # custom marker: the SSR engine knows how to start ssr-local with these.
        "type": "shadowsocksr",
        "tag": "proxy",
        "server": host,
        "server_port": port,
        "method": method,
        "password": password,
        "protocol": proto,
        "protocol_param": proto_param,
        "obfs": obfs,
        "obfs_param": obfs_param,
    }
    return ParsedLink(
        protocol="shadowsocksr",
        remark=remark,
        raw=url,
        server=host,
        port=port,
        outbound=outbound,
        meta={"method": method, "obfs": obfs, "protocol": proto},
    )
