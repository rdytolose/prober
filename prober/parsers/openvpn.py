"""Parser for our custom ``openvpn://`` scheme.

Native OpenVPN does not have a URL representation, so we define a simple one
to fit the rest of the system:

* ``openvpn://BASE64(.ovpn file contents)#remark``  — inline config.
* ``openvpn://url=https%3A%2F%2Fexample.com%2Fclient.ovpn#remark`` — fetched
  by the engine at runtime.

The parser stores the raw config (or the URL to fetch it from) in the
outbound dict; the OpenVPN engine handles bringing it up.
"""

from __future__ import annotations

from urllib.parse import unquote, urlparse

from ._util import b64decode_str, parse_qsd, split_fragment
from .base import ParsedLink, ParseError


def parse_openvpn(url: str) -> ParsedLink:
    if not url.startswith("openvpn://"):
        raise ParseError("not an openvpn URL")
    url_no_frag, remark = split_fragment(url)
    body = url_no_frag[len("openvpn://") :]
    parsed = urlparse(url_no_frag)
    q = parse_qsd(parsed.query)

    config_text: str | None = None
    config_url: str | None = None

    if q.get("url"):
        config_url = unquote(q["url"])
    else:
        # Treat the whole authority+path as base64 of the .ovpn config.
        try:
            config_text = b64decode_str(body.split("?", 1)[0])
        except Exception as exc:
            raise ParseError(f"openvpn URL base64 decode failed: {exc!s}") from exc

    server = ""
    port = 0
    if config_text:
        for line in config_text.splitlines():
            line = line.strip()
            if line.lower().startswith("remote "):
                parts = line.split()
                if len(parts) >= 2:
                    server = parts[1]
                if len(parts) >= 3:
                    try:
                        port = int(parts[2])
                    except ValueError:
                        port = 0
                break

    outbound = {
        "type": "openvpn",
        "tag": "proxy",
        "config_text": config_text,
        "config_url": config_url,
    }
    return ParsedLink(
        protocol="openvpn",
        remark=unquote(remark),
        raw=url,
        server=server,
        port=port,
        outbound=outbound,
        meta={"has_inline_config": config_text is not None},
    )
