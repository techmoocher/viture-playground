"""ctypes binding to the official VITURE Glasses SDK (glasses.dll, v2.4.2) — lifecycle and queries.

Callbacks are NOT implemented in Python: the IMU callbacks registered with the SDK are function
pointers exported by the native capture shim (capture_shim.py). Only the error-level log hook is
a Python callback; it fires rarely.

Every prototype below mirrors a declaration in the SDK headers; tests/test_sdk_binding.py checks
names and parameter counts against vendor/viture/windows_x86_64/include.
"""
from __future__ import annotations

import ctypes as C
import os
from pathlib import Path
from typing import Callable, Optional

H = C.c_void_p
LOG_HOOK = C.CFUNCTYPE(None, C.c_int, C.c_char_p, C.c_char_p)

IMU_MODE_RAW = 0
IMU_MODE_POSE = 1
MODE_BY_NAME = {"raw": IMU_MODE_RAW, "pose": IMU_MODE_POSE}
FREQUENCY_HZ = {0: 60, 1: 90, 2: 120, 3: 240, 4: 500, 5: 1000}  # VITURE_IMU_FREQUENCY_* constants
DEVICE_TYPES = {0: "GEN1", 1: "GEN2", 2: "CARINA"}
VITURE_VID = 0x35CA

ERRORS = {
    0: "SUCCESS", -1: "INVALID_PARAM", -2: "USB_UNAVAILABLE", -3: "USB_EXEC", -4: "NOT_SUPPORTED",
    -5: "NO_DATA", -6: "DATA_PARSE", -7: "DEVICE_REJECTED", -8: "CALIB_INIT", -9: "SERIAL_FETCH",
    -10: "INVALID_STATE", -11: "HANDLE_DESTROYED", -99: "UNKNOWN",
}

# name: (restype, argtypes, parameter count in the header declaration)
PROTOTYPES: dict[str, tuple] = {
    "GetVersionString": (C.c_char_p, [], 0),
    "xr_device_provider_create": (H, [C.c_int], 1),
    "xr_device_provider_initialize": (C.c_int, [H, C.c_char_p, C.c_char_p], 3),
    "xr_device_provider_start": (C.c_int, [H], 1),
    "xr_device_provider_stop": (C.c_int, [H], 1),
    "xr_device_provider_shutdown": (C.c_int, [H], 1),
    "xr_device_provider_destroy": (None, [H], 1),
    "xr_device_provider_get_device_type": (C.c_int, [H], 1),
    "xr_device_provider_is_product_id_valid": (C.c_int, [C.c_int], 1),
    "xr_device_provider_is_product_support_native_dof": (C.c_int, [C.c_int], 1),
    "xr_device_provider_is_product_support_imu_frequency": (C.c_int, [C.c_int, C.c_int, C.c_int], 3),
    "xr_device_provider_get_market_name": (C.c_int, [C.c_int, C.c_char_p, C.POINTER(C.c_int)], 3),
    "xr_device_provider_set_log_level": (None, [C.c_int], 1),
    "xr_device_provider_set_log_hook": (None, [LOG_HOOK], 1),
    "xr_device_provider_get_glasses_version": (C.c_int, [H, C.c_char_p, C.POINTER(C.c_int)], 3),
    "xr_device_provider_get_sn_hash": (C.c_int, [H, C.POINTER(C.c_uint8)], 2),
    "xr_device_provider_register_imu_pose_callback": (C.c_int, [H, C.c_void_p], 2),
    "xr_device_provider_register_imu_raw_callback": (C.c_int, [H, C.c_void_p], 2),
    "xr_device_provider_open_imu": (C.c_int, [H, C.c_uint8, C.c_uint8], 3),
    "xr_device_provider_close_imu": (C.c_int, [H, C.c_uint8], 2),
}


class SdkError(RuntimeError):
    def __init__(self, call: str, code: int, hint: str = "") -> None:
        self.call, self.code = call, code
        msg = f"{call} failed: {code} ({ERRORS.get(code, 'unrecognised')})"
        super().__init__(msg + (f" — {hint}" if hint else ""))


class VitureSdk:
    """Thin, typed wrapper around glasses.dll. Not thread-safe; use from one thread."""

    def __init__(self, dll_dir: Path) -> None:
        dll_dir = Path(dll_dir)
        path = dll_dir / "glasses.dll"
        if not path.is_file():
            raise FileNotFoundError(f"{path} not found — run: python scripts/setup_sdk.py")
        self.dll_path = path
        self._dll_dir_handle = os.add_dll_directory(str(dll_dir))
        self.lib = C.CDLL(str(path))
        for name, (res, args, _n) in PROTOTYPES.items():
            fn = getattr(self.lib, name)
            fn.restype = res
            fn.argtypes = args
        self._log_hook_ref = None

    # ------------------------------------------------------------------ static queries
    def version(self) -> str:
        return self.lib.GetVersionString().decode(errors="replace")

    def is_product_id_valid(self, pid: int) -> bool:
        return bool(self.lib.xr_device_provider_is_product_id_valid(pid))

    def supports_native_dof(self, pid: int) -> bool:
        return bool(self.lib.xr_device_provider_is_product_support_native_dof(pid))

    def supports_frequency(self, pid: int, mode: int, freq_idx: int) -> bool:
        return bool(self.lib.xr_device_provider_is_product_support_imu_frequency(pid, mode, freq_idx))

    def frequency_table(self, pid: int) -> dict[str, dict[str, bool]]:
        return {name: {str(hz): self.supports_frequency(pid, mode, idx) for idx, hz in FREQUENCY_HZ.items()}
                for name, mode in MODE_BY_NAME.items()}

    def market_name(self, pid: int) -> str:
        buf = C.create_string_buffer(64)
        n = C.c_int(64)
        rc = self.lib.xr_device_provider_get_market_name(pid, buf, C.byref(n))
        if rc != 0:
            raise SdkError("get_market_name", rc)
        return buf.value.decode(errors="replace")

    # ------------------------------------------------------------------ logging
    def set_log_level(self, level: int) -> None:
        self.lib.xr_device_provider_set_log_level(int(level))

    def set_log_hook(self, fn: Optional[Callable[[int, str, str], None]]) -> None:
        if fn is None:
            self.lib.xr_device_provider_set_log_hook(LOG_HOOK())
            self._log_hook_ref = None
            return

        def _hook(level, tag, msg):
            try:
                fn(int(level), (tag or b"").decode(errors="replace"), (msg or b"").decode(errors="replace"))
            except Exception:  # never propagate into the SDK thread
                pass
        self._log_hook_ref = LOG_HOOK(_hook)  # keep alive
        self.lib.xr_device_provider_set_log_hook(self._log_hook_ref)

    # ------------------------------------------------------------------ handle lifecycle
    def create(self, pid: int) -> int:
        h = self.lib.xr_device_provider_create(pid)
        if not h:
            raise SdkError("create", -99, "device not found, unsupported PID, or USB access denied")
        return h

    def device_type(self, h: int) -> int:
        return int(self.lib.xr_device_provider_get_device_type(h))

    def _check(self, name: str, rc: int, hint: str = "") -> None:
        if rc != 0:
            raise SdkError(name, rc, hint)

    def initialize(self, h: int) -> None:
        self._check("initialize", self.lib.xr_device_provider_initialize(h, None, None),
                    "on Windows only one process can open the glasses — close other VITURE apps")

    def start(self, h: int) -> None:
        self._check("start", self.lib.xr_device_provider_start(h))

    def stop(self, h: int) -> int:
        return int(self.lib.xr_device_provider_stop(h))

    def shutdown(self, h: int) -> int:
        return int(self.lib.xr_device_provider_shutdown(h))

    def destroy(self, h: int) -> None:
        self.lib.xr_device_provider_destroy(h)

    def glasses_version(self, h: int) -> str:
        buf = C.create_string_buffer(128)
        n = C.c_int(128)
        self._check("get_glasses_version", self.lib.xr_device_provider_get_glasses_version(h, buf, C.byref(n)))
        return buf.value.decode(errors="replace")

    def sn_hash(self, h: int) -> Optional[str]:
        buf = (C.c_uint8 * 32)()
        rc = self.lib.xr_device_provider_get_sn_hash(h, buf)
        return bytes(buf).hex() if rc == 0 else None

    def register_pose_callback(self, h: int, fn_ptr: int) -> None:
        self._check("register_imu_pose_callback", self.lib.xr_device_provider_register_imu_pose_callback(h, fn_ptr))

    def register_raw_callback(self, h: int, fn_ptr: int) -> None:
        self._check("register_imu_raw_callback", self.lib.xr_device_provider_register_imu_raw_callback(h, fn_ptr))

    def open_imu(self, h: int, mode: int, freq_idx: int) -> None:
        self._check("open_imu", self.lib.xr_device_provider_open_imu(h, mode, freq_idx))

    def close_imu(self, h: int, mode: int) -> int:
        return int(self.lib.xr_device_provider_close_imu(h, mode))


def select_frequency(requested_hz: int, supported: Callable[[int], bool]) -> tuple[int, int, str]:
    """Choose an IMU frequency index for a request (D6).

    The requested rate is used if supported in the selected mode; otherwise the highest supported
    rate below it. Never silently above the request. Returns (index, hz, reason)."""
    candidates = sorted(FREQUENCY_HZ.items(), key=lambda kv: kv[1])
    exact = [i for i, hz in candidates if hz == requested_hz]
    if exact and supported(exact[0]):
        return exact[0], requested_hz, "requested_supported"
    below = [(i, hz) for i, hz in candidates if hz < requested_hz and supported(i)]
    if below:
        i, hz = below[-1]
        why = "requested_not_supported" if exact else "requested_not_an_sdk_rate"
        return i, hz, f"fallback_highest_supported_below_request ({why})"
    raise ValueError(f"no supported IMU frequency at or below {requested_hz} Hz")
