"""Sampling-interval jitter, arrival-time jitter (relative latency), rate and loss.

Definitions (docs/quality-and-metrics.md §Metrics) — computed independently of each other:
- achieved rate: (N−1)/(t_last − t_first), on the device clock and on the host clock;
- sampling-interval jitter: distribution of consecutive intervals (device Δd; host Δh);
  summaries SD and p99−p1. Device intervals are floored by the 1 ms timestamp resolution;
- arrival-time jitter: least-squares fit host = a + b·device; skew (b−1)·1e6 ppm; SD and p99−p1
  of residuals; relative lateness = residual − min(residual). This is relative, not absolute,
  latency (there is no shared clock);
- loss: gap count, longest gap, estimated missing samples, loss fraction vs a reference rate.
- longest gap-free stretch: the longest run of samples with no gap between them (device time),
  with its achieved rate. This is the candidate measurement for the reference rate r_ref; it
  depends on the reference used to detect the gaps, so it is re-checked after r_ref changes.
"""
from __future__ import annotations

from typing import Optional

import numpy as np


def distribution_ms(x_ns: np.ndarray) -> dict:
    if x_ns.size == 0:
        return {}
    x = x_ns.astype(float) / 1e6
    p = np.percentile(x, [1, 5, 50, 95, 99])
    return {"n": int(x.size), "min": float(x.min()), "p1": float(p[0]), "p5": float(p[1]), "p50": float(p[2]),
            "p95": float(p[3]), "p99": float(p[4]), "max": float(x.max()), "mean": float(x.mean()),
            "sd": float(x.std(ddof=1)) if x.size > 1 else 0.0, "p99_minus_p1": float(p[4] - p[0])}


def achieved_rate_hz(t_ns: np.ndarray) -> Optional[float]:
    if t_ns.size < 2 or t_ns[-1] <= t_ns[0]:
        return None
    return float((t_ns.size - 1) / ((t_ns[-1] - t_ns[0]) / 1e9))


def clock_relation(device_ns: np.ndarray, host_ns: np.ndarray) -> dict:
    if device_ns.size < 3:
        return {}
    d = (device_ns - device_ns[0]).astype(float)
    h = (host_ns - host_ns[0]).astype(float)
    A = np.vstack([d, np.ones_like(d)]).T
    (b, a), *_ = np.linalg.lstsq(A, h, rcond=None)
    res = h - (a + b * d)
    late = res - res.min()
    p = np.percentile(res, [1, 99])
    return {"skew_ppm": float((b - 1.0) * 1e6), "residual_sd_ms": float(res.std(ddof=1) / 1e6),
            "residual_p99_minus_p1_ms": float((p[1] - p[0]) / 1e6),
            "relative_lateness_ms": {"p50": float(np.percentile(late, 50) / 1e6),
                                     "p99": float(np.percentile(late, 99) / 1e6), "max": float(late.max() / 1e6)},
            "note": "relative latency only: residual of host arrival vs a linear fit of the device clock"}


def _gap_mask(device_ns: np.ndarray, reference_interval_ns: float, k_gap: float, ts_resolution_ns: float):
    iv = np.diff(device_ns.astype(np.int64))
    return iv, iv > (k_gap * reference_interval_ns + ts_resolution_ns)


def longest_gap_free_stretch(device_ns: np.ndarray, reference_interval_ns: float, k_gap: float,
                             ts_resolution_ns: float) -> dict:
    """Longest run (by device time) of consecutive samples without a gap between them."""
    if device_ns.size < 2:
        return {}
    _, g = _gap_mask(device_ns, reference_interval_ns, k_gap, ts_resolution_ns)
    cuts = np.flatnonzero(g)
    starts = np.concatenate([[0], cuts + 1])
    ends = np.concatenate([cuts, [device_ns.size - 1]])
    spans = device_ns[ends] - device_ns[starts]
    k = int(np.argmax(spans))
    a, b = int(starts[k]), int(ends[k])
    return {"start_s": float((device_ns[a] - device_ns[0]) / 1e9), "duration_s": float(spans[k] / 1e9),
            "n": b - a + 1, "achieved_rate_device_hz": achieved_rate_hz(device_ns[a:b + 1])}


def gaps(device_ns: np.ndarray, reference_interval_ns: float, k_gap: float, ts_resolution_ns: float) -> dict:
    iv, g = _gap_mask(device_ns, reference_interval_ns, k_gap, ts_resolution_ns)
    missing = np.maximum(np.round(iv[g] / reference_interval_ns) - 1, 0)
    return {"reference_interval_ms": reference_interval_ns / 1e6, "count": int(g.sum()),
            "longest_ms": float(iv[g].max() / 1e6) if g.any() else 0.0, "est_missing": int(missing.sum())}


def timing_report(device_ns: np.ndarray, host_ns: np.ndarray, seq: np.ndarray, reference_rate_hz: Optional[float],
                  k_gap: float, ts_resolution_ns: float, segment_s: float = 60.0) -> dict:
    """All timing metrics for one stream of valid samples, overall and per segment."""
    out = {
        "n": int(device_ns.size),
        "achieved_rate_device_hz": achieved_rate_hz(device_ns),
        "achieved_rate_host_hz": achieved_rate_hz(host_ns),
        "interval_device_ms": distribution_ms(np.diff(device_ns)),
        "interval_host_ms": distribution_ms(np.diff(host_ns)),
        "clock_relation": clock_relation(device_ns, host_ns),
        "pipeline_seq_gaps": int(np.sum(np.diff(seq) > 1)) if seq.size > 1 else 0,
    }
    ref = reference_rate_hz or out["achieved_rate_device_hz"]
    if ref:
        out["gaps"] = gaps(device_ns, 1e9 / ref, k_gap, ts_resolution_ns)
        out["gaps"]["reference_source"] = "measured r_ref" if reference_rate_hz else "this recording's achieved rate"
        out["longest_gap_free_stretch"] = longest_gap_free_stretch(device_ns, 1e9 / ref, k_gap, ts_resolution_ns)
        span = (device_ns[-1] - device_ns[0]) / 1e9 if device_ns.size > 1 else 0
        expected = span * ref + 1
        out["loss_fraction"] = float(max(0.0, 1.0 - device_ns.size / expected)) if expected > 0 else None
    segs = []
    if device_ns.size > 1:
        t = (device_ns - device_ns[0]) / 1e9
        for k in range(int(t[-1] // segment_s) + 1):
            m = (t >= k * segment_s) & (t < (k + 1) * segment_s)
            if m.sum() > 10:
                segs.append({"segment": k, "start_s": k * segment_s, "n": int(m.sum()),
                             "achieved_rate_device_hz": achieved_rate_hz(device_ns[m]),
                             "interval_host_sd_ms": distribution_ms(np.diff(host_ns[m])).get("sd"),
                             "clock_residual_sd_ms": clock_relation(device_ns[m], host_ns[m]).get("residual_sd_ms")})
    out["segments"] = segs
    return out
