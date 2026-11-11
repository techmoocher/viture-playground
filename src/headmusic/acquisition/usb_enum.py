"""Find VITURE glasses on the USB bus (Windows SetupAPI via ctypes).

glasses.dll does not export an enumeration function, so — like the SDK's own demo — we list
present USB devices, keep vendor 0x35CA, and let the SDK validate the product ID.
"""
from __future__ import annotations

import ctypes as C
import re
import sys
from typing import Iterable

VITURE_VID = 0x35CA
_ID = re.compile(r"VID_([0-9A-Fa-f]{4}).*?PID_([0-9A-Fa-f]{4})")


def parse_hardware_ids(ids: Iterable[str]) -> set[tuple[int, int]]:
    out = set()
    for s in ids:
        m = _ID.search(s)
        if m:
            out.add((int(m.group(1), 16), int(m.group(2), 16)))
    return out


def _usb_hardware_ids() -> list[str]:
    if sys.platform != "win32":
        raise OSError("USB enumeration is implemented for Windows only")
    from ctypes import wintypes as W

    class SP_DEVINFO_DATA(C.Structure):
        _fields_ = [("cbSize", W.DWORD), ("ClassGuid", C.c_byte * 16), ("DevInst", W.DWORD),
                    ("Reserved", C.c_void_p)]

    setupapi = C.WinDLL("setupapi", use_last_error=True)
    get_devs = setupapi.SetupDiGetClassDevsW
    get_devs.restype = C.c_void_p
    get_devs.argtypes = [C.c_void_p, W.LPCWSTR, W.HWND, W.DWORD]
    enum_info = setupapi.SetupDiEnumDeviceInfo
    enum_info.restype = W.BOOL
    enum_info.argtypes = [C.c_void_p, W.DWORD, C.POINTER(SP_DEVINFO_DATA)]
    get_prop = setupapi.SetupDiGetDeviceRegistryPropertyW
    get_prop.restype = W.BOOL
    get_prop.argtypes = [C.c_void_p, C.POINTER(SP_DEVINFO_DATA), W.DWORD, C.POINTER(W.DWORD),
                         C.c_void_p, W.DWORD, C.POINTER(W.DWORD)]
    destroy = setupapi.SetupDiDestroyDeviceInfoList
    destroy.restype = W.BOOL
    destroy.argtypes = [C.c_void_p]

    DIGCF_PRESENT, DIGCF_ALLCLASSES, SPDRP_HARDWAREID = 0x2, 0x4, 0x1
    h = get_devs(None, "USB", None, DIGCF_PRESENT | DIGCF_ALLCLASSES)
    if h is None or h == C.c_void_p(-1).value:
        raise OSError(f"SetupDiGetClassDevsW failed ({C.get_last_error()})")
    ids: list[str] = []
    try:
        data = SP_DEVINFO_DATA()
        data.cbSize = C.sizeof(SP_DEVINFO_DATA)
        buf = C.create_unicode_buffer(2048)
        i = 0
        while enum_info(h, i, C.byref(data)):
            i += 1
            regtype = W.DWORD(0)
            C.memset(buf, 0, C.sizeof(buf))
            if get_prop(h, C.byref(data), SPDRP_HARDWAREID, C.byref(regtype), buf, C.sizeof(buf), None):
                raw = C.wstring_at(C.addressof(buf), C.sizeof(buf) // C.sizeof(C.c_wchar))
                raw = raw.split("\x00\x00", 1)[0]  # REG_MULTI_SZ ends with a double NUL
                ids.extend(s for s in raw.split("\x00") if s)
    finally:
        destroy(h)
    return ids


def find_viture_pids(is_valid=lambda pid: True) -> list[int]:
    """Sorted, de-duplicated VITURE product IDs that the SDK accepts."""
    pairs = parse_hardware_ids(_usb_hardware_ids())
    return sorted({pid for vid, pid in pairs if vid == VITURE_VID and is_valid(pid)})
