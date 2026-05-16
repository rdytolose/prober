"""Dispatch table: connection URL string → ParsedLink.

To add a protocol:
1. Write a ``parse_<name>`` function returning ``ParsedLink``.
2. Register the URL prefix(es) below.
"""

from __future__ import annotations

from collections.abc import Callable

from .anytls import parse_anytls
from .base import ParsedLink, ParseError
from .http_proxy import parse_http_proxy
from .hysteria import parse_hysteria
from .hysteria2 import parse_hysteria2
from .naive import parse_naive
from .openvpn import parse_openvpn
from .shadowsocks import parse_ss
from .shadowsocksr import parse_ssr
from .socks import parse_socks
from .trojan import parse_trojan
from .tuic import parse_tuic
from .vless import parse_vless
from .vmess import parse_vmess
from .wireguard import parse_wireguard

# Order matters: most specific prefix first.
_PARSERS: list[tuple[tuple[str, ...], Callable[[str], ParsedLink]]] = [
    (("ss://",), parse_ss),
    (("ssr://",), parse_ssr),
    (("vmess://",), parse_vmess),
    (("vless://",), parse_vless),
    (("trojan://", "trojan-go://"), parse_trojan),
    (("hysteria2://", "hy2://"), parse_hysteria2),
    (("hysteria://",), parse_hysteria),
    (("tuic://",), parse_tuic),
    (("socks5://", "socks5h://", "socks4://", "socks4a://", "socks://"), parse_socks),
    (("naive+https://",), parse_naive),
    (("httpproxy://", "httpsproxy://"), parse_http_proxy),
    (("wireguard://", "wg://"), parse_wireguard),
    (("anytls://",), parse_anytls),
    (("openvpn://",), parse_openvpn),
]


SUPPORTED_PREFIXES: tuple[str, ...] = tuple(p for prefixes, _ in _PARSERS for p in prefixes)


def parse(url: str) -> ParsedLink:
    """Return a ``ParsedLink`` for ``url`` or raise ``ParseError``."""
    if not isinstance(url, str):
        raise ParseError("URL must be a string")
    url = url.strip()
    if not url:
        raise ParseError("empty URL")
    for prefixes, fn in _PARSERS:
        if any(url.startswith(p) for p in prefixes):
            return fn(url)
    raise ParseError(f"unsupported protocol: {url[:32]!r}; supported prefixes: {SUPPORTED_PREFIXES}")


__all__ = ["parse", "ParsedLink", "ParseError", "SUPPORTED_PREFIXES"]
