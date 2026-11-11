"""Placement check before a bench recording: how still and how upright the glasses are.

`headmusic check-placement` streams for a few seconds, writes no files, and prints this summary, so the
operator can see whether the setup is still before a recording starts. No pass/fail threshold is applied:
the operator decides from the numbers.
"""
from __future__ import annotations

from typing import Iterable, Optional

from headmusic.config import reference_rate_hz
from headmusic.orientation.flags import GAP_BEFORE
from headmusic.orientation.processor import OrientationProcessor, ProcessorConfig
from headmusic.orientation.quaternion import angle_deg, mean_sign_aligned, up_axis_tilt_deg
from headmusic.types import Event, RawPoseSample

# Preliminary observation, shown for orientation only (docs/bench-report.md, earlier runs): untouched on a
# table, the maximum deviation stayed within about 0.005–0.011°. Not a pass limit.
REFERENCE_NOTE = ("for orientation only, not a pass limit: untouched on a table in the earlier (preliminary) runs, "
                  "the maximum deviation stayed within about 0.01°")


def placement_summary(items: Iterable[object], cfg: dict) -> dict:
    """Process collected source items (events and raw pose samples) the same way the pipeline does."""
    proc = OrientationProcessor(ProcessorConfig.from_config(cfg))
    rows, connections = [], set()
    for it in items:
        if isinstance(it, Event) and it.kind == "device_connected":
            hz = it.data.get("frequency_selected_hz")
            ref = reference_rate_hz(cfg, it.data.get("mode", "pose"), hz) \
                if cfg["flags"]["gap_reference"] == "measured" else None
            proc.configure_stream(hz, ref)
            connections.add(it.data.get("connection_id"))
        elif isinstance(it, RawPoseSample):
            rows.append(proc.process(it)[0])
    valid = [r for r in rows if r.valid and r.quat is not None]
    out: dict = {"n_samples": len(rows), "n_valid": len(valid), "n_invalid": len(rows) - len(valid),
                 "n_gaps": sum(1 for r in rows if GAP_BEFORE in r.flags), "n_connections": len(connections)}
    if len(valid) < 2:
        out["error"] = "too few valid samples"
        return out
    t0, t1 = valid[0].device_ts_raw, valid[-1].device_ts_raw
    out["duration_s"] = (t1 - t0) / 1e9
    out["achieved_rate_hz"] = (len(valid) - 1) / out["duration_s"] if t1 > t0 else None
    q = mean_sign_aligned([r.quat for r in valid])
    dev = [angle_deg(q, r.quat) for r in valid]
    out["tilt_from_upright_deg"] = up_axis_tilt_deg(q)
    out["deviation_max_deg"] = max(dev)
    out["deviation_rms_deg"] = (sum(d * d for d in dev) / len(dev)) ** 0.5
    first = [r.quat for r in valid if r.device_ts_raw <= t0 + 1_000_000_000]
    last = [r.quat for r in valid if r.device_ts_raw >= t1 - 1_000_000_000]
    out["change_first_to_last_second_deg"] = angle_deg(mean_sign_aligned(first), mean_sign_aligned(last))
    return out


def _f(x: Optional[float], nd: int) -> str:
    return "—" if x is None else f"{x:.{nd}f}"


def format_summary(s: dict) -> str:
    head = (f"placement check (nothing recorded): {_f(s.get('duration_s'), 1)} s, {s['n_samples']} samples "
            f"({s['n_invalid']} invalid, {s['n_gaps']} gaps), {_f(s.get('achieved_rate_hz'), 1)} Hz")
    if "error" in s:
        return f"{head}\n  {s['error']}"
    lines = [head,
             f"  tilt from upright: {s['tilt_from_upright_deg']:.1f}°  (0° upright, 90° on its side, 180° upside down)",
             f"  deviation from the mean orientation: max {s['deviation_max_deg']:.3f}°, RMS {s['deviation_rms_deg']:.3f}°",
             f"  change between the first and the last second: {s['change_first_to_last_second_deg']:.3f}°",
             f"  ({REFERENCE_NOTE})"]
    if s["n_connections"] > 1:
        lines.append("  the device reconnected during the check")
    return "\n".join(lines)
