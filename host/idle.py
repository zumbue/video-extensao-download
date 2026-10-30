"""Encerra o processo quando ninguém está baixando."""

import threading
import time


class IdleWatch:
    def __init__(self, on_idle, idle_seconds=90, settled_seconds=30, busy=None, enabled=True):
        self.enabled = enabled
        self.idle_seconds = idle_seconds
        self.settled_seconds = settled_seconds
        self._on_idle = on_idle
        self.busy_check = busy
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._deadline = None
        self._settled = False
        self._fired = False
        if enabled:
            threading.Thread(target=self._loop, daemon=True).start()

    def touch(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            seconds = self.settled_seconds if self._settled else self.idle_seconds
            self._deadline = time.monotonic() + seconds

    def pause(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._deadline = None

    def note_settled(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._settled = True
            self._deadline = time.monotonic() + self.settled_seconds

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(0.2):
            if self.busy_check is not None and self.busy_check():
                continue
            with self._lock:
                deadline = self._deadline
                fired = self._fired
            if fired or deadline is None or time.monotonic() < deadline:
                continue
            with self._lock:
                if self._fired:
                    return
                self._fired = True
            self._on_idle()
            return
