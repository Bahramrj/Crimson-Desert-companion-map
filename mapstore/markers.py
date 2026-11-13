"""Marker sets: <data>/markers/<set-id>.json, positions in game x/z (never image pixels).

    {"id", "name", "source": "A"|"B"|"C", "licence", "gameVersion",
     "categories": [{"id", "name", "group"}],
     "markers": [{"id", "category", "name", "realm", "x", "z", "y"?}]}

Like maps, every set records where it came from. Sets imported from the game are replaced
by the next import; the user's own sets are never touched by it.

The game's own map icons for the categories (gamedata/icons.py) are kept next to the sets as
_icons.png (one sprite sheet) and _icons.json ({rev, source, licence, gameVersion, cells}); they come
from the user's install and stay on this PC.
"""

import hashlib
import math
import os
import re
import time
import uuid
from pathlib import Path

from mapstore.store import REALMS, SOURCES, MapError, NotFound
from server.jsonstore import read_json, write_json

ID_RE = re.compile(r"^[a-z0-9-]{1,80}$")
PNG_MAGIC = bytes([0x89]) + b"PNG"
REV_RE = re.compile(r"^[0-9a-f]{12}$")
ICON_LICENCE = "From your own game install; stays on this PC, not for sharing"
KEY_RE = re.compile(r"^[a-z0-9-]{1,80}:[^\s]{1,200}$")
MAX_MARKERS = 100_000
MAX_NAME, MAX_NOTES = 80, 500
COMPACT_ABOVE = 1000         # sets with more markers are written as compact JSON (half the size)
MINE = "my-markers"
MAX_RESPAWN_HOURS = 24 * 30
PLACED_ID = re.compile(r"^(.+)@(-?\d+(?:\.\d+)?):(-?\d+(?:\.\d+)?)$")     # "<object type>@<x>:<z>": ids of placed objects
CARRY_M = 2.0                # a found tick follows its object when a patch moves it less than this
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
# Kinds for the user's own markers: the id picks the icon (web/src/local/icons.ts), the name is the panel row.
MINE_TYPES = {
    "mine": "My markers", "chest": "Chests", "cave": "Caves", "camp": "Camps", "village": "Villages", "ore": "Ore",
    "plant": "Plants", "fishing": "Fishing spots", "quest": "Quests", "enemy": "Enemies", "puzzle": "Puzzles",
    "shop": "Shops", "house": "Houses", "landmark": "Landmarks", "rest": "Rest places",
}


def validate(data):
    if not isinstance(data, dict):
        raise MapError("marker set must be an object")
    if not ID_RE.match(str(data.get("id", ""))):
        raise MapError("set id must be lowercase letters, digits and dashes")
    if data.get("source") not in SOURCES:
        raise MapError(f"source must be one of {', '.join(SOURCES)}")
    if data["source"] == "B" and not str(data.get("licence", "")).strip():
        raise MapError("downloaded marker sets need a licence note")
    cats = data.get("categories")
    if not isinstance(cats, list) or not all(isinstance(c, dict) and c.get("id") and c.get("name") for c in cats):
        raise MapError("categories must be a list of {id, name}")
    ids = {c["id"] for c in cats}
    markers = data.get("markers")
    if not isinstance(markers, list) or len(markers) > MAX_MARKERS:
        raise MapError(f"markers must be a list of at most {MAX_MARKERS}")
    seen = set()
    for m in markers:
        if not isinstance(m, dict) or not isinstance(m.get("category"), str) or m["category"] not in ids or m.get("realm") not in REALMS:
            raise MapError(f"bad marker {m!r:.120}: needs a known category and realm")
        if not all(isinstance(m.get(k), (int, float)) and math.isfinite(m[k]) for k in ("x", "z")):
            raise MapError(f"marker {m.get('id')!r} needs finite x and z")
        if not m.get("id") or m["id"] in seen:
            raise MapError(f"marker ids must be unique: {m.get('id')!r}")
        seen.add(m["id"])
    return data


class MarkerStore:
    def __init__(self, root):
        self.root = Path(root)

    def _path(self, set_id):
        if not isinstance(set_id, str) or not ID_RE.match(set_id):
            raise NotFound(set_id)
        return self.root / f"{set_id}.json"

    def save(self, data):
        write_json(self._path(validate(data)["id"]), data, indent=None if len(data["markers"]) > COMPACT_ABOVE else 2)
        return self.summary(data)

    def replace_set(self, data):
        """Save a re-imported set and keep its found ticks: ids of placed objects hold their position
        ("<type>@<x>:<z>"), so an object a patch moved a little would lose its tick. A tick whose id is gone
        moves to the nearest object of the same type within CARRY_M. Returns (summary, carried, dropped)."""
        prefix = data["id"] + ":"
        ids = {m["id"] for m in data["markers"]}
        found, until = self._progress_data()
        lost = [k for k in found if k.startswith(prefix) and k[len(prefix):] not in ids]
        carried = dropped = 0
        if lost:
            by_type = {}
            for m in data["markers"]:
                hit = PLACED_ID.match(m["id"])
                if hit:
                    by_type.setdefault(hit.group(1), []).append(m)
            for key in lost:
                hit = PLACED_ID.match(key[len(prefix):])
                best = None
                if hit:
                    x, z = float(hit.group(2)), float(hit.group(3))
                    near = [((m["x"] - x) ** 2 + (m["z"] - z) ** 2, m["id"]) for m in by_type.get(hit.group(1), ())]
                    best = min((n for n in near if n[0] <= CARRY_M ** 2 and prefix + n[1] not in found), default=None)
                found.discard(key)
                end = until.pop(key, None)
                if best is None:
                    dropped += 1
                    continue
                found.add(prefix + best[1])
                if end:
                    until[prefix + best[1]] = end
                carried += 1
            self._save_progress(found, until)
        return self.save(data), carried, dropped

    def get(self, set_id):
        data = read_json(self._path(set_id))
        if data is None:
            raise NotFound(set_id)
        return data

    def list(self):
        if not self.root.is_dir():
            return []
        files = (p for p in sorted(self.root.glob("*.json")) if not p.name.startswith("_"))
        return [d for d in (read_json(f) for f in files) if d]

    def delete(self, set_id):
        path = self._path(set_id)
        if not path.exists():
            raise NotFound(set_id)
        path.unlink()

    @staticmethod
    def summary(data):
        return {k: data.get(k) for k in ("id", "name", "source", "licence", "gameVersion", "categories")} | {
            "count": len(data["markers"])}

    def signature(self, set_id=None):
        """Changes whenever listing() would (name, time and size of each set file, the icon index and the
        found list), or with `set_id` whenever the file of that set does."""
        if set_id is not None:
            path = self._path(set_id)
            if not path.is_file():
                raise NotFound(set_id)
            files = [path]
        else:
            files = sorted(self.root.glob("*.json")) if self.root.is_dir() else []
        return tuple((p.name, s.st_mtime_ns, s.st_size) for p in files for s in (p.stat(),))

    @staticmethod
    def lazy(data):
        """A set whose categories all start switched off (ore, plants, animals: tens of thousands of
        markers). The shell fetches its markers only when one of them is switched on."""
        cats = data.get("categories") or []
        return bool(cats) and all(c.get("off") for c in cats)

    @staticmethod
    def counts(data, found=()):
        """{realm: {category: [markers, found]}}: what the marker panel shows without the markers."""
        out = {}
        for m in data["markers"]:
            cell = out.setdefault(m["realm"], {}).setdefault(m["category"], [0, 0])
            cell[0] += 1
            cell[1] += f"{data['id']}:{m['id']}" in found
        return out

    def set_markers(self, set_id):
        """The markers of one set, tagged like those in listing()."""
        return {"id": set_id, "markers": [{**m, "set": set_id} for m in self.get(set_id)["markers"]]}

    def listing(self):
        """Everything the shell needs at start: set summaries (with `lazy` and per-category `counts`),
        the markers of the sets that are not lazy (each tagged with its set; the others come from
        set_markers) and the game icon sheet, if one was imported."""
        sets = self.list()
        icons = self.icons()
        found = set(self.found())
        return {"sets": [self.summary(s) | {"lazy": self.lazy(s), "counts": self.counts(s, found)} for s in sets],
                "markers": [{**m, "set": s["id"]} for s in sets if not self.lazy(s) for m in s["markers"]],
                "icons": icons and {"rev": icons["rev"], "url": f"/cdlm/api/markers/icons/{icons['rev']}.png",
                                    "cells": icons["cells"]}}

    # ── game icon sheet ──

    def save_icons(self, png, cells, game_version=None):
        """Store the icon sheet (PNG bytes) and its cells {category: [x, y, w, h]}; None removes it."""
        if png is None:
            for name in ("_icons.json", "_icons.png"):
                (self.root / name).unlink(missing_ok=True)
            return None
        if not png.startswith(PNG_MAGIC) or not isinstance(cells, dict):
            raise MapError("icon sheet must be a PNG with a cell index")
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / "_icons.png.tmp"
        tmp.write_bytes(png)
        os.replace(tmp, self.root / "_icons.png")
        meta = {"rev": hashlib.sha1(png).hexdigest()[:12], "source": "A", "licence": ICON_LICENCE,
                "gameVersion": game_version, "cells": cells}
        write_json(self.root / "_icons.json", meta)
        return meta

    def icons(self):
        meta = read_json(self.root / "_icons.json")
        if not meta or not REV_RE.match(str(meta.get("rev", ""))) or not (self.root / "_icons.png").is_file():
            return None
        return meta

    def icons_path(self, rev):
        meta = self.icons()
        return self.root / "_icons.png" if meta and meta["rev"] == rev else None

    # ── found-progress: keys "<set>:<marker id>", shared by every device ──

    @property
    def _progress(self):
        return self.root / "_progress.json"

    def _progress_data(self):
        """(found keys, {key: time the tick ends}) as stored; ticks whose time is up are still in."""
        try:
            stat = self._progress.stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            return set(), {}
        if getattr(self, "_progress_cache", (None,))[0] != stamp:          # read again only when the file changed
            data = read_json(self._progress, {}) or {}
            self._progress_cache = (stamp, frozenset(data.get("found", [])), dict(data.get("until", {})))
        return set(self._progress_cache[1]), dict(self._progress_cache[2])

    def _save_progress(self, found, until):
        write_json(self._progress, {"found": sorted(found), "until": {k: until[k] for k in sorted(until) if k in found}})

    def found(self):
        found, until = self._progress_data()
        now = time.time()
        return sorted(k for k in found if until.get(k, math.inf) > now)

    def until(self):
        """{key: time the tick ends} for the found markers that come back (rule `respawnHours`)."""
        found, until = self._progress_data()
        now = time.time()
        return {k: t for k, t in until.items() if k in found and t > now}

    def set_found(self, key, found, until=None):
        """Tick or untick a marker; `until` (a time) makes the tick end by itself."""
        if not isinstance(key, str) or not KEY_RE.match(key) or not isinstance(found, bool):
            raise MapError("expected a marker key '<set>:<id>' and found true/false")
        keys, ends = self._progress_data()
        ends.pop(key, None)
        if found:
            keys.add(key)
            if until:
                ends[key] = float(until)
        else:
            keys.discard(key)
        self._save_progress(keys, ends)
        return found

    def expire(self):
        """Remove the ticks whose time is up; returns their keys."""
        keys, ends = self._progress_data()
        now = time.time()
        gone = sorted(k for k, t in ends.items() if t <= now and k in keys)
        if gone:
            self._save_progress(keys - set(gone), ends)
        return gone

    def merge_progress(self, found, until=None):
        """Add ticks from a backup; returns how many were new."""
        keys, ends = self._progress_data()
        new = {k for k in found if isinstance(k, str) and KEY_RE.match(k)} - keys
        for k in new:
            t = (until or {}).get(k)
            if isinstance(t, (int, float)) and math.isfinite(t):
                ends[k] = float(t)
        if new:
            self._save_progress(keys | new, ends)
        return len(new)

    # ── rules per category "<set>:<category>": {"auto": true, "respawnHours": 12} ──

    def rules(self):
        return dict((read_json(self.root / "_rules.json", {}) or {}).get("categories", {}))

    def set_rule(self, category, auto=None, respawn_hours=None):
        """Change one category's rule; None leaves a field as it is. Returns the rule ({} when it is the default)."""
        if not isinstance(category, str) or not KEY_RE.match(category):
            raise MapError("expected a category key '<set>:<category>'")
        if auto is not None and not isinstance(auto, bool):
            raise MapError("auto must be true or false")
        if respawn_hours is not None and (isinstance(respawn_hours, bool) or not isinstance(respawn_hours, (int, float))
                                          or not 0 <= respawn_hours <= MAX_RESPAWN_HOURS):
            raise MapError(f"respawnHours must be 0 (never) to {MAX_RESPAWN_HOURS}")
        rules = self.rules()
        rule = dict(rules.get(category, {}))
        if auto is not None:
            rule["auto"] = auto
        if respawn_hours is not None:
            rule["respawnHours"] = respawn_hours
        rule = {k: v for k, v in rule.items() if v}             # false and 0 are the defaults
        if rule:
            rules[category] = rule
        else:
            rules.pop(category, None)
        write_json(self.root / "_rules.json", {"categories": rules})
        return rule

    def until_for(self, category):
        """The time a tick made now in this category ends, or None (it stays)."""
        hours = self.rules().get(category, {}).get("respawnHours") if isinstance(category, str) else None
        return time.time() + hours * 3600 if hours else None

    def merge_rules(self, rules):
        mine = self.rules()
        new = {k: v for k, v in (rules or {}).items() if k not in mine and isinstance(v, dict)}
        for key, rule in new.items():
            self.set_rule(key, rule.get("auto") or None, rule.get("respawnHours") or None)
        return len(new)

    # ── the user's own markers ("add marker here") ──

    def _mine(self):
        try:
            return self.get(MINE)
        except NotFound:
            return {"id": MINE, "name": "My markers", "source": "C", "licence": "own markers", "categories": [], "markers": []}

    def _save_mine(self, data):
        used = {m["category"] for m in data["markers"]} or {"mine"}
        data["categories"] = [{"id": c, "name": n, "group": "My markers"} for c, n in MINE_TYPES.items() if c in used]
        self.save(data)                              # validates kinds, realm and coordinates

    @staticmethod
    def _color(value):
        """A marker colour "#rrggbb", or None for the colour of its kind."""
        if value in (None, ""):
            return None
        if not isinstance(value, str) or not COLOR_RE.match(value):
            raise MapError("colour must look like #a1b2c3")
        return value.lower()

    def add_mine(self, name, realm, x, z, notes="", category="mine", color=None):
        name = (name or "").strip()[:MAX_NAME]
        if not name:
            raise MapError("a marker needs a name")
        data = self._mine()
        marker = {"id": uuid.uuid4().hex[:10], "category": category, "name": name, "realm": realm,
                  "x": x, "z": z, "notes": str(notes or "")[:MAX_NOTES], "createdAt": time.time()}
        if self._color(color):
            marker["color"] = self._color(color)
        data["markers"].append(marker)
        self._save_mine(data)
        return {**marker, "set": MINE}

    def update_mine(self, marker_id, fields):
        """Change name, notes, category (a MINE_TYPES id), realm, x or z of one own marker."""
        data = self._mine()
        marker = next((m for m in data["markers"] if m["id"] == marker_id), None)
        if marker is None:
            raise NotFound(marker_id)
        if not isinstance(fields, dict):
            raise MapError("expected an object")
        if "name" in fields:
            marker["name"] = str(fields["name"] or "").strip()[:MAX_NAME]
            if not marker["name"]:
                raise MapError("a marker needs a name")
        if "notes" in fields:
            marker["notes"] = str(fields["notes"] or "")[:MAX_NOTES]
        for key in ("category", "realm", "x", "z"):
            if key in fields:
                marker[key] = fields[key]
        if "color" in fields:
            marker.pop("color", None)
            if self._color(fields["color"]):
                marker["color"] = self._color(fields["color"])
        marker["updatedAt"] = time.time()
        self._save_mine(data)
        return {**marker, "set": MINE}

    def merge_mine(self, markers):
        """Add own markers from a backup that are not here yet (by id); returns how many."""
        data = self._mine()
        have = {m["id"] for m in data["markers"]}
        added = 0
        for m in markers or []:
            if not isinstance(m, dict) or not isinstance(m.get("id"), str) or m["id"] in have or not str(m.get("name", "")).strip():
                continue
            data["markers"].append({"id": m["id"][:40], "category": m.get("category") if m.get("category") in MINE_TYPES else "mine", "name": str(m["name"]).strip()[:MAX_NAME],
                                    "realm": m.get("realm"), "x": m.get("x"), "z": m.get("z"),
                                    "notes": str(m.get("notes") or "")[:MAX_NOTES], "createdAt": m.get("createdAt") or time.time()}
                                   | ({"color": m["color"].lower()} if isinstance(m.get("color"), str) and COLOR_RE.match(m["color"]) else {}))
            have.add(m["id"])
            added += 1
        if added:
            self._save_mine(data)
        return added

    def delete_mine(self, marker_id):
        data = self.get(MINE)
        kept = [m for m in data["markers"] if m["id"] != marker_id]
        if len(kept) == len(data["markers"]):
            raise NotFound(marker_id)
        data["markers"] = kept
        self._save_mine(data)
        self.set_found(f"{MINE}:{marker_id}", False)
