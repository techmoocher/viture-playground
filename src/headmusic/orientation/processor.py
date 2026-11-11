"""OrientationProcessor: raw pose samples -> processed samples (pure and deterministic).

The processor reads only sample fields and commands, never a clock, so feeding it the same
sequence of samples and commands always yields identical output (the basis of replay).
Definitions of every flag and threshold: docs/quality-and-metrics.md.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Optional

from headmusic.orientation import flags as F
from headmusic.orientation.euler import zyx_from_quat
from headmusic.orientation.neutral import NeutralCapture, NeutralReference
from headmusic.orientation.quaternion import angle_deg, canonical, conj, dot, mul, neg, norm
from headmusic.types import Command, ProcessedSample, RawPoseSample


@dataclass(frozen=True, slots=True)
class ProcessorConfig:
    k_gap: float = 1.5
    ts_resolution_ns: int = 1_000_000
    ref_quantile: float = 0.25
    n_ref: int = 200
    n_min: int = 20
    tau_jump_deg: float = 20.0
    tau_norm: float = 1e-3
    eps_zero: float = 1e-6
    euler_singular_deg: float = 89.0
    neutral_window_s: float = 3.0
    neutral_tau_stab_deg: float = 2.0

    @classmethod
    def from_config(cls, cfg: dict) -> "ProcessorConfig":
        f, n = cfg["flags"], cfg["neutral"]
        return cls(k_gap=float(f["k_gap"]), ts_resolution_ns=int(f["ts_resolution_ns"]),
                   ref_quantile=float(f["ref_quantile"]), n_ref=int(f["n_ref"]), n_min=int(f["n_min"]),
                   tau_jump_deg=float(f["tau_jump_deg"]), tau_norm=float(f["tau_norm"]),
                   eps_zero=float(f["eps_zero"]), euler_singular_deg=float(f["euler_singular_deg"]),
                   neutral_window_s=float(n["window_s"]), neutral_tau_stab_deg=float(n["tau_stab_deg"]))


def _quantile(values, q: float) -> float:
    """Deterministic linear-interpolation quantile (same definition as numpy's default)."""
    s = sorted(values)
    pos = (len(s) - 1) * q
    lo = math.floor(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


class OrientationProcessor:
    def __init__(self, cfg: ProcessorConfig) -> None:
        self.cfg = cfg
        self.selected_hz: Optional[float] = None
        self.reference_interval_ns: Optional[float] = None  # set => gap_reference "measured"
        self._connection_id: Optional[int] = None
        self._next_neutral_id = 1
        self._capture = NeutralCapture()
        self._reset_connection_state()

    # ------------------------------------------------------------------ configuration
    def configure_stream(self, selected_hz: Optional[float], reference_rate_hz: Optional[float]) -> dict:
        """Called once the IMU frequency is known. Returns the resolved gap reference for metadata."""
        self.selected_hz = float(selected_hz) if selected_hz else None
        self.reference_interval_ns = 1e9 / reference_rate_hz if reference_rate_hz else None
        return self.gap_reference_info()

    def gap_reference_info(self) -> dict:
        if self.reference_interval_ns is not None:
            return {"gap_reference_used": "measured", "reference_interval_ns": self.reference_interval_ns}
        return {"gap_reference_used": "adaptive", "reference_quantile": self.cfg.ref_quantile,
                "n_ref": self.cfg.n_ref, "n_min": self.cfg.n_min, "warmup_selected_hz": self.selected_hz}

    @property
    def neutral(self) -> Optional[NeutralReference]:
        return self._neutral

    # ------------------------------------------------------------------ commands
    def handle_command(self, cmd: Command) -> list[dict]:
        if cmd.kind != "capture_neutral":
            return []  # segment marks are annotations only
        window = float(cmd.data.get("window_s", self.cfg.neutral_window_s))
        tau = float(cmd.data.get("tau_stab_deg", self.cfg.neutral_tau_stab_deg))
        conn = self._connection_id if self._connection_id is not None else -1
        after = cmd.after_seq if cmd.after_seq is not None else -1
        return self._capture.request(conn, after, window, tau)

    # ------------------------------------------------------------------ samples
    def process(self, raw: RawPoseSample) -> tuple[ProcessedSample, list[dict]]:
        cfg = self.cfg
        records: list[dict] = []
        if raw.connection_id != self._connection_id:
            # A capture pending across a connection change is rejected (criterion c), including one
            # requested while disconnected; the operator retries on the new connection.
            if self._connection_id is not None:
                records += self._capture.abort("connection_changed")
            self._connection_id = raw.connection_id
            self._reset_connection_state()

        flags: set[str] = set()
        d, h = raw.device_ts_raw, raw.host_rx_monotonic_ns
        dt_device = d - self._prev_d if self._prev_d is not None else None
        dt_host = h - self._prev_h if self._prev_h is not None else None

        vals = raw.values
        q = None
        if len(vals) != 7 or not all(math.isfinite(v) for v in vals):
            flags.add(F.NONFINITE)
        else:
            q_raw = vals[3:7]
            n = norm(q_raw)
            if n < cfg.eps_zero:
                flags.add(F.ZERO_NORM)
            else:
                if abs(n - 1.0) > cfg.tau_norm:
                    flags.add(F.NORM_DEVIATION)
                q = (q_raw[0] / n, q_raw[1] / n, q_raw[2] / n, q_raw[3] / n)

        # Timestamp order relative to the most recent sample whose timestamp was in order (d_ref).
        # Using d_ref rather than the last *valid* sample means a sample with bad values but a good
        # timestamp does not create a false gap: gaps count missing callbacks, not invalid values.
        ts_bad = False
        if self._d_ref is not None:
            if d == self._d_ref:
                flags.add(F.TS_DUPLICATE)
                ts_bad = True
            elif d < self._d_ref:
                flags.add(F.TS_BACKWARD)
                ts_bad = True

        est_missing = 0
        interval = None
        if self._d_ref is not None and not ts_bad:
            interval = d - self._d_ref
            m = self._reference_interval()
            if m is not None and interval > cfg.k_gap * m + cfg.ts_resolution_ns:
                flags.add(F.GAP_BEFORE)
                est_missing = max(0, int(round(interval / m)) - 1)

        # Glitch detector: a jump is flagged only if q is far from BOTH the last valid sample and the
        # previous finite sample. A one-sample glitch then flags one sample (the return is close to
        # the last valid one) and a persistent jump also flags only one (the next sample is close to
        # the previous finite one).
        if q is not None and self._last_sdk_q is not None and dot(q, self._last_sdk_q) < 0.0:
            # The SDK keeps w >= 0 (observed 2026-11-10), so its sign jumps whenever w passes 0.
            # Flag the event once; the processed stream below is always made continuous.
            flags.add(F.HEMISPHERE_FLIP)
        if q is not None:
            self._last_sdk_q = q
        if q is not None and self._last_q is not None:
            if dot(q, self._last_q) < 0.0:
                q = neg(q)
            if (angle_deg(self._last_q, q) > cfg.tau_jump_deg and
                    (self._last_valid_q is None or angle_deg(self._last_valid_q, q) > cfg.tau_jump_deg)):
                flags.add(F.ANGULAR_JUMP)
        if q is not None:
            self._last_q = q

        valid = not (flags & F.INVALIDATING)
        if not ts_bad:
            if interval is not None:
                self._intervals.append(interval)
            self._d_ref = d
        if valid:
            self._last_valid_q = q
        self._prev_d, self._prev_h = d, h

        # Neutral capture sees this sample (it may close the window and apply from this sample).
        recs, ref = self._capture.feed(raw.seq, d, q, valid, flags, self._next_neutral_id, raw.connection_id)
        records += recs
        if ref is not None:
            self._neutral = ref
            self._next_neutral_id += 1

        q_rel = euler = None
        if self._neutral is None:
            flags.add(F.NO_NEUTRAL)
        elif q is not None:
            q_rel = canonical(mul(conj(self._neutral.q0), q))
            euler = zyx_from_quat(q_rel)
            if abs(euler[1]) > cfg.euler_singular_deg:
                flags.add(F.EULER_NEAR_SINGULAR)

        ps = ProcessedSample(
            seq=raw.seq, connection_id=raw.connection_id, host_rx_monotonic_ns=h, device_ts_raw=d,
            dt_device_ns=dt_device, dt_host_ns=dt_host, quat=q, quat_rel=q_rel, euler_display=euler,
            valid=valid, flags=tuple(sorted(flags)),
            neutral_calibration_id=self._neutral.neutral_calibration_id if self._neutral else None,
            gap_est_missing=est_missing)
        return ps, records

    # ------------------------------------------------------------------ internals
    def _reset_connection_state(self) -> None:
        self._d_ref: Optional[int] = None  # device ts of the last sample whose timestamp was in order
        self._prev_d: Optional[int] = None
        self._prev_h: Optional[int] = None
        self._last_q = None  # previous finite (normalised, continuity-aligned) quaternion
        self._last_sdk_q = None  # previous finite normalised quaternion with the SDK's own sign
        self._last_valid_q = None
        self._intervals: deque = deque(maxlen=self.cfg.n_ref)
        self._neutral: Optional[NeutralReference] = None  # a new connection needs a new neutral (O5)

    def _reference_interval(self) -> Optional[float]:
        if self.reference_interval_ns is not None:
            return self.reference_interval_ns
        if len(self._intervals) >= self.cfg.n_min:
            return _quantile(self._intervals, self.cfg.ref_quantile)
        if self.selected_hz:
            return 1e9 / self.selected_hz
        return None
