"""Denormalised export: protocol §10 per-row fields, byte-reproducible."""
import csv
import hashlib

from headmusic.acquisition import synthetic as SY
from headmusic.config import load_config
from headmusic.recording.export import export_denormalized
from headmusic.recording.reader import read_jsonl
from headmusic.types import Command
from test_replay import live_like_session

PROTOCOL_FIELDS = ["schema_version", "participant_id", "session_id", "trial_id", "condition", "software_build",
                   "sdk_version", "device_ts_raw", "host_rx_monotonic_ns", "quat_wxyz_w", "quat_neutral_relative_wxyz_w",
                   "euler_display_deg_yaw", "sample_quality", "neutral_calibration_id"]


def test_export_fields_and_reproducibility(tmp_path):
    cfg = load_config()
    tr = SY.scenario_stationary(duration_s=8)
    tr.commands += [Command("segment_start", 0, {"label": "stationary_check"}, after_seq=1000),
                    Command("segment_end", 0, {}, after_seq=1200)]
    live = live_like_session(tmp_path, tr, cfg)
    a = export_denormalized(live, tmp_path / "e1")
    b = export_denormalized(live, tmp_path / "e2")
    assert hashlib.sha256(a.read_bytes()).digest() == hashlib.sha256(b.read_bytes()).digest()
    rows = list(csv.DictReader(a.open()))
    assert set(PROTOCOL_FIELDS) <= set(rows[0])
    assert len(rows) == len(tr.samples)
    trial = {int(r["seq"]): r["trial_id"] for r in rows}
    assert trial[1000] == "" and trial[1001] == "stationary_check" and trial[1200] == "stationary_check"
    assert trial[1201] == ""
    accepted = [r for r in read_jsonl(live / "calibration_neutral.jsonl") if r["accepted"]][0]
    applied = [r for r in rows if r["neutral_calibration_id"] == "1"][0]
    assert float(applied["neutral_q0_wxyz_w"]) == accepted["q0_wxyz"][0]
    assert rows[0]["sdk_qw"] != "" and rows[0]["sample_quality"] == "no_neutral"
    assert (tmp_path / "e1" / "export_manifest.json").exists()
