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
