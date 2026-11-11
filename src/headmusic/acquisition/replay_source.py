"""ReplaySource — re-emit a recorded session without glasses, in the original order.

Items: device_connected/device_disconnected events and operator commands are re-injected at the
recorded sample positions (`last_seq` / `after_seq`); samples come from raw_pose.csv (or
raw_imu.csv) and are bit-identical to the live ones (float32 round trip, see recording.schema).
Feeding these items to the same processor reproduces the processed output exactly.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable, Iterator, Optional

from headmusic.recording.reader import iter_raw_imu, iter_raw_pose, load_meta, read_jsonl
from headmusic.types import Command, Event, RawPoseSample

REPLAYED_EVENT_KINDS = ("device_connected", "device_disconnected")


class ReplaySource:
    def __init__(self, session_dir: Path, sink: Optional[Callable[[object], None]] = None,
                 speed: Optional[float] = None) -> None:
        self.dir = Path(session_dir)
        self.meta = load_meta(self.dir)
        self.sink = sink
        self.speed = speed  # None = as fast as possible
        self._stop = threading.Event()
        self.finished = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._virtual_now: Optional[int] = None
        self._real_t0 = self._orig_t0 = None

    @property
    def stream_config(self) -> dict:
        """Gap reference resolved by the live session (reproduce it, not today's defaults)."""
        return dict(self.meta.get("processing", {}))

    @property
    def config_snapshot(self) -> Optional[dict]:
        return self.meta.get("config")

    def items(self) -> Iterator[object]:
        inserts = []
        for e in read_jsonl(self.dir / "events.jsonl"):
            if e["kind"] in REPLAYED_EVENT_KINDS:
                pos = e.get("last_seq")
                inserts.append((-1 if pos is None else pos, e["host_monotonic_ns"], 0,
                                Event(e["kind"], e["host_monotonic_ns"], e.get("data", {}))))
        for c in read_jsonl(self.dir / "commands.jsonl"):
            pos = c.get("after_seq")
            inserts.append((-1 if pos is None else pos, c["host_monotonic_ns"], 1,
                            Command(c["kind"], c["host_monotonic_ns"], c.get("data", {}), after_seq=pos)))
        inserts.sort(key=lambda t: (t[0], t[1], t[2]))
        k = 0
        while k < len(inserts) and inserts[k][0] < 0:
            yield inserts[k][3]
            k += 1
        raw_pose = self.dir / "raw_pose.csv"
        samples = iter_raw_pose(raw_pose) if raw_pose.exists() else iter_raw_imu(self.dir / "raw_imu.csv")
        for s in samples:
            yield s
            while k < len(inserts) and inserts[k][0] <= s.seq:
                yield inserts[k][3]
                k += 1
        while k < len(inserts):
            yield inserts[k][3]
            k += 1

    # ------------------------------------------------------------------ threaded playback
    def clock(self) -> int:
        """Virtual 'now' in the recording's host timebase (for staleness and the gate)."""
        if self.speed is None or self._real_t0 is None:
            return self._virtual_now or 0
        return self._orig_t0 + int((time.perf_counter_ns() - self._real_t0) * self.speed)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="replay", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)

    def _run(self) -> None:
        try:
            for item in self.items():
                if self._stop.is_set():
                    break
                t = getattr(item, "host_rx_monotonic_ns", None)
                if t is not None:
                    if self._real_t0 is None:
                        self._real_t0, self._orig_t0 = time.perf_counter_ns(), t
                    if self.speed:
                        due = self._real_t0 + (t - self._orig_t0) / self.speed
                        delay = (due - time.perf_counter_ns()) / 1e9
                        if delay > 0:
                            self._stop.wait(delay)
                    self._virtual_now = t
                self.sink(item)
        finally:
            self.finished.set()
