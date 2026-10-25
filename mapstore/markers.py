"""Marker sets: <data>/markers/<set-id>.json, positions in game x/z (never image pixels).

    {"id", "name", "source": "A"|"B"|"C", "licence", "gameVersion",
     "categories": [{"id", "name", "group"}],
     "markers": [{"id", "category", "name", "realm", "x", "z", "y"?}]}

Like maps, every set records where it came from. Sets imported from the game are replaced
by the next import; the user's own sets are never touched by it.
"""

import math
import re
import time
import uuid
from pathlib import Path

from mapstore.store import REALMS, SOURCES, MapError, NotFound
from server.jsonstore import read_json, write_json

ID_RE = re.compile(r"^[a-z0-9-]{1,80}$")
KEY_RE = re.compile(r"^[a-z0-9-]{1,80}:[^\s]{1,200}$")
MAX_MARKERS = 100_000
MAX_NAME, MAX_NOTES = 80, 500
MINE = "my-markers"


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
        if not isinstance(m, dict) or m.get("category") not in ids or m.get("realm") not in REALMS:
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
        write_json(self._path(validate(data)["id"]), data)
        return self.summary(data)

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

    def listing(self):
        """Everything the shell needs: set summaries and all markers, each tagged with its set."""
        sets = self.list()
        return {"sets": [self.summary(s) for s in sets],
                "markers": [{**m, "set": s["id"]} for s in sets for m in s["markers"]]}

    # ── found-progress: keys "<set>:<marker id>", shared by every device ──

    @property
    def _progress(self):
        return self.root / "_progress.json"

    def found(self):
        return sorted((read_json(self._progress, {}) or {}).get("found", []))

    def set_found(self, key, found):
        if not isinstance(key, str) or not KEY_RE.match(key) or not isinstance(found, bool):
            raise MapError("expected a marker key '<set>:<id>' and found true/false")
        keys = set(self.found())
        keys.add(key) if found else keys.discard(key)
        write_json(self._progress, {"found": sorted(keys)})
        return found

    # ── the user's own markers ("add marker here") ──

    def add_mine(self, name, realm, x, z, notes=""):
        name = (name or "").strip()[:MAX_NAME]
        if not name:
            raise MapError("a marker needs a name")
        try:
            data = self.get(MINE)
        except NotFound:
            data = {"id": MINE, "name": "My markers", "source": "C", "licence": "own markers",
                    "categories": [{"id": "mine", "name": "My markers", "group": "My markers"}], "markers": []}
        marker = {"id": uuid.uuid4().hex[:10], "category": "mine", "name": name, "realm": realm,
                  "x": x, "z": z, "notes": str(notes or "")[:MAX_NOTES], "createdAt": time.time()}
        data["markers"].append(marker)
        self.save(data)                              # validates realm and coordinates
        return {**marker, "set": MINE}

    def delete_mine(self, marker_id):
        data = self.get(MINE)
        kept = [m for m in data["markers"] if m["id"] != marker_id]
        if len(kept) == len(data["markers"]):
            raise NotFound(marker_id)
        data["markers"] = kept
        self.save(data)
        self.set_found(f"{MINE}:{marker_id}", False)
