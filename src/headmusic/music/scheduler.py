"""A small timer thread for future MIDI actions (accompaniment clicks, quantized chord onsets).

Due times are on the given clock's timebase (live: perf_counter_ns; real-time replay: the recording's host
timebase). An action whose due time has already passed runs as soon as possible; its lateness is reported.
"""
from __future__ import annotations

import heapq
import itertools
import threading
from typing import Callable, Optional


class Scheduler:
    def __init__(self, clock: Callable[[], int], on_error: Optional[Callable[[BaseException], None]] = None) -> None:
        self.clock = clock
        self.on_error = on_error
        self._heap: list = []
        self._cancelled: set[int] = set()
        self._ids = itertools.count(1)
        self._cv = threading.Condition()
        self._stop = False
        self._thread = threading.Thread(target=self._run, name="music-scheduler", daemon=True)
        self._thread.start()

    def at(self, due_ns: int, fn: Callable[[int], None]) -> int:
        """Run fn(lateness_ns) at due_ns. Returns a token for cancel()."""
        token = next(self._ids)
        with self._cv:
            heapq.heappush(self._heap, (int(due_ns), token, fn))
            self._cv.notify()
        return token

    def cancel(self, token: Optional[int]) -> None:
        if token is not None:
            with self._cv:
                self._cancelled.add(token)

    def cancel_all(self) -> None:
        with self._cv:
            self._cancelled.update(t for _, t, _ in self._heap)

    def pending(self) -> int:
        with self._cv:
            return sum(1 for _, t, _ in self._heap if t not in self._cancelled)

    def stop(self, timeout: float = 2.0) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify()
        self._thread.join(timeout)

    def _run(self) -> None:
        while True:
            with self._cv:
                while not self._stop:
                    while self._heap and self._heap[0][1] in self._cancelled:
                        _, t, _ = heapq.heappop(self._heap)
                        self._cancelled.discard(t)
                    if self._heap:
                        wait = (self._heap[0][0] - self.clock()) / 1e9
                        if wait <= 0:
                            break
                        self._cv.wait(min(wait, 0.05))
                    else:
                        self._cv.wait(0.05)
                if self._stop:
                    return
                due, token, fn = heapq.heappop(self._heap)
            try:
                fn(self.clock() - due)
            except Exception as exc:  # noqa: BLE001
                if self.on_error:
                    self.on_error(exc)
