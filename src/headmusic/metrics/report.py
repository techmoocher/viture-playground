"""`headmusic analyze`: metrics report for one session (report.json + report.md)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import numpy as np

from headmusic.metrics.angular import stationary_angular
from headmusic.metrics import segments as SEG
from headmusic.metrics.timing import timing_report
from headmusic.recording.reader import iter_processed, iter_raw_imu, load_meta, read_jsonl


def analyze_session(session_dir: Path, stationary: Optional[bool] = None) -> dict:
    session_dir = Path(session_dir)
    meta = load_meta(session_dir)
    cfg = meta.get("config", {})
    flags_cfg = cfg.get("flags", {})
    k_gap = float(flags_cfg.get("k_gap", 1.5))
    res = float(flags_cfg.get("ts_resolution_ns", 1_000_000))
    ref_rate = meta.get("processing", {}).get("reference_rate_hz")
    report = {"session_id": meta.get("session_id"), "condition": meta.get("condition"),
              "mounting": meta.get("mounting"), "source": meta.get("source", {}).get("kind"),
              "device": {k: meta.get("device", {}).get(k) for k in ("market_name", "pid", "firmware", "sdk_version")},
              "imu": {k: meta.get("imu", {}).get(k) for k in ("mode", "frequency_requested_hz", "frequency_selected_hz",
                                                               "frequency_selection_reason")},
              "parameters_note": "all thresholds provisional engineering defaults (not validated limits)"}
    stationary = meta.get("stationary", False) if stationary is None else stationary

    processed_path = session_dir / "processed_pose.csv"
    if processed_path.exists():
        rows = list(iter_processed(processed_path))
        report["samples"] = {"total": len(rows), "valid": sum(r.valid for r in rows),
                             "invalid": sum(not r.valid for r in rows)}
        flag_counts: dict[str, int] = {}
        for r in rows:
            for f in r.flags:
                flag_counts[f] = flag_counts.get(f, 0) + 1
        report["flag_counts"] = dict(sorted(flag_counts.items()))
        per_conn = {}
        for cid in sorted({r.connection_id for r in rows}):
            vr = [r for r in rows if r.valid and r.connection_id == cid]
            if len(vr) < 3:
                continue
            dev = np.array([r.device_ts_raw for r in vr], dtype=np.int64)
            host = np.array([r.host_rx_monotonic_ns for r in vr], dtype=np.int64)
            seq = np.array([r.seq for r in vr], dtype=np.int64)
            entry = {"timing": timing_report(dev, host, seq, ref_rate, k_gap, res)}
            if stationary:
                q = np.array([r.quat for r in vr], dtype=float)
                m = cfg.get("metrics", {})
                entry["stationary_angular"] = stationary_angular(q, dev, float(m.get("w_ref_s", 5.0)),
                                                                 float(m.get("w_jitter_s", 1.0)))
                entry["stationary_angular"]["mounting"] = meta.get("mounting")
            per_conn[str(cid)] = entry
        report["connections"] = per_conn
        commands = read_jsonl(session_dir / "commands.jsonl")
        seg_window = float(cfg.get("metrics", {}).get("segment_window_s", 1.0))
        report["segments"] = SEG.segment_report(rows, commands, seg_window)
    imu_path = session_dir / "raw_imu.csv"
    if imu_path.exists():
        rows = list(iter_raw_imu(imu_path))
        if len(rows) > 2:
            dev = np.array([r.device_ts_raw for r in rows], dtype=np.int64)
            host = np.array([r.host_rx_monotonic_ns for r in rows], dtype=np.int64)
            seq = np.array([r.seq for r in rows], dtype=np.int64)
            vals = np.array([r.values for r in rows], dtype=float)
            names = ["gyro_x", "gyro_y", "gyro_z", "accel_x", "accel_y", "accel_z", "mag_x", "mag_y", "mag_z",
                     "temperature"]
            report["raw_imu"] = {"timing": timing_report(dev, host, seq, None, k_gap, res),
                                 "channels_units_undocumented": {
                                     n: {"mean": float(vals[:, i].mean()), "sd": float(vals[:, i].std(ddof=1))}
                                     for i, n in enumerate(names)}}
    calib = read_jsonl(session_dir / "calibration_neutral.jsonl")
    report["neutral_captures"] = [{k: c.get(k) for k in ("attempt", "accepted", "reasons", "dispersion_max_deg",
                                                         "dispersion_rms_deg", "n_samples", "neutral_calibration_id",
                                                         "q0_tilt_from_upright_deg")}
                                  for c in calib]
    events = read_jsonl(session_dir / "events.jsonl")
    report["events"] = {k: sum(1 for e in events if e["kind"] == k) for k in sorted({e["kind"] for e in events})}
    stopped = [e for e in events if e["kind"] == "source_stopped"]
    if stopped:
        report["shim_stats"] = stopped[-1]["data"].get("shim_stats")
    out = session_dir / "analysis"
    out.mkdir(exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (out / "report.md").write_text(to_markdown(report), encoding="utf-8")
    return report


def _f(x, nd=3):
    return "—" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


def to_markdown(r: dict) -> str:
    L = [f"# Session report {r.get('session_id')}", "",
         f"- condition: {r.get('condition')} · mounting: {r.get('mounting')} · source: {r.get('source')}",
         f"- device: {r.get('device')}", f"- imu: {r.get('imu')}", f"- {r.get('parameters_note')}", ""]
    if "samples" in r:
        L += [f"Samples: {r['samples']}", "", f"Flag counts: {r.get('flag_counts')}", ""]
    for cid, c in r.get("connections", {}).items():
        t = c["timing"]
        L += [f"## Connection {cid} — timing", "",
              "| metric | value |", "|---|---|",
              f"| valid samples | {t['n']} |",
              f"| achieved rate (device / host clock) | {_f(t['achieved_rate_device_hz'])} / {_f(t['achieved_rate_host_hz'])} Hz |",
              f"| device interval p50 / p99 / max / SD | {_f(t['interval_device_ms'].get('p50'))} / {_f(t['interval_device_ms'].get('p99'))} / {_f(t['interval_device_ms'].get('max'))} / {_f(t['interval_device_ms'].get('sd'))} ms |",
              f"| host interval p50 / p99 / max / SD | {_f(t['interval_host_ms'].get('p50'))} / {_f(t['interval_host_ms'].get('p99'))} / {_f(t['interval_host_ms'].get('max'))} / {_f(t['interval_host_ms'].get('sd'))} ms |",
              f"| clock skew | {_f(t['clock_relation'].get('skew_ppm'), 1)} ppm |",
              f"| arrival residual SD / p99−p1 | {_f(t['clock_relation'].get('residual_sd_ms'))} / {_f(t['clock_relation'].get('residual_p99_minus_p1_ms'))} ms |",
              f"| relative lateness p99 / max | {_f(t['clock_relation'].get('relative_lateness_ms', {}).get('p99'))} / {_f(t['clock_relation'].get('relative_lateness_ms', {}).get('max'))} ms |",
              f"| gaps / est. missing | {t.get('gaps', {}).get('count')} / {t.get('gaps', {}).get('est_missing')} ({t.get('gaps', {}).get('reference_source')}) |",
              f"| loss fraction | {_f(t.get('loss_fraction'), 4)} |",
              f"| longest gap-free stretch: rate / duration | {_f(t.get('longest_gap_free_stretch', {}).get('achieved_rate_device_hz'))} Hz / {_f(t.get('longest_gap_free_stretch', {}).get('duration_s'), 1)} s |",
              f"| pipeline seq gaps | {t['pipeline_seq_gaps']} |", ""]
        if "stationary_angular" in c:
            a = c["stationary_angular"]
            if "error" in a:
                L += [f"Stationary metrics: {a['error']}", ""]
            else:
                j, d = a["angular_jitter_deg"], a["apparent_drift"]
                L += [f"## Connection {cid} — stationary angular metrics (mounting: {a.get('mounting')})", "",
                      "| metric | x | y | z | geodesic |", "|---|---|---|---|---|",
                      f"| angular jitter SD (°) | {_f(j['sd_x'], 4)} | {_f(j['sd_y'], 4)} | {_f(j['sd_z'], 4)} | RMS {_f(j['geodesic_rms'], 4)} |",
                      f"| apparent drift (°/min) | {_f(d['slope_deg_per_min']['x'], 4)} | {_f(d['slope_deg_per_min']['y'], 4)} | {_f(d['slope_deg_per_min']['z'], 4)} | {_f(d['slope_deg_per_min']['geodesic'], 4)} |",
                      "", f"Net change {_f(d['net_change_deg'], 4)}°, max excursion {_f(d['max_excursion_deg'], 4)}°, "
                          f"first-difference jitter estimate {_f(j['first_difference_estimate'], 4)}°.", ""]
    L += SEG.to_markdown(r.get("segments", []))
    if r.get("neutral_captures"):
        L += ["## Neutral captures", "",
              "| attempt | accepted | reasons | max disp. (°) | RMS (°) | n | tilt from upright at q0 (°) |",
              "|---|---|---|---|---|---|---|"]
        for c in r["neutral_captures"]:
            L.append(f"| {c['attempt']} | {c['accepted']} | {', '.join(c['reasons'] or [])} | "
                     f"{_f(c['dispersion_max_deg'], 4)} | {_f(c['dispersion_rms_deg'], 4)} | {c['n_samples']} | "
                     f"{_f(c.get('q0_tilt_from_upright_deg'), 1)} |")
        L += ["", "Tilt is descriptive only (0° upright, 180° upside down); it does not affect acceptance.", ""]
    L += [f"Events: {r.get('events')}", "", f"Shim stats: {r.get('shim_stats')}", ""]
    return "\n".join(L)
