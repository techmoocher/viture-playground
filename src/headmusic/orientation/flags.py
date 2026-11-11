"""Sample quality flags (docs/quality-and-metrics.md §Sample flags).

A sample may carry several flags. `valid` is False iff any INVALIDATING flag is present.
Invalid rows are always kept. Staleness is NOT a sample flag: it is a property of the stream at
query time, evaluated by headmusic.tracking.gate. Recentering and disconnects are events, not
flags; samples carry connection_id and neutral_calibration_id for joining.
"""

NONFINITE = "nonfinite"  # any of the 7 SDK values is NaN or ±Inf
ZERO_NORM = "zero_norm"  # ‖q_sdk‖ < eps_zero
TS_DUPLICATE = "ts_duplicate"  # device ts == d_ref (last sample whose timestamp was in order)
TS_BACKWARD = "ts_backward"  # device ts < d_ref
ANGULAR_JUMP = "angular_jump"  # step > tau_jump from BOTH the last valid and the previous finite sample

NORM_DEVIATION = "norm_deviation"  # |‖q_sdk‖ − 1| > tau_norm (sample still normalised and used)
GAP_BEFORE = "gap_before"  # d − d_ref > k_gap·m + ts_resolution (missing callbacks before this sample)
HEMISPHERE_FLIP = "hemisphere_flip"  # SDK quaternion sign changed vs the previous finite SDK sample
                                     # (the SDK keeps w >= 0); processed quat stays continuous
EULER_NEAR_SINGULAR = "euler_near_singular"  # |display pitch| > euler_singular_deg (numeric guard)
NO_NEUTRAL = "no_neutral"  # no accepted neutral for this connection: quat_rel/euler empty

INVALIDATING = frozenset({NONFINITE, ZERO_NORM, TS_DUPLICATE, TS_BACKWARD, ANGULAR_JUMP})
INFORMATIONAL = frozenset({NORM_DEVIATION, GAP_BEFORE, HEMISPHERE_FLIP, EULER_NEAR_SINGULAR, NO_NEUTRAL})
ALL_FLAGS = INVALIDATING | INFORMATIONAL


def encode(flags) -> str:
    """Pipe-separated sorted flag names; 'valid' if there are none (sample_quality column)."""
    return "|".join(sorted(flags)) if flags else "valid"


def decode(text: str) -> tuple[str, ...]:
    if text in ("", "valid"):
        return ()
    return tuple(text.split("|"))
