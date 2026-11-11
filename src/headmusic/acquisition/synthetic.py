"""Deterministic synthetic traces for tests, demos and replay (no glasses needed).

Samples mimic the SDK stream: float32-rounded values, device timestamps quantised to the
measured 1 ms resolution, host arrival = device time + offset + small latency. The SDK Euler
fields are filled from our own Z-Y'-X'' conversion (the SDK's own order is undocumented), so
synthetic SDK Euler values are plausible placeholders only. Sessions written from synthetic
traces are marked source.kind = "synthetic".
"""
from __future__ import annotations

import math
import random
import struct
from dataclasses import dataclass, field
from typing import Callable, Optional

from headmusic.orientation.euler import quat_from_zyx, zyx_from_quat
from headmusic.orientation.quaternion import mul, neg
from headmusic.types import Command, Event, Quat, RawPoseSample

_F32 = struct.Struct("<f")
DEVICE_T0 = 5_595_861_000_000  # ns; similar magnitude to the real device clock
HOST_T0 = 1_000_000_000_000


def f32(x: float) -> float:
    return _F32.unpack(_F32.pack(x))[0]


@dataclass
class Trace:
    samples: list[RawPoseSample]
    commands: list[Command] = field(default_factory=list)  # after_seq already set
    events: list[Event] = field(default_factory=list)  # data["last_seq"] holds the position
    info: dict = field(default_factory=dict)

    def items(self) -> list[object]:
        """Interleave events/commands at their positions, like ReplaySource.items()."""
        inserts = sorted([(e.data.get("last_seq", -1), 0, e) for e in self.events] +
                         [(c.after_seq, 1, c) for c in self.commands], key=lambda t: (t[0], t[1]))
        out, k = [], 0
        while k < len(inserts) and inserts[k][0] < 0:
            out.append(inserts[k][2]); k += 1
        for s in self.samples:
            out.append(s)
            while k < len(inserts) and inserts[k][0] <= s.seq:
                out.append(inserts[k][2]); k += 1
        out.extend(t[2] for t in inserts[k:])
        return out


def _sample(seq, conn, host, dev, q: Quat) -> RawPoseSample:
    yaw, pitch, roll = zyx_from_quat(q)
    vals = (roll, pitch, yaw, *q)
    return RawPoseSample(seq, conn, int(host), int(dev), tuple(f32(v) for v in vals))


def generate(duration_s: float = 10.0, rate_hz: float = 202.5, orientation: Optional[Callable[[float], Quat]] = None,
             noise_deg: float = 0.0, seed: int = 0, connection_id: int = 1, seq0: int = 0,
             ts_resolution_ns: int = 1_000_000, device_t0: int = DEVICE_T0, host_t0: int = HOST_T0,
             latency_ns: tuple[float, float] = (300_000.0, 60_000.0), skew_ppm: float = 0.0) -> list[RawPoseSample]:
    rng = random.Random(seed)
    orientation = orientation or (lambda t: (1.0, 0.0, 0.0, 0.0))
    n = int(duration_s * rate_hz)
    out = []
    for i in range(n):
        t = i / rate_hz
        q = orientation(t)
        if noise_deg:
            q = mul(q, quat_from_zyx(rng.gauss(0, noise_deg), rng.gauss(0, noise_deg), rng.gauss(0, noise_deg)))
        dev = device_t0 + (int(t * 1e9) // ts_resolution_ns) * ts_resolution_ns
        host = host_t0 + t * 1e9 * (1 + skew_ppm * 1e-6) + max(0.0, rng.gauss(*latency_ns))
        out.append(_sample(seq0 + i, connection_id, host, dev, q))
    return out


def resequence(samples: list[RawPoseSample]) -> list[RawPoseSample]:
    """Renumber seq 0..n-1 (dropping samples upstream of the shim leaves no seq gaps)."""
    return [RawPoseSample(i, s.connection_id, s.host_rx_monotonic_ns, s.device_ts_raw, s.values)
            for i, s in enumerate(samples)]


def with_values(s: RawPoseSample, values) -> RawPoseSample:
    """Replace values, rounded to float32 like every real SDK value."""
    return RawPoseSample(s.seq, s.connection_id, s.host_rx_monotonic_ns, s.device_ts_raw,
                         tuple(f32(v) for v in values))


def with_device_ts(s: RawPoseSample, ts: int) -> RawPoseSample:
    return RawPoseSample(s.seq, s.connection_id, s.host_rx_monotonic_ns, int(ts), s.values)


def capture_command(after_seq: int, window_s: float = 3.0, tau_stab_deg: float = 2.0) -> Command:
    return Command("capture_neutral", 0, {"window_s": window_s, "tau_stab_deg": tau_stab_deg}, after_seq=after_seq)


def connected_event(connection_id: int, last_seq: int = -1) -> Event:
    return Event("device_connected", 0, {"connection_id": connection_id, "last_seq": last_seq})


# ---------------------------------------------------------------------------- scenarios
def _yaw_turn(rate_deg_s: float, start_deg: float = 0.0):
    return lambda t: quat_from_zyx(start_deg + rate_deg_s * t, 0.0, 0.0)


def scenario_stationary(duration_s: float = 60.0, drift_deg_per_min: float = 0.5, noise_deg: float = 0.01,
                        seed: int = 1) -> Trace:
    base = quat_from_zyx(-130.0, 10.0, -5.0)
    s = generate(duration_s, orientation=lambda t: mul(base, quat_from_zyx(drift_deg_per_min * t / 60.0, 0, 0)),
                 noise_deg=noise_deg, seed=seed)
    return Trace(s, [capture_command(200)], [connected_event(1)],
                 {"scenario": "stationary", "drift_deg_per_min": drift_deg_per_min, "noise_deg": noise_deg})


def scenario_sign_flip(duration_s: float = 6.0) -> Trace:
    s = generate(duration_s, orientation=_yaw_turn(5.0))
    s = [with_values(x, (*x.values[:3], *neg(x.values[3:7]))) if i % 2 else x for i, x in enumerate(s)]
    # short window: the trace rotates at 5°/s, so a 3 s window would (correctly) fail the stability check
    return Trace(s, [capture_command(10, window_s=0.2)], [connected_event(1)], {"scenario": "sign_flip"})


def scenario_yaw_wrap(duration_s: float = 6.0) -> Trace:
    # Absolute (tracking-frame) yaw crosses +180 -> -180 after 0.5 s; relative yaw stays within 0..120°.
    s = generate(duration_s, orientation=_yaw_turn(20.0, start_deg=170.0))
    return Trace(s, [capture_command(-1, window_s=0.1)], [connected_event(1)], {"scenario": "yaw_wrap"})


def scenario_dropped(duration_s: float = 10.0, drop_every: int = 97, seed: int = 3) -> Trace:
    s = generate(duration_s, seed=seed)
    kept = resequence([x for i, x in enumerate(s) if i % drop_every != drop_every // 2])
    return Trace(kept, [], [connected_event(1)], {"scenario": "dropped", "dropped": len(s) - len(kept)})


def scenario_sustained_loss(duration_s: float = 20.0, loss: float = 0.58, seed: int = 4) -> Trace:
    rng = random.Random(seed)
    s = generate(duration_s, seed=seed)
    kept = resequence([x for x in s if rng.random() >= loss])
    return Trace(kept, [], [connected_event(1)], {"scenario": "sustained_loss", "dropped": len(s) - len(kept)})


def scenario_faults() -> Trace:
    """One of each invalidating fault at known positions (see tests)."""
    s = generate(4.0, orientation=_yaw_turn(2.0))
    nan, inf = float("nan"), float("inf")
    s[100] = with_values(s[100], (*s[100].values[:3], nan, *s[100].values[4:]))
    s[200] = with_values(s[200], (*s[200].values[:6], inf))
    s[300] = with_values(s[300], (*s[300].values[:3], 0.0, 0.0, 0.0, 0.0))
    s[400] = with_device_ts(s[400], s[399].device_ts_raw)  # duplicate
    s[500] = with_device_ts(s[500], s[499].device_ts_raw - 3_000_000)  # backward
    jump = mul(s[600].values[3:7], quat_from_zyx(45.0, 0.0, 0.0))
    s[600] = with_values(s[600], (*s[600].values[:3], *jump))  # single-sample glitch
    big = s[700].values[3:7]
    s[700] = with_values(s[700], (*s[700].values[:3], *(c * 1.01 for c in big)))  # norm deviation
    return Trace(s, [], [connected_event(1)], {"scenario": "faults", "positions": {
        "nonfinite": [100, 200], "zero_norm": [300], "ts_duplicate": [400], "ts_backward": [500],
        "angular_jump": [600], "norm_deviation": [700]}})


def scenario_reconnect() -> Trace:
    a = generate(5.0, orientation=lambda t: quat_from_zyx(30.0, 0, 0), connection_id=1)
    b = generate(5.0, orientation=lambda t: quat_from_zyx(-60.0, 0, 0), connection_id=2, seq0=len(a),
                 device_t0=DEVICE_T0 + 9_000_000_000, host_t0=HOST_T0 + 9_000_000_000)
    ev = [connected_event(1),
          Event("device_disconnected", 0, {"connection_id": 1, "last_seq": len(a) - 1}),
          connected_event(2, last_seq=len(a) - 1)]
    return Trace(a + b, [capture_command(10, window_s=1.0)], ev, {"scenario": "reconnect", "split_seq": len(a)})


# ---------------------------------------------------------------------------- Phase 2: head-motion scripts
MOTION_BASE = quat_from_zyx(-130.0, 3.0, -2.0)  # arbitrary tracking-frame heading of the neutral pose


def keyframes(keys: list[tuple[float, float]], pitch_keys: Optional[list[tuple[float, float]]] = None,
              base: Quat = MOTION_BASE) -> Callable[[float], Quat]:
    """Piecewise-linear yaw (and optional pitch) in degrees relative to `base`: q_WH = base ⊗ R_zyx(yaw, pitch, 0).

    With a neutral captured at yaw = pitch = 0, q_rel is R_zyx(yaw, pitch, 0) and yaw_rel = yaw."""
    def interp(ks, t):
        if t <= ks[0][0]:
            return ks[0][1]
        for (t0, v0), (t1, v1) in zip(ks, ks[1:]):
            if t <= t1:
                return v0 + (v1 - v0) * (t - t0) / (t1 - t0) if t1 > t0 else v1
        return ks[-1][1]
    return lambda t: mul(base, quat_from_zyx(interp(keys, t), interp(pitch_keys, t) if pitch_keys else 0.0, 0.0))


def chord_tour(yaws=(31.0, 13.0, -13.0, -31.0), t0: float = 1.5, move: float = 0.3, hold: float = 0.8,
               rest: float = 0.6) -> tuple[list[tuple[float, float]], float]:
    """Neutral for t0 s, then for each yaw: move there, hold, move back, rest at neutral."""
    keys, t = [(0.0, 0.0), (t0, 0.0)], t0
    for y in yaws:
        keys += [(t + move, y), (t + move + hold, y), (t + 2 * move + hold, 0.0), (t + 2 * move + hold + rest, 0.0)]
        t += 2 * move + hold + rest
    return keys, t


def scenario_chords() -> Trace:
    """Neutral capture, then one held visit to each default chord region (C, G, Am, F) with returns."""
    keys, end = chord_tour()
    s = generate(end + 0.5, orientation=keyframes(keys))
    return Trace(s, [capture_command(20, window_s=0.5)], [connected_event(1)], {"scenario": "chords"})


def scenario_chords_faults() -> Trace:
    """Demo of the safety behaviour, with G0 fault patterns in the default chord tour:
    - C commits, then a 300 ms device pause while C sounds and the head stays in C: C is released, no re-commit;
    - a duplicate device timestamp during the G dwell: the dwell is cancelled, G is not played this visit;
    - Am plays normally;
    - a disconnect during the F dwell, reconnect (device clock restarts) with the head still at F: nothing plays
      until a new neutral is captured and the head returns to neutral; then F plays."""
    rate = 202.5
    keys, end = chord_tour()
    s = generate(end, orientation=keyframes(keys))
    i_g = int(4.0 * rate)  # during the G hold (G from ~3.8 s to ~4.6 s)
    s[i_g] = with_device_ts(s[i_g], s[i_g - 1].device_ts_raw)
    a, n = int(2.45 * rate), int(0.3 * rate)
    s = s[:a] + s[a + n:]
    cut = int(8.15 * rate) - n  # during the F dwell
    first = resequence(s[:cut])
    keys2 = [(0.0, -31.0), (2.0, -31.0), (2.4, 0.0), (4.0, 0.0), (4.3, -31.0), (5.3, -31.0), (5.6, 0.0)]
    second = generate(6.0, orientation=keyframes(keys2), connection_id=2, seq0=len(first),
                      device_t0=3_000_000_000, host_t0=first[-1].host_rx_monotonic_ns + 5_000_000_000)
    ev = [connected_event(1), Event("device_disconnected", 0, {"connection_id": 1, "last_seq": len(first) - 1}),
          connected_event(2, last_seq=len(first) - 1)]
    cmds = [capture_command(20, window_s=0.5), capture_command(len(first) + int(2.8 * rate), window_s=0.5)]
    return Trace(first + second, cmds, ev, {"scenario": "chords_faults"})


SCENARIOS = {
    "stationary": scenario_stationary, "sign_flip": scenario_sign_flip, "yaw_wrap": scenario_yaw_wrap,
    "dropped": scenario_dropped, "sustained_loss": scenario_sustained_loss, "faults": scenario_faults,
    "reconnect": scenario_reconnect, "chords": scenario_chords,
    "chords_faults": scenario_chords_faults,
}
