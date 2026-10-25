"""Server settings, stored as %LOCALAPPDATA%\\CompanionMap\\config.json."""

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

APP_DIR = "CompanionMap"          # separate from the online CD Live Map (%LOCALAPPDATA%\CDLiveMap)
OLD_APP_DIRS = ("CDLiveMapStandalone",)   # earlier name of this app: moved over once


def data_dir():
    override = os.environ.get("CDLIVEMAP_DATA")
    if override:
        return Path(override)
    base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    target = base / APP_DIR
    if not target.exists():
        for old in OLD_APP_DIRS:
            if (base / old).is_dir():
                try:
                    os.replace(base / old, target)       # keep maps, markers, progress, profiles and settings
                except OSError:
                    return base / old                    # in use (another copy running): keep using it
                break
    return target


@dataclass
class Config:
    port: int = 8788
    https: bool = False              # also serve HTTPS (local CA, server/tls.py); plain HTTP always stays on
    https_port: int = 8789
    mdns: bool = True                # answer for companionmap.local on the LAN (server/mdns.py)
    rate_hz: int = 30
    start_minimized: bool = False
    map_quality: str = "default"     # game map import: "default" (16384 px) or "high" (Pywel at 32768 px)
    game_dir: str = ""               # Crimson Desert install folder; empty = find it via Steam

    @classmethod
    def load(cls, path):
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        except FileNotFoundError:
            return cls()
        known = {f.name for f in fields(cls)}
        cfg = cls(**{k: v for k, v in raw.items() if k in known})
        cfg.validate()
        return cfg

    def save(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def validate(self):
        if not 1 <= self.port <= 65535 or not 1 <= self.https_port <= 65535:
            raise ValueError("port out of range")
        if self.https and self.https_port == self.port:
            raise ValueError("the HTTPS port must differ from the HTTP port")
        if not 10 <= self.rate_hz <= 60:
            raise ValueError("update rate must be 10-60 Hz")
        if self.map_quality not in ("default", "high"):
            raise ValueError("map quality must be default or high")
