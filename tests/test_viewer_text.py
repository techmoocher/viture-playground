"""Viewer text helpers (no window is opened)."""
from headmusic.viewer.app import tilt_text


def test_tilt_text_upright_has_no_warning():
    t = tilt_text(3.2)
    assert "3.2°" in t and "upside down?" not in t and "display only" in t


def test_tilt_text_upside_down_warns_without_blocking():
    assert "upside down?" in tilt_text(171.7)


def test_tilt_text_missing():
    assert tilt_text(None).endswith("—")


def test_window_fits_the_screen_that_hid_the_controls():
    from headmusic.viewer.app import fit_geometry
    # R6a, 2026-11-11: 1280x800 screen, 752 px working area; a 700 px window put the controls off-screen
    w, rest = fit_geometry(1280, 800).split("x")
    h = int(rest.split("+")[0])
    assert int(w) <= 1240 and h + 31 + 10 <= 752  # height + title bar + top offset within the working area
    assert fit_geometry(2560, 1440) == "1000x700+20+10"


def test_command_feedback_confirms_presses():
    from headmusic.viewer.app import command_feedback
    assert command_feedback(None, None) == "no segment open"
    assert command_feedback("yaw_left_90", "started 'yaw_left_90'") == \
        "segment OPEN: yaw_left_90  ·  last: started 'yaw_left_90'"
