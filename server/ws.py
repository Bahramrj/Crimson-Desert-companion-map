"""WebSocket hub: fans engine state out to the device shell.

Message `position` carries game x/y/z, realm and heading; the local map works in game units.
`progress_changed` carries key, found and, for ticks that end by themselves, `until`; `auto` + `name` when the
PC ticked it because the player reached it. `rules_changed` follows a change of the category rules.
Incoming messages are never acted on: there is nothing a client can ask the engine to do.
"""

import asyncio
import json
import logging
import time
from collections import deque

from aiohttp import WSMsgType, web

from server.jsonstore import read_json, write_json


log = logging.getLogger("cdlivemap.server")

IDLE_HEARTBEAT = 1.0   # resend the last position when nothing changed
TRAIL_STEP_M = 5.0     # the trail gets a point every few metres ...
TRAIL_JUMP_M = 150.0   # ... and a gap after a jump (fast travel); the device page uses the same numbers
TRAIL_POINTS = 6000    # per realm: about 30 km of walking
TRAIL_SAVE_S = 60.0    # the trail is written to disk this often while it grows, and when the server stops


def position_message(state):
    msg = {
        "type": "position",
        "x": round(state.x, 2), "y": round(state.y, 2), "z": round(state.z, 2),
        "realm": state.realm,
        "ts": state.ts,
    }
    if state.heading is not None:
        msg["heading"] = round(state.heading, 1)
    return msg


def device_name(agent):
    """A word for the device from its browser's User-Agent ("iPad", "Android device", ...)."""
    for key, name in (("iPad", "iPad"), ("iPhone", "iPhone"), ("Android", "Android device"), ("Windows", "Windows PC"),
                      ("Macintosh", "Mac or iPad"), ("Linux", "Linux device")):       # an iPad's Safari often says Macintosh
        if key in agent:
            return name
    return "Device"


def status_message(state):
    return {"type": "status", "status": state.status, "message": state.message}


class _Sender:
    """What one device still has to be sent: other messages in order, and of the positions only the newest."""
    __slots__ = ("ws", "queue", "position", "wake", "task")

    def __init__(self, ws):
        self.ws, self.queue, self.position, self.wake, self.task = ws, deque(), None, asyncio.Event(), None

    async def run(self):
        try:
            while True:
                await self.wake.wait()
                self.wake.clear()
                while self.queue:
                    await self.ws.send_str(self.queue.popleft())
                if self.position is not None:
                    data, self.position = self.position, None
                    await self.ws.send_str(data)
        except (ConnectionError, RuntimeError):      # the device went away; handle() cleans up
            pass


class Hub:
    def __init__(self, engine, trail_file=None):
        self.engine = engine
        self.trail_file = trail_file          # <data>/trail.json: the trail survives a restart of the app
        self._trail_dirty = False
        self._trail_saved = 0.0
        self.clients = set()
        self.info = {}                # per client: its address, a word for the device, since when
        self._senders = {}            # per client: its _Sender
        self._loop = None
        self._unsubscribe = None
        self._status_key = None
        self._last_position = None
        self._last_sent = 0.0
        self._heartbeat_task = None
        self.trail = {}               # realm -> deque of [x, z], or None for a gap
        self.watchers = []            # called with every engine state, on the event loop (server/auto.py)

    @property
    def client_count(self):
        return len(self.clients)

    def devices(self):
        """The connected devices, longest connected first: [{"ip", "agent", "since"}]."""
        return sorted((dict(d) for d in list(self.info.values())), key=lambda d: d["since"])

    async def start(self):
        self._loop = asyncio.get_running_loop()
        self._load_trail()
        self._unsubscribe = self.engine.subscribe(
            lambda state: self._loop.call_soon_threadsafe(self.on_state, state))
        self.on_state(self.engine.state)
        self._heartbeat_task = asyncio.create_task(self._heartbeat())

    async def close_clients(self, _app=None):
        """on_shutdown: open sockets would otherwise hold shutdown for its full timeout."""
        for ws in list(self.clients):
            await ws.close(message=b"server shutdown")

    async def stop(self):
        if self._unsubscribe:
            self._unsubscribe()
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        self._save_trail()
        await self.close_clients()

    def on_state(self, state):
        key = (state.status, state.message)
        if key != self._status_key:
            self._status_key = key
            self.broadcast(status_message(state))
        if state.x is not None:
            self._last_position = position_message(state)
            self.broadcast(self._last_position)
            self._extend_trail(state)
        for watch in self.watchers:
            try:
                watch(state)
            except Exception:
                log.exception("State watcher failed")

    def _extend_trail(self, state):
        """Where the player has been in this session, so a device that connects later shows it too."""
        points = self.trail.setdefault(state.realm, deque(maxlen=TRAIL_POINTS))
        last = next((p for p in reversed(points) if p is not None), None)
        step = None if last is None else ((state.x - last[0]) ** 2 + (state.z - last[1]) ** 2) ** 0.5
        if step is not None and step < TRAIL_STEP_M:
            return
        if step is not None and step > TRAIL_JUMP_M and points[-1] is not None:
            points.append(None)
        points.append([round(state.x, 1), round(state.z, 1)])
        self._trail_dirty = True

    def _load_trail(self):
        try:
            saved = (read_json(self.trail_file, {}) or {}).get("points", {}) if self.trail_file else {}
        except (OSError, ValueError):
            saved = {}
        self.trail = {}
        for realm, points in saved.items() if isinstance(saved, dict) else ():
            ok = [p for p in points if p is None or (isinstance(p, list) and len(p) == 2)][-TRAIL_POINTS:] if isinstance(points, list) else []
            if ok:
                self.trail[realm] = deque(ok + ([None] if ok[-1] is not None else []), maxlen=TRAIL_POINTS)   # a gap before this session

    def _save_trail(self):
        if not self.trail_file or not self._trail_dirty:
            return
        self._trail_dirty = False
        self._trail_saved = time.monotonic()
        try:
            write_json(self.trail_file, {"points": {realm: list(points) for realm, points in self.trail.items()}}, indent=None)
        except OSError as e:
            log.warning("Trail not saved: %s", e)

    def trail_message(self):
        return {"type": "trail", "points": {realm: list(points) for realm, points in self.trail.items()}}

    def clear_trail(self):
        self.trail = {}
        self._trail_dirty = True
        self._save_trail()
        self.broadcast(self.trail_message())

    def broadcast(self, msg):
        self._last_sent = time.monotonic() if msg.get("type") == "position" else self._last_sent
        data = json.dumps(msg)
        position = msg.get("type") == "position"
        for sender in list(self._senders.values()):
            if position:
                sender.position = data                # replaces one the device has not been sent yet
            else:
                sender.queue.append(data)
            sender.wake.set()

    async def _heartbeat(self):
        while True:
            await asyncio.sleep(IDLE_HEARTBEAT / 2)
            if self._last_position and time.monotonic() - self._last_sent >= IDLE_HEARTBEAT:
                self.broadcast(self._last_position)
            if self._trail_dirty and time.monotonic() - self._trail_saved >= TRAIL_SAVE_S:
                self._save_trail()

    async def handle(self, request):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        self.clients.add(ws)
        self.info[ws] = {"ip": request.remote or "", "agent": device_name(request.headers.get("User-Agent", "")), "since": time.time()}
        log.info("Client connected (%d total)", len(self.clients))
        sender = self._senders[ws] = _Sender(ws)
        sender.queue.append(json.dumps(status_message(self.engine.state)))
        if self._last_position:
            sender.queue.append(json.dumps(self._last_position))
        if self.trail:
            sender.queue.append(json.dumps(self.trail_message()))
        sender.wake.set()
        sender.task = asyncio.create_task(sender.run())
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    log.debug("Ignoring client message: %.200s", msg.data)
        finally:
            sender.task.cancel()
            self._senders.pop(ws, None)
            self.clients.discard(ws)
            self.info.pop(ws, None)
            log.info("Client disconnected (%d total)", len(self.clients))
        return ws
