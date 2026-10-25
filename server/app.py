"""aiohttp application: one port for the device shell (tablet, phone, browser), our API and the local map tiles.

    /                                         device shell (web/dist/index.html; assets under /cdlm/app/)
    /cdlm/ws                                  WebSocket: status, position, profile_changed, map_changed
    /cdlm/api/status                          engine + server status
    /cdlm/api/profiles                        layout profiles CRUD
    /cdlm/api/maps                            installed maps + the active map per realm
    /cdlm/api/maps/<id>/calibration           tap calibration of a map image
    /cdlm/api/markers                         marker sets and their markers (game x/z)
    /cdlm/api/markers/mine                    the user's own markers ("add marker here")
    /cdlm/api/progress                        found markers, shared by every device
    /cdlm/maps/<id>/<rev>/<z>/<x>/<y>.webp    map tiles (immutable; rev changes on re-import)
    /cdlm/setup                               how to set up HTTPS on a device (server/tls.py)
    /cdlm/ca.mobileconfig, /cdlm/ca.crt       the local CA certificate (iOS profile / DER)
Nothing else is served, and the app makes no request to the internet.
"""

import asyncio
import hmac
import html
import json
import logging
from pathlib import Path

from aiohttp import web

from mapstore import MapError, MapStore
from mapstore import NotFound as MapNotFound
from mapstore.markers import MarkerStore
from server import APP_NAME, __version__
from server.netinfo import MDNS_NAME, lan_urls
from server.profiles import NotFound, ProfileError, ProfileStore
from server.tls import LocalCA
from server.ws import Hub

log = logging.getLogger("cdlivemap.server")

ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
PROTECTED_PREFIXES = ("/cdlm/api/", "/cdlm/ws", "/cdlm/maps/")
TILE_CACHE = "public, max-age=31536000, immutable"
# Same origin only: the shell must work with the internet unplugged.
SHELL_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
             "img-src 'self' data: blob:; connect-src 'self' ws: wss:; worker-src 'self' blob:; "
             "object-src 'none'; base-uri 'none'; frame-ancestors 'none'")

FALLBACK_SHELL = """<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Companion Map</title>
<body style="font:16px system-ui;margin:2rem;background:#111;color:#eee">
<h1>Offline Companion Map for Crimson Desert is running</h1>
<p>The map page is not built (run <code>scripts\\web.ps1 run build</code>).</p>
<p><a style="color:#7cf" href="/cdlm/api/status">Status JSON</a> ·
<a style="color:#7cf" href="/cdlm/api/maps">Installed maps</a></p>
</body>"""


def pin_middleware(pin, prefixes=PROTECTED_PREFIXES):
    @web.middleware
    async def check(request, handler):
        if pin and request.path.startswith(prefixes):
            given = request.query.get("k") or request.headers.get("X-CDLM-Key") or ""
            if not hmac.compare_digest(given.encode(), pin.encode()):
                return web.json_response({"error": "PIN required"}, status=401)
        return await handler(request)
    return check


SETUP_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'"
SETUP_PAGE = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Secure connection · {app}</title>
<style>
body {{ font: 16px/1.5 -apple-system, system-ui, sans-serif; margin: 0; padding: 24px; max-width: 640px;
  background: #0a0c10; color: #f3f5f8; }}
h1 {{ font-size: 24px; margin: 0 0 4px; }} h2 {{ font-size: 17px; margin: 28px 0 8px; }}
p, li {{ color: #c6ccd6; }} .muted {{ color: #8e96a3; font-size: 14px; }}
a.btn {{ display: inline-block; margin: 6px 8px 6px 0; padding: 12px 18px; border-radius: 12px; background: #4c8dff;
  color: #fff; text-decoration: none; font-weight: 600; }}
a.btn.alt {{ background: rgba(255,255,255,.1); }} code {{ word-break: break-all; font-size: 13px; }}
.off {{ padding: 14px 16px; border-radius: 12px; background: rgba(251,191,36,.12); color: #fbbf24; }}
</style>
<h1>Secure connection (HTTPS)</h1>
<p class="muted">{app} runs on your PC. HTTPS is optional: it lets the device keep its screen awake
while the map is open. The plain address keeps working either way.</p>
{state}
<h2>1. Install the PC's certificate</h2>
<a class="btn" href="/cdlm/ca.mobileconfig">iPhone / iPad</a><a class="btn alt" href="/cdlm/ca.crt">Android / other</a>
<ul>
<li><b>iPhone / iPad</b>: after the download, open Settings → General → VPN &amp; Device Management, tap the profile and
Install. Then Settings → General → About → Certificate Trust Settings: turn on full trust for
“{ca}”.</li>
<li><b>Android</b>: Settings → Security → Encryption &amp; credentials → Install a certificate → CA certificate,
then pick the downloaded file.</li>
</ul>
<p class="muted">The certificate only works for local network names and addresses, not for websites.
Fingerprint (SHA-256): <code>{fp}</code></p>
<h2>2. Open the map securely</h2>
{links}
<p class="muted">You can remove the certificate at any time in the same settings.</p>
</html>"""


async def _json_body(request):
    try:
        return await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise web.HTTPBadRequest(text=json.dumps({"error": "invalid JSON"}), content_type="application/json")


def _error(status, msg):
    return web.json_response({"error": msg}, status=status)


class Api:
    def __init__(self, app):
        self.app = app

    @property
    def profiles(self):
        return self.app["profiles"]

    @property
    def maps(self):
        return self.app["maps"]

    @property
    def hub(self):
        return self.app["hub"]

    async def status(self, request):
        engine, config = self.app["engine"], self.app["config"]
        return web.json_response({
            "server": {"version": __version__, "port": config.port,
                       "urls": lan_urls(config.port), "clients": self.hub.client_count,
                       "simulated": self.app["simulated"], "pin": bool(self.app["pin"]),
                       "https": config.https_port if config.https else None},
            "engine": engine.state.to_dict(),
            "game": getattr(engine, "diagnostics", {}),
        })

    # ── profiles ─────────────────────────────────────────────────────

    def _profile_changed(self, pid, action):
        self.hub.broadcast({"type": "profile_changed", "id": pid, "action": action})

    async def list_profiles(self, request):
        return web.json_response({"profiles": self.profiles.list(), "default": self.profiles.default_id()})

    async def create_profile(self, request):
        try:
            profile = self.profiles.create(await _json_body(request))
        except ProfileError as e:
            return _error(400, str(e))
        self._profile_changed(profile["id"], "created")
        return web.json_response(profile, status=201)

    async def get_profile(self, request):
        try:
            return web.json_response(self.profiles.get(request.match_info["id"]))
        except NotFound:
            return _error(404, "profile not found")

    async def update_profile(self, request):
        pid = request.match_info["id"]
        try:
            profile = self.profiles.update(pid, await _json_body(request))
        except NotFound:
            return _error(404, "profile not found")
        except ProfileError as e:
            return _error(400, str(e))
        self._profile_changed(pid, "updated")
        return web.json_response(profile)

    async def delete_profile(self, request):
        pid = request.match_info["id"]
        try:
            self.profiles.delete(pid)
        except NotFound:
            return _error(404, "profile not found")
        self._profile_changed(pid, "deleted")
        return web.Response(status=204)

    async def set_default_profile(self, request):
        body = await _json_body(request)
        pid = body.get("id") if isinstance(body, dict) else None
        try:
            self.profiles.set_default(pid)
        except NotFound:
            return _error(404, "profile not found")
        self._profile_changed(pid, "default")
        return web.json_response({"default": pid})

    # ── maps ─────────────────────────────────────────────────────────

    def _map_changed(self, map_id, action):
        self.hub.broadcast({"type": "map_changed", "id": map_id, "action": action})

    async def list_maps(self, request):
        return web.json_response(self.maps.listing())

    async def set_active_map(self, request):
        body = await _json_body(request)
        if not isinstance(body, dict):
            return _error(400, "expected an object")
        try:
            self.maps.set_active(body.get("realm"), body.get("id"))
        except MapNotFound:
            return _error(404, "map not found")
        except MapError as e:
            return _error(400, str(e))
        self._map_changed(body.get("id"), "active")
        return web.json_response(self.maps.active())

    async def add_map_point(self, request):
        map_id = request.match_info["id"]
        body = await _json_body(request)
        if not isinstance(body, dict):
            return _error(400, "expected an object")
        try:
            summary = self.maps.add_point(map_id, body.get("game"), body.get("px"))
        except MapNotFound:
            return _error(404, "map not found")
        except MapError as e:
            return _error(400, str(e))
        self._map_changed(map_id, "calibration")
        return web.json_response(summary, status=201)

    async def delete_map_point(self, request):
        map_id = request.match_info["id"]
        try:
            summary = self.maps.delete_point(map_id, int(request.match_info["index"]))
        except (MapNotFound, ValueError):
            return _error(404, "point not found")
        self._map_changed(map_id, "calibration")
        return web.json_response(summary)

    async def reset_map_calibration(self, request):
        map_id = request.match_info["id"]
        try:
            summary = self.maps.reset_calibration(map_id)
        except MapNotFound:
            return _error(404, "map not found")
        self._map_changed(map_id, "calibration")
        return web.json_response(summary)

    async def list_markers(self, request):
        resp = web.json_response(self.app["markers"].listing())
        resp.enable_compression()                    # a few thousand markers: ~10x smaller gzipped
        return resp

    async def add_my_marker(self, request):
        body = await _json_body(request)
        if not isinstance(body, dict):
            return _error(400, "expected an object")
        try:
            marker = self.app["markers"].add_mine(body.get("name"), body.get("realm"), body.get("x"), body.get("z"),
                                                  body.get("notes", ""))
        except MapError as e:
            return _error(400, str(e))
        self.hub.broadcast({"type": "markers_changed"})
        return web.json_response(marker, status=201)

    async def delete_my_marker(self, request):
        try:
            self.app["markers"].delete_mine(request.match_info["id"])
        except MapNotFound:
            return _error(404, "marker not found")
        self.hub.broadcast({"type": "markers_changed"})
        return web.Response(status=204)

    async def get_progress(self, request):
        return web.json_response({"found": self.app["markers"].found()})

    async def set_progress(self, request):
        body = await _json_body(request)
        if not isinstance(body, dict):
            return _error(400, "expected an object")
        try:
            found = self.app["markers"].set_found(body.get("key"), body.get("found"))
        except MapError as e:
            return _error(400, str(e))
        self.hub.broadcast({"type": "progress_changed", "key": body["key"], "found": found})
        return web.json_response({"key": body["key"], "found": found})

    # ── HTTPS setup (public: the CA certificate is not a secret) ─────

    async def setup_page(self, request):
        config, ca = self.app["config"], self.app["tls"]
        _, cert = await asyncio.get_running_loop().run_in_executor(None, ca.ensure_ca)
        host = request.host.rsplit(":", 1)[0] if not request.host.startswith("[") else request.host
        if config.https:
            targets = [f"https://{host}:{config.https_port}/"]
            if host != MDNS_NAME and config.mdns:
                targets.append(f"https://{MDNS_NAME}:{config.https_port}/")
            links = "".join(f'<a class="btn" href="{html.escape(u)}">{html.escape(u)}</a>' for u in targets)
            state = ""
        else:
            links = '<p class="muted">Available once HTTPS is on.</p>'
            state = ('<p class="off">HTTPS is off. Turn it on in the Windows app: Settings → '
                     '“Also serve HTTPS”.</p>')
        page = SETUP_PAGE.format(app=html.escape(APP_NAME), state=state, links=links, fp=LocalCA.fingerprint(cert),
                                 ca=html.escape(cert.subject.rfc4514_string().split(",")[-1].split("=", 1)[-1]))
        return web.Response(text=page, content_type="text/html",
                            headers={"Content-Security-Policy": SETUP_CSP, "Cache-Control": "no-store"})

    async def ca_profile(self, request):
        data = await asyncio.get_running_loop().run_in_executor(None, self.app["tls"].mobileconfig)
        return web.Response(body=data, content_type="application/x-apple-aspen-config",
                            headers={"Content-Disposition": 'attachment; filename="companionmap-ca.mobileconfig"'})

    async def ca_cert(self, request):
        data = await asyncio.get_running_loop().run_in_executor(None, self.app["tls"].ca_der)
        return web.Response(body=data, content_type="application/x-x509-ca-cert",
                            headers={"Content-Disposition": 'attachment; filename="companionmap-ca.crt"'})

    async def tile(self, request):
        m = request.match_info
        path = self.maps.tile_path(m["id"], m["rev"], m["z"], m["x"], m["y"])
        if path is None:
            return _error(404, "no such tile")
        return web.FileResponse(path, headers={"Cache-Control": TILE_CACHE, "Content-Type": "image/webp"})


def create_app(config, engine, data_dir, web_dir=WEB_DIR, simulated=False, pin=""):
    """pin: optional, only for `python -m server --pin` (the Windows app has none)."""
    data_dir, web_dir = Path(data_dir), Path(web_dir)
    app = web.Application(middlewares=[pin_middleware(pin)], client_max_size=4 * 1024 ** 2)
    app["config"] = config
    app["pin"] = pin
    app["tls"] = LocalCA(data_dir)
    app["engine"] = engine
    app["simulated"] = simulated
    app["profiles"] = ProfileStore(data_dir / "profiles")
    app["maps"] = MapStore(data_dir / "maps")
    app["markers"] = MarkerStore(data_dir / "markers")
    app["hub"] = hub = Hub(engine)
    api = Api(app)

    async def shell(request):
        index = web_dir / "dist" / "index.html"
        if index.exists():
            return web.FileResponse(index, headers={"Content-Security-Policy": SHELL_CSP, "Cache-Control": "no-cache"})
        return web.Response(text=FALLBACK_SHELL, content_type="text/html")

    r = app.router
    r.add_get("/", shell)
    dist = web_dir / "dist"
    if dist.is_dir():
        r.add_static("/cdlm/app/", dist)
    r.add_get("/cdlm/ws", hub.handle)
    r.add_get("/cdlm/api/status", api.status)
    r.add_get("/cdlm/api/profiles", api.list_profiles)
    r.add_post("/cdlm/api/profiles", api.create_profile)
    r.add_put("/cdlm/api/profiles/default", api.set_default_profile)
    r.add_get("/cdlm/api/profiles/{id}", api.get_profile)
    r.add_put("/cdlm/api/profiles/{id}", api.update_profile)
    r.add_delete("/cdlm/api/profiles/{id}", api.delete_profile)
    r.add_get("/cdlm/api/maps", api.list_maps)
    r.add_put("/cdlm/api/maps/active", api.set_active_map)
    r.add_post("/cdlm/api/maps/{id}/calibration", api.add_map_point)
    r.add_delete("/cdlm/api/maps/{id}/calibration", api.reset_map_calibration)
    r.add_delete("/cdlm/api/maps/{id}/calibration/{index}", api.delete_map_point)
    r.add_get("/cdlm/api/markers", api.list_markers)
    r.add_post("/cdlm/api/markers/mine", api.add_my_marker)
    r.add_delete("/cdlm/api/markers/mine/{id}", api.delete_my_marker)
    r.add_get("/cdlm/api/progress", api.get_progress)
    r.add_post("/cdlm/api/progress", api.set_progress)
    r.add_get(r"/cdlm/maps/{id}/{rev:[0-9a-f]{1,32}}/{z:\d{1,2}}/{x:\d{1,6}}/{y:\d{1,6}}.webp", api.tile)
    r.add_get("/cdlm/setup", api.setup_page)
    r.add_get("/cdlm/ca.mobileconfig", api.ca_profile)
    r.add_get("/cdlm/ca.crt", api.ca_cert)

    async def lifecycle(app):
        engine.start()
        await hub.start()
        yield
        await hub.stop()
        await asyncio.get_running_loop().run_in_executor(None, engine.stop)

    app.cleanup_ctx.append(lifecycle)
    app.on_shutdown.append(hub.close_clients)
    return app

