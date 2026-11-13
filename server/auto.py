"""Found ticks that set and clear themselves.

- Auto-found: for the categories the user chose (rule `auto`), a marker is ticked when the player
  stands at it for a moment. This runs on the PC, so it works while the tablet sleeps.
- Respawn: a tick with an end time (rule `respawnHours`: ore and plants come back) is removed
  when the time is up.
Both only change our own progress file; nothing is written to the game.
"""

import asyncio
import logging
import time
from collections import defaultdict

log = logging.getLogger("cdlivemap.server")

RADIUS_M = 4.0        # on the map
HEIGHT_M = 6.0        # and this close in height (a chest one floor up is not reached)
DWELL_S = 1.5         # standing there this long, so riding past does not count
CHECK_S = 0.5
SWEEP_S = 20.0
CELL_M = 8.0


class AutoFound:
    def __init__(self, store, announce):
        self.store = store
        self.announce = announce          # announce(message): to every device
        self._signature = None
        self._index = {}                  # (realm, cell x, cell z) -> [(key, category key, name, x, y, z)]
        self._building = False
        self._checked = 0.0
        self._inside = {}                 # key -> time first seen in reach; None once handled

    # ── index of the markers in "auto" categories ──

    def _files(self):
        return tuple(e for e in self.store.signature() if e[0] != "_progress.json")

    def _build(self, signature):
        index = defaultdict(list)
        chosen = {key for key, rule in self.store.rules().items() if rule.get("auto")}
        for set_id in sorted({key.split(":", 1)[0] for key in chosen}):
            try:
                data = self.store.get(set_id)
            except KeyError:
                continue
            for m in data["markers"]:
                category = f"{set_id}:{m['category']}"
                if category in chosen:
                    cell = (m["realm"], int(m["x"] // CELL_M), int(m["z"] // CELL_M))
                    index[cell].append((f"{set_id}:{m['id']}", category, m.get("name", ""), m["x"], m.get("y"), m["z"]))
        return signature, dict(index)

    async def _rebuild(self, signature):
        try:
            self._signature, self._index = await asyncio.get_running_loop().run_in_executor(None, self._build, signature)
            log.info("Auto-found: watching %d markers", sum(len(v) for v in self._index.values()))
        except Exception:
            log.exception("Auto-found index failed")
            self._signature = signature       # not again until something changes
        finally:
            self._building = False

    # ── on the event loop, for every engine state ──

    def on_state(self, state):
        now = time.monotonic()
        if state.x is None or now - self._checked < CHECK_S:
            return
        self._checked = now
        signature = self._files()
        if signature != self._signature and not self._building:
            self._building = True
            asyncio.ensure_future(self._rebuild(signature))
        cx, cz = int(state.x // CELL_M), int(state.z // CELL_M)
        near = {}
        for gx in (cx - 1, cx, cx + 1):
            for gz in (cz - 1, cz, cz + 1):
                for key, category, name, x, y, z in self._index.get((state.realm, gx, gz), ()):
                    if (x - state.x) ** 2 + (z - state.z) ** 2 <= RADIUS_M ** 2 and (y is None or abs(y - state.y) <= HEIGHT_M):
                        near[key] = (category, name)
        self._inside = {key: self._inside.get(key, now) for key in near}
        due = [key for key, since in self._inside.items() if since is not None and now - since >= DWELL_S]
        if not due:
            return
        found = set(self.store.found())
        for key in due:
            self._inside[key] = None          # once per visit: an undo while standing there stays undone
            if key in found:
                continue
            category, name = near[key]
            until = self.store.until_for(category)
            self.store.set_found(key, True, until)
            log.info("Auto-found %s", key)
            self.announce({"type": "progress_changed", "key": key, "found": True, "until": until, "auto": True, "name": name})

    # ── ticks whose time is up ──

    async def sweep(self):
        while True:
            await asyncio.sleep(SWEEP_S)
            try:
                for key in self.store.expire():
                    self.announce({"type": "progress_changed", "key": key, "found": False, "until": None})
            except Exception:
                log.exception("Respawn sweep failed")
