"""Helpers shared between parsers."""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


def b64decode_padded(data: str) -> bytes:
    """Decode a base64 string that may be missing padding or use URL-safe alphabet."""
    if not data:
        return b""
    data = data.strip().replace("-", "+").replace("_", "/")
    padding = (-len(data)) % 4
    data += "=" * padding
    try:
        return base64.b64decode(data, validate=False)
    except (binascii.Error, ValueError) as exc:  # pragma: no cover - exotic input
        raise ValueError(f"invalid base64: {exc!s}") from exc


def b64decode_str(data: str) -> str:
    return b64decode_padded(data).decode("utf-8", errors="replace")


def split_fragment(url: str) -> tuple[str, str]:
    """Return ``(url_without_fragment, decoded_remark)``."""
    if "#" not in url:
        return url, ""
    base, frag = url.split("#", 1)
    return base, unquote(frag)


def parse_qsd(query: str) -> dict[str, str]:
    """Parse a query string into a flat dict (first value wins)."""
    out: dict[str, str] = {}
    for key, values in parse_qs(query, keep_blank_values=True).items():
        if values:
            out[key] = values[0]
    return out


def split_userinfo(userinfo: str) -> tuple[str, str | None]:
    if ":" in userinfo:
        user, password = userinfo.split(":", 1)
        return unquote(user), unquote(password)
    return unquote(userinfo), None


def url_components(url: str) -> tuple[str, str, dict[str, str], str]:
    """Split ``scheme://userinfo@host:port/?query#frag`` returning
    ``(userinfo, netloc, query_dict, remark)``."""
    url_no_frag, remark = split_fragment(url)
    parsed = urlparse(url_no_frag)
    userinfo = parsed.username or ""
    if parsed.password is not None:
        userinfo = f"{parsed.username}:{parsed.password}"
    host = parsed.hostname or ""
    port = parsed.port or 0
    netloc = f"{host}:{port}"
    return userinfo, netloc, parse_qsd(parsed.query), remark


def safe_json_loads(data: str | bytes) -> Any:
    try:
        return json.loads(data)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON payload: {exc!s}") from exc


def coerce_int(value: Any, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    return default
