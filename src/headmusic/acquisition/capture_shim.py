"""ctypes wrapper for native/build/capture_shim.dll (see native/capture_shim.c)."""
from __future__ import annotations

import ctypes as C
from pathlib import Path

ABI_VERSION = 1
KIND_POSE = 1
KIND_RAW = 2

POSE_CB = C.CFUNCTYPE(None, C.POINTER(C.c_float), C.c_uint64)
RAW_CB = C.CFUNCTYPE(None, C.POINTER(C.c_float), C.c_uint64, C.c_uint64)


class CapRecord(C.Structure):
    _fields_ = [("seq", C.c_uint64), ("host_ns", C.c_int64), ("device_ts", C.c_uint64), ("vsync", C.c_uint64),
                ("v", C.c_float * 10), ("kind", C.c_uint32), ("n_values", C.c_uint32)]


class CapStats(C.Structure):
    _fields_ = [("total", C.c_uint64), ("overflow", C.c_uint64), ("high_water", C.c_uint64),
                ("count_only_pose", C.c_uint64), ("count_only_raw", C.c_uint64)]


class CaptureShim:
    def __init__(self, dll_path: Path, batch: int = 4096) -> None:
        dll_path = Path(dll_path)
        if not dll_path.is_file():
            raise FileNotFoundError(f"{dll_path} not found — build it: wsl sh native/build_shim.sh")
        self.path = dll_path
        self.lib = C.CDLL(str(dll_path))
        L = self.lib
        for name in ("cap_abi_version", "cap_record_size", "cap_ring_size"):
            getattr(L, name).restype = C.c_uint32
            getattr(L, name).argtypes = []
        L.cap_reset.restype = None
        L.cap_reset.argtypes = []
        L.cap_now_ns.restype = C.c_int64
        L.cap_now_ns.argtypes = []
        for name in ("cap_pose_capture_callback", "cap_raw_capture_callback",
                     "cap_pose_count_callback", "cap_raw_count_callback"):
            getattr(L, name).restype = C.c_void_p
            getattr(L, name).argtypes = []
        L.cap_read.restype = C.c_int
        L.cap_read.argtypes = [C.POINTER(CapRecord), C.c_int]
        L.cap_stats.restype = None
        L.cap_stats.argtypes = [C.POINTER(CapStats)]
        if L.cap_abi_version() != ABI_VERSION:
            raise RuntimeError(f"capture shim ABI {L.cap_abi_version()} != expected {ABI_VERSION}; rebuild it")
        if L.cap_record_size() != C.sizeof(CapRecord):
            raise RuntimeError(f"capture shim record size {L.cap_record_size()} != {C.sizeof(CapRecord)}")
        self.ring_size = int(L.cap_ring_size())
        self._buf = (CapRecord * batch)()
        self._batch = batch

    def reset(self) -> None:
        """Only while no SDK callback can fire."""
        self.lib.cap_reset()

    def now_ns(self) -> int:
        return int(self.lib.cap_now_ns())

    def pose_capture_callback(self) -> int:
        return int(self.lib.cap_pose_capture_callback())

    def raw_capture_callback(self) -> int:
        return int(self.lib.cap_raw_capture_callback())

    def pose_count_callback(self) -> int:
        return int(self.lib.cap_pose_count_callback())

    def raw_count_callback(self) -> int:
        return int(self.lib.cap_raw_count_callback())

    def read(self) -> list[tuple]:
        """Drain up to one batch: [(kind, seq, host_ns, device_ts, vsync, values_tuple), ...]."""
        n = self.lib.cap_read(self._buf, self._batch)
        out = []
        for i in range(n):
            r = self._buf[i]
            out.append((r.kind, r.seq, r.host_ns, r.device_ts, r.vsync, tuple(r.v[: r.n_values])))
        return out

    def stats(self) -> dict:
        s = CapStats()
        self.lib.cap_stats(C.byref(s))
        return {"total": s.total, "overflow": s.overflow, "high_water": s.high_water,
                "count_only_pose": s.count_only_pose, "count_only_raw": s.count_only_raw,
                "ring_size": self.ring_size}
