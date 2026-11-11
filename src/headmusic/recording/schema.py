"""Column definitions and exact value formatting (docs/data-format.md).

Fidelity rules:
- SDK float32 values are written with 9 significant digits ('%.9g'), which identifies a float32
  uniquely; readers round the parsed value back to float32 (`to_f32`) so the reconstructed Python
  float is bit-identical to the one the live pipeline received.
- Derived doubles are written with repr(), the shortest exact round-trip representation.
- Integers (timestamps, seq) are written in full decimal. Missing values are empty strings.
"""
from __future__ import annotations

import math
import struct
from typing import Optional

SCHEMA_VERSION = "1.1.0"  # 1.1.0: calibration records gain q0_tilt_from_upright_deg (additive)

RAW_POSE_COLUMNS = [
    "seq", "connection_id", "host_rx_monotonic_ns", "device_ts_raw",
    "sdk_roll_deg", "sdk_pitch_deg", "sdk_yaw_deg", "sdk_qw", "sdk_qx", "sdk_qy", "sdk_qz",
]

RAW_IMU_COLUMNS = [
    "seq", "connection_id", "host_rx_monotonic_ns", "device_ts_raw", "vsync_raw",
    "gyro_x", "gyro_y", "gyro_z", "accel_x", "accel_y", "accel_z", "mag_x", "mag_y", "mag_z", "temperature",
]

PROCESSED_COLUMNS = [
    "seq", "connection_id", "host_rx_monotonic_ns", "device_ts_raw", "dt_device_ns", "dt_host_ns",
    "quat_w", "quat_x", "quat_y", "quat_z",
    "quat_rel_w", "quat_rel_x", "quat_rel_y", "quat_rel_z",
    "euler_display_yaw_deg", "euler_display_pitch_deg", "euler_display_roll_deg",
    "valid", "sample_quality", "neutral_calibration_id", "gap_est_missing",
]

_F32 = struct.Struct("<f")


def fmt_f32(x: float) -> str:
    if math.isnan(x):
        return "nan"
    if math.isinf(x):
        return "inf" if x > 0 else "-inf"
    return "%.9g" % x


def to_f32(text: str) -> float:
    """Parse a float32 field back to the exact float32 value (as a Python float)."""
    return _F32.unpack(_F32.pack(float(text)))[0]


def fmt_f64(x: Optional[float]) -> str:
    return "" if x is None else repr(float(x))


def fmt_int(x: Optional[int]) -> str:
    return "" if x is None else str(int(x))


def parse_int(text: str) -> Optional[int]:
    return None if text == "" else int(text)


def parse_f64(text: str) -> Optional[float]:
    return None if text == "" else float(text)
