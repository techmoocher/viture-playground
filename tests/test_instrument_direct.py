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
    """The MVP default: direct switching, immediate keys (dwell 0), latch, neutral = silence."""
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


def test_neutral_means_silence_by_default():
    d = direct()
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
    # C (60 64 67) sounds from its commit until Am is confirmed, while the head sweeps across G and neutral
    c_on = next(i for i in ons if m[i][1] == 60)
    am_on = next(i for i in ons if m[i][1] == 57 and i > c_on)
    assert not [i for i in offs if c_on < i < am_on - 3]
    from test_music_engine import check_pairing
    check_pairing(m)
    reasons = [e.get("reason") for e in stack.engine.events if e["event_type"] == "midi_note_off"]
    assert reasons == ["chord_change", "chord_change", "chord_change", "neutral_rest", "intentional"]


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
        ["neutral_rest", "intentional"]


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


def test_continuous_demo_scenario():
    stack = run_stack(syn.scenario_continuous().items())
    commits = [e["chord"] for e in stack.instrument.events if e["event_type"] == "raw_commit"]
    assert commits == ["G", "C", "G", "Am", "F", "Am", "G", "C", "G"]  # the way back to neutral crosses G
    from test_music_engine import check_pairing
    check_pairing(stack.engine.backend.messages)
    reasons = [e.get("reason") for e in stack.engine.events if e["event_type"] == "midi_note_off"]
    assert reasons[:-1] == ["chord_change"] * 8 and reasons[-1] == "neutral_rest"
