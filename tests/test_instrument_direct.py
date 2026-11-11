"""MVP iteration 2 (docs/mvp-iteration-2.md): direct transitions, latch and hold, dwell stability,
no re-trigger, intentional release, interruption recovery. The protocol machine stays in test_instrument_fsm.py."""
import random

import pytest

from headmusic.acquisition import synthetic as syn
from headmusic.config import load_config
from headmusic.instrument.events import AIMING, DWELL_ARMED, ENGAGED, INACTIVE, NEUTRAL, UNARMED
from headmusic.orientation.processor import OrientationProcessor, ProcessorConfig
from headmusic.pipeline import Pipeline
from headmusic.stack import build_stack
from headmusic.tracking.gate import TrackingGate
from headmusic.types import Command
from instrument_helpers import DT_NS, YAW, Driver

DWELL_MS = 500


def direct(**kw):
    """Direct switching WITH dwell confirmation (config/profiles/confirm.toml)."""
    kw.setdefault("transitions", "direct")
    kw.setdefault("dwell_stability_deg", 3.0)
    kw.setdefault("dwell_ms", 500.0)
    kw.setdefault("cooldown_ms", 300.0)
    return Driver(**kw)


def immediate(**kw):
    """Immediate keys as in the first iteration-2 MVP (config/profiles/immediate.toml): direct switching, dwell 0,
    latch, neutral = silence after 150 ms."""
    kw.setdefault("transitions", "direct")
    kw.setdefault("dwell_ms", 0.0)
    kw.setdefault("neutral_rest_release_ms", 150.0)
    return Driver(**kw)


def settle(**kw):
    """The MVP defaults (interaction refinement): direct, 80 ms settle with a 2° stability band, latch, and the
    neutral zone never silences the active chord."""
    kw.setdefault("transitions", "direct")
    return Driver(**kw)


def play(d, chord, hold_ms=700, from_yaw=None, move_ms=50):
    d.move(d.inputs[-1][1]["yaw"] if from_yaw is None else from_yaw, YAW[chord], move_ms)
    d.hold(YAW[chord], hold_ms)


def releases(d):
    return [(e.chord, e.reason) for e in d.events if e.event_type == "chord_release"]


# ---------------------------------------------------------------------------- direct switching
def test_g_to_c_without_neutral():
    d = direct()
    d.arm()
    play(d, "G")
    assert d.commits() == ["G"] and d.fsm.state == ENGAGED
    d.move(YAW["G"], YAW["C"], 100)  # straight across, never near neutral
    assert all(abs(x[1]["yaw"]) > 6 for x in d.inputs[-20:] if x[0] == "sample")
    d.hold(YAW["C"], 700)
    assert d.commits() == ["G", "C"]
    assert "return_to_neutral" not in [e.state for e in d.events]


def test_latch_keeps_g_sounding_while_travelling_across_other_keys():
    d = direct()
    d.arm()
    play(d, "G")
    d.move(YAW["G"], 38.0, 100)  # across C without stopping (shorter than the dwell)
    d.move(38.0, YAW["G"], 100)
    d.move(YAW["G"], -15.0, 100)  # a fast sweep across neutral (< 150 ms in it) into Am, and back
    d.move(-15.0, YAW["G"], 100)
    assert d.fsm.selected_chord == "G" and releases(d) == [] and d.commits() == ["G"]
    assert d.fsm.state == ENGAGED


def test_neutral_rest_release_when_configured():
    d = direct(neutral_rest_release_ms=150.0)  # iteration 2's first default; now 0 (off)
    d.arm()
    play(d, "G")
    d.move(YAW["G"], 0.0, 60)
    d.hold(0.0, 100)
    assert releases(d) == []  # not yet: a short debounce so sweeps across neutral keep the sound
    d.hold(0.0, 100)
    assert releases(d) == [("G", "neutral_rest")]


def test_with_neutral_release_off_the_chord_sounds_through_a_rest():
    d = direct(neutral_rest_release_ms=0.0)
    d.arm()
    play(d, "G")
    d.move(YAW["G"], 0.0, 100)
    d.hold(0.0, 3000)
    assert d.fsm.selected_chord == "G" and releases(d) == []


def test_hold_mode_releases_on_leaving_and_needs_a_fresh_dwell():
    d = direct(playback="hold")
    d.arm()
    play(d, "G")
    d.move(YAW["G"], 0.0, 100)
    assert releases(d) == [("G", "left_region")] and d.fsm.selected_chord is None
    play(d, "G")
    assert d.commits() == ["G", "G"]


@pytest.mark.parametrize("deg_per_s", [120.0, 40.0, 18.0, 12.0, 8.0])
def test_passing_through_other_regions_does_not_play_them(deg_per_s):
    """F → C crosses Am, neutral and G. With the stability rule (3°), only C — where the head stops — commits."""
    d = direct()
    d.arm()
    play(d, "F")
    d.move(YAW["F"], YAW["C"], 1000 * (YAW["C"] - YAW["F"]) / deg_per_s)
    d.hold(YAW["C"], 700)
    assert d.commits() == ["F", "C"]


def test_without_stability_a_slow_pass_commits_the_inner_region():
    """The limitation the stability rule removes (U1): width / dwell = 10° / 0.5 s = 20°/s."""
    d = direct(dwell_stability_deg=0.0)
    d.arm()
    d.move(0.0, YAW["C"], 1000 * YAW["C"] / 12.0)
    d.hold(YAW["C"], 700)
    assert d.commits() == ["G", "C"]


def test_stability_allows_a_steady_hold_with_small_sway():
    d = direct()
    d.arm()
    d.move(0.0, YAW["C"], 50)
    rng = random.Random(1)
    for _ in range(int(700e6 / DT_NS)):
        d.sample(YAW["C"] + rng.uniform(-1.2, 1.2))  # within ±1.2° of the dwell start
    assert d.commits() == ["C"]


def test_stability_restarts_the_dwell_on_drift():
    d = direct()
    d.arm()
    d.move(0.0, 26.0, 50)
    d.move(26.0, 38.0, 600)  # 12° of drift inside C within the dwell: restarts, no commit yet
    assert d.commits() == [] and "dwell_restart" in d.types()
    d.hold(38.0, DWELL_MS + 10)
    assert d.commits() == ["C"]


# ---------------------------------------------------------------------------- no re-trigger
def test_same_chord_never_retriggers_while_staying_or_on_reentry_in_latch():
    d = direct()
    d.arm()
    play(d, "G", hold_ms=5000)
    d.move(YAW["G"], YAW["C"], 100)  # into C, not long enough to confirm it
    d.hold(YAW["C"], 200)
    play(d, "G", hold_ms=2000)  # back to G: still the selected chord
    assert d.commits() == ["G"]
    assert "engaged_enter" in d.types() and d.fsm.state == ENGAGED


def test_switch_needs_a_fresh_confirmed_target():
    d = direct()
    d.arm()
    play(d, "G")
    d.move(YAW["G"], YAW["C"], 60)
    d.hold(YAW["C"], DWELL_MS - 50)  # not yet confirmed
    d.move(YAW["C"], YAW["G"], 60)  # back to the selected chord: engaged, no re-trigger
    d.hold(YAW["G"], 1000)
    assert d.commits() == ["G"] and d.fsm.state == ENGAGED


# ---------------------------------------------------------------------------- intentional release
def test_release_command_releases_and_blocks_the_region_until_left():
    d = direct()
    d.arm()
    play(d, "C")
    d.command("release_chord")
    assert releases(d) == [("C", "intentional")] and d.fsm.state == UNARMED
    d.hold(YAW["C"], 2000)  # still in C: no re-trigger
    assert d.commits() == ["C"]
    d.move(YAW["C"], 15.0, 50)  # leave C into G (no neutral needed), not long enough to play G, and come back
    play(d, "C")
    assert d.commits() == ["C", "C"]


def test_release_command_while_travelling():
    d = direct()
    d.arm()
    play(d, "Am")
    d.move(YAW["Am"], 0.0, 100)
    d.command("release_chord")
    assert releases(d) == [("Am", "intentional")] and d.fsm.state == NEUTRAL
    d.command("release_chord")  # nothing selected: no second release
    assert len(releases(d)) == 1


def test_neutral_rest_release_when_enabled():
    d = direct(neutral_rest_release_ms=800.0)
    d.arm()
    play(d, "F")
    d.move(YAW["F"], 0.0, 100)
    d.hold(0.0, 700)
    assert releases(d) == []
    d.hold(0.0, 200)
    assert releases(d) == [("F", "neutral_rest")]


# ---------------------------------------------------------------------------- interruption recovery
@pytest.mark.parametrize("trigger", ["stale_tick", "stale", "last_sample_invalid", "gap", "new_neutral",
                                     "reconnect", "late_processing"])
@pytest.mark.parametrize("where", ["engaged", "dwell", "neutral"])
def test_interruption_releases_blocks_and_rearms_by_leaving(trigger, where):
    d = direct()
    d.arm()
    if where == "engaged":
        play(d, "C")
        yaw = YAW["C"]
    elif where == "dwell":
        play(d, "G")
        d.move(YAW["G"], YAW["C"], 60)
        d.hold(YAW["C"], 200)
        yaw = YAW["C"]
    else:
        play(d, "G")
        d.move(YAW["G"], 0.0, 50)  # latched G, now in neutral
        yaw = 0.0
    n = len(d.events)
    if trigger == "stale_tick":
        d.interrupt("stale_tick")
    elif trigger in ("stale", "last_sample_invalid"):
        d.sample(yaw, usable=False, reasons=(trigger,))
    elif trigger == "gap":
        d.sample(yaw, flags=("gap_before",), dt_ns=300_000_000)
    elif trigger == "new_neutral":
        d.nid += 1
        d.sample(yaw)
    elif trigger == "late_processing":
        d.sample(yaw, late=True)
    else:
        d.connection("device_disconnected")
        d.conn += 1
        d.d = 3_000_000_000
        d.connection("device_connected")
        d.sample(yaw, usable=False, reasons=("no_neutral",), rel=False)
        d.nid += 1
    after = d.events[n:]
    assert "gesture_reset" in [e.event_type for e in after]  # the engine releases every note on this
    assert d.fsm.selected_chord is None
    commits_before = d.commits()
    d.hold(yaw, 2000)  # the head stays where it was: nothing plays
    assert d.commits() == commits_before
    if yaw == YAW["C"]:
        assert d.fsm.state == UNARMED  # C is blocked until left
    target = "G" if yaw == YAW["C"] else "C"
    play(d, target, move_ms=100)  # leave and confirm a fresh target: no neutral needed
    assert d.commits() == commits_before + [target]


def test_old_queued_samples_never_arm_after_recovery_in_direct_mode():
    d = direct()
    d.arm()
    play(d, "G")
    t_int = d.h + 1_000_000_000
    d.interrupt("stale_tick", host_ns=t_int)
    for yaw in [0.0] * 40 + [YAW["C"]] * 150:  # produced before the interruption, delivered after
        d.sample(yaw)
    assert d.fsm.state == INACTIVE and d.commits() == ["G"]
    d.h = t_int
    d.hold(YAW["C"], 300)  # fresh data, head still in C: blocked (it was in C at recovery)
    assert d.fsm.state == UNARMED and d.commits() == ["G"]
    d.move(YAW["C"], 15.0, 50)  # leave C, then confirm it as a fresh target
    play(d, "C")
    assert d.commits() == ["G", "C"]


# ---------------------------------------------------------------------------- MIDI: sustain, patch, releases
CONFIRM = {"dwell_ms": 500.0, "cooldown_ms": 300.0, "dwell_stability_deg": 3.0}  # config/profiles/confirm.toml
IMMEDIATE = {"dwell_ms": 0.0, "neutral_rest_release_ms": 150.0}  # config/profiles/immediate.toml


def run_stack(items, **instrument):
    cfg = load_config()
    cfg["instrument"] = {**cfg["instrument"], **instrument}
    gate = TrackingGate.from_config(cfg)
    stack = build_stack(cfg, gate, audio="null")
    pipe = Pipeline(cfg, OrientationProcessor(ProcessorConfig.from_config(cfg)), gate, None, clock=None,
                    fixed_stream_config={"selected_hz": 240, "reference_rate_hz": 202.5}, consumers=stack.consumers)
    pipe.process_all(items)
    stack.close("end_of_stream")
    return stack


def test_sustained_patch_and_no_note_off_while_latched_across_movement():
    stack = run_stack(syn.scenario_transitions().items(), **CONFIRM)
    m = stack.engine.backend.messages
    assert m[0] == (0xC0, 16, 0)  # Drawbar Organ program change first
    ons = [i for i, x in enumerate(m) if x[0] == 0x90]
    offs = [i for i, x in enumerate(m) if x[0] == 0x80]
    # C (60 64 67) sounds from its commit until Am is confirmed, while the head sweeps across G and neutral;
    # F sounds through the slow traverse (neutral never silences by default) until C is confirmed
    c_on = next(i for i in ons if m[i][1] == 60)
    am_on = next(i for i in ons if m[i][1] == 57 and i > c_on)
    assert not [i for i in offs if c_on < i < am_on - 3]
    from test_music_engine import check_pairing
    check_pairing(m)
    reasons = [e.get("reason") for e in stack.engine.events if e["event_type"] == "midi_note_off"]
    assert reasons == ["chord_change"] * 4 + ["intentional"]


def test_hold_mode_midi_releases_on_leaving():
    stack = run_stack(syn.scenario_transitions().items(), playback="hold", **CONFIRM)
    reasons = [e.get("reason") for e in stack.engine.events if e["event_type"] == "midi_note_off"]
    assert reasons == ["left_region"] * 4 + ["intentional"]


def test_release_command_through_the_pipeline_is_logged_and_replayable():
    items = syn.scenario_transitions().items()
    cmds = [x for x in items if isinstance(x, Command) and x.kind == "release_chord"]
    assert len(cmds) == 1
    stack = run_stack(items, **CONFIRM)
    assert [e["reason"] for e in stack.instrument.events if e["event_type"] == "chord_release"] == \
        ["intentional"]


def test_transitions_demo_commits():
    stack = run_stack(syn.scenario_transitions().items(), **CONFIRM)
    assert [e["chord"] for e in stack.instrument.events if e["event_type"] == "raw_commit"] == \
        ["G", "C", "Am", "F", "C"]


# ---------------------------------------------------------------------------- immediate keys (the MVP default)
def test_neutral_once_then_c_g_f_am_c_continuously():
    """The operator's flow: calibrate at neutral once, then play C -> G -> F -> Am -> C without returning to neutral.
    Each chord sounds on the first sample inside its key. Keys crossed on the way sound briefly (no dwell)."""
    d = immediate()
    d.arm()
    for a, b in [(0.0, 31.0), (31.0, 13.0), (13.0, -31.0), (-31.0, -13.0), (-13.0, 31.0)]:
        d.move(a, b, 150)
        d.hold(b, 600)
    assert [c for c in d.commits()] == ["G", "C", "G", "Am", "F", "Am", "G", "C"]
    held = [c for c, nxt in zip(d.commits(), d.commits()[1:] + [None])]
    assert d.fsm.selected_chord == "C" and releases(d) == []  # never silenced: no rest in neutral on the way
    assert "return_to_neutral" not in [e.state for e in d.events]


def test_immediate_sound_on_the_first_sample_inside_the_key():
    d = immediate()
    d.arm()
    d.move(0.0, 4.9, 20)
    assert d.commits() == []
    d.sample(5.1)  # first sample inside G
    assert d.commits() == ["G"] and d.events[-1].state == ENGAGED


def test_immediate_keys_do_not_flicker_at_a_shared_edge():
    d = immediate()
    d.arm()
    d.move(0.0, 18.5, 40)  # G holds past its edge (18) until 18 + 1.5
    assert d.commits() == ["G"]
    d.sample(19.8)  # clearly into C
    for _ in range(100):  # wobble across the edge, within C's hysteresis (down to 16.5)
        d.sample(17.2)
        d.sample(19.8)
    assert d.commits() == ["G", "C"]
    d.sample(16.4)  # clearly back in G (beyond 18 - 1.5)
    assert d.commits() == ["G", "C", "G"]


def test_immediate_staying_or_wobbling_in_a_key_never_retriggers():
    d = immediate()
    d.arm()
    d.move(0.0, 13.0, 40)
    rng = random.Random(3)
    for _ in range(1000):
        d.sample(13.0 + rng.uniform(-4.0, 4.0))  # stays inside G [5, 18]
    assert d.commits() == ["G"]


def test_immediate_hold_mode_sounds_only_while_on_the_key():
    d = immediate(playback="hold")
    d.arm()
    d.move(0.0, 31.0, 150)
    d.hold(31.0, 300)
    assert d.fsm.selected_chord == "C"
    d.move(31.0, 0.0, 150)
    d.hold(0.0, 50)
    assert d.fsm.selected_chord is None and ("C", "left_region") in releases(d)


def test_immediate_neutral_silences_and_recovery_needs_leaving_the_key():
    d = immediate()
    d.arm()
    d.move(0.0, 31.0, 100)
    d.hold(31.0, 300)
    d.interrupt("stale_tick")  # e.g. a 300 ms device pause while on C
    assert d.fsm.selected_chord is None
    d.hold(31.0, 1000)  # still on C after recovery: blocked, silent
    assert d.commits()[-1] == "C" and d.fsm.state == UNARMED and d.commits().count("C") == 1
    d.move(31.0, 13.0, 100)  # move to another key: sounds at once
    assert d.commits()[-1] == "G"
    d.move(13.0, 0.0, 60)
    d.hold(0.0, 200)
    assert releases(d)[-1] == ("G", "neutral_rest")


def test_continuous_demo_with_immediate_keys():
    stack = run_stack(syn.scenario_continuous().items(), **IMMEDIATE)
    commits = [e["chord"] for e in stack.instrument.events if e["event_type"] == "raw_commit"]
    assert commits == ["G", "C", "G", "Am", "F", "Am", "G", "C", "G"]  # the way back to neutral crosses G
    from test_music_engine import check_pairing
    check_pairing(stack.engine.backend.messages)
    reasons = [e.get("reason") for e in stack.engine.events if e["event_type"] == "midi_note_off"]
    assert reasons[:-1] == ["chord_change"] * 8 and reasons[-1] == "neutral_rest"


# ---------------------------------------------------------------------------- the MVP default: 80 ms / 2° settle
# docs/mvp-iteration-2.md §8. The ACTIVE chord (last confirmed) keeps sounding while a CANDIDATE is confirmed.
def default_stack_trace(path):
    """Neutral capture, then the head path `path` [(t_s, yaw_deg), ...] (keyframes)."""
    s = syn.generate(path[-1][0] + 0.2, orientation=syn.keyframes(path))
    return syn.Trace(s, [syn.capture_command(20, window_s=0.5)], [syn.connected_event(1)])


def step_stack(items, **instrument):
    """Runs the full stack (FSM + chord engine, null MIDI) item by item and records, after every pose sample,
    (FSM state, active chord, candidate chord, chord the engine sounds, MIDI notes on)."""
    cfg = load_config()
    cfg["instrument"] = {**cfg["instrument"], **instrument}
    gate = TrackingGate.from_config(cfg)
    stack = build_stack(cfg, gate, audio="null")
    pipe = Pipeline(cfg, OrientationProcessor(ProcessorConfig.from_config(cfg)), gate, None, clock=None,
                    fixed_stream_config={"selected_hz": 240, "reference_rate_hz": 202.5}, consumers=stack.consumers)
    trace = []
    fsm = stack.instrument.fsm
    for item in items:
        pipe._handle(item)
        if hasattr(item, "device_ts_raw"):
            snap = stack.engine.snapshot()
            trace.append((fsm.state, fsm.active_chord, fsm.candidate_chord, snap["chord"], tuple(snap["notes_on"])))
    stack.final_snapshot = stack.engine.snapshot()  # after every input, before the stream-end stop
    stack.close("end_of_stream")
    return stack, trace


def note_events(stack):
    return [(e["event_type"], e["chord"], e.get("reason")) for e in stack.engine.events
            if e["event_type"] in ("midi_note_on", "midi_note_off")]


@pytest.mark.parametrize("deg_per_s", [30.0, 60.0, 120.0, 240.0])
def test_f_to_c_has_no_audible_gap_through_other_keys_and_neutral(deg_per_s):
    """F sounds, the head turns to C across Am, neutral and G: F sounds at every sample until C is confirmed,
    then C. Nothing else sounds and there is never a sample with no chord."""
    move = (31.0 - -31.0) / deg_per_s
    stack, trace = step_stack(default_stack_trace(
        [(0.0, 0.0), (1.0, 0.0), (1.3, -31.0), (2.3, -31.0), (2.3 + move, 31.0), (3.3 + move, 31.0)]).items())
    first_f = next(i for i, x in enumerate(trace) if x[3] == "F")
    sounding = [x[3] for x in trace[first_f:]]
    assert None not in sounding  # no gap, ever
    c_from = sounding.index("C")
    assert set(sounding[:c_from]) == {"F"} and set(sounding[c_from:]) == {"C"}
    assert note_events(stack) == [("midi_note_on", "F", None), ("midi_note_off", "F", "chord_change"),
                                  ("midi_note_on", "C", None), ("midi_note_off", "C", "interruption:stop")]
    f_notes = trace[first_f][4]
    assert all(x[4] == f_notes for x in trace[first_f:first_f + c_from])  # the F notes stay on, unchanged


def test_slow_pass_across_neutral_keeps_the_active_chord():
    """neutral_rest_release_ms = 0: Am -> G at 10 deg/s spends ~1 s in the neutral zone; Am sounds throughout."""
    stack, trace = step_stack(default_stack_trace(
        [(0.0, 0.0), (1.0, 0.0), (1.3, -13.0), (2.3, -13.0), (4.9, 13.0), (5.9, 13.0)]).items())
    first = next(i for i, x in enumerate(trace) if x[3] == "Am")
    sounding = [x[3] for x in trace[first:]]
    assert None not in sounding and sounding[-1] == "G"
    assert any(x[0] == NEUTRAL and x[3] == "Am" for x in trace)
    assert [e for e in note_events(stack) if e[0] == "midi_note_off"] == [
        ("midi_note_off", "Am", "chord_change"), ("midi_note_off", "G", "interruption:stop")]


def test_g_sustains_while_c_is_pending_confirmation():
    d = settle()
    d.arm()
    play(d, "G")
    d.move(YAW["G"], YAW["C"], 300)  # 60 deg/s
    pending = []
    while d.commits() == ["G"]:
        d.sample(YAW["C"])
        if d.fsm.candidate_chord == "C":
            pending.append(d.fsm.active_chord)
    assert pending and set(pending) == {"G"}  # C was the candidate for a while, G active the whole time
    starts = [e for e in d.events if e.event_type == "dwell_start" and e.chord == "C"]
    assert starts and all(e.active_chord == "G" for e in starts)
    commit = [e for e in d.events if e.event_type == "raw_commit"][-1]
    assert commit.chord == "C" and commit.active_chord == "G"  # the confirmation names the chord it replaces
    assert len(pending) * DT_NS <= 80e6 + DT_NS  # onset after stopping: the 80 ms dwell, within one sample
    assert releases(d) == []


def test_cancelled_or_restarted_confirmation_never_releases_g():
    d = settle()
    d.arm()
    play(d, "G")
    d.move(YAW["G"], YAW["C"], 300)
    d.hold(YAW["C"], 40)  # C pending
    for k in range(20):  # sway of ±3° inside C: the confirmation restarts again and again
        d.sample(YAW["C"] + (3.0 if k % 2 else -3.0))
    assert "dwell_restart" in d.types() and d.commits() == ["G"]
    d.move(YAW["C"], 0.0, 300)  # change direction: C is cancelled, back across G to neutral
    d.hold(0.0, 3000)  # a long rest in neutral
    assert "dwell_cancel" in d.types()
    g_commit = max(i for i, e in enumerate(d.events) if e.event_type == "raw_commit")
    candidate_events = [e for e in d.events[g_commit:] if e.event_type in ("dwell_restart", "dwell_cancel")]
    assert candidate_events
    assert all(e.active_chord == "G" for e in candidate_events)
    assert d.commits() == ["G"] and releases(d) == [] and d.fsm.active_chord == "G"


def test_a_confirmed_chord_switches_the_sound_exactly_once():
    stack, trace = step_stack(default_stack_trace(
        [(0.0, 0.0), (1.0, 0.0), (1.3, 13.0), (2.3, 13.0), (2.6, 31.0), (5.0, 31.0)]).items())
    assert note_events(stack) == [("midi_note_on", "G", None), ("midi_note_off", "G", "chord_change"),
                                  ("midi_note_on", "C", None), ("midi_note_off", "C", "interruption:stop")]
    m = stack.engine.backend.messages
    assert len([x for x in m if x[0] == 0x90 and x[1] == 60]) == 1  # C's root note-on is sent once
    from test_music_engine import check_pairing
    check_pairing(m)
    changes = [i for i in range(1, len(trace)) if trace[i][3] != trace[i - 1][3]]
    assert [trace[i][3] for i in changes] == ["G", "C"]  # silent -> G -> C: one switch to C, on one sample


def test_remaining_within_one_region_never_retriggers():
    d = settle()
    d.arm()
    play(d, "C")
    rng = random.Random(7)
    for _ in range(3000):  # 15 s of large movement that stays inside C [18, 40] (beyond the 2° band)
        d.sample(rng.uniform(21.0, 38.0))
    assert d.commits() == ["C"] and releases(d) == [] and d.fsm.state == ENGAGED


@pytest.mark.parametrize("deg_per_s, expected", [(15.0, ["F", "Am", "G", "C"]), (30.0, ["F", "C"])])
def test_very_slow_crossings_may_still_activate_intermediate_keys(deg_per_s, expected):
    """Known limitation (docs/mvp-iteration-2.md §8): below about stability / dwell = 2° / 80 ms = 25 deg/s, a
    crossing looks like a deliberate placement, so the crossed keys become active on the way."""
    d = settle()
    d.arm()
    play(d, "F")
    d.move(YAW["F"], YAW["C"], 1000 * (YAW["C"] - YAW["F"]) / deg_per_s)
    d.hold(YAW["C"], 300)
    assert d.commits() == expected


def test_release_r_while_a_candidate_is_pending_silences_and_cancels_it():
    d = settle()
    d.arm()
    play(d, "G")
    d.move(YAW["G"], YAW["C"], 300)
    d.hold(YAW["C"], 30)
    assert d.fsm.candidate_chord == "C" and d.fsm.active_chord == "G"
    d.command("release_chord")
    assert releases(d) == [("G", "intentional")] and d.fsm.state == UNARMED
    assert d.fsm.active_chord is None and d.fsm.candidate_chord is None
    d.hold(YAW["C"], 2000)  # still in C: R means silence, C does not start a moment later
    assert d.commits() == ["G"]
    play(d, "G", move_ms=300)  # leave C: armed again
    assert d.commits() == ["G", "G"]


@pytest.mark.parametrize("how", ["release", "panic", "stale", "disconnect"])
@pytest.mark.parametrize("when", ["active", "pending"])
def test_release_panic_and_tracking_failure_silence(how, when):
    """R, Esc (panic) and genuine tracking failures silence the active chord, also while a candidate is pending."""
    from headmusic.types import Event
    rate = 202.5
    path = [(0.0, 0.0), (1.0, 0.0), (1.3, 13.0), (2.3, 13.0)]
    if when == "pending":
        path += [(2.6, 31.0)]  # the interruption hits ~20 ms after reaching C, before the 80 ms confirmation
    t_cut = path[-1][0] + 0.02
    path += [(t_cut + 2.0, path[-1][1])]
    s = syn.generate(path[-1][0], orientation=syn.keyframes(path))
    i_cut = int(t_cut * rate)
    cmds, evs = [syn.capture_command(20, window_s=0.5)], [syn.connected_event(1)]
    if how == "release":
        cmds.append(Command("release_chord", 0, {}, after_seq=i_cut))
    elif how == "panic":
        cmds.append(Command("panic", 0, {}, after_seq=i_cut))
    elif how == "stale":
        s = syn.resequence(s[:i_cut] + s[i_cut + int(0.6 * rate):])  # 600 ms device pause
    else:
        s = s[:i_cut]
        evs.append(Event("device_disconnected", 0, {"connection_id": 1, "last_seq": i_cut - 1}))
    stack, trace = step_stack(syn.Trace(s, cmds, evs).items())
    assert stack.final_snapshot["chord"] is None and stack.final_snapshot["notes_on"] == []  # silent afterwards
    assert [e["chord"] for e in stack.instrument.events if e["event_type"] == "raw_commit"] == ["G"]
    if how == "panic":  # everything off at once (CC 123/120 + reset), logged as one panic event
        assert "panic" in [e["event_type"] for e in stack.engine.events]
        return
    offs = [e for e in note_events(stack) if e[0] == "midi_note_off"]
    expected = {"release": "intentional", "stale": "interruption:gap", "disconnect": "interruption:disconnect"}[how]
    assert offs and offs[0][1] == "G" and offs[0][2] == expected, offs


def test_continuous_demo_default_settle():
    """The operator's flow with the defaults: C -> G -> F -> Am -> C, every crossed key silent, no gap, then R."""
    stack, trace = step_stack(syn.scenario_continuous().items())
    assert [e["chord"] for e in stack.instrument.events if e["event_type"] == "raw_commit"] == \
        ["C", "G", "F", "Am", "C"]
    first = next(i for i, x in enumerate(trace) if x[3] == "C")
    last = max(i for i, x in enumerate(trace) if x[3] is not None)
    assert None not in [x[3] for x in trace[first:last + 1]]
    reasons = [e[2] for e in note_events(stack) if e[0] == "midi_note_off"]
    assert reasons == ["chord_change"] * 4 + ["intentional"]


def test_settle_session_replays_identically(tmp_path):
    """The candidate and active fields are deterministic: record the continuous demo, replay it, compare."""
    from headmusic.cli import main
    s = tmp_path / "s"
    assert main(["synth", "continuous", "--instrument", "--out", str(s)]) == 0
    text = (s / "interaction_events.jsonl").read_text(encoding="utf-8")
    assert '"active_chord"' in text  # candidate events name the sounding chord
    assert main(["replay", str(s), "--reprocess", "--instrument", "--out", str(tmp_path / "r")]) == 0
    for f in ("interaction_events.jsonl", "music_events.jsonl"):
        assert (s / f).read_bytes() == (tmp_path / "r" / f).read_bytes()


@pytest.mark.parametrize("profile, expected", [
    ({}, ["F", "C", "F", "Am", "G", "C"]),  # defaults: only the 15 deg/s pass sounds the crossed keys
    (IMMEDIATE, ["Am", "F", "Am", "G", "C", "G", "Am", "F", "Am", "G", "C"]),  # every crossed key sounds
    (CONFIRM, ["F", "C", "F", "C"])])
def test_traverse_demo_compares_settle_settings(profile, expected):
    stack, trace = step_stack(syn.scenario_traverse().items(), **profile)
    assert [e["chord"] for e in stack.instrument.events if e["event_type"] == "raw_commit"] == expected
