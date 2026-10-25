"""Run the LAN server.

  python -m server --simulate        no game needed (engine/simulator.py)
  python -m server                   live engine (run as administrator)
Options override %LOCALAPPDATA%\\CompanionMap\\config.json for this run only.
"""

import argparse
import asyncio
import logging
import sys

from engine import create_engine
from server import sites
from server.app import create_app
from server.config import Config, data_dir
from server.logs import setup_logging
from server.netinfo import bind_hosts, lan_urls

log = logging.getLogger("cdlivemap.server")


async def serve(config, simulate, hosts, root, pin=""):
    engine = create_engine(simulate=simulate, rate_hz=config.rate_hz)
    app = create_app(config, engine, root, simulated=simulate, pin=pin)
    running = await sites.start(app, config, hosts)
    log.info("Serving on %s (engine: %s)", ", ".join(f"{h}:{config.port}" for h in hosts),
             "simulator" if simulate else "memory")
    for url in lan_urls(config.port) + (lan_urls(config.https_port, "https") if config.https else []):
        log.info("Open on your tablet or phone: %s", url)
    try:
        await asyncio.Event().wait()
    finally:
        await running.stop()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m server")
    ap.add_argument("--simulate", action="store_true", help="use the path simulator instead of the game")
    ap.add_argument("--port", type=int)
    ap.add_argument("--pin", help="require this PIN (?k=PIN) from devices; not available in the Windows app")
    ap.add_argument("--https", action="store_true", help="also serve HTTPS (port from config, default 8789)")
    ap.add_argument("--host", action="append", help="bind address (repeatable); default: loopback + LAN")
    args = ap.parse_args(argv)

    root = data_dir()
    setup_logging(root, logging.StreamHandler(sys.stdout))
    config = Config.load(root / "config.json")
    if args.port:
        config.port = args.port
    if args.pin and not (args.pin.isdigit() and 4 <= len(args.pin) <= 12):
        ap.error("--pin must be 4-12 digits")
    if args.https:
        config.https = True
    config.validate()
    try:
        asyncio.run(serve(config, args.simulate, args.host or bind_hosts(), root, pin=args.pin or ""))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
