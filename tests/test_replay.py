"""Deterministic replay: a recorded session reprocesses to byte-identical output."""
import hashlib
from pathlib import Path

import pytest

from headmusic.acquisition import synthetic as SY
from headmusic.acquisition.replay_source import ReplaySource
from headmusic.config import load_config
from headmusic.orientation.processor import OrientationProcessor, ProcessorConfig
from headmusic.pipeline import Pipeline
from headmusic.recording.reader import read_jsonl
from headmusic.recording.writer import SessionWriter
from headmusic.tracking.gate import TrackingGate
from headmusic.types import Command, Event, RawPoseSample

STREAM = {"selected_hz": 240, "reference_rate_hz": 202.5}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def live_like_session(tmp: Path, trace, cfg) -> Path:
    """Write a session the way the live pipeline does (raw first, commands positioned by queue order)."""
    meta = {"config": cfg, "processing": dict(STREAM), "schema_version": "1.0.0"}
    w = SessionWriter(tmp / "live", meta)
    pipe = Pipeline(cfg, OrientationProcessor(ProcessorConfig.from_config(cfg)), TrackingGate(100_000_000), w,
                    clock=None, fixed_stream_config=STREAM)
    for item in trace.items():
        if isinstance(item, Command):
            item = Command(item.kind, item.host_monotonic_ns, item.data)  # after_seq assigned by the pipeline
        if isinstance(item, Event):
            item = Event(item.kind, item.host_monotonic_ns, {k: v for k, v in item.data.items() if k != "last_seq"})
        pipe.put(item)
    pipe.start()
    pipe.stop()
    w.close()
    return tmp / "live"


def reprocess(src: Path, out: Path, cfg_override=None) -> Path:
    rs = ReplaySource(src)
    cfg = cfg_override or rs.config_snapshot
    w = SessionWriter(out, {"source": "replay"}, write_raw_pose=False)
    pipe = Pipeline(cfg, OrientationProcessor(ProcessorConfig.from_config(cfg)), TrackingGate(100_000_000), w,
                    clock=None, fixed_stream_config=rs.stream_config)
    pipe.process_all(rs.items())
    w.close()
    return out


@pytest.mark.parametrize("scenario", ["stationary", "faults", "reconnect", "sign_flip", "sustained_loss"])
def test_replay_is_byte_identical(tmp_path, scenario):
    cfg = load_config()
    trace = SY.SCENARIOS[scenario]()
    live = live_like_session(tmp_path, trace, cfg)
    out = reprocess(live, tmp_path / "re")
    assert sha(live / "processed_pose.csv") == sha(out / "processed_pose.csv")
    assert sha(live / "calibration_neutral.jsonl") == sha(out / "calibration_neutral.jsonl")


def test_commands_replay_at_recorded_position(tmp_path):
    cfg = load_config()
    trace = SY.scenario_stationary(duration_s=8)
    live = live_like_session(tmp_path, trace, cfg)
    cmds = read_jsonl(live / "commands.jsonl")
    assert cmds[0]["after_seq"] == 200
    items = list(ReplaySource(live).items())
    k = next(i for i, it in enumerate(items) if isinstance(it, Command))
    assert isinstance(items[k - 1], RawPoseSample) and items[k - 1].seq == 200


def test_replay_reproduces_reconnect_events(tmp_path):
    cfg = load_config()
    live = live_like_session(tmp_path, SY.scenario_reconnect(), cfg)
    kinds = [it.kind for it in ReplaySource(live).items() if isinstance(it, Event)]
    assert kinds == ["device_connected", "device_disconnected", "device_connected"]


def test_reprocess_with_other_parameters_changes_output(tmp_path):
    """Config overrides apply to commands that did not record explicit parameters."""
    cfg = load_config()
    tr = SY.scenario_stationary(duration_s=8)
    tr.commands = [Command("capture_neutral", 0, {}, after_seq=200)]
    live = live_like_session(tmp_path, tr, cfg)
    assert read_jsonl(live / "calibration_neutral.jsonl")[0]["accepted"] is True
    strict = load_config(overrides={"neutral": {"tau_stab_deg": 0.001}})
    out = reprocess(live, tmp_path / "strict", strict)
    rec = read_jsonl(out / "calibration_neutral.jsonl")[0]
    assert rec["accepted"] is False and rec["reasons"] == ["dispersion_exceeds_tau_stab"]


def test_recorded_command_parameters_win_over_config(tmp_path):
    cfg = load_config()
    live = live_like_session(tmp_path, SY.scenario_stationary(duration_s=8), cfg)  # command records tau = 2.0
    strict = load_config(overrides={"neutral": {"tau_stab_deg": 0.001}})
    out = reprocess(live, tmp_path / "strict", strict)
    assert read_jsonl(out / "calibration_neutral.jsonl")[0]["accepted"] is True


def test_threaded_replay_clock_follows_recording(tmp_path):
    cfg = load_config()
    live = live_like_session(tmp_path, SY.scenario_stationary(duration_s=2), cfg)
    got = []
    rs = ReplaySource(live, sink=got.append, speed=None)
    rs.start()
    assert rs.finished.wait(10)
    samples = [g for g in got if isinstance(g, RawPoseSample)]
    assert len(samples) == len(SY.scenario_stationary(duration_s=2).samples)
    assert rs.clock() == samples[-1].host_rx_monotonic_ns
