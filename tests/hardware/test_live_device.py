"""Opt-in hardware tests (pytest --hardware). They need the VITURE glasses connected and no other
VITURE application running (Windows allows one process per device)."""
import time

import pytest

from conftest import SDK_DIR, SHIM
from headmusic.config import load_config
from headmusic.orientation.processor import OrientationProcessor, ProcessorConfig
from headmusic.pipeline import Pipeline
from headmusic.tracking.gate import TrackingGate

pytestmark = pytest.mark.hardware


def run_live(seconds, freq=240):
    from headmusic.acquisition.capture_shim import CaptureShim
    from headmusic.acquisition.viture_sdk import VitureSdk
    from headmusic.acquisition.viture_source import VitureSdkSource
    cfg = load_config(overrides={"imu": {"frequency_requested_hz": freq}})
    clock = time.perf_counter_ns
    pipe = Pipeline(cfg, OrientationProcessor(ProcessorConfig.from_config(cfg)), TrackingGate(100_000_000), None, clock)
    shim = CaptureShim(SHIM)
    src = VitureSdkSource(VitureSdk(SDK_DIR), shim, cfg, pipe.put, clock)
    pipe.start()
    src.start()
    time.sleep(seconds)
    src.stop(15)
    pipe.stop(15)
    return pipe, src, shim


@pytest.mark.parametrize("freq", [60, 90, 120, 240])
def test_stream_each_supported_pose_rate(freq):
    pipe, src, shim = run_live(10, freq)
    hist, st, _ = pipe.snapshot(seconds=1e6)
    assert st["pose_samples"] > 5 * freq * 0.5
    assert shim.stats()["overflow"] == 0
    assert st["device"]["frequency_selected_hz"] == freq
    # Observed on this unit (2026-11-10): occasional extra pose report with the SAME device timestamp
    # as the previous one (values differ slightly, ~1 ms later). It must be flagged ts_duplicate,
    # kept, and never anything else.
    invalid = [p for p in hist if not p.valid]
    assert all(p.flags == ("no_neutral", "ts_duplicate") or p.flags == ("ts_duplicate",) for p in invalid)
    assert len(invalid) <= max(3, 0.005 * st["pose_samples"])


def test_identity():
    from headmusic.acquisition.usb_enum import find_viture_pids
    from headmusic.acquisition.viture_sdk import VitureSdk
    sdk = VitureSdk(SDK_DIR)
    pids = find_viture_pids(sdk.is_product_id_valid)
    assert pids, "no VITURE device connected"
    assert sdk.version() == "2.4.2"
    assert sdk.market_name(pids[0])
