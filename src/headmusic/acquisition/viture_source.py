"""VitureSdkSource — live acquisition from VITURE glasses through the SDK and the native shim.

One acquisition thread owns the device: it connects, drains the native ring buffer, watches for
disconnects (USB re-enumeration once per reconnect_poll_s), tears down (≈1.9 s, off the UI
thread) and reconnects. Ordering guarantee: all records captured on a connection are drained and
emitted (tagged with that connection_id) before the device_disconnected event.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from headmusic.acquisition import capture_shim as CS
from headmusic.acquisition.capture_shim import CaptureShim
from headmusic.acquisition.usb_enum import find_viture_pids
from headmusic.acquisition.viture_sdk import (DEVICE_TYPES, IMU_MODE_POSE, IMU_MODE_RAW, MODE_BY_NAME, SdkError,
                                              VitureSdk, select_frequency)
from headmusic.types import Event, RawImuSample, RawPoseSample

Sink = Callable[[object], None]


class VitureSdkSource:
    def __init__(self, sdk: VitureSdk, shim: CaptureShim, cfg: dict, sink: Sink,
                 clock: Callable[[], int], pid: Optional[int] = None,
                 enumerate_pids: Optional[Callable[[], list[int]]] = None) -> None:
        self.sdk, self.shim, self.cfg, self.sink, self.clock = sdk, shim, cfg, sink, clock
        self.mode_name = cfg["imu"]["mode"]
        self.mode = MODE_BY_NAME[self.mode_name]
        self.requested_hz = int(cfg["imu"]["frequency_requested_hz"])
        acq = cfg["acquisition"]
        self.drain_s = float(acq["drain_interval_ms"]) / 1000.0
        self.poll_s = float(acq["reconnect_poll_s"])
        self.auto_reconnect = bool(acq["auto_reconnect"])
        self.pid_override = pid
        self._enumerate = enumerate_pids or (lambda: find_viture_pids(self.sdk.is_product_id_valid))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.finished = threading.Event()
        self.connection_id = 0
        self.last_error: Optional[str] = None

    # ------------------------------------------------------------------ control
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="viture-acquisition", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)

    def _emit(self, kind: str, **data) -> None:
        self.sink(Event(kind, self.clock(), data))

    # ------------------------------------------------------------------ thread body
    def _run(self) -> None:
        try:
            self.sdk.set_log_level(int(self.cfg["acquisition"]["sdk_log_level"]))
            self.sdk.set_log_hook(lambda lvl, tag, msg: self.sink(
                Event("sdk_log", self.clock(), {"level": lvl, "tag": tag, "message": msg})))
            self.shim.reset()  # no callbacks registered yet
            self._emit("source_started", sdk_version=self.sdk.version(), mode=self.mode_name,
                       frequency_requested_hz=self.requested_hz)
            announced_waiting = False
            while not self._stop.is_set():
                pids = self._present_pids()
                if not pids:
                    if not announced_waiting:
                        self._emit("waiting_for_device")
                        announced_waiting = True
                    if not self.auto_reconnect and self.connection_id == 0:
                        self.last_error = "no VITURE device found"
                        break
                    self._stop.wait(self.poll_s)
                    continue
                announced_waiting = False
                pid = pids[0]
                self.connection_id += 1
                h = None
                try:
                    h, info = self._connect(pid)
                except SdkError as e:
                    self.last_error = str(e)
                    self._emit("sdk_error", connection_id=self.connection_id, error=str(e), code=e.code)
                    if h:
                        self._teardown(h)
                    if not self.auto_reconnect:
                        break
                    self._stop.wait(self.poll_s)
                    continue
                self._emit("device_connected", connection_id=self.connection_id, **info)
                reason = self._stream(pid)
                t0 = time.perf_counter()
                close_rc = self._teardown(h)
                self._drain(self.connection_id)  # anything captured before callbacks stopped
                self._emit("device_disconnected", connection_id=self.connection_id, reason=reason,
                           teardown_ms=round((time.perf_counter() - t0) * 1000, 1), **close_rc)
                if self._stop.is_set() or not self.auto_reconnect:
                    break
        finally:
            try:
                self.sdk.set_log_hook(None)
            except Exception:
                pass
            self._emit("source_stopped", shim_stats=self.shim.stats(), last_error=self.last_error)
            self.finished.set()

    def _present_pids(self) -> list[int]:
        pids = self._enumerate()
        if self.pid_override is not None:
            pids = [p for p in pids if p == self.pid_override]
        return pids

    def _connect(self, pid: int):
        sdk = self.sdk
        h = sdk.create(pid)
        try:
            dtype = sdk.device_type(h)
            if dtype not in (0, 1):
                raise SdkError("device_type", -4, f"device type {dtype} ({DEVICE_TYPES.get(dtype)}) is not "
                                                  "a Gen1/Gen2 IMU-callback device")
            if self.mode == IMU_MODE_POSE:
                sdk.register_pose_callback(h, self.shim.pose_capture_callback())
                sdk.register_raw_callback(h, self.shim.raw_count_callback())  # diagnostic count only
            else:
                sdk.register_raw_callback(h, self.shim.raw_capture_callback())
                sdk.register_pose_callback(h, self.shim.pose_count_callback())
            sdk.initialize(h)
            sdk.start(h)
            table = sdk.frequency_table(pid)
            idx, hz, why = select_frequency(self.requested_hz, lambda i: sdk.supports_frequency(pid, self.mode, i))
            info = {
                "pid": f"0x{pid:04X}", "market_name": sdk.market_name(pid), "device_type": dtype,
                "device_type_name": DEVICE_TYPES.get(dtype), "firmware": sdk.glasses_version(h),
                "sn_hash": sdk.sn_hash(h) if self.cfg.get("record_sn_hash", True) else None,
                "native_dof": sdk.supports_native_dof(pid), "sdk_version": sdk.version(),
                "frequency_support": table, "mode": self.mode_name,
                "frequency_requested_hz": self.requested_hz, "frequency_selected_hz": hz,
                "frequency_selected_index": idx, "frequency_selection_reason": why,
            }
            t_open = self.clock()
            sdk.open_imu(h, self.mode, idx)
            info["imu_open_host_ns"] = t_open
            self._handle = h
            return h, info
        except Exception:
            self._teardown(h)
            raise

    def _stream(self, pid: int) -> str:
        """Drain until stop or disconnect. Returns the stop reason."""
        next_check = time.monotonic() + self.poll_s
        while True:
            if self._stop.is_set():
                return "stop_requested"
            self._drain(self.connection_id)
            now = time.monotonic()
            if now >= next_check:
                next_check = now + self.poll_s
                try:
                    present = pid in self._enumerate()
                except OSError:
                    present = True  # enumeration failure is not evidence of unplugging
                if not present:
                    return "usb_device_removed"
            time.sleep(self.drain_s)

    def _drain(self, connection_id: int) -> None:
        while True:
            recs = self.shim.read()
            if not recs:
                return
            for kind, seq, host_ns, dev_ts, vsync, values in recs:
                if kind == CS.KIND_POSE:
                    self.sink(RawPoseSample(seq, connection_id, host_ns, dev_ts, values))
                elif kind == CS.KIND_RAW:
                    self.sink(RawImuSample(seq, connection_id, host_ns, dev_ts, vsync, values))

    def _teardown(self, h) -> dict:
        rc = {}
        if not h:
            return rc
        try:
            rc["close_imu_rc"] = self.sdk.close_imu(h, self.mode)
            rc["stop_rc"] = self.sdk.stop(h)
            rc["shutdown_rc"] = self.sdk.shutdown(h)
        finally:
            self.sdk.destroy(h)  # idempotent since SDK 2.4.1
        return rc
