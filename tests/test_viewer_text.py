"""Viewer text helpers (no window is opened)."""
from headmusic.viewer.app import tilt_text


def test_tilt_text_upright_has_no_warning():
    t = tilt_text(3.2)
    assert "3.2°" in t and "upside down?" not in t and "display only" in t


def test_tilt_text_upside_down_warns_without_blocking():
    assert "upside down?" in tilt_text(171.7)


def test_tilt_text_missing():
    assert tilt_text(None).endswith("—")
