"""GestureFSM (Phase 2A): transitions, repeat and switching rules, resets, freshness, invariant."""
import random

import pytest

from headmusic.instrument.events import AIMING, DWELL_ARMED, INACTIVE, NEUTRAL, RETURN_TO_NEUTRAL, UNARMED
from instrument_helpers import DT_NS, YAW, Driver, check_invariant

DWELL_MS = 500


def test_starts_inactive_and_arms_only_in_neutral():
    d = Driver()
    assert d.fsm.state == INACTIVE
    d.sample(YAW["C"])  # first usable sample, already in a region
    assert d.fsm.state == UNARMED
    d.hold(YAW["C"], 2000)  # resting in a region after startup never arms or commits
    assert d.fsm.state == UNARMED and d.commits() == []
    d.move(YAW["C"], 0.0, 100)
    assert d.fsm.state == NEUTRAL
    assert "return_neutral" in d.types()


def test_happy_path_commits_each_chord_once_at_exact_dwell():
    d = Driver()
    d.arm()
    for chord in ("C", "G", "Am", "F"):
        d.move(0.0, YAW[chord], 50)
        d.hold(YAW[chord], 700)
        d.move(YAW[chord], 0.0, 50)
        d.hold(0.0, 400)
    assert d.commits() == ["C", "G", "Am", "F"]
    for e in d.events:
        if e.event_type == "raw_commit":
            assert e.dwell_elapsed_ns == DWELL_MS * 1_000_000  # first sample with elapsed >= dwell
    assert check_invariant(d) == 4


def test_one_sample_short_of_dwell_does_not_commit():
    d = Driver()
    d.arm()
    d.sample(YAW["C"])  # dwell starts here
    assert d.fsm.state == DWELL_ARMED
    d.hold(YAW["C"], DWELL_MS - DT_NS / 1e6)  # elapsed = dwell - 1 period
    assert d.fsm.state == DWELL_ARMED and d.commits() == []
    assert d.fsm.progress == pytest.approx((DWELL_MS - 5) / DWELL_MS)
    d.sample(0.0)
    assert d.commits() == [] and "dwell_cancel" in d.types()
    d.sample(YAW["C"])
    d.hold(YAW["C"], DWELL_MS)
    assert d.commits() == ["C"]


def test_no_repeated_activation_from_one_pose_or_without_neutral():
    d = Driver()
    d.arm()
    d.move(0.0, YAW["C"], 20)
    d.hold(YAW["C"], 3000)
    assert d.commits() == ["C"] and d.fsm.state == RETURN_TO_NEUTRAL
    d.move(YAW["C"], YAW["G"], 60)  # to another region without returning to neutral
    d.hold(YAW["G"], 2000)
    assert d.commits() == ["C"]
    d.move(YAW["G"], 0.0, 30)
    d.hold(0.0, 400)
    d.move(0.0, YAW["G"], 20)
    d.hold(YAW["G"], 600)
    assert d.commits() == ["C", "G"]
    assert check_invariant(d) == 2


def test_target_switching_restarts_dwell():
    d = Driver()
    d.arm()
    d.move(0.0, YAW["G"], 20)
    d.hold(YAW["G"], 300)
    d.move(YAW["G"], YAW["C"], 60)  # leaves G (cancel), enters C
    d.hold(YAW["C"], DWELL_MS - 100)
    assert d.commits() == []
    cancels = [e for e in d.events if e.event_type == "dwell_cancel"]
    assert [e.chord for e in cancels] == ["G"]
    d.hold(YAW["C"], 200)
    assert d.commits() == ["C"]
    starts = [e for e in d.events if e.event_type == "dwell_start"]
    assert [e.chord for e in starts] == ["G", "C"]
    assert check_invariant(d) == 1


def test_rapid_movement_through_regions_commits_nothing():
    d = Driver()
    d.arm()
    for _ in range(5):
        d.move(0.0, 45.0, 200)
        d.move(45.0, -45.0, 400)
        d.move(-45.0, 0.0, 200)
    assert d.commits() == []
    assert "aim_enter" in d.types() and "dwell_cancel" in d.types()


def test_hysteresis_keeps_one_dwell_at_a_boundary():
    d = Driver()
    d.arm()
    d.move(0.0, 22.5, 40)  # just inside C (enters at 22)
    for _ in range(60):  # oscillate between 21.0 and 22.5: below the entry edge but within hysteresis (20.5)
        d.sample(21.0)
        d.sample(22.5)
    starts = [e for e in d.events if e.event_type == "dwell_start" and e.chord == "C"]  # the move passes G
    assert len(starts) == 1 and d.commits() == ["C"]


def test_leaving_beyond_hysteresis_cancels():
    d = Driver()
    d.arm()
    d.move(0.0, 22.5, 40)
    d.hold(20.4, 600)  # beyond 22 - 1.5
    assert d.commits() == [] and "dwell_cancel" in d.types()


def test_neutral_hysteresis():
    d = Driver()
    d.arm()
    d.hold(5.0, 200)  # beyond 4 but within 4 + 1.5: still neutral
    assert d.fsm.state == NEUTRAL
    d.sample(5.6)
    assert d.fsm.state == AIMING
    d.sample(4.5)  # re-entering needs <= 4
    assert d.fsm.state == AIMING
    d.sample(3.9)
    assert d.fsm.state == NEUTRAL


def test_cooldown_delays_the_next_dwell():
    d = Driver()  # cooldown 300 ms
    d.arm()
    d.sample(YAW["C"])
    d.hold(YAW["C"], DWELL_MS)
    assert d.commits() == ["C"]
    d.sample(0.0)  # back to neutral immediately
    d.sample(YAW["G"])  # 10 ms after the commit
    assert d.fsm.state == AIMING and d.types()[-1] == "aim_enter"
    d.hold(YAW["G"], 280)
    assert d.fsm.state == AIMING  # still in cooldown
    d.hold(YAW["G"], 20)
    assert d.fsm.state == DWELL_ARMED
    d.hold(YAW["G"], DWELL_MS)
    assert d.commits() == ["C", "G"]
    assert check_invariant(d) == 2


def test_rearm_hold():
    d = Driver(rearm_hold_ms=200.0)
    d.hold(0.0, 100)
    assert d.fsm.state == UNARMED
    d.hold(0.0, 105)
    assert d.fsm.state == NEUTRAL


def test_elevation_guard_excludes_poses():
    d = Driver(max_elevation_deg=30.0)
    d.arm()
    d.hold(YAW["C"], 1000, pitch=40.0)  # nose down 40°: forward axis 40° below the neutral plane
    assert d.commits() == [] and "aim_enter" not in d.types()
    d.hold(0.0, 100, pitch=40.0)  # not neutral either
    assert d.fsm.state == AIMING


def test_same_chord_can_be_committed_again_after_neutral():
    d = Driver()
    d.arm()
    for _ in range(2):
        d.move(0.0, YAW["Am"], 20)
        d.hold(YAW["Am"], 600)
        d.move(YAW["Am"], 0.0, 20)
        d.hold(0.0, 300)
    assert d.commits() == ["Am", "Am"]


# ---------------------------------------------------------------------------- resets: every trigger, every state
def _to_state(d: Driver, where: str):
    d.arm()
    if where == "neutral":
        return
    if where == "aiming":
        d.move(0.0, YAW["between"], 20)
        assert d.fsm.state == AIMING
        return
    d.move(0.0, YAW["C"], 20)
    assert d.fsm.state == DWELL_ARMED
    if where == "dwell_mid":
        d.hold(YAW["C"], 200)
    elif where == "dwell_last":
        d.hold(YAW["C"], DWELL_MS - 2 * DT_NS / 1e6)  # the next sample would commit
    elif where == "return":
        d.hold(YAW["C"], DWELL_MS)
        assert d.fsm.state == RETURN_TO_NEUTRAL


def _trigger(d: Driver, trig: str, yaw: float):
    """Apply one interruption while the head stays at `yaw`; return a function that ends it."""
    if trig in ("stale", "last_sample_invalid", "disconnected", "no_neutral", "no_valid_sample"):
        d.sample(yaw, usable=False, reasons=(trig,))
        return lambda: None
    if trig == "late_processing":
        d.sample(yaw, late=True)
        return lambda: None
    if trig == "gap":
        d.sample(yaw, flags=("gap_before",), dt_ns=300_000_000)
        return lambda: None
    if trig == "pause_600ms":
        d.interrupt("stale_tick", host_ns=d.h + 100_000_000)
        d.sample(yaw, flags=("gap_before",), dt_ns=600_000_000)
        return lambda: None
    if trig == "new_neutral":
        d.nid += 1
        d.sample(yaw)
        return lambda: None
    if trig == "reconnect":
        d.connection("device_disconnected")
        d.conn += 1
        d.d = 3_000_000_000  # the device clock restarts per connection
        d.connection("device_connected")
        d.sample(yaw, usable=False, reasons=("no_neutral",), rel=False)
        def end():
            d.nid += 1
        return end
    if trig == "stale_tick":
        d.interrupt("stale_tick")
        return lambda: None
    if trig == "capture_neutral":
        d.command("capture_neutral")
        d.hold(yaw, 100)
        def end():
            d.capture_result(accepted=True)
            d.nid += 1
        return end
    if trig in ("instrument_disable", "panic"):
        d.command(trig)
        d.hold(yaw, 100)
        return lambda: d.command("instrument_enable")
    raise AssertionError(trig)


TRIGGERS = ["stale", "last_sample_invalid", "disconnected", "no_neutral", "no_valid_sample", "late_processing", "gap",
            "pause_600ms", "new_neutral", "reconnect", "stale_tick", "capture_neutral", "instrument_disable", "panic"]
STATES = ["neutral", "aiming", "dwell_start", "dwell_mid", "dwell_last", "return"]


@pytest.mark.parametrize("where", STATES)
@pytest.mark.parametrize("trig", TRIGGERS)
def test_every_interruption_in_every_state_resets_and_needs_neutral(trig, where):
    d = Driver()
    _to_state(d, where)
    commits_before = d.commits()
    yaw = YAW["C"] if where.startswith("dwell") or where == "return" else d.inputs[-1][1]["yaw"]
    n_before = len(d.events)
    end = _trigger(d, trig, yaw)
    after = d.events[n_before:]
    assert d.commits(after) == []
    assert d.fsm.state in (INACTIVE, UNARMED)
    if where.startswith("dwell"):
        assert "dwell_cancel" in d.types(after)
    if where != "neutral":
        assert "gesture_reset" in d.types(after)
    assert any(e.event_type == "state_change" and e.state in (INACTIVE, UNARMED) for e in after)
    # the head stays in the C region throughout and after the interruption: nothing may commit
    end()
    d.hold(YAW["C"], 2000)
    assert d.commits() == commits_before
    assert d.fsm.state == UNARMED
    # deliberate re-arm: back to neutral, then a fresh dwell commits
    d.move(YAW["C"], 0.0, 50)
    d.move(0.0, YAW["C"], 50)
    d.hold(YAW["C"], 700)
    assert d.commits() == commits_before + ["C"]
    check_invariant(d)


def test_reset_reasons_are_logged():
    d = Driver()
    _to_state(d, "dwell_mid")
    d.sample(YAW["C"], flags=("gap_before",))
    resets = [e for e in d.events if e.event_type == "gesture_reset"]
    assert resets[-1].reason == "gap" and resets[-1].chord == "C"


def test_gap_reset_can_be_disabled():
    d = Driver(reset_on_gap_before=False)
    _to_state(d, "dwell_mid")
    d.sample(YAW["C"], flags=("gap_before",))
    assert d.fsm.state == DWELL_ARMED


# ---------------------------------------------------------------------------- freshness watermark
def test_data_produced_before_an_interruption_never_arms():
    d = Driver()
    _to_state(d, "dwell_mid")
    t_int = d.h + 1_000_000_000  # interruption detected 1 s after the last arrival (e.g. a pause)
    d.interrupt("stale_tick", host_ns=t_int)
    # queued samples produced before the interruption arrive afterwards: neutral, then the region
    for yaw in [0.0] * 40 + [YAW["C"]] * 150:  # 190 samples x 5 ms = 0.95 s, all produced before t_int
        d.sample(yaw)
    assert d.fsm.state == INACTIVE and d.commits() == []
    d.h = t_int  # fresh data from now on
    d.hold(YAW["C"], 1000)
    assert d.commits() == [] and d.fsm.state == UNARMED
    d.move(YAW["C"], 0.0, 30)
    d.move(0.0, YAW["C"], 20)
    d.hold(YAW["C"], 600)
    assert d.commits() == ["C"]


def test_capture_in_progress_rejection_does_not_end_suspension():
    d = Driver()
    d.arm()
    d.command("capture_neutral")
    d.capture_result(accepted=False, reasons=("capture_in_progress",))
    assert d.fsm.suspended
    d.capture_result(accepted=False, reasons=("dispersion_exceeds_tau_stab",))
    assert not d.fsm.suspended


# ---------------------------------------------------------------------------- randomised invariant
@pytest.mark.parametrize("seed", range(12))
def test_random_motion_with_random_faults_keeps_the_invariant(seed):
    rng = random.Random(seed)
    d = Driver()
    yaw = yaw_goal = 0.0
    for _ in range(12000):
        r = rng.random()
        if r < 0.001:
            d.interrupt("stale_tick")
        elif r < 0.0015:
            d.connection("device_disconnected"); d.conn += 1; d.connection("device_connected"); d.nid += 1
        elif r < 0.002:
            d.nid += 1
        if rng.random() < 0.006:
            yaw_goal = rng.choice([0.0, 0.0, YAW["C"], YAW["G"], YAW["Am"], YAW["F"], YAW["between"]])
        yaw += max(-1.5, min(1.5, yaw_goal - yaw)) + rng.gauss(0, 0.3)
        f = rng.random()
        if f < 0.0015:
            d.sample(yaw, usable=False, reasons=(rng.choice(["stale", "last_sample_invalid"]),))
        elif f < 0.0025:
            d.sample(yaw, flags=("gap_before",))
        elif f < 0.003:
            d.sample(yaw, late=True)
        else:
            d.sample(yaw)
    n = check_invariant(d)
    assert n >= 1  # the walk does commit sometimes, so the check is not vacuous
