"""Display Euler angles — the exact, documented conversion (docs/conventions.md §Display Euler).

Sequence: intrinsic Z-Y'-X'' (yaw ψ, then pitch θ, then roll φ):

    q = q_z(ψ) ⊗ q_y(θ) ⊗ q_x(φ)        (R = R_z(ψ)·R_y(θ)·R_x(φ))

    ψ = atan2(2(w·z + x·y), 1 − 2(y² + z²))   ∈ (−180°, 180°]
    θ = asin(clamp(2(w·y − z·x), −1, 1))      ∈ [−90°, 90°]
    φ = atan2(2(w·x + y·z), 1 − 2(x² + y²))   ∈ (−180°, 180°]

Signs follow the right-handed NWU frame with no flips: +yaw = turn left, +pitch = nose down,
+roll = right ear down (to be confirmed on hardware, bench checklist G0).

These angles are for display and diagnostics only; all computation uses quaternions. Their
interaction products must not be read as anatomical coupling (threats-to-validity TV1).
"""
from __future__ import annotations

import math
from typing import Sequence

from headmusic.orientation.quaternion import from_axis_angle, mul
from headmusic.types import Euler, Quat


def _wrap180(deg: float) -> float:
    """Map to (−180, 180]."""
    return 180.0 if deg == -180.0 else deg


def zyx_from_quat(q: Sequence[float]) -> Euler:
    w, x, y, z = q
    yaw = math.degrees(math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z)))
    s = 2.0 * (w * y - z * x)
    s = 1.0 if s > 1.0 else (-1.0 if s < -1.0 else s)
    pitch = math.degrees(math.asin(s))
    roll = math.degrees(math.atan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y)))
    return (_wrap180(yaw), pitch, _wrap180(roll))


def quat_from_zyx(yaw_deg: float, pitch_deg: float, roll_deg: float) -> Quat:
    qz = from_axis_angle((0.0, 0.0, 1.0), yaw_deg)
    qy = from_axis_angle((0.0, 1.0, 0.0), pitch_deg)
    qx = from_axis_angle((1.0, 0.0, 0.0), roll_deg)
    return mul(mul(qz, qy), qx)


def direction_words(yaw: float, pitch: float, roll: float) -> tuple[str, str, str]:
    """Human-readable directions for the NWU sign convention (display only)."""
    return (
        "left" if yaw > 0 else ("right" if yaw < 0 else ""),
        "down" if pitch > 0 else ("up" if pitch < 0 else ""),
        "right ear down" if roll > 0 else ("left ear down" if roll < 0 else ""),
    )
