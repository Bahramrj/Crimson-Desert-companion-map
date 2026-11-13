"""Small helpers for JSON files written atomically."""

import json
import os
from pathlib import Path


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def write_json(path, data, indent=2):
    """indent=None writes compact JSON (large files that nobody reads by hand)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    text = json.dumps(data, indent=indent) if indent else json.dumps(data, separators=(",", ":"))
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
