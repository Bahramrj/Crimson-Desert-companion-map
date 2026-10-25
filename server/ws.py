"""WebSocket hub: fans engine state out to the device shell.

Message `position` carries game x/y/z, realm and heading; the local map works in game units.
Incoming messages are never acted on: there is nothing a client can ask the engine to do.
"""

import asyncio
import json
import logging
import time

from aiohttp import WSMsgType, web


log = logging.getLogger("cdlivemap.server")

IDLE_HEARTBEAT = 1.0   # resend the last position when nothing changed


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


def status_message(state):
    return {"type": "status", "status": state.status, "message": state.message}


class Hub:
    def __init__(self, engine):
        self.engine = engine
        self.clients = set()
        self._loop = None
        self._unsubscribe = None
        self._status_key = None
        self._last_position = None
        self._last_sent = 0.0
        self._heartbeat_task = None

    @property
    def client_count(self):
        return len(self.clients)

    async def start(self):
        self._loop = asyncio.get_running_loop()
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
        await self.close_clients()

    def on_state(self, state):
        key = (state.status, state.message)
        if key != self._status_key:
            self._status_key = key
            self.broadcast(status_message(state))
        if state.x is not None:
            self._last_position = position_message(state)
            self.broadcast(self._last_position)

    def broadcast(self, msg):
        self._last_sent = time.monotonic() if msg.get("type") == "position" else self._last_sent
        data = json.dumps(msg)
        for ws in list(self.clients):
            if not ws.closed:
                asyncio.ensure_future(self._send(ws, data))

    async def _send(self, ws, data):
        try:
            await ws.send_str(data)
        except (ConnectionError, RuntimeError):
            self.clients.discard(ws)

    async def _heartbeat(self):
        while True:
            await asyncio.sleep(IDLE_HEARTBEAT / 2)
            if self._last_position and time.monotonic() - self._last_sent >= IDLE_HEARTBEAT:
                self.broadcast(self._last_position)

    async def handle(self, request):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        self.clients.add(ws)
        log.info("Client connected (%d total)", len(self.clients))
        await ws.send_str(json.dumps(status_message(self.engine.state)))
        if self._last_position:
            await ws.send_str(json.dumps(self._last_position))
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    log.debug("Ignoring client message: %.200s", msg.data)
        finally:
            self.clients.discard(ws)
            log.info("Client disconnected (%d total)", len(self.clients))
        return ws
