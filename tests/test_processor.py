"""Sample flags, sign handling, timestamps and invalid measurements."""
import math

import pytest

from conftest import load_real_trace
from headmusic.acquisition import synthetic as SY
from headmusic.orientation import flags as F
from headmusic.orientation import quaternion as Q
from headmusic.orientation.euler import quat_from_zyx
from headmusic.types import RawPoseSample


def run(proc, items):
    out, records = [], []
    for it in items:
        if isinstance(it, RawPoseSample):
            ps, recs = proc.process(it)
            out.append(ps)
            records += recs
        elif hasattr(it, "after_seq"):
            records += proc.handle_command(it)
    return out, records


def samples_from_ts(ts_list, conn=1):
    q = (1.0, 0.0, 0.0, 0.0)
    return [RawPoseSample(i, conn, 1_000_000_000 + (t - ts_list[0]), t, (0.0, 0.0, 0.0, *q))
            for i, t in enumerate(ts_list)]


# ---------------------------------------------------------------- invalid measurements
def test_each_fault_flags_exactly_its_sample(make_processor):
    tr = SY.scenario_faults()
    out, _ = run(make_processor(), tr.items())
    pos = tr.info["positions"]
    by_flag = {f: [p.seq for p in out if f in p.flags] for f in F.ALL_FLAGS}
    assert by_flag[F.NONFINITE] == pos["nonfinite"]
    assert by_flag[F.ZERO_NORM] == pos["zero_norm"]
    assert by_flag[F.TS_DUPLICATE] == pos["ts_duplicate"]
    assert by_flag[F.TS_BACKWARD] == pos["ts_backward"]
    assert by_flag[F.ANGULAR_JUMP] == pos["angular_jump"]  # the return from the glitch is NOT flagged
    assert by_flag[F.NORM_DEVIATION] == pos["norm_deviation"]
    invalid = sorted(p.seq for p in out if not p.valid)
    assert invalid == sorted(pos["nonfinite"] + pos["zero_norm"] + pos["ts_duplicate"] + pos["ts_backward"]
                             + pos["angular_jump"])
    # Invalid values with in-order timestamps do not create gaps; bad timestamps leave one gap after them.
    assert by_flag[F.GAP_BEFORE] == [pos["ts_duplicate"][0] + 1, pos["ts_backward"][0] + 1]
    # Invalid rows are kept, never dropped.
    assert len(out) == len(tr.samples)


def test_nonfinite_rows_have_no_derived_orientation(make_processor):
    out, _ = run(make_processor(), SY.scenario_faults().items())
    for p in out:
        if F.NONFINITE in p.flags or F.ZERO_NORM in p.flags:
            assert p.quat is None and p.quat_rel is None and p.euler_display is None


def test_persistent_jump_flags_one_sample(make_processor):
    s = SY.generate(2.0)
    jumped = [SY.with_values(x, (*x.values[:3], *Q.mul(x.values[3:7], quat_from_zyx(60, 0, 0))))
              if i >= 100 else x for i, x in enumerate(s)]
    out, _ = run(make_processor(), jumped)
    assert [p.seq for p in out if F.ANGULAR_JUMP in p.flags] == [100]


def test_norm_deviation_sample_is_normalised_and_valid(make_processor):
    out, _ = run(make_processor(), SY.scenario_faults().items())
    p = next(p for p in out if F.NORM_DEVIATION in p.flags)
    assert p.valid and Q.norm(p.quat) == pytest.approx(1.0, abs=1e-12)


# ---------------------------------------------------------------- quaternion sign changes
def test_sign_flips_are_made_continuous_and_flagged(make_processor):
    tr = SY.scenario_sign_flip()
    out, _ = run(make_processor(), tr.items())
    flipped = [p for p in out if F.HEMISPHERE_FLIP in p.flags]
    assert len(flipped) == len(out) - 1  # the SDK sign alternates on every sample in this trace
    assert all(p.valid for p in out)
    for a, b in zip(out, out[1:]):
        assert Q.dot(a.quat, b.quat) > 0.99
    rels = [p for p in out if p.quat_rel is not None]
    assert rels and all(p.quat_rel[0] >= 0 for p in rels)


def test_sdk_canonical_sign_change_flagged_once(make_processor):
    """Like the real SDK (w >= 0): a rotation through w = 0 changes the SDK sign once."""
    s = SY.generate(4.0, orientation=lambda t: quat_from_zyx(150 + 15 * t, 0, 0))  # yaw 150° -> 210°
    s = [SY.with_values(x, (*x.values[:3], *Q.canonical(x.values[3:7]))) for x in s]
    out, _ = run(make_processor(), s)
    assert len([p for p in out if F.HEMISPHERE_FLIP in p.flags]) == 1
    assert all(Q.dot(a.quat, b.quat) > 0 for a, b in zip(out, out[1:]))


def test_yaw_wrap_has_no_discontinuity(make_processor):
    out, _ = run(make_processor(), SY.scenario_yaw_wrap().items())
    rel = [p for p in out if p.euler_display is not None]
    steps = [Q.angle_deg(a.quat, b.quat) for a, b in zip(out, out[1:])]
    assert max(steps) < 0.2  # 20°/s at 202.5 Hz ≈ 0.1° per sample
    assert all(p.valid for p in out)
    sdk_yaws = [p.euler_display for p in out]
    raw_yaws = [s.values[2] for s in SY.scenario_yaw_wrap().samples]
    assert max(raw_yaws) > 175 and min(raw_yaws) < -175  # absolute yaw wrapped at ±180
    yaws = [p.euler_display[0] for p in rel]
    assert max(yaws) > 100  # relative yaw keeps increasing through the wrap
    assert all(abs(b - a) < 0.2 for a, b in zip(yaws, yaws[1:]))
    assert sdk_yaws


# ---------------------------------------------------------------- timestamp problems
def test_regular_stream_has_no_gaps(make_processor):
    out, _ = run(make_processor(), samples_from_ts(load_real_trace("clean")))
    assert not [p for p in out if F.GAP_BEFORE in p.flags]
    assert all(p.valid for p in out)


@pytest.mark.parametrize("measured", [True, False])
def test_real_sustained_loss_is_detected(make_processor, measured):
    ts = load_real_trace("lossy")
    true_missing = (ts[-1] - ts[0]) / 1e9 * 202.5 - (len(ts) - 1)  # ≈ 2354
    proc = make_processor(measured_rate_hz=202.5 if measured else None)
    out, _ = run(proc, samples_from_ts(ts))
    est = sum(p.gap_est_missing for p in out)
    if measured:
        assert est >= 0.99 * true_missing
    else:
        assert est >= 0.80 * true_missing
    assert est <= true_missing * 1.01


def test_adaptive_reference_has_no_false_gaps_on_clean_trace(make_processor):
    out, _ = run(make_processor(measured_rate_hz=None), samples_from_ts(load_real_trace("clean")))
    assert not [p for p in out if F.GAP_BEFORE in p.flags]


def test_dropped_samples_estimate(make_processor):
    tr = SY.scenario_dropped()
    out, _ = run(make_processor(), tr.items())
    assert sum(p.gap_est_missing for p in out) == tr.info["dropped"]


def test_low_rate_stream(make_processor):
    s = SY.generate(5.0, rate_hz=60.0)
    out, _ = run(make_processor(measured_rate_hz=None, selected_hz=60), s)
    assert all(p.valid for p in out) and not [p for p in out if F.GAP_BEFORE in p.flags]


def test_bursty_host_arrival_does_not_affect_device_flags(make_processor):
    s = SY.generate(3.0)
    bursty = [RawPoseSample(x.seq, 1, 10_000 + (x.seq // 10) * 50_000_000, x.device_ts_raw, x.values) for x in s]
    out, _ = run(make_processor(), bursty)
    assert all(p.valid for p in out) and not [p for p in out if F.GAP_BEFORE in p.flags]


def test_dt_columns(make_processor):
    s = SY.generate(0.1)
    out, _ = run(make_processor(), s)
    assert out[0].dt_device_ns is None and out[1].dt_device_ns == s[1].device_ts_raw - s[0].device_ts_raw


def test_euler_near_singular_flag(make_processor):
    s = SY.generate(2.0, orientation=lambda t: quat_from_zyx(0, 89.5 if t > 1.5 else 0.0, 0))
    out, _ = run(make_processor(tau_jump_deg=180.0), [SY.capture_command(-1, window_s=0.5)] + s)
    assert any(F.EULER_NEAR_SINGULAR in p.flags for p in out)


def test_processor_is_deterministic(make_processor):
    tr = SY.scenario_stationary(duration_s=10)
    a, ra = run(make_processor(), tr.items())
    b, rb = run(make_processor(), tr.items())
    assert a == b and ra == rb


def test_nan_in_euler_fields_also_invalidates(make_processor):
    s = SY.generate(0.1)
    bad = SY.with_values(s[5], (math.nan, *s[5].values[1:]))
    out, _ = run(make_processor(), s[:5] + [bad] + s[6:])
    assert F.NONFINITE in out[5].flags and not out[5].valid
