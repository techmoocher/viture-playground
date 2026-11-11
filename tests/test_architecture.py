"""Module boundaries: hardware access stays in headmusic.acquisition (AC9)."""
import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "headmusic"
CORE = ["types.py", "config.py", "orientation", "tracking", "recording", "metrics"]
FORBIDDEN_FOR_CORE = ("ctypes", "headmusic.acquisition", "headmusic.pipeline", "headmusic.viewer", "headmusic.cli",
                      "tkinter")


def imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def core_files():
    for entry in CORE:
        p = SRC / entry
        yield from ([p] if p.is_file() else sorted(p.rglob("*.py")))


@pytest.mark.parametrize("path", list(core_files()), ids=lambda p: str(p.relative_to(SRC)))
def test_core_modules_do_not_touch_hardware(path):
    bad = {m for m in imports_of(path) if m.startswith(FORBIDDEN_FOR_CORE)}
    assert not bad, f"{path.name} imports {bad}"


INSTRUMENT_FORBIDDEN = FORBIDDEN_FOR_CORE + ("headmusic.music",)


@pytest.mark.parametrize("path", sorted((SRC / "instrument").rglob("*.py")), ids=lambda p: p.name)
def test_instrument_is_independent_of_acquisition_audio_and_ui(path):
    """Phase 2: gesture recognition never touches sensors, the DLL, audio output or the UI."""
    bad = {m for m in imports_of(path) if m.startswith(INSTRUMENT_FORBIDDEN)}
    assert not bad, f"{path.name} imports {bad}"


MUSIC_FORBIDDEN = ("headmusic.acquisition", "headmusic.pipeline", "headmusic.viewer", "headmusic.cli", "tkinter")


@pytest.mark.parametrize("path", sorted((SRC / "music").rglob("*.py")), ids=lambda p: p.name)
def test_music_never_sees_sensors_or_ui(path):
    """Phase 2B: the chord engine consumes instrument events only."""
    bad = {m for m in imports_of(path) if m.startswith(MUSIC_FORBIDDEN)}
    assert not bad, f"{path.name} imports {bad}"


@pytest.mark.parametrize("name", ["hud.py", "play.py"])
def test_play_display_decides_nothing(name):
    """2C-3: the HUD reads snapshots and sends commands; it never imports the FSM, engine or pipeline logic."""
    bad = {m for m in imports_of(SRC / "viewer" / name)
           if m.startswith(("headmusic.instrument.fsm", "headmusic.instrument.consumer", "headmusic.music",
                            "headmusic.pipeline", "headmusic.acquisition", "ctypes"))}
    assert not bad, f"{name} imports {bad}"


def test_only_hardware_boundaries_use_ctypes():
    users = {str(p.relative_to(SRC).as_posix()) for p in SRC.rglob("*.py") if "ctypes" in imports_of(p)}
    assert {u for u in users if not u.startswith("acquisition/")} <= {"music/backends/winmm.py"}
    assert {u for u in users if u.startswith("acquisition/")} <= {"acquisition/capture_shim.py",
                                                                  "acquisition/viture_sdk.py",
                                                                  "acquisition/usb_enum.py",
                                                                  "acquisition/power.py"}


def test_core_imports_without_sdk_present():
    import importlib
    for mod in ("headmusic.orientation.processor", "headmusic.tracking.gate", "headmusic.recording.writer",
                "headmusic.recording.export", "headmusic.metrics.report", "headmusic.pipeline"):
        importlib.import_module(mod)
