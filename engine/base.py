"""Common Engine interface: start(), stop(), state, subscribe().

Subclasses implement _tick() (one poll, returns the new state and how long to
wait before the next poll) and optionally _cleanup() (runs on the engine thread
when it stops). Subscribers are called on the engine thread, only when the
state changes past the thresholds below.
"""

import logging
import math
import threading

from engine.models import EngineState

log = logging.getLogger("cdlivemap.engine")

MIN_RATE_HZ = 10
MAX_RATE_HZ = 60
DEFAULT_RATE_HZ = 30


def heading_delta(a, b):
    return abs((a - b + 180.0) % 360.0 - 180.0)


def significant_change(old, new, pos_threshold, heading_threshold):
    if (old.status, old.realm, old.message, old.marker) != (new.status, new.realm, new.message, new.marker):
        return True
    if (old.x is None) != (new.x is None) or (old.heading is None) != (new.heading is None):
        return True
    if (old.camera_heading is None) != (new.camera_heading is None):
        return True
    if new.x is not None and math.dist((old.x, old.y, old.z), (new.x, new.y, new.z)) > pos_threshold:
        return True
    if new.heading is not None and heading_delta(old.heading, new.heading) > heading_threshold:
        return True
    if new.camera_heading is not None and heading_delta(old.camera_heading, new.camera_heading) > heading_threshold:
        return True
    return False


class Engine:
    def __init__(self, rate_hz=DEFAULT_RATE_HZ, pos_threshold=0.1, heading_threshold=0.5):
        self.rate_hz = min(MAX_RATE_HZ, max(MIN_RATE_HZ, rate_hz))
        self.pos_threshold = pos_threshold
        self.heading_threshold = heading_threshold
        self._state = EngineState()
        self._lock = threading.Lock()
        self._subscribers = []
        self._stop_event = threading.Event()
        self._thread = None

    @property
    def interval(self):
        return 1.0 / self.rate_hz

    @property
    def state(self):
        with self._lock:
            return self._state

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def subscribe(self, callback):
        """Call callback(state) on significant changes. Returns an unsubscribe function."""
        with self._lock:
            self._subscribers.append(callback)

        def unsubscribe():
            with self._lock:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)
        return unsubscribe

    def start(self):
        if self.running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name=type(self).__name__, daemon=True)
        self._thread.start()

    def stop(self, timeout=5.0):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def _run(self):
        try:
            while not self._stop_event.is_set():
                state, delay = self._tick()
                self._publish(state)
                self._stop_event.wait(delay)
        except Exception:
            log.exception("Engine thread crashed")
        finally:
            try:
                self._cleanup()
            except Exception:
                log.exception("Engine cleanup failed")

    def _publish(self, state):
        with self._lock:
            old, self._state = self._state, state
            subscribers = list(self._subscribers) if significant_change(
                old, state, self.pos_threshold, self.heading_threshold) else []
        for callback in subscribers:
            try:
                callback(state)
            except Exception:
                log.exception("Engine subscriber failed")

    def _tick(self):
        raise NotImplementedError

    def _cleanup(self):
        pass
