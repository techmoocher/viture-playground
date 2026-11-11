import math
import random

import pytest

from headmusic.orientation import quaternion as Q


def close(a, b, tol=1e-12):
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def test_hamilton_product_basis():
    i, j, k = (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)
    assert Q.mul(i, j) == (0, 0, 0, 1)        # i·j = k
    assert Q.mul(j, i) == (0, 0, 0, -1)       # j·i = −k
    assert Q.mul(i, i) == (-1, 0, 0, 0)
    assert Q.mul(Q.mul(i, j), k) == (-1, 0, 0, 0)  # ijk = −1


def test_associativity_and_inverse():
    rng = random.Random(0)
    for _ in range(200):
        a, b, c = (Q.normalize([rng.gauss(0, 1) for _ in range(4)]) for _ in range(3))
        assert close(Q.mul(Q.mul(a, b), c), Q.mul(a, Q.mul(b, c)), 1e-12)
        assert close(Q.mul(a, Q.conj(a)), Q.IDENTITY, 1e-12)


def test_rotation_direction_active_right_handed():
    q = Q.from_axis_angle((0, 0, 1), 90)  # +90° about Z (up)
    assert close(Q.rotate(q, (1, 0, 0)), (0, 1, 0), 1e-12)  # North -> West: +yaw turns left


def test_geodesic_is_sign_invariant_and_accurate_for_small_angles():
    a = Q.from_axis_angle((0.3, -0.2, 0.9), 37.0)
    b = Q.mul(a, Q.from_axis_angle((1, 2, 3), 1e-6))
    assert Q.angle_deg(a, b) == pytest.approx(1e-6, rel=1e-6)
    assert Q.angle_deg(a, Q.neg(b)) == pytest.approx(Q.angle_deg(a, b), rel=1e-12)
    assert Q.angle_deg(a, Q.neg(a)) == pytest.approx(0.0, abs=1e-12)


def test_normalize_rejects_zero_and_nonfinite():
    with pytest.raises(ValueError):
        Q.normalize((0.0, 0.0, 0.0, 0.0))
    with pytest.raises(ValueError):
        Q.normalize((math.nan, 0.0, 0.0, 1.0))
    with pytest.raises(ValueError):
        Q.normalize((math.inf, 0.0, 0.0, 1.0))


def test_canonical_and_align():
    q = (-0.5, 0.5, 0.5, 0.5)
    assert Q.canonical(q) == (0.5, -0.5, -0.5, -0.5)
    assert Q.align(q, (0.5, -0.5, -0.5, -0.5)) == (0.5, -0.5, -0.5, -0.5)


def test_rotvec_round_trip():
    for r in [(10.0, -5.0, 2.0), (0.0, 0.0, 179.0), (1e-9, 0.0, 0.0)]:
        back = Q.to_rotvec_deg(Q.from_rotvec_deg(r))
        assert close(back, r, 1e-9)


def test_mean_handles_mixed_signs():
    base = Q.from_axis_angle((0, 0, 1), 40)
    qs = [Q.mul(base, Q.from_axis_angle((1, 0, 0), d)) for d in (-0.5, 0.0, 0.5)]
    qs[1] = Q.neg(qs[1])  # same rotation, opposite sign
    m = Q.mean_sign_aligned(qs)
    assert Q.angle_deg(m, base) < 1e-9
