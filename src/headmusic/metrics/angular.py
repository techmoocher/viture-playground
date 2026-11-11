"""Stationary angular jitter and apparent drift (independent definitions).

Only meaningful for recordings declared stationary. Fixture (intrinsic tracking) and worn
recordings (which include natural head movement) are reported separately and never pooled.

ref  = normalised sign-aligned mean of the first W_ref seconds of valid quaternions
v(t) = rotation vector of conj(ref) ⊗ q(t), degrees, components along the reference X, Y, Z axes
       (sequence-free; avoids the Euler parameterisation issue, threats-to-validity TV1)

angular jitter : per-component SD of v(t) minus its centred moving average of width W_j,
                 and the RMS of the geodesic residual; cross-check: RMS of consecutive geodesic
                 steps / √2 (underestimates if the SDK filter smooths)
apparent drift : least-squares slope of each v component and of θ(ref, q(t)) vs device time
                 (°/min), plus the net change between the first and last W_ref means.
                 "Apparent": sensor bias, SDK filter behaviour and fixture creep cannot be separated.
"""
from __future__ import annotations

import numpy as np

from headmusic.orientation.quaternion import angle_deg, conj, mean_sign_aligned, mul, to_rotvec_deg


def _moving_average(x: np.ndarray, w: int) -> np.ndarray:
    k = np.ones(w) / w
    return np.convolve(x, k, mode="same")


def stationary_angular(quats: np.ndarray, device_ns: np.ndarray, w_ref_s: float, w_jitter_s: float) -> dict:
    n = len(quats)
    if n < 10:
        return {"error": "too few valid samples"}
    t = (device_ns - device_ns[0]) / 1e9
    ref_mask = t <= w_ref_s
    ref = mean_sign_aligned([tuple(q) for q in quats[ref_mask]])
    v = np.array([to_rotvec_deg(mul(conj(ref), tuple(q))) for q in quats])
    geo = np.array([angle_deg(ref, tuple(q)) for q in quats])
    rate = (n - 1) / t[-1] if t[-1] > 0 else 0
    w = max(3, int(round(w_jitter_s * rate)) | 1)  # odd window
    half = w // 2
    core = slice(half, n - half) if n > w else slice(0, n)
    resid = v - np.column_stack([_moving_average(v[:, i], w) for i in range(3)])
    resid_core = resid[core]
    steps = np.array([angle_deg(tuple(quats[i - 1]), tuple(quats[i])) for i in range(1, n)])
    out = {"reference_quat_wxyz": list(ref), "n": n, "duration_s": float(t[-1]),
           "jitter_window_samples": w,
           "angular_jitter_deg": {
               "sd_x": float(resid_core[:, 0].std(ddof=1)), "sd_y": float(resid_core[:, 1].std(ddof=1)),
               "sd_z": float(resid_core[:, 2].std(ddof=1)),
               "geodesic_rms": float(np.sqrt(np.mean(np.sum(resid_core ** 2, axis=1)))),
               "first_difference_estimate": float(np.sqrt(np.mean(steps ** 2)) / np.sqrt(2.0)),
           }}
    minutes = t / 60.0
    slope = {}
    for i, name in enumerate(("x", "y", "z")):
        slope[name] = float(np.polyfit(minutes, v[:, i], 1)[0]) if t[-1] > 0 else None
    slope["geodesic"] = float(np.polyfit(minutes, geo, 1)[0]) if t[-1] > 0 else None
    end_mask = t >= t[-1] - w_ref_s
    end_mean = mean_sign_aligned([tuple(q) for q in quats[end_mask]])
    out["apparent_drift"] = {
        "slope_deg_per_min": slope,
        "net_change_deg": float(angle_deg(ref, end_mean)),
        "net_change_rotvec_deg": list(to_rotvec_deg(mul(conj(ref), end_mean))),
        "max_excursion_deg": float(geo.max()),
    }
    return out
