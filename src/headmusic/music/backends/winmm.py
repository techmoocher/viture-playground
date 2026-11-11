"""Windows MIDI output through winmm.dll (built into Windows; no extra dependency).

The default device 0 is usually "Microsoft GS Wavetable Synth". It is audible out of the box, but its output
latency is known to be noticeable and is NOT measured here (docs/phase2-proposal.md §5, O4). Any other MIDI
output port (a loopback port feeding a software synth) can be chosen by index or name.

This module is the music package's only hardware boundary (it uses ctypes). The instrument never imports it.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Optional

from headmusic.music.backends import BackendError

MMSYSERR_NOERROR = 0
CALLBACK_NULL = 0


class MIDIOUTCAPSW(ctypes.Structure):
    _fields_ = [("wMid", wintypes.WORD), ("wPid", wintypes.WORD), ("vDriverVersion", wintypes.UINT),
                ("szPname", wintypes.WCHAR * 32), ("wTechnology", wintypes.WORD), ("wVoices", wintypes.WORD),
                ("wNotes", wintypes.WORD), ("wChannelMask", wintypes.WORD), ("dwSupport", wintypes.DWORD)]


def _load(dll=None):
    if dll is not None:
        return dll
    try:
        w = ctypes.WinDLL("winmm")
    except (AttributeError, OSError) as e:  # not on Windows
        raise BackendError(f"winmm is not available: {e}") from None
    w.midiOutGetNumDevs.restype = wintypes.UINT
    w.midiOutGetDevCapsW.argtypes = [ctypes.c_size_t, ctypes.POINTER(MIDIOUTCAPSW), wintypes.UINT]
    w.midiOutGetDevCapsW.restype = wintypes.UINT
    w.midiOutOpen.argtypes = [ctypes.POINTER(wintypes.HANDLE), wintypes.UINT, ctypes.c_size_t, ctypes.c_size_t,
                              wintypes.DWORD]
    w.midiOutOpen.restype = wintypes.UINT
    w.midiOutShortMsg.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    w.midiOutShortMsg.restype = wintypes.UINT
    w.midiOutReset.argtypes = [wintypes.HANDLE]
    w.midiOutReset.restype = wintypes.UINT
    w.midiOutClose.argtypes = [wintypes.HANDLE]
    w.midiOutClose.restype = wintypes.UINT
    return w


def list_devices(dll=None) -> list[str]:
    w = _load(dll)
    out = []
    for i in range(int(w.midiOutGetNumDevs())):
        caps = MIDIOUTCAPSW()
        rc = w.midiOutGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps))
        out.append(caps.szPname if rc == MMSYSERR_NOERROR else f"<device {i}: error {rc}>")
    return out


def pack(status: int, d1: int, d2: int) -> int:
    """midiOutShortMsg layout: status in the low byte, then data1, then data2."""
    return (status & 0xFF) | ((d1 & 0x7F) << 8) | ((d2 & 0x7F) << 16)


class WinmmBackend:
    name = "winmm"

    def __init__(self, device=None, dll=None) -> None:
        self._w = _load(dll)
        names = list_devices(self._w)
        if not names:
            raise BackendError("no MIDI output devices")
        if device is None:
            index = 0
        elif isinstance(device, int):
            index = device
        else:
            matches = [i for i, n in enumerate(names) if str(device).lower() in n.lower()]
            if not matches:
                raise BackendError(f"no MIDI output device matching {device!r}; available: {names}")
            index = matches[0]
        if not 0 <= index < len(names):
            raise BackendError(f"MIDI output device {index} does not exist; available: {names}")
        self.device_index, self.device_name = index, names[index]
        self._h = wintypes.HANDLE()
        rc = self._w.midiOutOpen(ctypes.byref(self._h), index, 0, 0, CALLBACK_NULL)
        if rc != MMSYSERR_NOERROR:
            raise BackendError(f"midiOutOpen({index}) failed: {rc}")
        self._open = True

    def send(self, status: int, d1: int, d2: int) -> None:
        if not self._open:
            raise BackendError("MIDI device is closed")
        rc = self._w.midiOutShortMsg(self._h, pack(status, d1, d2))
        if rc != MMSYSERR_NOERROR:
            raise BackendError(f"midiOutShortMsg failed: {rc}")

    def reset(self) -> None:
        if self._open:
            self._w.midiOutReset(self._h)

    def close(self) -> None:
        if self._open:
            self._open = False
            try:
                self._w.midiOutReset(self._h)
            finally:
                self._w.midiOutClose(self._h)

    def describe(self) -> dict:
        return {"backend": "winmm", "device_index": self.device_index, "device_name": self.device_name}


def describe_devices(dll=None) -> Optional[str]:
    try:
        names = list_devices(dll)
    except BackendError as e:
        return str(e)
    return "\n".join(f"{i}: {n}" for i, n in enumerate(names)) or "no MIDI output devices"
