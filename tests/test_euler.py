import itertools

import pytest

from headmusic.orientation import quaternion as Q
from headmusic.orientation.euler import direction_words, quat_from_zyx, zyx_from_quat


@pytest.mark.parametrize("axis,expected", [
    ((0, 0, 1), (90.0, 0.0, 0.0)),   # about Z (up): yaw +90 = turn left
    ((0, 1, 0), (0.0, 89.999999, 0.0)),  # about Y (left): pitch (+90 is singular; use 89.999999)
    ((1, 0, 0), (0.0, 0.0, 90.0)),   # about X (forward): roll +90 = right ear down
])
def test_single_axis_signs(axis, expected):
    angle = 89.999999 if axis == (0, 1, 0) else 90.0
    e = zyx_from_quat(Q.from_axis_angle(axis, angle))
    assert e == pytest.approx(expected, abs=1e-6)


def test_positive_pitch_is_nose_down():
    q = Q.from_axis_angle((0, 1, 0), 10)
    nose = Q.rotate(q, (1, 0, 0))
    assert nose[2] < 0  # forward axis tilts toward −Z (down)
    assert zyx_from_quat(q)[1] == pytest.approx(10)


def test_positive_roll_is_right_ear_down():
    q = Q.from_axis_angle((1, 0, 0), 10)
    left_ear = Q.rotate(q, (0, 1, 0))
    assert left_ear[2] > 0  # left side rises, so the right ear goes down
    assert zyx_from_quat(q)[2] == pytest.approx(10)


def test_round_trip_grid_away_from_singularity():
    for yaw, pitch, roll in itertools.product(range(-175, 180, 35), range(-80, 81, 20), range(-175, 180, 35)):
        e = zyx_from_quat(quat_from_zyx(yaw, pitch, roll))
        assert e == pytest.approx((yaw, pitch, roll), abs=1e-9)


def test_sign_invariance():
    q = quat_from_zyx(33, -12, 7)
    assert zyx_from_quat(Q.neg(q)) == pytest.approx(zyx_from_quat(q), abs=1e-12)


def test_singularity_is_clamped_not_an_error():
    q = Q.normalize(Q.mul(Q.from_axis_angle((0, 1, 0), 90.0), (1.0, 0, 0, 1e-17)))
    yaw, pitch, roll = zyx_from_quat(q)
    assert pitch == pytest.approx(90.0, abs=1e-6)


def test_yaw_range_is_minus180_exclusive():
    yaw = zyx_from_quat(Q.from_axis_angle((0, 0, 1), 180.0))[0]
    assert -180.0 < yaw <= 180.0


def test_direction_words():
    assert direction_words(5, -3, 2) == ("left", "up", "right ear down")
    assert direction_words(-5, 3, -2) == ("right", "down", "left ear down")
