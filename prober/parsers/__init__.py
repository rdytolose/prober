"""Public parser surface.  See ``registry.parse`` for the entry point."""

from .base import ParsedLink, ParseError
from .registry import SUPPORTED_PREFIXES, parse

__all__ = ["parse", "ParsedLink", "ParseError", "SUPPORTED_PREFIXES"]
