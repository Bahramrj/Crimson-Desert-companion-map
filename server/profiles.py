"""Layout profiles, one JSON file each in <data>/profiles/."""

import re
import time
import uuid
from pathlib import Path

from server.jsonstore import read_json, write_json

ENUMS = {
    "sidebar": ("collapsed", "expanded"),
    "toolbarSide": ("bottom", "left", "right"),
    "markerSize": ("small", "medium", "large"),
    "theme": ("auto", "dark", "light"),
}
DEFAULTS = {
    "types": [], "hide": [], "show": [],
    "zoom": None, "follow": True, "rotateWithHeading": False, "hideFound": False,
    "sidebar": "collapsed", "toolbarSide": "bottom", "markerSize": "medium", "theme": "auto",
    "mapOpacity": 1.0, "markerOpacity": 1.0,
}
OPACITY = (0.2, 1.0)
EDITABLE = {"name", *DEFAULTS}
MAX_NAME = 60
MAX_IDS = 2000
ID_RE = re.compile(r"^[a-z0-9-]{1,80}$")


class ProfileError(ValueError):
    pass


class NotFound(KeyError):
    pass


def validate(data, partial=False):
    if not isinstance(data, dict):
        raise ProfileError("profile must be an object")
    unknown = set(data) - EDITABLE
    if unknown:
        raise ProfileError(f"unknown fields: {', '.join(sorted(unknown))}")
    if not partial and "name" not in data:
        raise ProfileError("name is required")
    out = {}
    for key, value in data.items():
        if key == "name":
            if not isinstance(value, str) or not value.strip() or len(value) > MAX_NAME:
                raise ProfileError(f"name must be 1-{MAX_NAME} characters")
            value = value.strip()
        elif key in ("types", "hide", "show"):
            if not isinstance(value, list) or len(value) > MAX_IDS or not all(isinstance(v, str) for v in value):
                raise ProfileError(f"{key} must be a list of marker category ids")
        elif key == "zoom":
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 20):
                raise ProfileError("zoom must be a number between 0 and 20, or null")
        elif key in ("mapOpacity", "markerOpacity"):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not OPACITY[0] <= value <= OPACITY[1]:
                raise ProfileError(f"{key} must be a number between {OPACITY[0]} and {OPACITY[1]}")
        elif key in ("follow", "rotateWithHeading", "hideFound"):
            if not isinstance(value, bool):
                raise ProfileError(f"{key} must be true or false")
        elif key in ENUMS and value not in ENUMS[key]:
            raise ProfileError(f"{key} must be one of {', '.join(ENUMS[key])}")
        out[key] = value
    return out


def _slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "profile"


class ProfileStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._index_path = self.root / "_index.json"

    def _path(self, pid):
        if not ID_RE.match(pid):
            raise NotFound(pid)
        return self.root / f"{pid}.json"

    @staticmethod
    def _upgrade(profile):
        return {**DEFAULTS, **profile} if profile else profile

    def list(self):
        items = [self._upgrade(read_json(p)) for p in sorted(self.root.glob("*.json")) if p.name != "_index.json"]
        return sorted((p for p in items if p), key=lambda p: (p["name"].lower(), p["id"]))

    def get(self, pid):
        profile = self._upgrade(read_json(self._path(pid)))
        if profile is None:
            raise NotFound(pid)
        return profile

    def create(self, data):
        fields = validate(data)
        now = time.time()
        pid = f"{_slug(fields['name'])}-{uuid.uuid4().hex[:6]}"
        profile = {"id": pid, **DEFAULTS, **fields, "createdAt": now, "updatedAt": now}
        write_json(self._path(pid), profile)
        return profile

    def update(self, pid, data):
        profile = self.get(pid)
        profile.update(validate(data, partial=True))
        profile["updatedAt"] = time.time()
        write_json(self._path(pid), profile)
        return profile

    def delete(self, pid):
        path = self._path(pid)
        if not path.exists():
            raise NotFound(pid)
        path.unlink()
        if self.default_id() == pid:
            self.set_default(None)

    def default_id(self):
        return (read_json(self._index_path, {}) or {}).get("default")

    def set_default(self, pid):
        if pid is not None:
            self.get(pid)
        write_json(self._index_path, {"default": pid})
