"""Metrics recover known properties of synthetic traces (AC7)."""
import numpy as np
import pytest

from conftest import load_real_trace
from headmusic.acquisition import synthetic as SY
from headmusic.metrics.angular import stationary_angular
from headmusic.metrics.timing import clock_relation, gaps, timing_report
from headmusic.orientation.euler import quat_from_zyx
from headmusic.orientation.quaternion import mul


def arrays(samples):
    d = np.array([s.device_ts_raw for s in samples], dtype=np.int64)
    h = np.array([s.host_rx_monotonic_ns for s in samples], dtype=np.int64)
    q = np.array([s.values[3:7] for s in samples], dtype=float)
    seq = np.array([s.seq for s in samples], dtype=np.int64)
    return d, h, q, seq


def test_rate_and_skew_recovered():
    s = SY.generate(60.0, rate_hz=202.5, skew_ppm=40.0, latency_ns=(300_000, 1.0))
    d, h, _, seq = arrays(s)
    r = timing_report(d, h, seq, 202.5, 1.5, 1e6)
    assert r["achieved_rate_device_hz"] == pytest.approx(202.5, rel=1e-3)
    assert r["clock_relation"]["skew_ppm"] == pytest.approx(40.0, abs=1.0)
    assert r["gaps"]["count"] == 0 and r["pipeline_seq_gaps"] == 0
    assert r["loss_fraction"] == pytest.approx(0.0, abs=1e-3)
    assert len(r["segments"]) == 1


def test_arrival_jitter_recovered():
    s = SY.generate(30.0, latency_ns=(2_000_000, 400_000), seed=5)
    d, h, _, seq = arrays(s)
    c = clock_relation(d, h)
    # residual SD = latency SD combined with the device timestamp quantisation (uniform over 1 ms: SD 0.289 ms)
    assert c["residual_sd_ms"] == pytest.approx(np.hypot(0.4, 1 / np.sqrt(12)), rel=0.05)


def test_gap_count_exact_and_real_loss_fraction():
    tr = SY.scenario_dropped()
    d, h, _, seq = arrays(tr.samples)
    g = gaps(d, 1e9 / 202.5, 1.5, 1e6)
    assert g["est_missing"] == tr.info["dropped"]
    ts = np.array(load_real_trace("lossy"), dtype=np.int64)
    r = timing_report(ts, ts, np.arange(ts.size), 202.5, 1.5, 1e6)
    assert r["loss_fraction"] == pytest.approx(0.58, abs=0.01)
    assert r["gaps"]["est_missing"] >= 2300


def test_stationary_drift_and_jitter_recovered():
    tr = SY.scenario_stationary(duration_s=120, drift_deg_per_min=0.5, noise_deg=0.01)
    d, h, q, _ = arrays(tr.samples)
    a = stationary_angular(q, d, w_ref_s=5.0, w_jitter_s=1.0)
    assert a["apparent_drift"]["slope_deg_per_min"]["z"] == pytest.approx(0.5, rel=0.02)
    assert abs(a["apparent_drift"]["slope_deg_per_min"]["x"]) < 0.01
    for k in ("sd_x", "sd_y", "sd_z"):
        assert a["angular_jitter_deg"][k] == pytest.approx(0.01, rel=0.05)


def test_drift_metric_independent_of_jitter():
    base = quat_from_zyx(20, 5, 0)
    s = SY.generate(60.0, orientation=lambda t: mul(base, quat_from_zyx(0, 0.2 * t / 60.0, 0)), noise_deg=0.0)
    d, h, q, _ = arrays(s)
    a = stationary_angular(q, d, 5.0, 1.0)
    assert a["apparent_drift"]["slope_deg_per_min"]["y"] == pytest.approx(0.2, rel=0.02)
    assert a["angular_jitter_deg"]["sd_y"] < 1e-3  # float32 rounding only
