"""Parser for ``ss://`` (Shadowsocks) connection URLs.

Two forms exist in the wild:

* SIP002:  ``ss://method:password@host:port?plugin=...#tag``
  where ``method:password`` may be base64-encoded.
* Legacy:  ``ss://BASE64(method:password@host:port)#tag``
"""

from __future__ import annotations

from urllib.parse import unquote, urlparse

from ._util import b64decode_str, parse_qsd, split_fragment, split_userinfo
from .base import ParsedLink, ParseError


def parse_ss(url: str) -> ParsedLink:
    if not url.startswith("ss://"):
        raise ParseError("not a ss:// URL")
    url_no_frag, remark = split_fragment(url)
    body = url_no_frag[len("ss://") :]

    # SIP002 form has an '@'; the legacy form does not (it's one big base64 blob).
    if "@" not in body:
        try:
            decoded = b64decode_str(body.split("/", 1)[0].split("?", 1)[0])
        except Exception as exc:
            raise ParseError(f"failed to base64-decode legacy ss URL: {exc!s}") from exc
        # decoded looks like "method:password@host:port"
        if "@" not in decoded:
            raise ParseError("malformed legacy ss URL (no @ after decode)")
        userinfo, host_port = decoded.rsplit("@", 1)
        plugin = ""
        plugin_opts = ""
    else:
        # SIP002 — userinfo may itself be base64.
        parsed = urlparse(url_no_frag)
        userinfo_raw = parsed.username or ""
        # If urlparse split the userinfo on ":" we recombine it; plain
        # ``method:password`` is a legitimate userinfo per SIP002.
        if parsed.password is not None:
            userinfo_raw = f"{parsed.username}:{parsed.password}"
        # Some clients use base64(userinfo); others use plain method:password.
        if ":" not in userinfo_raw:
            try:
                decoded_user = b64decode_str(unquote(userinfo_raw))
                if ":" in decoded_user:
                    userinfo_raw = decoded_user
            except Exception:
                pass
        host = parsed.hostname or ""
        port = parsed.port or 0
        userinfo = userinfo_raw
        host_port = f"{host}:{port}"
        query = parse_qsd(parsed.query)
        plugin_spec = query.get("plugin", "")
        if ";" in plugin_spec:
            plugin, plugin_opts = plugin_spec.split(";", 1)
        else:
            plugin, plugin_opts = plugin_spec, ""

    method, password = split_userinfo(userinfo)
    if not password:
        raise ParseError("ss URL missing password")
    if ":" not in host_port:
        raise ParseError("ss URL missing port")
    host, port_s = host_port.rsplit(":", 1)
    try:
        port = int(port_s)
    except ValueError as exc:
        raise ParseError(f"ss URL invalid port: {port_s!r}") from exc

    outbound: dict = {
        "type": "shadowsocks",
        "tag": "proxy",
        "server": host,
        "server_port": port,
        "method": method,
        "password": password,
    }
    meta: dict = {"method": method}
    if "plugin" in locals() and plugin:
        # sing-box plugin field expects a name, plugin_opts is a string.
        outbound["plugin"] = plugin
        if plugin_opts:
            outbound["plugin_opts"] = plugin_opts
        meta["plugin"] = plugin

    return ParsedLink(
        protocol="shadowsocks",
        remark=remark,
        raw=url,
        server=host,
        port=port,
        outbound=outbound,
        meta=meta,
    )
