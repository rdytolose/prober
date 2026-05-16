"""Parser for ``wireguard://`` / ``wg://`` URLs.

There is no formal standard.  Common conventions used by clients like Nekoray
and Hiddify:

  wireguard://BASE64URL(private_key)@server:port?\
      publickey=BASE64URL(public_key)&\
      address=10.0.0.2/32,fd00::2/128&\
      mtu=1420&reserved=0,0,0&presharedkey=...#remark

Some links use a v2-style JSON payload; that variant isn't covered here.
"""

from __future__ import annotations

from urllib.parse import unquote, urlparse

from ._util import coerce_int, parse_qsd, split_fragment
from .base import ParsedLink, ParseError


def _split_addresses(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def parse_wireguard(url: str) -> ParsedLink:
    if not (url.startswith("wireguard://") or url.startswith("wg://")):
        raise ParseError("not a wireguard URL")
    url_no_frag, remark = split_fragment(url)
    parsed = urlparse(url_no_frag)
    priv = unquote(parsed.username or "")
    host = parsed.hostname or ""
    port = parsed.port or 0
    if not (priv and host and port):
        raise ParseError("wireguard URL missing private_key/host/port")
    q = parse_qsd(parsed.query)
    pub = unquote(q.get("publickey") or q.get("peer", ""))
    if not pub:
        raise ParseError("wireguard URL missing publickey")
    addresses = _split_addresses(unquote(q.get("address", "")))
    if not addresses:
        addresses = ["10.0.0.2/32"]
    mtu = coerce_int(q.get("mtu"), 1420) or 1420
    reserved_raw = q.get("reserved", "")
    reserved: list[int] = []
    if reserved_raw:
        for chunk in reserved_raw.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                reserved.append(int(chunk))
            except ValueError:
                pass
    psk = unquote(q.get("presharedkey", "") or q.get("psk", ""))

    outbound: dict = {
        "type": "wireguard",
        "tag": "proxy",
        "server": host,
        "server_port": port,
        "local_address": addresses,
        "private_key": priv,
        "peer_public_key": pub,
        "mtu": mtu,
    }
    if psk:
        outbound["pre_shared_key"] = psk
    if reserved:
        outbound["reserved"] = reserved
    return ParsedLink(
        protocol="wireguard",
        remark=unquote(remark),
        raw=url,
        server=host,
        port=port,
        outbound=outbound,
        meta={"mtu": mtu, "addresses": addresses},
    )
