"""Marker sets from files: CSV, GeoJSON or JSON, positions in game x/z.

CSV       header row with name, x, z and optionally category, realm, y, id, notes
GeoJSON   FeatureCollection of Points; coordinates are [game x, game z] (y optional as a 3rd value);
          properties name, category, realm, id, notes
JSON      a marker set ({"markers": [...], "categories": [...]}) or a plain list of markers

The realm comes from the `realm` column, else from y (above 1400 = Abyss), else the default.
"""

import csv
import json
import re
from pathlib import Path

from mapstore.markers import validate
from mapstore.store import MapError

ABYSS_Y = 1400.0


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:40] or "other"


def _num(value, what, row):
    try:
        return float(value)
    except (TypeError, ValueError):
        raise MapError(f"row {row}: {what} must be a number, got {value!r}") from None


def _records(path):
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".csv":
        rows = list(csv.DictReader(text.splitlines()))
        return [{k.strip().lower(): (v or "").strip() for k, v in r.items() if k} for r in rows], None
    data = json.loads(text)
    if isinstance(data, dict) and data.get("type") == "FeatureCollection":
        out = []
        for f in data.get("features", []):
            geom, props = f.get("geometry") or {}, f.get("properties") or {}
            if geom.get("type") != "Point":
                continue
            coords = geom.get("coordinates") or []
            out.append({**props, "x": coords[0] if coords else None, "z": coords[1] if len(coords) > 1 else None,
                        **({"y": coords[2]} if len(coords) > 2 else {}), "id": props.get("id", f.get("id"))})
        return out, None
    if isinstance(data, dict) and isinstance(data.get("markers"), list):
        return data["markers"], data.get("categories")
    if isinstance(data, list):
        return data, None
    raise MapError("unknown JSON layout: expected a marker set, a list of markers or a GeoJSON FeatureCollection")


def read_marker_file(path, name, source="C", licence="", realm="pywel"):
    """Parse a file into a validated marker set (not saved)."""
    records, given_cats = _records(path)
    cat_names = {c["id"]: c["name"] for c in given_cats or [] if isinstance(c, dict) and c.get("id")}
    markers, ids = [], set()
    for i, r in enumerate(records, start=1):
        if not isinstance(r, dict):
            raise MapError(f"row {i}: expected an object")
        cat_label = r.get("category") or "Markers"
        cat = cat_label if cat_label in cat_names else _slug(cat_label)
        cat_names.setdefault(cat, str(cat_label).strip() or "Markers")
        y = _num(r["y"], "y", i) if r.get("y") not in (None, "") else None
        row_realm = (r.get("realm") or "").lower() or ("abyss" if y is not None and y > ABYSS_Y else realm)
        mid = str(r.get("id") or i)
        while mid in ids:
            mid += "-dup"
        ids.add(mid)
        marker = {"id": mid, "category": cat, "name": str(r.get("name") or f"Marker {i}")[:80], "realm": row_realm,
                  "x": _num(r.get("x"), "x", i), "z": _num(r.get("z"), "z", i)}
        if y is not None:
            marker["y"] = y
        if r.get("notes"):
            marker["notes"] = str(r["notes"])[:500]
        markers.append(marker)
    if not markers:
        raise MapError("no markers found in the file")
    data = {"id": f"import-{_slug(name)}", "name": str(name)[:60], "source": source, "licence": licence,
            "gameVersion": None, "categories": [{"id": c, "name": n, "group": str(name)[:60]} for c, n in cat_names.items()
                                                if any(m["category"] == c for m in markers)],
            "markers": markers}
    return validate(data)
