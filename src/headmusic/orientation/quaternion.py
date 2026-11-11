"""Quaternion math on plain tuples (w, x, y, z).

Convention: Hamilton product, scalar-first storage, active rotations. For a unit quaternion q
that maps head-frame vectors into the tracking frame (q_WH), v_W = q ⊗ (0, v_H) ⊗ conj(q).
Pure Python `math` keeps per-sample processing deterministic and dependency-free.
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence

from headmusic.types import Quat

IDENTITY: Quat = (1.0, 0.0, 0.0, 0.0)


def mul(a: Sequence[float], b: Sequence[float]) -> Quat:
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    )


def conj(q: Sequence[float]) -> Quat:
    return (q[0], -q[1], -q[2], -q[3])


def neg(q: Sequence[float]) -> Quat:
    return (-q[0], -q[1], -q[2], -q[3])


def dot(a: Sequence[float], b: Sequence[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]


def norm(q: Sequence[float]) -> float:
    return math.sqrt(dot(q, q))


def is_finite(values: Iterable[float]) -> bool:
    return all(math.isfinite(v) for v in values)


def normalize(q: Sequence[float], eps: float = 1e-12) -> Quat:
    n = norm(q)
    if not math.isfinite(n) or n < eps:
        raise ValueError(f"cannot normalise quaternion with norm {n!r}")
    return (q[0] / n, q[1] / n, q[2] / n, q[3] / n)


def canonical(q: Sequence[float]) -> Quat:
    """Representative with w >= 0 (q and -q are the same rotation)."""
    return tuple(q) if q[0] >= 0.0 else neg(q)  # type: ignore[return-value]


def align(q: Sequence[float], ref: Sequence[float]) -> Quat:
    """Sign of q chosen so that <q, ref> >= 0 (hemisphere continuity)."""
    return tuple(q) if dot(q, ref) >= 0.0 else neg(q)  # type: ignore[return-value]


def angle_deg(a: Sequence[float], b: Sequence[float]) -> float:
    """Geodesic angle between two unit quaternions, sign-invariant, in degrees.

    Uses 2·atan2(|vec(conj(a)⊗b)|, |w|), which stays accurate for small angles."""
    d = mul(conj(a), b)
    s = math.sqrt(d[1] * d[1] + d[2] * d[2] + d[3] * d[3])
    return math.degrees(2.0 * math.atan2(s, abs(d[0])))


def from_axis_angle(axis: Sequence[float], angle_deg_: float) -> Quat:
    n = math.sqrt(sum(c * c for c in axis))
    if n == 0.0:
        raise ValueError("zero axis")
    h = math.radians(angle_deg_) / 2.0
    s = math.sin(h) / n
    return (math.cos(h), axis[0] * s, axis[1] * s, axis[2] * s)


def rotate(q: Sequence[float], v: Sequence[float]) -> tuple[float, float, float]:
    p = mul(mul(q, (0.0, v[0], v[1], v[2])), conj(q))
    return (p[1], p[2], p[3])


def up_axis_tilt_deg(q: Sequence[float]) -> float:
    """Tilt from upright: angle between the glasses' up axis (head-frame +Z rotated into the
    tracking frame) and the tracking frame's up axis (+Z, NWU), in degrees [0, 180].

    0° = upright, 90° = up axis horizontal, 180° = upside down. The value only depends on the
    (3,3) element of the rotation matrix, 1 − 2(x² + y²), which is the same for q, −q and conj(q).
    So it does not depend on the unverified quaternion direction (head→world vs world→head).
    Descriptive only: nothing is accepted or rejected on this value."""
    w, x, y, z = normalize(q)
    c = 1.0 - 2.0 * (x * x + y * y)
    c = 1.0 if c > 1.0 else (-1.0 if c < -1.0 else c)
    return math.degrees(math.acos(c))


def to_rotvec_deg(q: Sequence[float]) -> tuple[float, float, float]:
    """Rotation vector (axis × angle, degrees) of the rotation q; sequence-free parameterisation."""
    w, x, y, z = canonical(q)
    s = math.sqrt(x * x + y * y + z * z)
    if s < 1e-300:
        return (0.0, 0.0, 0.0)
    angle = math.degrees(2.0 * math.atan2(s, w))
    return (x / s * angle, y / s * angle, z / s * angle)


def from_rotvec_deg(r: Sequence[float]) -> Quat:
    angle = math.sqrt(r[0] * r[0] + r[1] * r[1] + r[2] * r[2])
    if angle == 0.0:
        return IDENTITY
    return from_axis_angle(r, angle)


def mean_sign_aligned(qs: Sequence[Sequence[float]]) -> Quat:
    """Normalised arithmetic mean after aligning every sample to the first one's hemisphere.

    For tightly clustered samples (enforced by the neutral stability check) this differs from the
    Markley eigenvector mean only at second order in the dispersion."""
    if not qs:
        raise ValueError("no quaternions to average")
    ref = qs[0]
    sw = sx = sy = sz = 0.0
    for q in qs:
        a = align(q, ref)
        sw += a[0]
        sx += a[1]
        sy += a[2]
        sz += a[3]
    return normalize((sw, sx, sy, sz))
