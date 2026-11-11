"""Placement check summary (no hardware: synthetic source items)."""
import pytest

from headmusic.acquisition import synthetic as SY
from headmusic.cli import build_parser
from headmusic.metrics.placement import format_summary, placement_summary
from headmusic.orientation.euler import quat_from_zyx
from headmusic.types import Event


def connected(hz=240):
    return Event("device_connected", 0, {"connection_id": 1, "mode": "pose", "frequency_selected_hz": hz})


def test_still_and_upright(cfg):
    samples = SY.generate(15.0, orientation=lambda t: quat_from_zyx(-130.0, 12.0, 0.0), noise_deg=0.003, seed=2)
    s = placement_summary([connected(), *samples], cfg)
    assert s["n_samples"] == len(samples) and s["n_invalid"] == 0 and s["n_gaps"] == 0
    assert s["tilt_from_upright_deg"] == pytest.approx(12.0, abs=0.05)
    assert s["deviation_max_deg"] < 0.05
    assert s["change_first_to_last_second_deg"] < 0.01
    assert s["achieved_rate_hz"] == pytest.approx(202.5, rel=1e-3)
    text = format_summary(s)
    assert "nothing recorded" in text and "tilt from upright: 12.0°" in text and "not a pass limit" in text


def test_movement_shows_up(cfg):
    samples = SY.generate(15.0, orientation=lambda t: quat_from_zyx(-130.0 + 0.5 * t, 10.0, 0.0))
    s = placement_summary([connected(), *samples], cfg)
    assert s["deviation_max_deg"] > 3.0
    assert s["change_first_to_last_second_deg"] == pytest.approx(7.0, abs=0.2)


def test_upside_down_is_visible(cfg):
    samples = SY.generate(5.0, orientation=lambda t: quat_from_zyx(0.0, 0.0, 178.0))
    s = placement_summary([connected(), *samples], cfg)
    assert s["tilt_from_upright_deg"] == pytest.approx(178.0, abs=0.05)


def test_too_few_samples(cfg):
    s = placement_summary([connected()], cfg)
    assert s["error"] == "too few valid samples"
    assert "too few valid samples" in format_summary(s)


def test_cli_has_check_placement():
    a = build_parser().parse_args(["check-placement", "--seconds", "10"])
    assert a.cmd == "check-placement" and a.seconds == 10.0
