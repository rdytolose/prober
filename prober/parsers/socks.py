"""Parser for ``socks://``, ``socks4://``, ``socks5://``, ``socks5h://`` URLs."""

from __future__ import annotations

from urllib.parse import urlparse

from ._util import split_fragment, split_userinfo
from .base import ParsedLink, ParseError

_SCHEMES = ("socks://", "socks4://", "socks4a://", "socks5://", "socks5h://")


def parse_socks(url: str) -> ParsedLink:
    if not any(url.startswith(s) for s in _SCHEMES):
        raise ParseError("not a socks URL")
    url_no_frag, remark = split_fragment(url)
    parsed = urlparse(url_no_frag)
    host = parsed.hostname or ""
    port = parsed.port or 0
    if not (host and port):
        raise ParseError("socks URL missing host/port")
    version = "5"
    scheme = parsed.scheme.lower()
    if scheme in ("socks4", "socks4a"):
        version = "4"
    elif scheme == "socks":
        version = "5"

    outbound: dict = {
        "type": "socks",
        "tag": "proxy",
        "server": host,
        "server_port": port,
        "version": version,
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
    return ParsedLink(
        protocol=f"socks{version}",
        remark=remark,
        raw=url,
        server=host,
        port=port,
        outbound=outbound,
        meta={"version": version},
    )
