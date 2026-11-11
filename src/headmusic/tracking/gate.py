"""TrackingGate — the single sanctioned check before any future module acts on head orientation.

    usable_for_control(now) := connected
                               ∧ a valid sample has been received on this connection
                               ∧ the most recent sample is valid
                               ∧ not stale(now)            (data age of the last valid sample <= T_stale)
                               ∧ an accepted neutral reference exists for this connection

Data age is measured from when the sample was *produced*, not from when it arrived. G0 run R9 (2026-11-11)
showed why: after a PC sleep, a sample produced before the sleep arrived 29.9 s late, and an arrival-time rule
would have treated it as fresh. The production time is estimated on the host clock as device_ts + o_min.
- o = host_rx − device_ts is each valid sample's clock offset.
- o_min is its running minimum on this connection: the least-delayed arrivals.
- o_min may rise by at most `offset_drift_ppm` of the elapsed host time, so a slow relative clock drift is
  followed (G0 measured 12–17 ppm), while a late sample stays late.
- data age = now − (device_ts + o_min) = arrival age + lateness (o − o_min).
The offset baseline resets with each connection, because the device clock restarts on replug (G0 R7).
Assumption: the host clock keeps counting during PC sleep (QPC did in R9).

Validity is a property of each received sample (orientation.flags). Staleness is a property of the stream at
query time and is never stored on samples. Phase 1 has no command producers; it displays and logs the gate
state. Invalid or stale tracking must never trigger musical commands.
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

DEFAULT_OFFSET_DRIFT_PPM = 200.0  # provisional engineering default (docs/quality-and-metrics.md)


@dataclass(frozen=True, slots=True)
class GateStatus:
    usable: bool
    reasons: tuple[str, ...]
    age_ns: Optional[int]  # data age of the last valid sample: now − estimated production time
    lateness_ns: Optional[int] = None  # how late the last valid sample arrived vs the offset baseline


class TrackingGate:
    def __init__(self, t_stale_ns: int, offset_drift_ppm: float = DEFAULT_OFFSET_DRIFT_PPM) -> None:
        self.t_stale_ns = int(t_stale_ns)
        self.offset_drift_ppm = float(offset_drift_ppm)
        self._lock = threading.Lock()
        self._connected = False
        self._connection_id: Optional[int] = None
        self._neutral_ok = False
        self._reset_samples()

    @classmethod
    def from_config(cls, cfg: dict) -> "TrackingGate":
        g = cfg["gate"]
        return cls(int(float(g["t_stale_ms"]) * 1_000_000), float(g.get("offset_drift_ppm", DEFAULT_OFFSET_DRIFT_PPM)))

    def _reset_samples(self) -> None:
        self._last_valid_produced_ns: Optional[float] = None
        self._last_lateness_ns: Optional[float] = None
        self._last_sample_valid = False
        self._o_min: Optional[float] = None
        self._o_last_host: Optional[int] = None

    def on_event(self, event: Event) -> None:
        with self._lock:
            if event.kind == "device_connected":
                self._connected = True
                self._connection_id = event.data.get("connection_id")
                self._neutral_ok = False
                self._reset_samples()
            elif event.kind == "device_disconnected":
                self._connected = False
                self._last_sample_valid = False
                self._neutral_ok = False

    def on_sample(self, ps: ProcessedSample) -> None:
        with self._lock:
            if self._connection_id is not None and ps.connection_id != self._connection_id:
                return  # late sample from a previous connection
            self._last_sample_valid = ps.valid
            if not ps.valid:
                return  # invalid timestamps (duplicate, backward) never move the offset baseline
            host, dev = ps.host_rx_monotonic_ns, ps.device_ts_raw
            o = float(host - dev)
            if self._o_min is None:
                self._o_min = o
            else:
                elapsed = max(0, host - self._o_last_host)
                self._o_min = min(o, self._o_min + elapsed * self.offset_drift_ppm * 1e-6)
            self._o_last_host = host
            self._last_valid_produced_ns = dev + self._o_min
            self._last_lateness_ns = o - self._o_min
            self._neutral_ok = ps.quat_rel is not None

    def status(self, now_ns: int) -> GateStatus:
        with self._lock:
            reasons = []
            produced = self._last_valid_produced_ns
            age = None if produced is None else int(round(now_ns - produced))
            if not self._connected:
                reasons.append(DISCONNECTED)
            if produced is None:
                reasons.append(NO_VALID_SAMPLE)
            else:
                if not self._last_sample_valid:
                    reasons.append(LAST_SAMPLE_INVALID)
                if age > self.t_stale_ns:
                    reasons.append(STALE)
            if not self._neutral_ok:
                reasons.append(NO_NEUTRAL)
            late = None if self._last_lateness_ns is None else int(round(self._last_lateness_ns))
            return GateStatus(usable=not reasons, reasons=tuple(reasons), age_ns=age, lateness_ns=late)

    def usable_for_control(self, now_ns: int) -> bool:
        return self.status(now_ns).usable
