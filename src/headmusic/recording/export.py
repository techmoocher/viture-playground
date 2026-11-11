"""Denormalised export: protocol §10 per-row fields expanded from the normalised session files.

Same inputs + same exporter version -> byte-identical CSV (values are copied as text, the order
is fixed, and no export time is written into the CSV). export_manifest.json records the SHA-256
of every input file and the parameters.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Optional

from headmusic import __version__
from headmusic.recording.reader import load_meta, read_jsonl

EXPORTER_VERSION = f"headmusic-export/{__version__}"

PROCESSED_TO_PROTOCOL = {
    "quat_w": "quat_wxyz_w", "quat_x": "quat_wxyz_x", "quat_y": "quat_wxyz_y", "quat_z": "quat_wxyz_z",
    "quat_rel_w": "quat_neutral_relative_wxyz_w", "quat_rel_x": "quat_neutral_relative_wxyz_x",
    "quat_rel_y": "quat_neutral_relative_wxyz_y", "quat_rel_z": "quat_neutral_relative_wxyz_z",
    "euler_display_yaw_deg": "euler_display_deg_yaw", "euler_display_pitch_deg": "euler_display_deg_pitch",
    "euler_display_roll_deg": "euler_display_deg_roll",
}

CONSTANT_COLUMNS = [
    "schema_version", "participant_id", "session_id", "trial_id", "condition", "mounting",
    "software_build", "sdk_version", "glasses_firmware", "device_market_name", "imu_mode",
    "frequency_requested_hz", "frequency_selected_hz", "host_clock", "device_ts_description",
]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _segments(commands: list[dict]) -> list[tuple[int, Optional[int], str]]:
    """(start_after_seq, end_after_seq or None, label) from segment commands."""
    out, open_seg = [], None
    for c in commands:
        if c["kind"] == "segment_start":
            if open_seg is not None:
                out.append((open_seg[0], c["after_seq"], open_seg[1]))
            open_seg = (c["after_seq"], c["data"].get("label", ""))
        elif c["kind"] == "segment_end" and open_seg is not None:
            out.append((open_seg[0], c["after_seq"], open_seg[1]))
            open_seg = None
    if open_seg is not None:
        out.append((open_seg[0], None, open_seg[1]))
    return out


def _trial_for(seq: int, segments) -> str:
    for start, end, label in segments:
        if seq > start and (end is None or seq <= end):
            return label
    return ""


def export_denormalized(session_dir: Path, out_dir: Optional[Path] = None) -> Path:
    session_dir = Path(session_dir)
    out_dir = Path(out_dir) if out_dir else session_dir / "export"
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = load_meta(session_dir)
    processed_path = session_dir / "processed_pose.csv"
    raw_path = session_dir / "raw_pose.csv"
    calib = [r for r in read_jsonl(session_dir / "calibration_neutral.jsonl") if r.get("accepted")]
    q0_by_id = {r["neutral_calibration_id"]: r["q0_wxyz"] for r in calib}
    segments = _segments(read_jsonl(session_dir / "commands.jsonl"))

    dev, imu, prov = meta.get("device", {}), meta.get("imu", {}), meta.get("provenance", {})
    constants = {
        "schema_version": meta.get("schema_version", ""),
        "participant_id": meta.get("participant_id") or "",
        "session_id": meta.get("session_id", ""),
        "condition": meta.get("condition", ""),
        "mounting": meta.get("mounting", ""),
        "software_build": f"{prov.get('package_version', '')}+{prov.get('git_commit', 'unknown')}"
                          f"{'-dirty' if prov.get('git_dirty') else ''}",
        "sdk_version": dev.get("sdk_version", ""),
        "glasses_firmware": dev.get("firmware", ""),
        "device_market_name": dev.get("market_name", ""),
        "imu_mode": imu.get("mode", ""),
        "frequency_requested_hz": str(imu.get("frequency_requested_hz", "")),
        "frequency_selected_hz": str(imu.get("frequency_selected_hz", "")),
        "host_clock": meta.get("clocks", {}).get("host_clock", ""),
        "device_ts_description": meta.get("clocks", {}).get("device_ts", ""),
    }

    raw_by_seq = {}
    with raw_path.open(newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        raw_header = next(r)
        sdk_cols = raw_header[4:11]
        for row in r:
            if len(row) == len(raw_header):
                raw_by_seq[row[0]] = row[4:11]

    out_path = out_dir / "pose_samples_denormalized.csv"
    with processed_path.open(newline="", encoding="utf-8") as f, \
            out_path.open("w", newline="", encoding="utf-8") as g:
        r = csv.reader(f)
        header = next(r)
        w = csv.writer(g, lineterminator="\n")
        mapped = [PROCESSED_TO_PROTOCOL.get(c, c) for c in header]
        w.writerow(CONSTANT_COLUMNS + mapped[:4] + sdk_cols + mapped[4:] +
                   ["neutral_q0_wxyz_w", "neutral_q0_wxyz_x", "neutral_q0_wxyz_y", "neutral_q0_wxyz_z"])
        i_seq, i_nid = header.index("seq"), header.index("neutral_calibration_id")
        for row in r:
            if len(row) != len(header):
                break
            seq = row[i_seq]
            c = dict(constants, trial_id=_trial_for(int(seq), segments))
            q0 = q0_by_id.get(int(row[i_nid])) if row[i_nid] else None
            w.writerow([c[k] for k in CONSTANT_COLUMNS] + row[:4] + raw_by_seq.get(seq, [""] * 7) + row[4:] +
                       ([repr(float(v)) for v in q0] if q0 else [""] * 4))

    inputs = ["session.json", "raw_pose.csv", "processed_pose.csv", "calibration_neutral.jsonl", "commands.jsonl"]
    manifest = {
        "exporter": EXPORTER_VERSION,
        "output": out_path.name,
        "output_sha256": _sha256(out_path),
        "inputs_sha256": {n: _sha256(session_dir / n) for n in inputs if (session_dir / n).exists()},
        "note": "sample_quality is the pipe-separated flag set ('valid' if none); see docs/data-format.md",
    }
    (out_dir / "export_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return out_path
