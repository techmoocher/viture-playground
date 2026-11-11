"""TrackingGate: invalid or stale tracking, disconnects and missing neutral are never usable."""
from headmusic.tracking.gate import (DISCONNECTED, LAST_SAMPLE_INVALID, NO_NEUTRAL, NO_VALID_SAMPLE, STALE,
                                     TrackingGate)
from headmusic.types import Event, ProcessedSample

T_STALE = 100_000_000


def ps(t, valid=True, rel=True, conn=1):
    return ProcessedSample(seq=0, connection_id=conn, host_rx_monotonic_ns=t, device_ts_raw=t, dt_device_ns=None,
                           dt_host_ns=None, quat=(1.0, 0, 0, 0), quat_rel=(1.0, 0, 0, 0) if rel else None,
                           euler_display=(0, 0, 0) if rel else None, valid=valid, flags=(),
                           neutral_calibration_id=1 if rel else None)


def connected(conn=1):
    return Event("device_connected", 0, {"connection_id": conn})


def test_initially_not_usable():
    g = TrackingGate(T_STALE)
    st = g.status(0)
    assert not st.usable and DISCONNECTED in st.reasons and NO_VALID_SAMPLE in st.reasons


def test_usable_only_when_all_conditions_hold():
    g = TrackingGate(T_STALE)
    g.on_event(connected())
    g.on_sample(ps(1_000))
    assert g.usable_for_control(1_000 + T_STALE)
    assert g.status(1_000 + T_STALE).reasons == ()


def test_stale():
    g = TrackingGate(T_STALE)
    g.on_event(connected())
    g.on_sample(ps(1_000))
    st = g.status(1_000 + T_STALE + 1)
    assert not st.usable and st.reasons == (STALE,)


def test_invalid_last_sample():
    g = TrackingGate(T_STALE)
    g.on_event(connected())
    g.on_sample(ps(1_000))
    g.on_sample(ps(2_000, valid=False))
    assert g.status(2_000).reasons == (LAST_SAMPLE_INVALID,)


def test_no_neutral():
    g = TrackingGate(T_STALE)
    g.on_event(connected())
    g.on_sample(ps(1_000, rel=False))
    assert g.status(1_000).reasons == (NO_NEUTRAL,)


def test_disconnect_then_reconnect_requires_fresh_samples():
    g = TrackingGate(T_STALE)
    g.on_event(connected(1))
    g.on_sample(ps(1_000))
    g.on_event(Event("device_disconnected", 0, {"connection_id": 1}))
    assert DISCONNECTED in g.status(1_000).reasons
    g.on_event(connected(2))
    st = g.status(1_000)
    assert not st.usable and NO_VALID_SAMPLE in st.reasons
    g.on_sample(ps(5_000, conn=1))  # late sample from the old connection is ignored
    assert not g.status(5_000).usable
    g.on_sample(ps(6_000, conn=2))
    assert g.usable_for_control(6_000)


def sample(host, dev, valid=True, conn=1):
    return ProcessedSample(seq=0, connection_id=conn, host_rx_monotonic_ns=host, device_ts_raw=dev, dt_device_ns=None,
                           dt_host_ns=None, quat=(1.0, 0, 0, 0), quat_rel=(1.0, 0, 0, 0), euler_display=(0, 0, 0),
                           valid=valid, flags=(), neutral_calibration_id=1)


def test_sample_produced_before_a_pc_sleep_is_stale_on_arrival():
    """G0 R9: after a 30 s PC sleep, a sample produced before the sleep arrived 29.9 s late, then a burst."""
    g = TrackingGate(T_STALE)
    g.on_event(connected())
    offset = 7_000_000_000  # host and device clocks have different epochs
    for k in range(200):  # 1 s at 5 ms, arriving 0.3 ms after production
        t = k * 5_000_000
        g.on_sample(sample(offset + t + 300_000, t))
        assert g.usable_for_control(offset + t + 300_000)
    last_dev = 199 * 5_000_000
    wake = offset + last_dev + 29_916_000_000  # the pre-sleep sample arrives 29.9 s late
    g.on_sample(sample(wake, last_dev + 5_000_000))
    st = g.status(wake)
    assert not st.usable and st.reasons == (STALE,) and st.age_ns > 29_000_000_000
    # burst: samples produced 316 ms .. 0 ms before the wake arrive at once
    for k in range(64):
        dev = last_dev + 29_601_000_000 + k * 5_000_000
        g.on_sample(sample(wake, dev))
    st = g.status(wake)
    assert st.lateness_ns is not None
    late_ms = st.lateness_ns / 1e6
    assert (STALE in st.reasons) == (late_ms > 100)
    for k in range(64, 120):  # back to normal arrivals
        dev = last_dev + 29_601_000_000 + k * 5_000_000
        g.on_sample(sample(offset + dev + 300_000, dev))
    assert g.usable_for_control(offset + dev + 300_000)


def test_slow_clock_drift_never_becomes_stale():
    """The host clock runs 50 ppm fast against the device for 3 h (G0 measured 12-17 ppm)."""
    g = TrackingGate(T_STALE)
    g.on_event(connected())
    for k in range(0, 3 * 3600 * 4):  # 4 samples per second
        dev = k * 250_000_000
        host = int(dev * (1 + 50e-6)) + 300_000
        g.on_sample(sample(host, dev))
        assert g.usable_for_control(host), k


def test_invalid_timestamps_do_not_move_the_baseline():
    g = TrackingGate(T_STALE)
    g.on_event(connected())
    g.on_sample(sample(1_000_000_300_000, 1_000_000_000_000))
    g.on_sample(sample(1_000_005_300_000, 900_000_000_000, valid=False))  # backward timestamp, invalid
    g.on_sample(sample(1_000_010_300_000, 1_000_010_000_000))
    st = g.status(1_000_010_300_000)
    assert st.usable and st.lateness_ns == 0


def test_reconnect_resets_the_offset_baseline():
    """The device clock restarts on replug (G0 R7): the new connection's offset must not look late or early."""
    g = TrackingGate(T_STALE)
    g.on_event(connected(1))
    g.on_sample(sample(50_000_000_000, 13_228_000_000_000))
    g.on_event(Event("device_disconnected", 0, {"connection_id": 1}))
    g.on_event(connected(2))
    g.on_sample(sample(59_400_000_000, 3_342_000_000, conn=2))
    st = g.status(59_400_000_000)
    assert st.usable and st.age_ns == 0


def test_from_config_reads_the_drift_allowance():
    g = TrackingGate.from_config({"gate": {"t_stale_ms": 100, "offset_drift_ppm": 150.0}})
    assert g.t_stale_ns == 100_000_000 and g.offset_drift_ppm == 150.0
