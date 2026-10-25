"""Logging to <data>/logs/server.log (rotating) plus any extra handlers (console, launcher Log tab)."""

import logging
import logging.handlers

FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def setup_logging(root, *extra_handlers):
    (root / "logs").mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(FORMAT)
    handlers = [logging.handlers.RotatingFileHandler(root / "logs" / "server.log", maxBytes=2_000_000,
                                                     backupCount=3, encoding="utf-8"), *extra_handlers]
    for h in handlers:
        h.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    logging.getLogger("pymem").setLevel(logging.WARNING)
