"""Per-segment net rotation (bench checks of axis signs and the quaternion-direction test U1)."""
import math

import pytest

from headmusic.acquisition import synthetic as SY
from headmusic.config import load_config
from headmusic.metrics.report import analyze_session
from headmusic.metrics.segments import segment_report
from headmusic.orientation.euler import quat_from_zyx
from headmusic.orientation.processor import OrientationProcessor, ProcessorConfig
from headmusic.orientation.quaternion import conj, mul
from headmusic.pipeline import Pipeline
from headmusic.recording.writer import SessionWriter
from headmusic.tracking.gate import TrackingGate
from headmusic.types import Command

HOLD, MOVE = 2.0, 3.0  # hold still, rotate smoothly, hold still
HEADING = -130.0  # the SDK heading is arbitrary (no magnetometer); any value must work


def ramp(t, hold=HOLD, move=MOVE):
    u = min(max((t - hold) / move, 0.0), 1.0)
    return 0.5 - 0.5 * math.cos(math.pi * u)


def seg_commands(last_seq, label="seg"):
    return [{"kind": "segment_start", "after_seq": -1, "data": {"label": label}},
            {"kind": "segment_end", "after_seq": last_seq, "data": {}}]


def run(make_processor, orientation, reading="head_to_track", duration=2 * HOLD + MOVE, capture_after=None,
        noise_deg=0.0):
    """Process a synthetic trace. reading='track_to_head' simulates an SDK that reports the inverse quaternion."""
    f = orientation if reading == "head_to_track" else (lambda t: conj(orientation(t)))
    samples = SY.generate(duration, orientation=f, noise_deg=noise_deg, seed=7)
    p = make_processor()
    rows = []
    for s in samples:
        rows.append(p.process(s)[0])
        if capture_after is not None and s.seq == capture_after:
            p.handle_command(SY.capture_command(s.seq, window_s=1.0))
    return segment_report(rows, seg_commands(samples[-1].seq), window_s=1.0)[0]


def test_yaw_left_from_level(make_processor):
    s = run(make_processor, lambda t: quat_from_zyx(HEADING + 90.0 * ramp(t), 0.0, 0.0), capture_after=10)
    assert "error" not in s
    for key in ("P_head", "P_track"):  # level start: both products coincide
        p = s[key]
        assert p["angle_deg"] == pytest.approx(90.0, abs=0.05)
        assert p["axis"] == pytest.approx((0.0, 0.0, 1.0), abs=1e-3)
        assert p["axis_from_vertical_deg"] == pytest.approx(0.0, abs=0.1)
        assert p["euler_display_deg"]["yaw"] == pytest.approx(90.0, abs=0.05)
    assert s["start"]["dispersion_max_deg"] < 0.01 and s["end"]["dispersion_max_deg"] < 0.01
    assert s["end"]["neutral_relative"]["euler_display_deg"]["yaw"] == pytest.approx(90.0, abs=0.05)


@pytest.mark.parametrize("pitch,roll,axis,name", [(30.0, 0.0, (0.0, 1.0, 0.0), "pitch"),
                                                  (0.0, 25.0, (1.0, 0.0, 0.0), "roll")])
def test_pitch_and_roll_signs(make_processor, pitch, roll, axis, name):
    s = run(make_processor, lambda t: quat_from_zyx(HEADING, pitch * ramp(t), roll * ramp(t)))
    p = s["P_head"]
    assert p["axis"] == pytest.approx(axis, abs=1e-3)
    assert p["axis_from_vertical_deg"] == pytest.approx(90.0, abs=0.1)
    assert p["euler_display_deg"][name] == pytest.approx(pitch or roll, abs=0.05)


WEDGE = quat_from_zyx(HEADING, 20.0, 0.0)  # glasses on a 20° nose-down wedge


def about_vertical(t):  # the whole wedge is turned on the table: rotation about the tracking-frame vertical
    return mul(quat_from_zyx(90.0 * ramp(t), 0.0, 0.0), WEDGE)


def about_own_up_axis(t):  # tilted turntable: rotation about the glasses' own up axis
    return mul(WEDGE, quat_from_zyx(90.0 * ramp(t), 0.0, 0.0))


@pytest.mark.parametrize("reading,vertical,tilted", [("head_to_track", "P_track", "P_head"),
                                                      ("track_to_head", "P_head", "P_track")])
def test_u1_rotation_about_vertical_tells_the_readings_apart(make_processor, reading, vertical, tilted):
    s = run(make_processor, about_vertical, reading=reading)
    assert s["start"]["tilt_from_upright_deg"] == pytest.approx(20.0, abs=0.05)
    assert s[vertical]["axis_from_vertical_deg"] == pytest.approx(0.0, abs=0.1)
    assert s[tilted]["axis_from_vertical_deg"] == pytest.approx(20.0, abs=0.1)  # = the wedge tilt
    assert s["P_head"]["angle_deg"] == pytest.approx(90.0, abs=0.05) == s["P_track"]["angle_deg"]


@pytest.mark.parametrize("reading,vertical,tilted", [("head_to_track", "P_head", "P_track"),
                                                      ("track_to_head", "P_track", "P_head")])
def test_u1_rotation_about_own_up_axis_reverses_the_roles(make_processor, reading, vertical, tilted):
    s = run(make_processor, about_own_up_axis, reading=reading)
    assert s[vertical]["axis_from_vertical_deg"] == pytest.approx(0.0, abs=0.1)
    assert s[tilted]["axis_from_vertical_deg"] == pytest.approx(20.0, abs=0.1)


def test_motion_inside_a_window_shows_in_its_dispersion(make_processor):
    # rotation starts 0.5 s into the segment, so the 1 s start window is not still
    s = run(make_processor, lambda t: quat_from_zyx(HEADING + 90.0 * ramp(t, hold=0.5), 0.0, 0.0))
    assert s["start"]["dispersion_max_deg"] > 1.0
    assert s["end"]["dispersion_max_deg"] < 0.01


def test_noise_is_reported_not_rejected(make_processor):
    s = run(make_processor, lambda t: quat_from_zyx(HEADING + 45.0 * ramp(t), 0.0, 0.0), noise_deg=0.05)
    assert 0.0 < s["start"]["dispersion_max_deg"] < 1.0
    assert s["P_head"]["angle_deg"] == pytest.approx(45.0, abs=0.1)


def test_errors_for_short_or_reconnecting_segments(make_processor):
    p = make_processor()
    short = [p.process(x)[0] for x in SY.generate(1.5)]
    assert segment_report(short, seg_commands(short[-1].seq), 1.0)[0]["error"] == "segment shorter than two windows"
    tr = SY.scenario_reconnect()
    p = make_processor()
    rows = [p.process(x)[0] for x in tr.samples]
    assert "reconnection" in segment_report(rows, seg_commands(rows[-1].seq), 1.0)[0]["error"]


def test_segments_follow_command_positions(make_processor):
    samples = SY.generate(12.0, orientation=lambda t: quat_from_zyx(HEADING + (30.0 if t > 6.0 else 0.0), 0, 0))
    p = make_processor()
    rows = [p.process(x)[0] for x in samples]
    split = next(x.seq for x in samples if x.seq > 0 and x.device_ts_raw - samples[0].device_ts_raw > 6e9) - 1
    cmds = [{"kind": "segment_start", "after_seq": -1, "data": {"label": "a"}},
            {"kind": "segment_start", "after_seq": split, "data": {"label": "b"}},
            {"kind": "segment_end", "after_seq": rows[-1].seq, "data": {}}]
    a, b = segment_report(rows, cmds, 1.0)
    assert (a["label"], b["label"]) == ("a", "b")
    assert a["n_samples"] + b["n_samples"] == len(rows)
    assert a["P_head"]["angle_deg"] < 0.05 and b["P_head"]["angle_deg"] < 0.05  # the jump is between them


def test_analyze_reports_segments(tmp_path):
    cfg = load_config()
    samples = SY.generate(2 * HOLD + MOVE, orientation=lambda t: quat_from_zyx(HEADING + 90.0 * ramp(t), 0, 0))
    trace = SY.Trace(samples, [Command("segment_start", 0, {"label": "yaw_left_90"}, after_seq=-1),
                               Command("segment_end", 0, {}, after_seq=samples[-1].seq)], [SY.connected_event(1)])
    meta = {"config": cfg, "processing": {"selected_hz": 240, "reference_rate_hz": 202.5}, "schema_version": "1.1.0",
            "mounting": "synthetic"}
    w = SessionWriter(tmp_path / "s", meta)
    pipe = Pipeline(cfg, OrientationProcessor(ProcessorConfig.from_config(cfg)), TrackingGate(100_000_000), w,
                    clock=None, fixed_stream_config={"selected_hz": 240, "reference_rate_hz": 202.5})
    pipe.process_all(trace.items())
    w.close()
    rep = analyze_session(tmp_path / "s")
    (seg,) = rep["segments"]
    assert seg["label"] == "yaw_left_90"
    assert seg["P_head"]["euler_display_deg"]["yaw"] == pytest.approx(90.0, abs=0.05)
    md = (tmp_path / "s" / "analysis" / "report.md").read_text(encoding="utf-8")
    assert "## Segments" in md and "yaw_left_90" in md
