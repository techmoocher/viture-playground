"""Pipeline: one consumer thread that orders and routes everything.

    source(s) / UI ──► queue ──► [pipeline thread]
                                   RawPoseSample → raw writer (first) → processor → processed writer,
                                                   calibration records, gate, live state
                                   RawImuSample  → raw IMU writer, live counters
                                   Event         → event log, gate, stream configuration
                                   Command       → after_seq assigned, command log, processor

Commands are positioned between samples by the queue order, logged with `after_seq`, and
re-injected at the same place on replay, so processing is deterministic.
"""
from __future__ import annotations

import queue
import threading
from collections import deque
from typing import Callable, Optional

from headmusic.config import reference_rate_hz
from headmusic.orientation.processor import OrientationProcessor
from headmusic.recording.writer import SessionWriter
from headmusic.tracking.gate import GateStatus, TrackingGate
from headmusic.types import Command, Event, ProcessedSample, RawImuSample, RawPoseSample

_STOP = object()


class Pipeline:
    def __init__(self, cfg: dict, processor: OrientationProcessor, gate: TrackingGate,
                 writer: Optional[SessionWriter], clock: Optional[Callable[[], int]], history_s: float = 12.0,
                 fixed_stream_config: Optional[dict] = None) -> None:
        """clock=None: virtual time = host time of the last processed sample (offline processing)."""
        self.cfg = cfg
        self.processor = processor
        self.gate = gate
        self.writer = writer
        self.clock = clock if clock is not None else (lambda: self._last_rx or 0)
        self.stream_info: dict = {}
        self.q: queue.Queue = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._history: deque = deque(maxlen=int(history_s * 300))  # live view only (~12 s at ≤ 300 Hz)
        self._last_seq = -1
        self._last_rx: Optional[int] = None
        self._stale = False
        self._fixed_stream_config = fixed_stream_config
        self.t_stale_ns = int(cfg["gate"]["t_stale_ms"] * 1_000_000)
        self.stats = {"pose_samples": 0, "imu_samples": 0, "valid": 0, "invalid": 0, "gaps": 0,
                      "est_missing": 0, "neutral_attempts": 0, "neutral_accepted": 0, "max_queue": 0,
                      "connected": False, "connection_id": None, "device": {}, "last_neutral": None,
                      "last_event": None, "source_finished": False}
        self._rate_window: deque = deque(maxlen=400)
        if fixed_stream_config:
            self._apply_stream_config(fixed_stream_config)

    # ------------------------------------------------------------------ producer API (any thread)
    def put(self, item) -> None:
        self.q.put(item)

    def submit_command(self, kind: str, **data) -> None:
        self.q.put(Command(kind, self.clock(), data))

    # ------------------------------------------------------------------ consumer
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="pipeline", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        """Process everything already queued, then stop."""
        self.q.put(_STOP)
        if self._thread:
            self._thread.join(timeout)

    def process_all(self, items) -> None:
        """Synchronous processing (replay --reprocess, tests)."""
        for item in items:
            self._handle(item)

    def _run(self) -> None:
        while True:
            try:
                item = self.q.get(timeout=0.02)
            except queue.Empty:
                self._check_stale()
                continue
            if item is _STOP:
                return
            self._handle(item)
            qs = self.q.qsize()
            if qs > self.stats["max_queue"]:
                self.stats["max_queue"] = qs

    def _handle(self, item) -> None:
        if isinstance(item, RawPoseSample):
            self._on_pose(item)
        elif isinstance(item, RawImuSample):
            if self.writer:
                self.writer.write_raw_imu(item)
            self._last_rx = item.host_rx_monotonic_ns
            with self._lock:
                self.stats["imu_samples"] += 1
                self._rate_window.append(item.device_ts_raw)
        elif isinstance(item, Command):
            self._on_command(item)
        elif isinstance(item, Event):
            self._on_event(item)
        self._check_stale()

    def _on_pose(self, s: RawPoseSample) -> None:
        if self.writer:
            self.writer.write_raw_pose(s)  # raw first: processing can never corrupt raw data
        ps, records = self.processor.process(s)
        if self.writer:
            self.writer.write_processed(ps)
        self._last_seq = s.seq
        self.gate.on_sample(ps)
        if ps.valid:
            self._last_rx = ps.host_rx_monotonic_ns
        self._records(records)
        with self._lock:
            st = self.stats
            st["pose_samples"] += 1
            st["valid" if ps.valid else "invalid"] += 1
            if ps.gap_est_missing or "gap_before" in ps.flags:
                st["gaps"] += 1
                st["est_missing"] += ps.gap_est_missing
            self._history.append(ps)
            self._rate_window.append(ps.device_ts_raw)

    def _records(self, records: list[dict]) -> None:
        for r in records:
            if self.writer:
                self.writer.write_calibration(r)
            with self._lock:
                self.stats["neutral_attempts"] += 1
                self.stats["neutral_accepted"] += 1 if r.get("accepted") else 0
                self.stats["last_neutral"] = r

    def _on_command(self, c: Command) -> None:
        if c.after_seq is None:
            c.after_seq = self._last_seq
        if self.writer:
            self.writer.write_command(c)
        self._records(self.processor.handle_command(c))

    def _on_event(self, e: Event) -> None:
        if self.writer:
            self.writer.write_event(e, self._last_seq)
        self.gate.on_event(e)
        with self._lock:
            if e.kind != "sdk_log":
                self.stats["last_event"] = (e.kind, e.data)
            if e.kind == "device_connected":
                self.stats["connected"] = True
                self.stats["connection_id"] = e.data.get("connection_id")
                self.stats["device"] = {k: e.data.get(k) for k in (
                    "market_name", "pid", "firmware", "frequency_selected_hz", "frequency_requested_hz",
                    "frequency_selection_reason", "mode")}
            elif e.kind == "device_disconnected":
                self.stats["connected"] = False
            elif e.kind == "source_stopped":
                self.stats["source_finished"] = True
        if e.kind == "device_connected" and self._fixed_stream_config is None:
            self._configure_from_device(e.data)

    def _configure_from_device(self, d: dict) -> None:
        mode, hz = d.get("mode"), d.get("frequency_selected_hz")
        ref = reference_rate_hz(self.cfg, mode, hz) if self.cfg["flags"]["gap_reference"] == "measured" else None
        info = self._apply_stream_config({"selected_hz": hz, "reference_rate_hz": ref})
        if self.writer:
            device = {k: v for k, v in d.items() if k not in ("frequency_support",)}
            self.writer.update_meta(
                device=device,
                imu={"mode": mode, "frequency_requested_hz": d.get("frequency_requested_hz"),
                     "frequency_selected_hz": hz, "frequency_selection_reason": d.get("frequency_selection_reason"),
                     "frequency_support": d.get("frequency_support")},
                processing=info)

    def _apply_stream_config(self, sc: dict) -> dict:
        info = self.processor.configure_stream(sc.get("selected_hz"), sc.get("reference_rate_hz"))
        info = {"selected_hz": sc.get("selected_hz"), "reference_rate_hz": sc.get("reference_rate_hz"), **info}
        self.stream_info = info
        return info

    def _check_stale(self) -> None:
        if self._last_rx is None:
            return
        now = self.clock()
        stale = now - self._last_rx > self.t_stale_ns
        if stale != self._stale:
            self._stale = stale
            e = Event("stale_begin" if stale else "stale_end", now,
                      {"age_ms": round((now - self._last_rx) / 1e6, 3), "t_stale_ms": self.cfg["gate"]["t_stale_ms"]})
            if self.writer:
                self.writer.write_event(e, self._last_seq)

    # ------------------------------------------------------------------ live state (any thread)
    def snapshot(self, seconds: float = 10.0) -> tuple[list[ProcessedSample], dict, GateStatus]:
        now = self.clock()
        with self._lock:
            hist = list(self._history)
            stats = dict(self.stats)
            rw = list(self._rate_window)
        if hist:
            cutoff = hist[-1].host_rx_monotonic_ns - int(seconds * 1e9)
            hist = [p for p in hist if p.host_rx_monotonic_ns >= cutoff]
        stats["observed_rate_hz"] = ((len(rw) - 1) / ((rw[-1] - rw[0]) / 1e9)) if len(rw) > 10 and rw[-1] > rw[0] else None
        return hist, stats, self.gate.status(now)
