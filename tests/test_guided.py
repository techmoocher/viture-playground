"""Guided bench scripts: the step machine, a simulated operator end to end, and the viewer wiring."""
import pytest

from headmusic.acquisition import synthetic as SY
from headmusic.metrics.segments import segment_report
from headmusic.orientation.euler import quat_from_zyx
from headmusic.orientation.quaternion import from_axis_angle, mul
from headmusic.types import Command
from headmusic.viewer.guided import SCRIPTS, GuidedScript, Step, make_script


def test_neutral_step_retries_until_accepted():
    g = GuidedScript("t", [Step("neutral", "neutral", "flat"), Step("segment", "s", "flat", "turn")])
    assert g.press(0.0) == [("capture_neutral", {})]
    assert g.press(0.5) == []  # ignored while capturing
    g.observe_neutral({"attempt": 1, "accepted": False, "reasons": ["gap_in_window"]})
    assert g.phase == "ready" and "REJECTED (gap_in_window)" in g.text(1.0)
    assert g.press(1.0) == [("capture_neutral", {})]
    g.observe_neutral({"attempt": 1, "accepted": False, "reasons": ["gap_in_window"]})  # old record: no change
    assert g.phase == "capturing"
    g.observe_neutral({"attempt": 2, "accepted": True, "reasons": []})
    assert g.i == 1 and g.phase == "ready" and "Neutral accepted" in g.text(5.0)


def test_segment_step_holds_inside_the_segment():
    g = GuidedScript("t", [Step("segment", "yaw_left_90", "flat on A", "turn left")], hold_s=2.0)
    start = g.press(10.0)
    assert start == [("segment_start", {"label": "yaw_left_90", "script": "t", "step": 1})]
    assert "HOLD STILL" in g.text(10.5) and g.press(10.5) == []  # presses during the countdown are ignored
    assert g.tick(11.9) == [] and g.phase == "hold_start"
    assert g.tick(12.0) == [] and g.phase == "moving" and "NOW: turn left" in g.text(12.0)
    assert g.press(15.0) == [] and g.phase == "hold_end"
    assert g.tick(16.9) == []
    assert g.tick(17.0) == [("segment_end", {})]
    assert g.phase == "done" and "all 1 steps done" in g.text(17.0)
    assert g.press(18.0) == [] and g.tick(30.0) == []


def test_scripts_match_the_checklist_labels():
    assert [s.label for s in SCRIPTS["r6a"]] == ["neutral", "yaw_left_90", "yaw_right_90", "pitch_down",
                                                  "roll_right_down"]
    assert [s.label for s in SCRIPTS["r6b"]] == ["u1_pitched_about_vertical", "u1_rolled_about_vertical"]
    assert [s.kind for s in SCRIPTS["r6c"]] == ["neutral", "segment", "neutral"]
    assert all(s.move for steps in SCRIPTS.values() for s in steps if s.kind == "segment")


# ---------------------------------------------------------------------------- simulated operator, end to end
RATE = 202.5
BASE = quat_from_zyx(-40.0, 5.0, 0.0)  # flat on line A, tilted back 5° like the real table placement
MOVES = {  # the physical movement of each step: (frame, axis, angle)
    "yaw_left_90": ("track", (0, 0, 1), 90.0), "yaw_right_90": ("track", (0, 0, 1), -90.0),
    "pitch_down": ("head", (0, 1, 0), 20.0), "roll_right_down": ("head", (1, 0, 0), 20.0),
}
STARTS = {"yaw_right_90": "after_previous"}  # every other step starts flat on line A


def simulate(script: GuidedScript, make_processor, react_s=0.5, move_s=2.0):
    """Walk the whole script: the operator presses Space 0.5 s after each prompt and moves for 2 s."""
    p = make_processor()
    rows, commands = [], []
    q_now, q_from, move, t_move = BASE, BASE, None, None
    t_prompt, last_phase, seq, t = 0.0, None, 0, 0.0
    while script.phase != "done" and t < 120.0:
        t = seq / RATE
        for kind, data in script.tick(t):
            commands.append(Command(kind, 0, data, after_seq=seq - 1))
        if (script.i, script.phase) != last_phase:
            last_phase, t_prompt = (script.i, script.phase), t
            step = script.step
            if script.phase == "ready" and step is not None:
                q_now = q_now if STARTS.get(step.label) == "after_previous" else BASE  # set up the step
            if script.phase == "moving":
                move, t_move, q_from = MOVES[step.label], t, q_now
        if move is not None:
            frame, axis, angle = move
            u = min(1.0, (t - t_move) / move_s)
            r = from_axis_angle(axis, angle * u)
            q_now = mul(r, q_from) if frame == "track" else mul(q_from, r)
        pressed = script.phase in ("ready", "moving") and t - t_prompt >= (react_s if script.phase == "ready"
                                                                           else move_s + react_s)
        if pressed:
            move = None if script.phase == "moving" else move
            for kind, data in script.press(t):
                commands.append(Command(kind, 0, data, after_seq=seq - 1))
        for c in [c for c in commands if c.after_seq == seq - 1 and c.kind == "capture_neutral"]:
            p.handle_command(Command(c.kind, 0, {"window_s": 3.0, "tau_stab_deg": 2.0}, after_seq=seq - 1))
        raw = SY.generate(1 / RATE + 1e-9, orientation=lambda _t, q=q_now: q, seq0=seq,
                          device_t0=SY.DEVICE_T0 + int(round(t * 1e9 / 1e6)) * 1_000_000,
                          host_t0=SY.HOST_T0 + int(t * 1e9))[0]
        ps, records = p.process(raw)
        rows.append(ps)
        for rec in records:
            script.observe_neutral(rec)
        seq += 1
    cmd_dicts = [{"kind": c.kind, "after_seq": c.after_seq, "data": c.data} for c in commands]
    return rows, cmd_dicts


def test_simulated_r6a_walkthrough_gives_the_expected_signs(make_processor):
    script = make_script("r6a")
    rows, cmds = simulate(script, make_processor)
    assert script.phase == "done"
    kinds = [c["kind"] for c in cmds]
    assert kinds.count("capture_neutral") == 1 and kinds.count("segment_start") == 4 == kinds.count("segment_end")
    segs = {s["label"]: s for s in segment_report(rows, cmds, window_s=1.0)}
    assert set(segs) == {"yaw_left_90", "yaw_right_90", "pitch_down", "roll_right_down"}
    for s in segs.values():
        assert "error" not in s, s
        assert s["start"]["dispersion_max_deg"] < 0.01 and s["end"]["dispersion_max_deg"] < 0.01  # holds inside
    assert segs["yaw_left_90"]["P_head"]["euler_display_deg"]["yaw"] == pytest.approx(90.0, abs=0.5)
    assert segs["yaw_right_90"]["P_head"]["euler_display_deg"]["yaw"] == pytest.approx(-90.0, abs=0.5)
    assert segs["pitch_down"]["P_head"]["euler_display_deg"]["pitch"] == pytest.approx(20.0, abs=0.1)
    assert segs["roll_right_down"]["P_head"]["euler_display_deg"]["roll"] == pytest.approx(20.0, abs=0.1)


# ---------------------------------------------------------------------------- viewer wiring (needs Tk)
class StubPipeline:
    cfg = {"neutral": {"window_s": 3.0, "tau_stab_deg": 2.0}}

    def __init__(self):
        self.cmds = []

    def submit_command(self, kind, **data):
        self.cmds.append((kind, data))


def test_viewer_guided_mode_submits_commands():
    tk = pytest.importorskip("tkinter")
    from headmusic.viewer.app import ViewerApp
    now = [0.0]
    stub = StubPipeline()
    try:
        app = ViewerApp(stub, "guided test", on_close=lambda: None, script=make_script("r6a"), clock=lambda: now[0])
    except tk.TclError as e:  # no display
        pytest.skip(f"Tk unavailable: {e}")
    try:
        app.root.withdraw()
        assert app.root.bind("<Key-n>") == ""  # the N shortcut is off in guided mode
        app.guided_press()
        assert stub.cmds[-1][0] == "capture_neutral"
        app._guided_refresh({"attempt": 1, "accepted": True, "reasons": []})
        assert "yaw_left_90" in app.guide.cget("text")
        app.guided_press()
        assert stub.cmds[-1] == ("segment_start", {"label": "yaw_left_90", "script": "r6a", "step": 2})
        now[0] = 2.1
        app._guided_refresh(None)
        assert "NOW:" in app.guide.cget("text")
        app.guided_press()
        now[0] = 4.3
        app._guided_refresh(None)
        assert stub.cmds[-1] == ("segment_end", {}) and "yaw_right_90" in app.guide.cget("text")
    finally:
        app.root.destroy()


def test_view_script_requires_record(capsys):
    from headmusic.cli import main
    assert main(["view", "--script", "r6a"]) == 2
    assert "--script needs --record" in capsys.readouterr().err
