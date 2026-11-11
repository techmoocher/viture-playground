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


def test_only_acquisition_uses_ctypes():
    users = {p.relative_to(SRC).parts[0] for p in SRC.rglob("*.py") if "ctypes" in imports_of(p)}
    assert users <= {"acquisition"}


def test_core_imports_without_sdk_present():
    import importlib
    for mod in ("headmusic.orientation.processor", "headmusic.tracking.gate", "headmusic.recording.writer",
                "headmusic.recording.export", "headmusic.metrics.report", "headmusic.pipeline"):
        importlib.import_module(mod)
