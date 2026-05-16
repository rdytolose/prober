"""Entry point: ``python -m prober`` or ``vpn-prober``."""

from __future__ import annotations

import logging

import uvicorn

from .app import create_app
from .config import load_settings


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = load_settings()
    app = create_app(settings)
    uvicorn.run(
        app,
        host=settings.prober_host,
        port=settings.prober_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
