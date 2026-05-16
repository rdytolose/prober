"""Parser for ``naive+https://`` URLs (NaiveProxy).

NaiveProxy uses TLS-tunnelled HTTP/2 and is exposed by sing-box as the
``naive`` outbound.  Common URL form:

    naive+https://user:pass@host:port?padding=true#remark
"""

from __future__ import annotations

from urllib.parse import unquote, urlparse

from ._util import coerce_bool, parse_qsd, split_fragment, split_userinfo
from .base import ParsedLink, ParseError


def parse_naive(url: str) -> ParsedLink:
    if not url.startswith("naive+https://"):
        raise ParseError("not a naive+https URL")
    inner = url[len("naive+") :]
    url_no_frag, remark = split_fragment(inner)
    parsed = urlparse(url_no_frag)
    host = parsed.hostname or ""
    port = parsed.port or 443
    userinfo = parsed.username or ""
    if parsed.password is not None:
        userinfo = f"{parsed.username}:{parsed.password}"
    user, password = split_userinfo(userinfo)
    if not (host and user and password):
        raise ParseError("naive URL missing host/credentials")
    q = parse_qsd(parsed.query)
    outbound: dict = {
        "type": "naive",
        "tag": "proxy",
        "server": host,
        "server_port": port,
        "username": user,
        "password": password,
        "network": "tcp",
        "tls": {
            "enabled": True,
            "server_name": q.get("sni") or host,
            "insecure": coerce_bool(q.get("insecure"), False),
        },
    }
    return ParsedLink(
        protocol="naive",
        remark=unquote(remark),
        raw=url,
        server=host,
        port=port,
        outbound=outbound,
        meta={},
    )
