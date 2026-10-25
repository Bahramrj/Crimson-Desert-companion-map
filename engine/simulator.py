"""Replay recorded paths through the Engine interface: the app's demo mode
(`CompanionMap.exe --simulate`) runs without the game.

Path files (engine/paths/*.json):
  {"name": ..., "realm": "pywel" | "abyss", "source": ...,
   "samples": [{"t": seconds, "x": ..., "y": ..., "z": ..., "heading": ...}, ...]}
Coordinates are absolute game coordinates, the same as EngineState.
"""

import bisect
import json
import time
from pathlib import Path

from engine.base import Engine
from engine.models import ATTACHED, WAITING_FOR_GAME, EngineState, realm_for_height

PATHS_DIR = Path(__file__).with_name("paths")
GAP_SECONDS = 1.0   # transition time between consecutive paths


def load_paths(paths=None):
    if paths is None:
        paths = PATHS_DIR.glob("*.json")
    elif isinstance(paths, (str, Path)):
        paths = [paths]
    loaded = []
    for p in paths:
        with open(p, encoding="utf-8") as f:
            loaded.append(json.load(f))
    loaded.sort(key=lambda d: (d.get("realm") != "pywel", d.get("name", "")))
    return loaded


def build_timeline(path_docs):
    timeline, offset = [], 0.0
    for doc in path_docs:
        samples = doc["samples"]
        t_first = samples[0]["t"]
        for s in samples:
            timeline.append({**s, "t": offset + s["t"] - t_first})
        offset = timeline[-1]["t"] + GAP_SECONDS
    if not timeline:
        raise ValueError("no samples in the given paths")
    return timeline


def lerp_heading(a, b, f):
    if a is None or b is None:
        return a if f < 0.5 else b
    d = (b - a + 180.0) % 360.0 - 180.0
    h = a + d * f
    return (h + 180.0) % 360.0 - 180.0


class SimulatorEngine(Engine):
    def __init__(self, paths=None, speed=1.0, loop=True, waiting_seconds=0.0, clock=time.monotonic, **kwargs):
        super().__init__(**kwargs)
        self.timeline = build_timeline(load_paths(paths))
        self._times = [s["t"] for s in self.timeline]
        self.duration = self._times[-1]
        self.speed = speed
        self.loop = loop
        self.waiting_seconds = waiting_seconds
        self._clock = clock
        self._t0 = None

    def start(self):
        self._t0 = None
        super().start()

    def state_at(self, elapsed, now=None):
        """State `elapsed` simulated seconds after start."""
        now = time.time() if now is None else now
        if elapsed < self.waiting_seconds:
            return EngineState(WAITING_FOR_GAME)
        t = elapsed - self.waiting_seconds
        stale_for = 0.0
        if self.loop and self.duration > 0:
            t %= self.duration
        elif t > self.duration:
            stale_for, t = (t - self.duration) / self.speed, self.duration

        i = bisect.bisect_right(self._times, t)
        a = self.timeline[max(0, i - 1)]
        b = self.timeline[min(i, len(self.timeline) - 1)]
        span = b["t"] - a["t"]
        f = (t - a["t"]) / span if span > 0 else 0.0
        x, y, z = (a[k] + (b[k] - a[k]) * f for k in ("x", "y", "z"))
        heading = lerp_heading(a.get("heading"), b.get("heading"), f)
        return EngineState(ATTACHED, x=x, y=y, z=z, realm=realm_for_height(y),
                           heading=heading, ts=now - stale_for)

    def _tick(self):
        if self._t0 is None:
            self._t0 = self._clock()
        return self.state_at((self._clock() - self._t0) * self.speed), self.interval
