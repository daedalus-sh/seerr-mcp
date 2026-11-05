"""seerr-mcp: run the server."""

from __future__ import annotations

import logging
import sys

import uvicorn

from . import config
from .client import Seerr
from .server import build_app
from .service import Requests


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    # One line per tool call is ours; the libraries' per-request lines (with
    # URLs and search terms) stay out of the log.
    for noisy in ("httpx", "httpcore", "mcp"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    try:
        settings = config.load()
    except config.ConfigError as exc:
        print(f"seerr-mcp: {exc}", file=sys.stderr)
        sys.exit(2)
    seerr = Seerr(settings)
    logging.getLogger("seerr_mcp").info("Seerr at %s; streaming region %s", settings.url, settings.watch_region or "none")
    app = build_app(settings.token, seerr, Requests(seerr, watch_region=settings.watch_region))
    uvicorn.run(app, host=settings.listen_host, port=settings.listen_port, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
