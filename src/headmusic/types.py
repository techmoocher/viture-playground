"""Shared data types. No dependencies on other headmusic packages.

Conventions (docs/conventions.md):
- quaternions are Hamilton, scalar-first (w, x, y, z);
- SDK pose values are stored exactly as delivered: (roll, pitch, yaw, qw, qx, qy, qz);
- times are integer nanoseconds: device_ts_raw is the SDK timestamp verbatim,
  host_rx_monotonic_ns is QueryPerformanceCounter-based (same timebase as time.perf_counter_ns).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Tuple

Quat = Tuple[float, float, float, float]
Euler = Tuple[float, float, float]  # (yaw, pitch, roll) in degrees


@dataclass(frozen=True, slots=True)
class RawPoseSample:
    """One VITURE_IMU_MODE_POSE callback, unmodified."""

    seq: int
    connection_id: int
    host_rx_monotonic_ns: int
    device_ts_raw: int
    values: Tuple[float, ...]  # (roll, pitch, yaw, qw, qx, qy, qz) as delivered (float32 values)

    @property
    def sdk_quat(self) -> Tuple[float, ...]:
        return tuple(self.values[3:7])


@dataclass(frozen=True, slots=True)
class RawImuSample:
    """One VITURE_IMU_MODE_RAW callback, unmodified. Units are undocumented by the SDK."""

    seq: int
    connection_id: int
    host_rx_monotonic_ns: int
    device_ts_raw: int
    vsync_raw: int
    values: Tuple[float, ...]  # (gyro xyz, accel xyz, mag xyz, temperature) as delivered


@dataclass(frozen=True, slots=True)
class ProcessedSample:
    """Derived values for one pose sample. Always regenerable from the raw sample stream."""

    seq: int
    connection_id: int
    host_rx_monotonic_ns: int
    device_ts_raw: int
    dt_device_ns: Optional[int]
    dt_host_ns: Optional[int]
    quat: Optional[Quat]  # normalised q_WH, hemisphere-continuous
    quat_rel: Optional[Quat]  # conj(q0) ⊗ q_WH, canonical w >= 0; None without accepted neutral
    euler_display: Optional[Euler]  # Z-Y'-X'' from quat_rel (yaw, pitch, roll), degrees
    valid: bool
    flags: Tuple[str, ...]  # sorted flag names
    neutral_calibration_id: Optional[int]
    gap_est_missing: int = 0


@dataclass(frozen=True, slots=True)
class Event:
    """Something that happened to the stream or device. Written to events.jsonl."""

    kind: str
    host_monotonic_ns: int
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Command:
    """Operator command. `after_seq` is assigned by the pipeline: the command applies after the
    pose sample with that seq (-1: before any sample). Replay re-injects it at the same place."""

    kind: str  # "capture_neutral" | "segment_start" | "segment_end"
    host_monotonic_ns: int
    data: dict[str, Any] = field(default_factory=dict)
    after_seq: Optional[int] = None
