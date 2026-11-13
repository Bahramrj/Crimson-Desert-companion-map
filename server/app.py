"""aiohttp application: one port for the device shell (tablet, phone, browser), our API and the local map tiles.

    /                                         device shell (web/dist/index.html; assets under /cdlm/app/)
    /cdlm/ws                                  WebSocket: status, position, profile_changed, map_changed
    /cdlm/api/status                          engine + server status
    /cdlm/api/profiles                        layout profiles CRUD
    /cdlm/api/maps                            installed maps + the active map per realm
    /cdlm/api/maps/<id>/calibration           tap calibration of a map image
    /cdlm/api/markers                         marker sets and their markers (game x/z)
    /cdlm/api/markers/sets/<id>               the markers of one off-by-default set, fetched when switched on
    /cdlm/api/markers/mine                    the user's own markers ("add marker here")
    /cdlm/api/progress                        found markers, shared by every device
    /cdlm/api/rules                           per category: tick when the player gets there, come back after N hours
    /cdlm/api/backup                          found ticks, rules, own markers and profiles as one file (GET), merged in (POST)
    /cdlm/maps/<id>/<rev>/<z>/<x>/<y>.webp    map tiles (immutable; rev changes on re-import)
    /cdlm/setup                               how to set up HTTPS on a device (server/tls.py)
    /cdlm/ca.mobileconfig, /cdlm/ca.crt       the local CA certificate (iOS profile / DER)
Nothing else is served, and the app makes no request to the internet.
"""

import asyncio
import gzip
import hashlib
import hmac
import html
import json
import logging
import time
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import web

from mapstore import MapError, MapStore
from mapstore import NotFound as MapNotFound
from mapstore.markers import MarkerStore
from server import APP_NAME, __version__
from server.auto import AutoFound
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


SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


@web.middleware
async def same_origin(request, handler):
    """Only our own page may change things or open the live feed. A page of another website, open in a
    browser on this network, could otherwise post to the API (the Windows app has no PIN): requests that
    name another origin are refused, and bodies must be JSON, which a cross-site form cannot send."""
    if request.path.startswith("/cdlm/"):
        origin = request.headers.get("Origin")
        cross = origin is not None and urlsplit(origin).netloc.lower() != request.host.lower()
        if cross and (request.method not in SAFE_METHODS or request.path == "/cdlm/ws"):
            log.warning("Refused a %s %s from another origin (%.100s)", request.method, request.path, origin)
            return web.json_response({"error": "cross-site request refused"}, status=403)
        if request.method in ("POST", "PUT") and request.content_type != "application/json":
            return web.json_response({"error": "expected Content-Type: application/json"}, status=415)
    return await handler(request)


def _packed(signature, build):
    """(signature, ETag, JSON, gzipped JSON) of build(); runs off the event loop."""
    raw = json.dumps(build(), separators=(",", ":")).encode("utf-8")
    etag = '"' + hashlib.sha1(repr(signature).encode("utf-8")).hexdigest()[:16] + '"'
    return signature, etag, raw, gzip.compress(raw, 6)


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
        self._packed = {}             # marker responses kept ready, see _cached

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

    async def _cached(self, request, key, signature, build):
        """A large JSON answer, built once per `signature`, kept gzipped (~10x smaller); a page that
        already has it gets "304 Not Modified"."""
        hit = self._packed.get(key)
        if hit is None or hit[0] != signature:
            hit = self._packed[key] = await asyncio.get_running_loop().run_in_executor(None, _packed, signature, build)
        _, etag, raw, packed = hit
        headers = {"ETag": etag, "Cache-Control": "no-cache", "Vary": "Accept-Encoding"}
        if etag in request.headers.get("If-None-Match", ""):
            return web.Response(status=304, headers=headers)
        if "gzip" in request.headers.get("Accept-Encoding", "").lower():
            return web.Response(body=packed, content_type="application/json", headers={**headers, "Content-Encoding": "gzip"})
        return web.Response(body=raw, content_type="application/json", headers=headers)

    async def list_markers(self, request):
        store = self.app["markers"]
        return await self._cached(request, "", store.signature(), store.listing)

    async def marker_set(self, request):
        """The markers of one set: the shell asks for the big, off-by-default sets only when needed."""
        store, set_id = self.app["markers"], request.match_info["id"]
        try:
            return await self._cached(request, set_id, store.signature(set_id), lambda: store.set_markers(set_id))
        except MapNotFound:
            return _error(404, "marker set not found")

    async def marker_icons(self, request):
        path = self.app["markers"].icons_path(request.match_info["rev"])
        if path is None:
            return _error(404, "no such icon sheet")
        return web.FileResponse(path, headers={"Cache-Control": TILE_CACHE, "Content-Type": "image/png"})

    async def add_my_marker(self, request):
        body = await _json_body(request)
        if not isinstance(body, dict):
            return _error(400, "expected an object")
        try:
            marker = self.app["markers"].add_mine(body.get("name"), body.get("realm"), body.get("x"), body.get("z"),
                                                  body.get("notes", ""), body.get("category", "mine"), body.get("color"))
        except MapError as e:
            return _error(400, str(e))
        self.hub.broadcast({"type": "markers_changed"})
        return web.json_response(marker, status=201)

    async def update_my_marker(self, request):
        try:
            marker = self.app["markers"].update_mine(request.match_info["id"], await _json_body(request))
        except MapNotFound:
            return _error(404, "marker not found")
        except MapError as e:
            return _error(400, str(e))
        self.hub.broadcast({"type": "markers_changed"})
        return web.json_response(marker)

    async def delete_my_marker(self, request):
        try:
            self.app["markers"].delete_mine(request.match_info["id"])
        except MapNotFound:
            return _error(404, "marker not found")
        self.hub.broadcast({"type": "markers_changed"})
        return web.Response(status=204)

    async def get_progress(self, request):
        store = self.app["markers"]
        return web.json_response({"found": store.found(), "until": store.until()})

    async def set_progress(self, request):
        """Tick or untick a marker. With its `category` ("<set>:<category>") a tick in a category that
        comes back (rule respawnHours) gets its end time."""
        body = await _json_body(request)
        if not isinstance(body, dict):
            return _error(400, "expected an object")
        store = self.app["markers"]
        try:
            until = store.until_for(body.get("category")) if body.get("found") is True else None
            found = store.set_found(body.get("key"), body.get("found"), until)
        except MapError as e:
            return _error(400, str(e))
        self.hub.broadcast({"type": "progress_changed", "key": body["key"], "found": found, "until": until})
        return web.json_response({"key": body["key"], "found": found, "until": until})

    async def clear_trail(self, request):
        self.hub.clear_trail()
        return web.Response(status=204)

    async def get_rules(self, request):
        return web.json_response({"categories": self.app["markers"].rules()})

    async def set_rule(self, request):
        body = await _json_body(request)
        if not isinstance(body, dict):
            return _error(400, "expected an object")
        try:
            rule = self.app["markers"].set_rule(body.get("category"), body.get("auto"), body.get("respawnHours"))
        except MapError as e:
            return _error(400, str(e))
        self.hub.broadcast({"type": "rules_changed"})
        return web.json_response({"category": body["category"], "rule": rule})

    # ── backup: found ticks, rules, own markers and profiles in one file ──

    async def get_backup(self, request):
        store = self.app["markers"]
        try:
            mine = store.get("my-markers")["markers"]
        except MapNotFound:
            mine = []
        found, until = store._progress_data()
        data = {"app": "companion-map", "kind": "backup", "version": 1, "savedAt": time.time(), "appVersion": __version__,
                "found": sorted(found), "until": until, "rules": store.rules(), "myMarkers": mine,
                "profiles": self.profiles.list(), "defaultProfile": self.profiles.default_id()}
        name = time.strftime("companionmap-backup-%Y%m%d.json")
        return web.json_response(data, headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})

    async def restore_backup(self, request):
        """Merge a backup in: nothing here is removed or overwritten. Returns what was added."""
        body = await _json_body(request)
        if not isinstance(body, dict) or body.get("kind") != "backup":
            return _error(400, "not a Companion Map backup file")
        store = self.app["markers"]
        try:                 # own markers first: they are the part that can be refused, before anything is changed
            mine = store.merge_mine(body.get("myMarkers") if isinstance(body.get("myMarkers"), list) else None)
        except MapError as e:
            return _error(400, str(e))
        added = {"found": store.merge_progress(body.get("found") if isinstance(body.get("found"), list) else [],
                                               body.get("until") if isinstance(body.get("until"), dict) else None),
                 "rules": store.merge_rules(body.get("rules") if isinstance(body.get("rules"), dict) else None),
                 "myMarkers": mine, "profiles": 0}
        names = {p["name"] for p in self.profiles.list()}
        for p in body.get("profiles") if isinstance(body.get("profiles"), list) else []:
            if not isinstance(p, dict) or p.get("name") in names:
                continue
            try:
                self.profiles.create({k: v for k, v in p.items() if k not in ("id", "createdAt", "updatedAt")})
            except ProfileError:
                continue
            names.add(p.get("name"))
            added["profiles"] += 1
        self.hub.broadcast({"type": "markers_changed"})
        self.hub.broadcast({"type": "rules_changed"})
        if added["profiles"]:
            self._profile_changed(None, "created")
        log.info("Backup restored: %s", added)
        return web.json_response({"added": added})

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

    async def road_grid(self, request):
        m = request.match_info
        path = self.maps.extra_path(m["id"], m["rev"], "roads.png")
        if path is None:
            return _error(404, "no road grid")
        return web.FileResponse(path, headers={"Cache-Control": TILE_CACHE, "Content-Type": "image/png"})

    async def tile(self, request):
        m = request.match_info
        path = self.maps.tile_path(m["id"], m["rev"], m["z"], m["x"], m["y"])
        if path is None:
            return _error(404, "no such tile")
        return web.FileResponse(path, headers={"Cache-Control": TILE_CACHE, "Content-Type": "image/webp"})


def create_app(config, engine, data_dir, web_dir=WEB_DIR, simulated=False, pin=""):
    """pin: optional, only for `python -m server --pin` (the Windows app has none)."""
    data_dir, web_dir = Path(data_dir), Path(web_dir)
    app = web.Application(middlewares=[same_origin, pin_middleware(pin)], client_max_size=4 * 1024 ** 2)
    app["config"] = config
    app["pin"] = pin
    app["tls"] = LocalCA(data_dir)
    app["engine"] = engine
    app["simulated"] = simulated
    app["profiles"] = ProfileStore(data_dir / "profiles")
    app["maps"] = MapStore(data_dir / "maps")
    app["markers"] = MarkerStore(data_dir / "markers")
    app["hub"] = hub = Hub(engine, data_dir / "trail.json")
    api = Api(app)

    async def shell(request):
        index = web_dir / "dist" / "index.html"
        if index.exists():
            return web.FileResponse(index, headers={"Content-Security-Policy": SHELL_CSP, "Cache-Control": "no-cache"})
        return web.Response(text=FALLBACK_SHELL, content_type="text/html")

    r = app.router
    packed = {}                       # hashed .js / .css of the page, gzipped once

    async def asset(request):
        """A file of the built page. Files in assets/ have a hash in their name: browsers keep them for
        good, and scripts and styles go out gzipped (a third of the size)."""
        dist = (web_dir / "dist").resolve()
        name = request.match_info["path"]
        path = (dist / name).resolve()
        if dist not in path.parents or not path.is_file():
            return _error(404, "not found")
        if not name.startswith("assets/"):
            return web.FileResponse(path, headers={"Cache-Control": "no-cache"})
        headers = {"Cache-Control": TILE_CACHE, "Vary": "Accept-Encoding"}
        kind = {".js": "text/javascript", ".css": "text/css"}.get(path.suffix)
        if kind and "gzip" in request.headers.get("Accept-Encoding", "").lower():
            if name not in packed:
                packed[name] = await asyncio.get_running_loop().run_in_executor(None, lambda: gzip.compress(path.read_bytes(), 9))
            return web.Response(body=packed[name], content_type=kind, charset="utf-8", headers={**headers, "Content-Encoding": "gzip"})
        return web.FileResponse(path, headers=headers)

    r.add_get("/", shell)
    r.add_get("/cdlm/app/{path:.+}", asset)
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
    r.add_get("/cdlm/api/markers/sets/{id}", api.marker_set)
    r.add_get(r"/cdlm/api/markers/icons/{rev:[0-9a-f]{12}}.png", api.marker_icons)
    r.add_post("/cdlm/api/markers/mine", api.add_my_marker)
    r.add_put("/cdlm/api/markers/mine/{id}", api.update_my_marker)
    r.add_delete("/cdlm/api/markers/mine/{id}", api.delete_my_marker)
    r.add_get("/cdlm/api/progress", api.get_progress)
    r.add_post("/cdlm/api/progress", api.set_progress)
    r.add_delete("/cdlm/api/trail", api.clear_trail)
    r.add_get("/cdlm/api/rules", api.get_rules)
    r.add_put("/cdlm/api/rules", api.set_rule)
    r.add_get("/cdlm/api/backup", api.get_backup)
    r.add_post("/cdlm/api/backup", api.restore_backup)
    r.add_get(r"/cdlm/maps/{id}/{rev:[0-9a-f]{1,32}}/{z:\d{1,2}}/{x:\d{1,6}}/{y:\d{1,6}}.webp", api.tile)
    r.add_get(r"/cdlm/maps/{id}/{rev:[0-9a-f]{1,32}}/roads.png", api.road_grid)
    r.add_get("/cdlm/setup", api.setup_page)
    r.add_get("/cdlm/ca.mobileconfig", api.ca_profile)
    r.add_get("/cdlm/ca.crt", api.ca_cert)

    auto = AutoFound(app["markers"], hub.broadcast)
    hub.watchers.append(auto.on_state)

    async def lifecycle(app):
        engine.start()
        await hub.start()
        sweep = asyncio.create_task(auto.sweep())
        yield
        sweep.cancel()
        await hub.stop()
        await asyncio.get_running_loop().run_in_executor(None, engine.stop)

    app.cleanup_ctx.append(lifecycle)
    app.on_shutdown.append(hub.close_clients)
    return app

