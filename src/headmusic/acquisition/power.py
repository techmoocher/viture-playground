"""Keep Windows from sleeping while the instrument runs (G0 R9: a PC sleep delivers stale data late).

SetThreadExecutionState is a per-process request, not a settings change; Windows drops it when the
process exits, and release() clears it earlier. No effect on other platforms.
"""
from __future__ import annotations

import ctypes
import sys

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def _call(flags: int) -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.kernel32.SetThreadExecutionState(flags))
    except (AttributeError, OSError):
        return False


def keep_awake() -> bool:
    return _call(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)


def release() -> bool:
    return _call(ES_CONTINUOUS)
