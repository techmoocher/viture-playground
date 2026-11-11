"""Instrument in the real pipeline (2A): real flags and gate, faults from G0, live-vs-replay determinism."""
import hashlib
from pathlib import Path

import pytest

from headmusic.acquisition import synthetic as syn
from headmusic.acquisition.replay_source import ReplaySource
from headmusic.config import load_config
from headmusic.instrument.consumer import InstrumentConsumer
from headmusic.instrument.fsm import GestureFSM
from headmusic.instrument.log import EVENTS_FILE, INPUTS_FILE, TIMING_FILE, InteractionLog, read_inputs
from headmusic.instrument.regions import InstrumentConfig
from headmusic.orientation.processor import OrientationProcessor, ProcessorConfig
from headmusic.pipeline import Pipeline
from headmusic.provenance import new_session_meta
from headmusic.recording.writer import SessionWriter
from headmusic.tracking.gate import TrackingGate
from headmusic.types import Event, RawPoseSample

STREAM = {"selected_hz": 240, "reference_rate_hz": 202.5}


def build(cfg, writer=None, clock=None, recorded_inputs=None, log_dir=None):
    gate = TrackingGate.from_config(cfg)
    log = InteractionLog(log_dir, write_timing=clock is not None) if log_dir else None
    cons = InstrumentConsumer(GestureFSM(InstrumentConfig.from_config(cfg)), gate, log, clock=clock,
                              recorded_inputs=recorded_inputs)
    pipe = Pipeline(cfg, OrientationProcessor(ProcessorConfig.from_config(cfg)), gate, writer, clock=clock,
                    fixed_stream_config=STREAM, consumers=[cons])
    return pipe, cons, log


def commits(cons):
    return [e["chord"] for e in cons.events if e["event_type"] == "raw_commit"]


def resets(cons):
    return [e["reason"] for e in cons.events if e["event_type"] == "gesture_reset"]


def tour(**kw):
    keys, end = syn.chord_tour(**kw)
    return syn.generate(end + 0.5, orientation=syn.keyframes(keys)), keys


def seq_at(samples, t_s):
    return int(t_s * 202.5)


def run(trace_items, cfg=None):
    cfg = cfg or load_config()
    pipe, cons, _ = build(cfg)
    pipe.process_all(trace_items)
    cons.finish()
    return cons


def test_chord_tour_commits_all_four():
    cons = run(syn.scenario_chords().items())
    assert commits(cons) == ["C", "G", "Am", "F"]


def _with_capture(samples, events=None):
    return syn.Trace(samples, [syn.capture_command(20, window_s=0.5)], events or [syn.connected_event(1)]).items()


# C is held from t = 1.8 s to 2.6 s in the default tour; its dwell completes at about 2.3 s.
C_MID = seq_at(None, 2.05)


def test_duplicate_timestamp_during_a_dwell_cancels_it():
    s, _ = tour()
    s[C_MID] = syn.with_device_ts(s[C_MID], s[C_MID - 1].device_ts_raw)  # real ts_duplicate flag
    cons = run(_with_capture(s))
    assert commits(cons) == ["G", "Am", "F"]  # C needs a fresh return to neutral, which the tour does not give
    assert "last_sample_invalid" in resets(cons)


@pytest.mark.parametrize("pause_ms", [300, 600])
def test_device_pause_during_a_dwell_resets(pause_ms):
    s, _ = tour()
    n_drop = int(pause_ms / 1000 * 202.5)
    s = syn.resequence(s[:C_MID] + s[C_MID + n_drop:])  # the device produces nothing (G0 pattern)
    cons = run(_with_capture(s))
    assert "C" not in commits(cons)
    assert "gap" in resets(cons)


def test_nan_and_angular_jump_reset():
    s, _ = tour()
    s[C_MID] = syn.with_values(s[C_MID], (*s[C_MID].values[:3], float("nan"), *s[C_MID].values[4:]))
    cons = run(_with_capture(s))
    assert "C" not in commits(cons) and "last_sample_invalid" in resets(cons)


def test_pc_sleep_late_sample_is_stale_and_resets():
    """G0 R9: a sample produced before a sleep arrives 29.9 s late, then a late burst."""
    s, _ = tour()
    late = 29_900_000_000
    s = [RawPoseSample(x.seq, x.connection_id, x.host_rx_monotonic_ns + (late if i >= C_MID else 0),
                       x.device_ts_raw, x.values) for i, x in enumerate(s)]
    cons = run(_with_capture(s))
    assert "C" not in commits(cons)
    assert any("stale" in (r or "") for r in resets(cons))


def test_reconnect_needs_a_new_neutral_and_a_return_to_neutral():
    a, _ = tour()
    a = a[:C_MID]  # disconnect in the middle of the C dwell
    keys = [(0.0, 31.0), (3.0, 31.0), (3.5, 0.0), (5.0, 0.0), (5.3, 31.0), (6.5, 31.0)]
    b = syn.generate(6.5, orientation=syn.keyframes(keys), connection_id=2, seq0=len(a),
                     device_t0=3_000_000_000, host_t0=a[-1].host_rx_monotonic_ns + 9_000_000_000)
    ev = [syn.connected_event(1), Event("device_disconnected", 0, {"connection_id": 1, "last_seq": len(a) - 1}),
          syn.connected_event(2, last_seq=len(a) - 1)]
    cap2 = syn.capture_command(len(a) + int(3.8 * 202.5), window_s=0.5)  # at neutral on the new connection
    items = syn.Trace(a + b, [syn.capture_command(20, window_s=0.5), cap2], ev).items()
    cons = run(items)
    # held in C on the new connection for 3 s with no neutral: nothing; after capture + return + dwell: C
    assert commits(cons) == ["C"]
    first_c = next(e for e in cons.events if e["event_type"] == "raw_commit" and e["chord"] == "C")
    assert first_c["connection_id"] == 2 and first_c["neutral_calibration_id"] == 2
    assert "disconnect" in resets(cons)


def test_no_consumers_leaves_phase1_output_unchanged(tmp_path):
    cfg = load_config()
    out = {}
    for name, with_inst in (("plain", False), ("inst", True)):
        meta = new_session_meta(cfg, condition="bench", mounting="synthetic", source_kind="synthetic", argv=[])
        w = SessionWriter(tmp_path / name, meta)
        if with_inst:
            pipe, cons, log = build(cfg, writer=w, log_dir=tmp_path / name)
        else:
            pipe = Pipeline(cfg, OrientationProcessor(ProcessorConfig.from_config(cfg)), TrackingGate.from_config(cfg),
                            w, clock=None, fixed_stream_config=STREAM)
        pipe.process_all(syn.scenario_chords().items())
        w.close()
        out[name] = (tmp_path / name / "processed_pose.csv").read_bytes()
    assert out["plain"] == out["inst"]


# ---------------------------------------------------------------------------- live simulation vs replay
class FakeClock:
    def __init__(self):
        self.t = 0

    def __call__(self):
        return self.t


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_live_simulation_and_replay_give_identical_interaction_events(tmp_path):
    """Live: 1 ms processing delay, 20 ms idle ticks during a 600 ms device pause, one late-processed sample.
    Replay: offline, no clock. The logged inputs make the decisions identical."""
    cfg = load_config()
    s, _ = tour()
    n_drop = int(0.6 * 202.5)
    s = syn.resequence(s[:C_MID] + s[C_MID + n_drop:])
    trace = syn.Trace(s, [syn.capture_command(20, window_s=0.5)], [syn.connected_event(1)])
    late_seq = seq_at(None, 3.5)  # during the G visit

    meta = new_session_meta(cfg, condition="bench", mounting="synthetic", source_kind="synthetic", argv=[])
    live_dir = tmp_path / "live"
    w = SessionWriter(live_dir, meta)
    clock = FakeClock()
    pipe, cons, log = build(cfg, writer=w, clock=clock, log_dir=live_dir)
    w.update_meta(processing=pipe.stream_info)
    prev_host = None
    for item in trace.items():
        h = getattr(item, "host_rx_monotonic_ns", None)
        if h is not None:
            if prev_host is not None:
                t = prev_host + 20_000_000
                while t < h:  # idle ticks while the queue is empty
                    clock.t = t
                    pipe.tick()
                    t += 20_000_000
            clock.t = h + (150_000_000 if item.seq == late_seq else 1_000_000)
            prev_host = h
        pipe._handle(item)
    cons.finish()
    log.close()
    w.close()
    inputs = read_inputs(live_dir)
    kinds = [r["kind"] for r in inputs]
    assert "stale_tick" in kinds and "late_processing" in kinds
    assert (live_dir / TIMING_FILE).stat().st_size > 0

    rep_dir = tmp_path / "replay"
    rep_dir.mkdir()
    src = ReplaySource(live_dir)
    pipe2, cons2, log2 = build(cfg, recorded_inputs=read_inputs(live_dir), log_dir=rep_dir)
    pipe2.process_all(src.items())
    cons2.finish()
    log2.close()
    assert _sha(live_dir / EVENTS_FILE) == _sha(rep_dir / EVENTS_FILE)
    assert _sha(live_dir / INPUTS_FILE) == _sha(rep_dir / INPUTS_FILE)
    assert "stale_tick" in resets(cons) or any(e["reason"] == "stale_tick" for e in cons.events)

    # Without the logged inputs, the replay would differ: the inputs are what makes it deterministic.
    pipe3, cons3, _ = build(cfg, recorded_inputs=[])
    pipe3.process_all(ReplaySource(live_dir).items())
    cons3.finish()
    assert [e["event_type"] for e in cons3.events] != [e["event_type"] for e in cons.events]
