"""Neutral capture: stability check, rejection reasons, retries, application point, reconnects."""
import pytest

from headmusic.acquisition import synthetic as SY
from headmusic.orientation import flags as F
from headmusic.orientation import quaternion as Q
from headmusic.orientation.euler import quat_from_zyx
from headmusic.types import Command, RawPoseSample


def feed(proc, items):
    out, recs = [], []
    for it in items:
        if isinstance(it, RawPoseSample):
            ps, r = proc.process(it)
            out.append(ps)
            recs += r
        else:
            recs += proc.handle_command(it)
    return out, recs


def test_accepted_capture_applies_from_closing_sample(make_processor):
    q_abs = quat_from_zyx(-130, 10, -5)
    s = SY.generate(5.0, orientation=lambda t: q_abs)
    out, recs = feed(make_processor(), [*s[:20], SY.capture_command(19, window_s=1.0), *s[20:]])
    (rec,) = recs
    assert rec["accepted"] and rec["reasons"] == [] and rec["neutral_calibration_id"] == 1
    assert rec["window_first_seq"] == 20
    first = rec["applies_from_seq"]
    span = s[first].device_ts_raw - s[20].device_ts_raw
    assert span > 1e9 and s[first - 1].device_ts_raw - s[20].device_ts_raw <= 1e9
    assert all(F.NO_NEUTRAL in p.flags for p in out[:first])
    applied = out[first]
    assert applied.neutral_calibration_id == 1 and F.NO_NEUTRAL not in applied.flags
    expected = Q.canonical(Q.mul(Q.conj(tuple(rec["q0_wxyz"])), applied.quat))
    assert applied.quat_rel == pytest.approx(expected, abs=1e-15)
    assert Q.angle_deg(applied.quat_rel, Q.IDENTITY) < 1e-5  # float32 input precision


@pytest.mark.parametrize("pitch,expected_tilt", [(0.0, 0.0), (25.0, 25.0), (-172.0, 172.0)])
def test_capture_records_tilt_without_affecting_acceptance(make_processor, pitch, expected_tilt):
    s = SY.generate(4.0, orientation=lambda t: quat_from_zyx(-100.0, pitch, 0.0))
    _, recs = feed(make_processor(), [SY.capture_command(-1, window_s=1.0), *s])
    assert recs[0]["accepted"] is True  # an upside-down neutral is still accepted: tilt is descriptive
    assert recs[0]["q0_tilt_from_upright_deg"] == pytest.approx(expected_tilt, abs=1e-3)


def test_rejected_capture_without_q0_has_no_tilt(make_processor):
    s = SY.generate(3.0)
    s = [SY.with_values(x, (*x.values[:3], float("nan"), *x.values[4:])) for x in s]
    _, recs = feed(make_processor(), [SY.capture_command(-1, window_s=1.0), *s])
    assert recs[0]["q0_tilt_from_upright_deg"] is None


def test_raw_values_untouched_by_recentering(make_processor):
    s = SY.generate(3.0, orientation=lambda t: quat_from_zyx(40, 0, 0))
    before = [x.values for x in s]
    feed(make_processor(), [SY.capture_command(-1, window_s=0.5), *s])
    assert [x.values for x in s] == before


def test_rejection_dispersion(make_processor):
    s = SY.generate(3.0, orientation=lambda t: quat_from_zyx(10 * t, 0, 0))  # moving 10°/s
    _, recs = feed(make_processor(), [SY.capture_command(-1, window_s=1.0, tau_stab_deg=2.0), *s])
    assert recs[0]["accepted"] is False and recs[0]["reasons"] == ["dispersion_exceeds_tau_stab"]
    assert recs[0]["dispersion_max_deg"] > 2.0


def test_rejection_invalid_sample_in_window(make_processor):
    s = SY.generate(3.0)
    s[30] = SY.with_values(s[30], (*s[30].values[:3], float("nan"), *s[30].values[4:]))
    _, recs = feed(make_processor(), [SY.capture_command(10, window_s=1.0), *s])
    assert recs[0]["reasons"] == ["invalid_samples_in_window"]


def test_rejection_gap_in_window(make_processor):
    s = SY.resequence([x for i, x in enumerate(SY.generate(3.0)) if not 40 <= i < 45])
    _, recs = feed(make_processor(), [SY.capture_command(10, window_s=1.0), *s])
    assert recs[0]["reasons"] == ["gap_in_window"]


def test_rejection_connection_change(make_processor):
    tr = SY.scenario_reconnect()
    split = tr.info["split_seq"]
    items = [*tr.samples[:split - 50], SY.capture_command(split - 51, window_s=2.0), *tr.samples[split - 50:]]
    out, recs = feed(make_processor(), items)
    assert recs[0]["accepted"] is False and recs[0]["reasons"] == ["connection_changed"]


def test_retry_after_rejection_then_accept(make_processor):
    moving = SY.generate(2.0, orientation=lambda t: quat_from_zyx(20 * t, 0, 0))
    still = SY.generate(3.0, orientation=lambda t: quat_from_zyx(40, 0, 0), seq0=len(moving),
                        device_t0=moving[-1].device_ts_raw + 5_000_000, host_t0=moving[-1].host_rx_monotonic_ns + 5_000_000)
    items = [SY.capture_command(-1, window_s=1.0), *moving, SY.capture_command(len(moving) - 1, window_s=1.0), *still]
    _, recs = feed(make_processor(), items)
    assert [r["accepted"] for r in recs] == [False, True]
    assert [r["attempt"] for r in recs] == [1, 2]
    assert recs[1]["neutral_calibration_id"] == 1


def test_request_while_capturing_is_rejected(make_processor):
    s = SY.generate(3.0)
    _, recs = feed(make_processor(), [SY.capture_command(5, window_s=1.0), *s[:10],
                                      SY.capture_command(9, window_s=1.0), *s[10:]])
    assert recs[0]["reasons"] == ["capture_in_progress"] and recs[1]["accepted"]


def test_reconnect_invalidates_neutral(make_processor):
    tr = SY.scenario_reconnect()
    out, recs = feed(make_processor(), tr.items())
    split = tr.info["split_seq"]
    assert recs[0]["accepted"]
    assert out[split - 1].quat_rel is not None
    assert all(p.quat_rel is None and F.NO_NEUTRAL in p.flags for p in out[split:])


def test_ids_increment_across_captures(make_processor):
    s = SY.generate(8.0)
    items = [SY.capture_command(-1, window_s=1.0), *s[:400], SY.capture_command(399, window_s=1.0), *s[400:]]
    out, recs = feed(make_processor(), items)
    assert [r["neutral_calibration_id"] for r in recs] == [1, 2]
    assert out[-1].neutral_calibration_id == 2


def test_command_defaults_come_from_config(make_processor):
    s = SY.generate(4.0)
    _, recs = feed(make_processor(), [Command("capture_neutral", 0, {}, after_seq=-1), *s])
    assert recs[0]["window_s"] == 3.0 and recs[0]["tau_stab_deg"] == 2.0
