"""MIDI output backends. A backend sends raw 3-byte MIDI messages; the engine owns all musical state.

    send(status, data1, data2)   raise BackendError on failure
    reset()                      best-effort: silence everything the device is playing
    close()
"""
from __future__ import annotations

from typing import Optional


class BackendError(RuntimeError):
    pass


class NullBackend:
    """No sound. Records every message (tests, offline replay, headless runs)."""

    name = "null"

    def __init__(self, fail_after: Optional[int] = None) -> None:
        self.messages: list[tuple[int, int, int]] = []
        self.resets = 0
        self.closed = False
        self._fail_after = fail_after  # tests: raise on the n-th send

    def send(self, status: int, d1: int, d2: int) -> None:
        if self._fail_after is not None and len(self.messages) >= self._fail_after:
            raise BackendError("simulated backend failure")
        self.messages.append((status, d1, d2))

    def reset(self) -> None:
        self.resets += 1

    def close(self) -> None:
        self.closed = True

    def describe(self) -> dict:
        return {"backend": "null"}


def make_backend(name: str, device=None):
    if name == "null":
        return NullBackend()
    if name == "winmm":
        from headmusic.music.backends.winmm import WinmmBackend
        return WinmmBackend(device)
    raise ValueError(f"unknown backend {name!r}")
