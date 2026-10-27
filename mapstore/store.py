"""Local map asset store: <root>/<map-id>/{manifest.json, tiles/} plus <root>/_index.json.

Stateless: every call reads the files, so the server, the launcher and the CLI can share
one folder. Writes are atomic (manifest) or staged (tiles are built next to the map and
swapped in).
"""

import math
import re
import shutil
import time
import uuid
from pathlib import Path

from mapstore import georef as geo
from mapstore import tiler
from server.jsonstore import read_json, write_json

REALMS = ("pywel", "abyss")
SOURCES = {"A": "game files", "B": "download", "C": "own capture"}
ID_RE = re.compile(r"^[a-z0-9-]{1,80}$")
MAX_POINTS = 50
MAX_NAME = 60
MAX_LICENCE = 300


class MapError(ValueError):
    pass


class NotFound(KeyError):
    pass


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "map"


def _pair(value, name):
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in value)):
        raise MapError(f"{name} must be two finite numbers")
    return [float(value[0]), float(value[1])]


def summary(manifest):
    """Manifest plus what clients need: bounds, tile URL, calibration error."""
    w, h = manifest["image"]
    g = manifest["georef"]
    res = geo.residuals(g, manifest["calibration"]) if len(manifest["calibration"]) >= 2 else []
    return {
        **manifest,
        "bounds": geo.bounds(g, w, h),
        "tiles": f"/cdlm/maps/{manifest['id']}/{manifest['rev']}/{{z}}/{{x}}/{{y}}.webp",
        "residuals": res,
        "errorM": geo.rms(res),
    }


class MapStore:
    def __init__(self, root):
        self.root = Path(root)
        self._index = self.root / "_index.json"

    # ── read ──────────────────────────────────────────────────────

    def _dir(self, map_id):
        if not isinstance(map_id, str) or not ID_RE.match(map_id):
            raise NotFound(map_id)
        return self.root / map_id

    def get(self, map_id):
        manifest = read_json(self._dir(map_id) / "manifest.json")
        if manifest is None:
            raise NotFound(map_id)
        return manifest

    def list(self):
        if not self.root.is_dir():
            return []
        found = [read_json(d / "manifest.json") for d in sorted(self.root.iterdir()) if d.is_dir() and ID_RE.match(d.name)]
        return sorted((m for m in found if m), key=lambda m: (m["realm"], -m["createdAt"]))

    def active(self):
        saved = (read_json(self._index, {}) or {}).get("active", {})
        maps = self.list()
        ids = {m["id"] for m in maps}
        out = {}
        for realm in REALMS:
            pick = saved.get(realm)
            if pick not in ids:   # deleted or never set: newest map of that realm
                pick = next((m["id"] for m in maps if m["realm"] == realm), None)
            out[realm] = pick
        return out

    def listing(self):
        return {"maps": [summary(m) for m in self.list()], "active": self.active()}

    def tile_path(self, map_id, rev, z, x, y):
        """File for a tile request, or None (wrong rev, missing tile)."""
        try:
            manifest = self.get(map_id)
        except NotFound:
            return None
        if rev != manifest["rev"]:
            return None
        path = self._dir(map_id) / "tiles" / str(z) / str(x) / f"{y}.webp"
        return path if path.is_file() else None

    # ── write ─────────────────────────────────────────────────────

    def set_active(self, realm, map_id):
        if realm not in REALMS:
            raise MapError(f"realm must be one of {', '.join(REALMS)}")
        if map_id is not None and self.get(map_id)["realm"] != realm:
            raise MapError("that map belongs to the other realm")
        index = read_json(self._index, {}) or {}
        index.setdefault("active", {})[realm] = map_id
        write_json(self._index, index)

    def import_image(self, path, realm, name=None, source="C", licence="", game_version=None,
                     fixed_georef=None, progress=None):
        """Tile an image into a new map and make it the realm's active map. Returns the summary."""
        self._check(realm, source, licence)
        img = tiler.open_image(path)
        w, h = img.size
        return self._create(lambda tiles: tiler.build(img, tiles, progress=progress), (w, h), realm,
                            name or Path(path).stem, source, licence, game_version, fixed_georef)

    def import_rendered(self, render, size, realm, name, source="A", licence="", game_version=None,
                        fixed_georef=None, replace=None, progress=None, quality=85):
        """New map from a tile renderer (see tiler.build_from); `replace` deletes that map afterwards.
        `quality` is the WebP quality of the tiles."""
        self._check(realm, source, licence)
        w, h = size
        result = self._create(lambda tiles: tiler.build_from(render, w, h, tiles, quality=quality, progress=progress),
                              size, realm, name, source, licence, game_version, fixed_georef)
        if replace and replace != result["id"]:
            try:
                self.delete(replace)
            except NotFound:
                pass
        return result

    @staticmethod
    def _check(realm, source, licence):
        if realm not in REALMS:
            raise MapError(f"realm must be one of {', '.join(REALMS)}")
        if source not in SOURCES:
            raise MapError(f"source must be one of {', '.join(SOURCES)} ({', '.join(SOURCES.values())})")
        if source == "B" and not (licence or "").strip():
            raise MapError("downloaded maps need a licence note (where it came from, what it allows)")

    def _create(self, build, size, realm, name, source, licence, game_version, fixed_georef):
        name = (name or "").strip()[:MAX_NAME] or "Map"
        licence = (licence or ("own install, personal use" if source == "A" else "")).strip()[:MAX_LICENCE]
        w, h = size
        map_id = f"{realm}-{_slug(name)}-{uuid.uuid4().hex[:6]}"
        staging = self.root / f".{map_id}.tmp"
        shutil.rmtree(staging, ignore_errors=True)
        try:
            top = build(staging / "tiles")
            now = time.time()
            manifest = {
                "id": map_id, "name": name, "realm": realm, "source": source, "licence": licence,
                "image": [w, h], "tileSize": tiler.TILE, "maxZoom": top, "rev": uuid.uuid4().hex[:8],
                "georef": fixed_georef or geo.default_georef(w, h), "fixed": fixed_georef is not None,
                "calibration": [], "gameVersion": game_version, "createdAt": now, "updatedAt": now,
            }
            write_json(staging / "manifest.json", manifest)
            staging.rename(self._dir(map_id))
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        self.set_active(realm, map_id)
        return summary(manifest)

    def delete(self, map_id):
        path = self._dir(map_id)
        if not (path / "manifest.json").exists():
            raise NotFound(map_id)
        shutil.rmtree(path)

    def _save(self, manifest):
        manifest["updatedAt"] = time.time()
        write_json(self._dir(manifest["id"]) / "manifest.json", manifest)
        return summary(manifest)

    def _refit(self, manifest):
        points = manifest["calibration"]
        w, h = manifest["image"]
        manifest["georef"] = geo.fit(points) if len(points) >= 2 else geo.default_georef(w, h)

    def add_point(self, map_id, game, px):
        manifest = self.get(map_id)
        if manifest.get("fixed"):
            raise MapError("this map is placed from the game's own data and needs no calibration")
        point = {"game": _pair(game, "game"), "px": _pair(px, "px")}
        w, h = manifest["image"]
        if not (-w <= point["px"][0] <= 2 * w and -h <= point["px"][1] <= 2 * h):
            raise MapError("that tap is outside the map image")
        if len(manifest["calibration"]) >= MAX_POINTS:
            raise MapError(f"at most {MAX_POINTS} points per map")
        manifest["calibration"].append(point)
        try:
            self._refit(manifest)
        except geo.GeorefError as e:
            raise MapError(str(e)) from e
        return self._save(manifest)

    def delete_point(self, map_id, index):
        manifest = self.get(map_id)
        if not 0 <= index < len(manifest["calibration"]):
            raise NotFound(index)
        del manifest["calibration"][index]
        try:
            self._refit(manifest)
        except geo.GeorefError:
            w, h = manifest["image"]
            manifest["georef"] = geo.default_georef(w, h)
        return self._save(manifest)

    def reset_calibration(self, map_id):
        manifest = self.get(map_id)
        if manifest.get("fixed"):
            return summary(manifest)
        manifest["calibration"] = []
        self._refit(manifest)
        return self._save(manifest)
