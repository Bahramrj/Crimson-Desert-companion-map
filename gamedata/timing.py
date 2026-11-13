"""Seconds per import phase in the log, so a slow import shows where the time goes."""

import logging
import time
from contextlib import contextmanager

log = logging.getLogger("cdlivemap.gamedata")


@contextmanager
def timed(what):
    started = time.perf_counter()
    try:
        yield
    finally:
        log.info("  %s: %.1f s", what, time.perf_counter() - started)
