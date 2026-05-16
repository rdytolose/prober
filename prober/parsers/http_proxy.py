"""Parser for HTTP/HTTPS proxy URLs (``http://``, ``https://``, ``httpproxy://``).

To disambiguate from regular HTTP target URLs we only treat a URL as a proxy
URL if the scheme is ``httpproxy`` / ``httpsproxy``, OR if the path is empty
and credentials or a port are present.  This is enforced by the registry,
not here.
"""

from __future__ import annotations

from urllib.parse import urlparse

from ._util import split_fragment, split_userinfo
from .base import ParsedLink, ParseError


def parse_http_proxy(url: str) -> ParsedLink:
    url_no_frag, remark = split_fragment(url)
    parsed = urlparse(url_no_frag)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https", "httpproxy", "httpsproxy"):
        raise ParseError("not an http proxy URL")
    host = parsed.hostname or ""
    port = parsed.port or (443 if scheme.startswith("https") else 80)
    if not host:
        raise ParseError("http proxy URL missing host")

    tls_on = scheme in ("https", "httpsproxy")
    outbound: dict = {
        "type": "http",
        "tag": "proxy",
        "server": host,
        "server_port": port,
    }
    if parsed.username is not None:
        userinfo = parsed.username
        if parsed.password is not None:
            userinfo = f"{parsed.username}:{parsed.password}"
        user, pwd = split_userinfo(userinfo)
        if user:
            outbound["username"] = user
        if pwd:
            outbound["password"] = pwd
    if tls_on:
        outbound["tls"] = {"enabled": True, "server_name": host}

    return ParsedLink(
        protocol="https" if tls_on else "http",
        remark=remark,
        raw=url,
        server=host,
        port=port,
        outbound=outbound,
        meta={"tls": tls_on},
    )
