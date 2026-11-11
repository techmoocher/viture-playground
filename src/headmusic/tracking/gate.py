"""TrackingGate — the single sanctioned check before any future module acts on head orientation.

    usable_for_control(now) := connected
                               ∧ a valid sample has been received on this connection
                               ∧ the most recent sample is valid
                               ∧ not stale(now)            (now − host_rx(last valid) <= T_stale)
                               ∧ an accepted neutral reference exists for this connection

Validity is a property of each received sample (orientation.flags). Staleness is a property of
the stream at query time and is never stored on samples. Phase 1 has no command producers; it
displays and logs the gate state. Invalid or stale tracking must never trigger musical commands.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional

from headmusic.types import Event, ProcessedSample

DISCONNECTED = "disconnected"
NO_VALID_SAMPLE = "no_valid_sample"
LAST_SAMPLE_INVALID = "last_sample_invalid"
STALE = "stale"
NO_NEUTRAL = "no_neutral"


@dataclass(frozen=True, slots=True)
class GateStatus:
    usable: bool
    reasons: tuple[str, ...]
    age_ns: Optional[int]  # now − host_rx of the last valid sample


class TrackingGate:
    def __init__(self, t_stale_ns: int) -> None:
        self.t_stale_ns = int(t_stale_ns)
        self._lock = threading.Lock()
        self._connected = False
        self._connection_id: Optional[int] = None
        self._last_valid_host_ns: Optional[int] = None
        self._last_sample_valid = False
        self._neutral_ok = False

    def on_event(self, event: Event) -> None:
        with self._lock:
            if event.kind == "device_connected":
                self._connected = True
                self._connection_id = event.data.get("connection_id")
                self._last_valid_host_ns = None
                self._last_sample_valid = False
                self._neutral_ok = False
            elif event.kind == "device_disconnected":
                self._connected = False
                self._last_sample_valid = False
                self._neutral_ok = False

    def on_sample(self, ps: ProcessedSample) -> None:
        with self._lock:
            if self._connection_id is not None and ps.connection_id != self._connection_id:
                return  # late sample from a previous connection
            self._last_sample_valid = ps.valid
            if ps.valid:
                self._last_valid_host_ns = ps.host_rx_monotonic_ns
                self._neutral_ok = ps.quat_rel is not None

    def status(self, now_ns: int) -> GateStatus:
        with self._lock:
            reasons = []
            age = None if self._last_valid_host_ns is None else now_ns - self._last_valid_host_ns
            if not self._connected:
                reasons.append(DISCONNECTED)
            if self._last_valid_host_ns is None:
                reasons.append(NO_VALID_SAMPLE)
            else:
                if not self._last_sample_valid:
                    reasons.append(LAST_SAMPLE_INVALID)
                if age > self.t_stale_ns:
                    reasons.append(STALE)
            if not self._neutral_ok:
                reasons.append(NO_NEUTRAL)
            return GateStatus(usable=not reasons, reasons=tuple(reasons), age_ns=age)

    def usable_for_control(self, now_ns: int) -> bool:
        return self.status(now_ns).usable
