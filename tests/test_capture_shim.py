"""Native capture shim, exercised without glasses by calling its callbacks directly."""
import ctypes as C
import struct
import time

import pytest

from conftest import SHIM

pytestmark = pytest.mark.skipif(not SHIM.exists(), reason="build it: wsl sh native/build_shim.sh")


@pytest.fixture
def shim():
    from headmusic.acquisition.capture_shim import CaptureShim
    s = CaptureShim(SHIM)
    s.reset()
    return s


def pose_fn(shim):
    from headmusic.acquisition.capture_shim import POSE_CB
    return C.cast(C.c_void_p(shim.pose_capture_callback()), POSE_CB)


def raw_fn(shim):
    from headmusic.acquisition.capture_shim import RAW_CB
    return C.cast(C.c_void_p(shim.raw_capture_callback()), RAW_CB)


def test_record_layout_matches(shim):
    from headmusic.acquisition.capture_shim import CapRecord
    assert shim.lib.cap_record_size() == C.sizeof(CapRecord) == 80


def test_clock_is_perf_counter_ns(shim):
    for _ in range(200):
        a = time.perf_counter_ns()
        s = shim.now_ns()
        b = time.perf_counter_ns()
        assert a <= s <= b


def test_values_are_bit_exact_and_seq_continuous(shim):
    f = pose_fn(shim)
    vals = [(1.5e-7 * i, -168.27409363, -130.75175476, 0.04515858, -0.90442407, -0.41421568, -0.09166938)
            for i in range(50)]
    for i, v in enumerate(vals):
        arr = (C.c_float * 7)(*v)
        f(arr, 5_595_861_000_000 + i * 5_000_000)
    recs = shim.read()
    assert [r[1] for r in recs] == list(range(50))
    for (kind, seq, host, dev, vsync, values), v in zip(recs, vals):
        assert kind == 1 and vsync == 0 and dev == 5_595_861_000_000 + seq * 5_000_000
        assert [struct.pack("<f", x) for x in values] == [struct.pack("<f", x) for x in v]
    hosts = [r[2] for r in recs]
    assert hosts == sorted(hosts)


def test_raw_records_carry_vsync_and_ten_values(shim):
    raw_fn(shim)((C.c_float * 10)(*range(10)), 123, 456)
    (kind, seq, host, dev, vsync, values), = shim.read()
    assert kind == 2 and dev == 123 and vsync == 456 and values == tuple(float(i) for i in range(10))


def test_null_data_pointer_is_recorded_with_no_values(shim):
    pose_fn(shim)(None, 7)
    (rec,) = shim.read()
    assert rec[5] == () and rec[3] == 7


def test_ring_wraps_and_overflow_is_counted_not_silent(shim):
    f = pose_fn(shim)
    arr = (C.c_float * 7)(0, 0, 0, 1, 0, 0, 0)
    n = shim.ring_size + 25
    for i in range(n):
        f(arr, i)
    st = shim.stats()
    assert st["total"] == n and st["overflow"] == 25 and st["high_water"] == shim.ring_size
    got = []
    while True:
        batch = shim.read()
        if not batch:
            break
        got += batch
    assert len(got) == shim.ring_size
    assert got[-1][1] == shim.ring_size - 1  # overflowed records consumed seq numbers -> visible gap later
    for i in range(10):
        f(arr, n + i)
    assert shim.read()[0][1] == n  # seq continues after the dropped 25: a downstream seq gap of 25


def test_count_only_callbacks(shim):
    from headmusic.acquisition.capture_shim import POSE_CB, RAW_CB
    C.cast(C.c_void_p(shim.raw_count_callback()), RAW_CB)(None, 1, 2)
    C.cast(C.c_void_p(shim.pose_count_callback()), POSE_CB)(None, 1)
    st = shim.stats()
    assert st["count_only_raw"] == 1 and st["count_only_pose"] == 1 and st["total"] == 0
    assert shim.read() == []
