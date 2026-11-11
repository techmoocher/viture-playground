"""ctypes prototypes vs the SDK 2.4.2 headers; frequency selection; USB id parsing (no device needed)."""
import re

import pytest

from conftest import INCLUDE_DIR
from headmusic.acquisition.usb_enum import parse_hardware_ids
from headmusic.acquisition.viture_sdk import FREQUENCY_HZ, PROTOTYPES, select_frequency


def header_declarations() -> dict[str, int]:
    text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in INCLUDE_DIR.glob("*.h"))
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    decls = {}
    for m in re.finditer(r"VITURE_API\s+[\w\s\*]+?\b(\w+)\s*\(([^)]*)\)\s*;", text):
        name, params = m.group(1), m.group(2).strip()
        n = 0 if params in ("", "void") else params.count(",") + 1
        decls.setdefault(name, set()).add(n)
    return decls


@pytest.mark.skipif(not INCLUDE_DIR.exists(), reason="run scripts/setup_sdk.py first")
def test_prototypes_match_header_parameter_counts():
    decls = header_declarations()
    for name, (_res, args, n_header) in PROTOTYPES.items():
        assert name in decls, f"{name} not declared in the SDK headers"
        assert n_header in decls[name], f"{name}: header has {decls[name]} params, binding expects {n_header}"
        assert len(args) == n_header


@pytest.mark.skipif(not INCLUDE_DIR.exists(), reason="run scripts/setup_sdk.py first")
def test_thread_id_buffer_size_is_documented_as_four():
    text = (INCLUDE_DIR / "viture_glasses_provider.h").read_text()
    assert "#define VITURE_THREAD_ID_COUNT 4" in text  # SDK 2.4.2 breaking change; we do not bind this call


def test_select_frequency_prefers_request_when_supported():
    pro_pose = {0, 1, 2, 3}  # VITURE Pro pose mode (probe 2026-11-10)
    assert select_frequency(240, lambda i: i in pro_pose) == (3, 240, "requested_supported")


def test_select_frequency_falls_back_below_never_above():
    pro_pose = {0, 1, 2, 3}
    idx, hz, why = select_frequency(500, lambda i: i in pro_pose)
    assert (idx, hz) == (3, 240) and why.startswith("fallback_highest_supported_below_request")
    idx, hz, why = select_frequency(200, lambda i: i in pro_pose)
    assert hz == 120 and "not_an_sdk_rate" in why
    with pytest.raises(ValueError):
        select_frequency(50, lambda i: i in pro_pose)


def test_frequency_constants():
    assert FREQUENCY_HZ == {0: 60, 1: 90, 2: 120, 3: 240, 4: 500, 5: 1000}


def test_parse_hardware_ids():
    ids = ["USB\\VID_35CA&PID_101D&REV_0100", "USB\\VID_35CA&PID_101D", "USB\\VID_046D&PID_C52B&MI_00", "garbage"]
    assert parse_hardware_ids(ids) == {(0x35CA, 0x101D), (0x046D, 0xC52B)}
