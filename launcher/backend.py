"""Engine + LAN server on a background asyncio thread, driven by the Qt window.

The window never touches aiohttp or the engine directly: it calls start/restart/stop
and reads snapshot(), which is safe from any thread.
"""

import asyncio
import collections
import logging
import threading
import time
from pathlib import Path

from engine import create_engine
from mapstore import MapStore
from mapstore.markers import MarkerStore
from server import sites
from server.app import create_app
from server.netinfo import MDNS_NAME, bind_hosts

log = logging.getLogger("cdlivemap.launcher")

LOOPBACK = "127.0.0.1"


class Backend:
    def __init__(self, data_dir, simulate=False, hosts=None):
        self.data_dir = Path(data_dir)
        self.maps = MapStore(self.data_dir / "maps")
        self.markers = MarkerStore(self.data_dir / "markers")
        self.simulate = simulate
        self._fixed_hosts = hosts
        self.config = None
        self.app = None
        self.engine = None
        self.hosts = []
        self.error = ""
        self._sites = None
        self._updates = collections.deque(maxlen=256)
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="cdlm-backend", daemon=True)
        self._thread.start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _submit(self, coro, timeout=30):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    # ── control (any thread) ───────────────────────────────────────

    def start(self, config):
        self._submit(self._start(config))

    def restart(self, config):
        self._submit(self._stop())
        self._submit(self._start(config))

    def stop(self):
        try:
            self._submit(self._stop())
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self._thread.join(5)

    def call(self, fn, *args):
        """Run fn(*args) on the server loop (the stores and hub live there) and return its result."""
        async def run():
            return fn(*args)
        return self._submit(run())

    # ── on the loop ────────────────────────────────────────────────

    async def _start(self, config):
        self.config, self.error = config, ""
        self.hosts = list(self._fixed_hosts or bind_hosts())
        self.engine = create_engine(simulate=self.simulate, rate_hz=config.rate_hz)
        self.engine.subscribe(self._on_state)
        app = create_app(config, self.engine, self.data_dir, simulated=self.simulate)
        try:
            self._sites = await sites.start(app, config, self.hosts)
        except OSError as e:
            self.error = e.strerror or str(e)
            log.error("%s", self.error)
            return
        self.app = app
        log.info("Server running on %s%s (engine: %s)", ", ".join(f"{h}:{config.port}" for h in self.hosts),
                 f", HTTPS on port {config.https_port}" if config.https else "", "simulator" if self.simulate else "memory")

    async def _stop(self):
        self.app = None
        if self._sites:
            await self._sites.stop()
            self._sites = None

    def _on_state(self, state):   # engine thread
        if state.x is not None:
            self._updates.append(time.monotonic())

    # ── read (any thread) ──────────────────────────────────────────

    def urls(self, secure=False):
        """Addresses for other devices; secure=True gives the HTTPS ones (empty when HTTPS is off)."""
        c = self.config
        if not c or (secure and not c.https):
            return []
        scheme, port = ("https", c.https_port) if secure else ("http", c.port)
        return [f"{scheme}://{h}:{port}/" for h in self.hosts if h != LOOPBACK]

    def name_url(self, secure=False):
        """The address by mDNS name, if the name is announced."""
        c = self.config
        if not c or not c.mdns or (secure and not c.https) or not self.app:
            return ""
        return f"https://{MDNS_NAME}:{c.https_port}/" if secure else f"http://{MDNS_NAME}:{c.port}/"

    def setup_url(self, host):
        """The device setup page for HTTPS, on the plain address (works before the certificate is trusted)."""
        return f"http://{host}:{self.config.port}/cdlm/setup" if self.config else ""

    def local_url(self):
        return f"http://{LOOPBACK}:{self.config.port}/" if self.config else ""

    def snapshot(self):
        app, engine = self.app, self.engine
        now = time.monotonic()
        recent = sum(1 for t in list(self._updates) if now - t <= 2.0)
        return {
            "running": app is not None,
            "error": self.error,
            "port": self.config.port if self.config else None,
            "https_port": self.config.https_port if self.config and self.config.https else None,
            "mdns": bool(self.config and self.config.mdns),
            "urls": self.urls(),
            "clients": app["hub"].client_count if app else 0,
            "engine": engine.state if engine else None,
            "diagnostics": dict(getattr(engine, "diagnostics", None) or {}),
            "rate": recent / 2.0,
            "simulated": self.simulate,
        }

    # ── maps ───────────────────────────────────────────────────────
    # The store only reads and writes files, so the window may use self.maps from any
    # thread; connected devices hear about changes through notify_maps().

    def notify_maps(self, map_id, action):
        if self.app:
            self.call(self.app["hub"].broadcast, {"type": "map_changed", "id": map_id, "action": action})

    def notify_markers(self):
        if self.app:
            self.call(self.app["hub"].broadcast, {"type": "markers_changed"})
