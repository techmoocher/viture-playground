"""Play window (2C): the HUD model shows the FSM and engine state; the window only sends commands."""
import pytest

from headmusic.acquisition import synthetic as syn
from headmusic.cli import build_parser
from headmusic.config import load_config
from headmusic.instrument.regions import InstrumentConfig
from headmusic.orientation.processor import OrientationProcessor, ProcessorConfig
from headmusic.pipeline import Pipeline
from headmusic.stack import build_stack
from headmusic.tracking.gate import TrackingGate
from headmusic.viewer.hud import axis_half_range, hud_model, yaw_to_x

ICFG = InstrumentConfig.from_config(load_config())


def fsm(state, region=None, progress=None, yaw=0.0, elev=0.0, reason=None):
    return {"state": state, "region": region, "progress": progress, "yaw_rel_deg": yaw, "elevation_deg": elev,
            "inactive_reason": reason, "enabled": True, "suspended": False, "last_commit_chord": None}


ENGINE_SILENT = {"chord": None, "pending": None, "accompaniment": "off", "failed": None}


def model(f, engine=ENGINE_SILENT, usable=True, reasons=(), connected=True, **kw):
    return hud_model(ICFG, f, engine, usable, reasons, connected, **kw)


def test_axis_puts_left_turns_on_the_left():
    half = axis_half_range(ICFG)
    assert half == 50.0
    assert yaw_to_x(31.0, half) < 0.5 < yaw_to_x(-31.0, half)
    boxes = {b.chord: b for b in model(fsm("neutral")).regions}
    assert boxes["C"].x1 <= boxes["G"].x0 < boxes["G"].x1 < 0.5 < boxes["Am"].x0 < boxes["F"].x0  # contiguous
    m = model(fsm("dwell_armed", "C", 0.4, yaw=31.0))
    assert boxes["C"].x0 <= m.cursor_x <= boxes["C"].x1


@pytest.mark.parametrize("reason, hint", [("no_neutral", "press N"), ("panic", "EMERGENCY STOP"),
                                          ("disabled", "press E"), ("neutral_capture", "hold still"),
                                          ("stale|no_neutral", "stale"), ("disconnect", "disconnected")])
def test_inactive_hints(reason, hint):
    m = model(fsm("inactive", reason=reason), usable=False, reasons=("stale",))
    assert m.state_text == "INACTIVE" and hint in m.hint
    assert m.tracking_level == "bad" and "stale" in m.tracking_text


def test_state_texts_and_progress():
    assert "return to the neutral zone" in model(fsm("unarmed")).hint
    assert model(fsm("neutral")).state_text == "NEUTRAL: armed"
    m = model(fsm("dwell_armed", "G", 0.62, yaw=13.0))
    assert m.state_text == "DWELL G   62%" and m.progress == 0.62
    assert "return to the neutral zone" in model(fsm("return_to_neutral")).hint
    assert "cooldown" in model(fsm("aiming", "Am", yaw=-13.0)).hint


def test_region_roles_show_dwell_and_sounding():
    eng = {**ENGINE_SILENT, "chord": "C"}
    roles = {b.chord: b.role for b in model(fsm("dwell_armed", "G", 0.1, yaw=13.0), eng).regions}
    assert roles == {"C": "sounding", "G": "dwell", "Am": "", "F": ""}
    assert model(fsm("neutral"), eng).sounding_text == "SOUNDING: C"
    assert "next beat: G" in model(fsm("return_to_neutral"), {**eng, "pending": "G"}).sounding_text


def test_connection_output_and_eligibility_texts():
    assert model(fsm("inactive"), connected=False).tracking_text == "NOT CONNECTED"
    m = model(fsm("neutral"), {**ENGINE_SILENT, "failed": "BackendError('x')"})
    assert m.output_level == "bad" and "OUTPUT FAILED" in m.output_text
    m = model(fsm("aiming", yaw=31.0, elev=-89.5))
    assert not m.cursor_eligible and "ignored" in m.yaw_text
    assert model(fsm("inactive", yaw=None)).cursor_x is None
    assert "disabled in config" in model(fsm("neutral")).accompaniment_text
    assert model(fsm("neutral"), recent_commits=list("CGAF") * 3).recent_commits == tuple("CGAF" * 2)


def test_play_and_replay_view_arguments():
    ap = build_parser()
    a = ap.parse_args(["play", "--audio", "null", "--no-record", "--capture-neutral-at", "2"])
    assert a.cmd == "play" and not a.record and a.keep_awake and a.audio == "null"
    a = ap.parse_args(["replay", "x", "--instrument", "--view"])
    assert a.instrument and a.view


def test_play_window_draws_and_sends_only_commands():
    tk = pytest.importorskip("tkinter")
    cfg = load_config()
    gate = TrackingGate.from_config(cfg)
    stack = build_stack(cfg, gate, audio="null")
    pipe = Pipeline(cfg, OrientationProcessor(ProcessorConfig.from_config(cfg)), gate, None, clock=None,
                    fixed_stream_config={"selected_hz": 240, "reference_rate_hz": 202.5}, consumers=stack.consumers)
    items = syn.scenario_chords().items()
    pipe.process_all(items[: int(2.5 * 202.5)])  # C committed and sounding, head still in C
    from headmusic.viewer.play import PlayApp
    try:
        app = PlayApp(pipe, stack, "test", on_close=lambda: None)
    except tk.TclError as e:
        pytest.skip(f"no display: {e}")
    try:
        app.root.update()
        app.draw()
        m = app.model
        assert m.sounding_text == "SOUNDING: C" and m.state_text == "PLAYING C"  # direct + latch (iteration 2)
        assert m.notes_text.startswith("notes on: 60 64 67") and "Drawbar Organ" in m.notes_text
        assert m.recent_commits[-1] == "C"  # immediate keys: G sounded briefly on the way
        n_before = pipe.q.qsize()
        app.emergency_stop()
        app.capture()
        app.enable()
        kinds = [pipe.q.get_nowait().kind for _ in range(pipe.q.qsize() - n_before)]
        assert kinds == ["panic", "capture_neutral", "instrument_enable"]
        # nothing was decided by the window: the chord sounds until the pipeline processes the panic
        assert stack.engine.snapshot()["chord"] == "C"
        pipe.process_all([syn.Command("panic", 0, {}, after_seq=0)])
        assert stack.engine.snapshot()["chord"] is None
    finally:
        app.root.destroy()
        stack.close("test")


def test_emergency_stop_fallback_silences_when_the_pipeline_does_not_act():
    """Esc enqueues panic; if the pipeline thread is stuck, the window silences the engine directly."""
    tk = pytest.importorskip("tkinter")
    cfg = load_config()
    gate = TrackingGate.from_config(cfg)
    stack = build_stack(cfg, gate, audio="null")
    pipe = Pipeline(cfg, OrientationProcessor(ProcessorConfig.from_config(cfg)), gate, None, clock=None,
                    fixed_stream_config={"selected_hz": 240, "reference_rate_hz": 202.5}, consumers=stack.consumers)
    pipe.process_all(syn.scenario_chords().items()[: int(2.5 * 202.5)])  # C sounding
    from headmusic.viewer.play import PlayApp
    try:
        app = PlayApp(pipe, stack, "test", on_close=lambda: None)
    except tk.TclError as e:
        pytest.skip(f"no display: {e}")
    try:
        app.emergency_stop()  # the queued panic is never processed: the pipeline is "stuck"
        assert stack.engine.snapshot()["chord"] == "C"
        app._stop_fallback()  # what the window runs fallback_ms later
        assert stack.engine.snapshot()["chord"] is None
        m = stack.engine.backend.messages
        assert {(0x80, n, 0) for n in (60, 64, 67)} <= set(m) and (0xB0, 123, 0) in m
        assert stack.engine.events[-1]["event_type"] == "panic" and stack.engine.events[-1]["reason"] == "ui_direct"
    finally:
        app.root.destroy()
        stack.close("test")


def test_direct_mode_shows_the_sounding_chord_apart_from_the_candidate():
    """MVP refinement: G sounds while C is being confirmed; the HUD shows both, and the confirmation progress."""
    f = {**fsm("dwell_armed", "C", 0.5, yaw=31.0), "transitions": "direct", "playback": "latch",
         "active": "G", "candidate": "C"}
    m = model(f, {"chord": "G", "notes_on": [55, 59, 62]})
    assert m.sounding_text == "SOUNDING: G"
    assert m.state_text == "CONFIRMING C   50%" and m.progress == 0.5
    assert m.candidate_text == "candidate: C   confirming  50%"
    assert "G keeps sounding until C is confirmed" in m.hint
    roles = {b.chord: b.role for b in m.regions}
    assert roles["G"] == "sounding" and roles["C"] == "dwell"
    m2 = model({**f, "state": "engaged", "region": "G", "progress": None, "candidate": None}, {"chord": "G"})
    assert m2.candidate_text == "candidate: none" and m2.progress is None
