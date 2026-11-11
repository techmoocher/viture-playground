"""Per-segment net rotation, for the G0 bench checks of axis signs and quaternion direction (U1).

For each operator segment (segment_start / segment_end commands), the start and end orientations
are the sign-aligned means of the valid samples in the first and last `window_s` seconds of the
segment (device clock). The operator holds the glasses still at both ends; the dispersion of each
window is reported so this can be checked.

Two products of the start and end quaternions q_s, q_e are reported, because which one is the
head-frame change depends on the quaternion direction, which is not yet verified (U1):

    P_head  = conj(q_s) ⊗ q_e   head-frame change   if the SDK quaternion maps head → tracking frame
    P_track = q_e ⊗ conj(q_s)   tracking-frame change under the same reading

Under the inverse reading (tracking → head), P_head is the inverse of the tracking-frame change and
P_track the inverse of the head-frame change. Both share the rotation angle; they differ in the axis.

For each product: rotation angle, unit axis, the angle between the axis and the vertical ±Z (sign-
insensitive), and its display Euler angles (Z-Y'-X''). How to read them for each bench procedure
is in docs/bench-checklist.md. Descriptive only: no pass/fail threshold is applied here.
"""
from __future__ import annotations

import math
from typing import Optional, Sequence

from headmusic.orientation.euler import zyx_from_quat
from headmusic.orientation.flags import GAP_BEFORE
from headmusic.orientation.quaternion import angle_deg, canonical, conj, mean_sign_aligned, mul, up_axis_tilt_deg
from headmusic.recording.reader import segments_from_commands
from headmusic.types import ProcessedSample

MIN_WINDOW_SAMPLES = 2


def _product(q: Sequence[float]) -> dict:
    w, x, y, z = canonical(q)
    s = math.sqrt(x * x + y * y + z * z)
    angle = math.degrees(2.0 * math.atan2(s, w))
    if s < 1e-12:
        axis, from_vertical = None, None
    else:
        axis = (x / s, y / s, z / s)
        from_vertical = math.degrees(math.acos(min(1.0, abs(axis[2]))))
    yaw, pitch, roll = zyx_from_quat((w, x, y, z))
    return {"angle_deg": angle, "axis": axis, "axis_from_vertical_deg": from_vertical,
            "euler_display_deg": {"yaw": yaw, "pitch": pitch, "roll": roll}}


def _window(rows: list[ProcessedSample]) -> dict:
    q = mean_sign_aligned([r.quat for r in rows])
    out = {"n": len(rows), "seq_first": rows[0].seq, "seq_last": rows[-1].seq,
           "dispersion_max_deg": max(angle_deg(q, r.quat) for r in rows),
           "tilt_from_upright_deg": up_axis_tilt_deg(q), "quat_wxyz": q}
    rel = [r for r in rows if r.quat_rel is not None]
    if len(rel) == len(rows) and len({r.neutral_calibration_id for r in rel}) == 1:
        qr = mean_sign_aligned([r.quat_rel for r in rel])
        yaw, pitch, roll = zyx_from_quat(canonical(qr))
        out["neutral_relative"] = {"neutral_calibration_id": rel[0].neutral_calibration_id,
                                   "euler_display_deg": {"yaw": yaw, "pitch": pitch, "roll": roll}}
    return out


def one_segment(rows: list[ProcessedSample], label: str, window_s: float) -> dict:
    """Net-rotation summary of the processed rows of one segment (rows in sequence order)."""
    valid = [r for r in rows if r.valid and r.quat is not None]
    out: dict = {"label": label, "n_samples": len(rows), "n_valid": len(valid),
                 "n_invalid": sum(1 for r in rows if not r.valid),
                 "n_gaps": sum(1 for r in rows if GAP_BEFORE in r.flags),
                 "connection_ids": sorted({r.connection_id for r in rows}), "window_s": window_s}
    if len(out["connection_ids"]) > 1:
        out["error"] = "segment spans a reconnection; start and end are not comparable"
        return out
    if len(valid) < 2 * MIN_WINDOW_SAMPLES:
        out["error"] = "too few valid samples"
        return out
    t0, t1 = valid[0].device_ts_raw, valid[-1].device_ts_raw
    out["duration_s"] = (t1 - t0) / 1e9
    w = int(window_s * 1e9)
    if 2 * w > t1 - t0:
        out["error"] = "segment shorter than two windows"
        return out
    first = [r for r in valid if r.device_ts_raw <= t0 + w]
    last = [r for r in valid if r.device_ts_raw >= t1 - w]
    if len(first) < MIN_WINDOW_SAMPLES or len(last) < MIN_WINDOW_SAMPLES:
        out["error"] = "too few valid samples in the start or end window"
        return out
    start, end = _window(first), _window(last)
    qs, qe = start["quat_wxyz"], end["quat_wxyz"]
    out["start"], out["end"] = start, end
    out["P_head"] = _product(mul(conj(qs), qe))
    out["P_track"] = _product(mul(qe, conj(qs)))
    return out


def segment_report(rows: list[ProcessedSample], commands: list[dict], window_s: float = 1.0) -> list[dict]:
    """One summary per segment found in the commands, in command order."""
    out = []
    for start, end, label in segments_from_commands(commands):
        seg = [r for r in rows if r.seq > start and (end is None or r.seq <= end)]
        out.append(one_segment(seg, label, window_s))
    return out


def _f(x: Optional[float], nd: int = 1) -> str:
    return "—" if x is None else f"{x:.{nd}f}"


def to_markdown(segments: list[dict]) -> list[str]:
    if not segments:
        return []
    L = ["## Segments (net rotation, bench checks)", "",
         "Start and end are the mean orientations of the first and last window of each segment. "
         "P_head = conj(q_s)⊗q_e and P_track = q_e⊗conj(q_s); which one is the head-frame change depends on "
         "the quaternion direction (U1). See docs/bench-checklist.md for how to read them. Descriptive only.", "",
         "| segment | dur. (s) | still start / end (max disp. °) | tilt start / end (°) | angle (°) | "
         "P_head axis from vertical (°) | P_head yaw / pitch / roll (°) | P_track axis from vertical (°) | "
         "P_track yaw / pitch / roll (°) |",
         "|---|---|---|---|---|---|---|---|---|"]
    for s in segments:
        if "error" in s:
            L.append(f"| {s['label']} | {_f(s.get('duration_s'))} | {s['error']} | | | | | | |")
            continue
        h, t = s["P_head"], s["P_track"]
        eh, et = h["euler_display_deg"], t["euler_display_deg"]
        L.append(f"| {s['label']} | {_f(s['duration_s'])} | {_f(s['start']['dispersion_max_deg'], 2)} / "
                 f"{_f(s['end']['dispersion_max_deg'], 2)} | {_f(s['start']['tilt_from_upright_deg'])} / "
                 f"{_f(s['end']['tilt_from_upright_deg'])} | {_f(h['angle_deg'])} | {_f(h['axis_from_vertical_deg'])} | "
                 f"{_f(eh['yaw'])} / {_f(eh['pitch'])} / {_f(eh['roll'])} | {_f(t['axis_from_vertical_deg'])} | "
                 f"{_f(et['yaw'])} / {_f(et['pitch'])} / {_f(et['roll'])} |")
    flagged = [s["label"] for s in segments if "error" not in s and (s["n_invalid"] or s["n_gaps"])]
    L.append("")
    if flagged:
        L += [f"Segments with invalid samples or gaps (check before using): {', '.join(flagged)}", ""]
    return L
