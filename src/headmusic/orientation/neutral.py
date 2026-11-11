"""Neutral-reference capture with a stability check and retries (docs/quality-and-metrics.md §Neutral).

1. A capture request arrives as a command; samples AFTER it are collected until the device-clock
   span since the first collected sample exceeds window_s. The sample that closes the window is
   not part of it; if the capture is accepted, the new neutral applies from that sample on.
2. Acceptance requires: (a) every window sample valid, (b) no gap_before inside the window,
   (c) no connection change during the capture, (d) dispersion max_i θ(q_i, q0) <= tau_stab_deg.
3. q0 = normalised sign-aligned mean of the window quaternions. RMS dispersion is also logged.
4. Retries are unlimited and operator-initiated; every attempt produces one record.
All thresholds are provisional engineering defaults, not validated limits.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional

from headmusic.orientation import flags as F
from headmusic.orientation.quaternion import angle_deg, mean_sign_aligned
from headmusic.types import Quat


@dataclass(frozen=True, slots=True)
class NeutralReference:
    neutral_calibration_id: int
    connection_id: int
    q0: Quat
    applies_from_seq: int


@dataclass(slots=True)
class _Capture:
    attempt: int
    connection_id: int
    requested_after_seq: int
    window_ns: int
    window_s: float
    tau_stab_deg: float
    first_d: Optional[int] = None
    first_seq: Optional[int] = None
    last_seq: Optional[int] = None
    last_d: Optional[int] = None
    n: int = 0
    n_invalid: int = 0
    n_gaps: int = 0
    quats: list = field(default_factory=list)


class NeutralCapture:
    """State machine for one connection's neutral captures. Deterministic: device clock only."""

    def __init__(self) -> None:
        self._active: Optional[_Capture] = None
        self._attempts = 0

    @property
    def active(self) -> bool:
        return self._active is not None

    def request(self, connection_id: int, after_seq: int, window_s: float, tau_stab_deg: float) -> list[dict]:
        self._attempts += 1
        if self._active is not None:
            return [self._record(self._new(connection_id, after_seq, window_s, tau_stab_deg),
                                 accepted=False, reasons=["capture_in_progress"])]
        self._active = self._new(connection_id, after_seq, window_s, tau_stab_deg)
        return []

    def abort(self, reason: str) -> list[dict]:
        if self._active is None:
            return []
        rec = self._record(self._active, accepted=False, reasons=[reason])
        self._active = None
        return [rec]

    def feed(self, seq: int, device_ts: int, q: Optional[Quat], valid: bool, flags: set[str],
             next_neutral_id: int, connection_id: int) -> tuple[list[dict], Optional[NeutralReference]]:
        """Offer one sample. Returns (records, accepted reference or None)."""
        c = self._active
        if c is None:
            return [], None
        if c.connection_id == -1:  # requested before the first sample of the stream
            c.connection_id = connection_id
        if c.first_d is not None and device_ts - c.first_d > c.window_ns and c.n > 0:
            return self._close(c, closing_seq=seq, next_neutral_id=next_neutral_id)
        if c.first_d is None:
            c.first_d, c.first_seq = device_ts, seq
        c.n += 1
        c.last_seq, c.last_d = seq, device_ts
        if not valid:
            c.n_invalid += 1
        if F.GAP_BEFORE in flags and c.n > 1:  # a gap into the first window sample is outside the window
            c.n_gaps += 1
        if valid and q is not None:
            c.quats.append(q)
        return [], None

    # ------------------------------------------------------------------ internals
    def _new(self, connection_id, after_seq, window_s, tau) -> _Capture:
        return _Capture(attempt=self._attempts, connection_id=connection_id, requested_after_seq=after_seq,
                        window_ns=int(round(window_s * 1e9)), window_s=float(window_s), tau_stab_deg=float(tau))

    def _close(self, c: _Capture, closing_seq: int, next_neutral_id: int):
        self._active = None
        reasons = []
        q0 = None
        d_max = d_rms = None
        if c.n_invalid:
            reasons.append("invalid_samples_in_window")
        if c.n_gaps:
            reasons.append("gap_in_window")
        if not c.quats:
            reasons.append("no_valid_samples")
        else:
            q0 = mean_sign_aligned(c.quats)
            dev = [angle_deg(q, q0) for q in c.quats]
            d_max = max(dev)
            d_rms = math.sqrt(sum(v * v for v in dev) / len(dev))
            if d_max > c.tau_stab_deg:
                reasons.append("dispersion_exceeds_tau_stab")
        accepted = not reasons
        ref = None
        if accepted:
            ref = NeutralReference(next_neutral_id, c.connection_id, q0, closing_seq)
        rec = self._record(c, accepted=accepted, reasons=reasons, q0=q0, d_max=d_max, d_rms=d_rms,
                           neutral_id=next_neutral_id if accepted else None,
                           applies_from_seq=closing_seq if accepted else None)
        return [rec], ref

    @staticmethod
    def _record(c: _Capture, accepted: bool, reasons: list[str], q0=None, d_max=None, d_rms=None,
                neutral_id=None, applies_from_seq=None) -> dict[str, Any]:
        return {
            "type": "neutral_capture",
            "attempt": c.attempt,
            "connection_id": c.connection_id,
            "requested_after_seq": c.requested_after_seq,
            "window_s": c.window_s,
            "tau_stab_deg": c.tau_stab_deg,
            "window_first_seq": c.first_seq,
            "window_last_seq": c.last_seq,
            "window_first_device_ts": c.first_d,
            "window_last_device_ts": c.last_d,
            "n_samples": c.n,
            "n_valid_used": len(c.quats),
            "n_invalid": c.n_invalid,
            "n_gaps": c.n_gaps,
            "q0_wxyz": list(q0) if q0 is not None else None,
            "dispersion_max_deg": d_max,
            "dispersion_rms_deg": d_rms,
            "accepted": accepted,
            "reasons": reasons,
            "neutral_calibration_id": neutral_id,
            "applies_from_seq": applies_from_seq,
        }
