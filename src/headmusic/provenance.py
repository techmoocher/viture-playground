"""Session metadata: identity, provenance and clock conventions (normalised; see data-format.md)."""
from __future__ import annotations

import hashlib
import platform
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from headmusic import __version__
from headmusic.config import REPO_ROOT, config_sha256
from headmusic.recording.schema import SCHEMA_VERSION

HOST_CLOCK = ("QueryPerformanceCounter scaled to ns (identical to Python time.perf_counter_ns on Windows); "
              "arbitrary per-boot epoch")
DEVICE_TS = ("SDK device timebase, stored verbatim; observed nanosecond units with 1 ms resolution "
             "(2026-11-10 probe); epoch and sample instant undocumented")


def file_sha256(path: Path) -> Optional[str]:
    path = Path(path)
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_state() -> dict:
    def run(*args):
        return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=5)
    try:
        head = run("rev-parse", "HEAD")
        status = run("status", "--porcelain", "--untracked-files=no")
        commit = head.stdout.strip() if head.returncode == 0 else "uncommitted"
        return {"git_commit": commit, "git_dirty": bool(status.stdout.strip()) if status.returncode == 0 else None}
    except (OSError, subprocess.SubprocessError):
        return {"git_commit": "unknown", "git_dirty": None}


def clock_anchor() -> dict:
    """A (host monotonic, UTC wall clock) pair taken back to back."""
    t0 = time.perf_counter_ns()
    wall = time.time_ns()
    t1 = time.perf_counter_ns()
    return {"host_monotonic_ns": (t0 + t1) // 2, "utc_time_ns": wall,
            "utc_iso": datetime.fromtimestamp(wall / 1e9, tz=timezone.utc).isoformat(), "bracket_ns": t1 - t0}


def new_session_meta(cfg: dict, condition: str, mounting: str, source_kind: str, argv: list[str],
                     stationary: bool = False, notes: str = "", extra_files: Optional[dict] = None) -> dict:
    import numpy
    session_id = str(uuid.uuid4())
    files = {k: {"path": str(v), "sha256": file_sha256(v)} for k, v in (extra_files or {}).items()}
    return {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "participant_id": None,  # Phase 1: bench only, no participants (IRB gate, protocol §3)
        "condition": condition,
        "mounting": mounting,
        "stationary": bool(stationary),
        "notes": notes,
        "notes_reminder": "no personally identifiable information in notes",
        "source": {"kind": source_kind},
        "provenance": {
            "package_version": __version__, **git_state(), "python": sys.version.split()[0],
            "numpy": numpy.__version__, "platform": platform.platform(), "command_line": argv,
            "binaries": files,
        },
        "config": cfg,
        "config_sha256": config_sha256(cfg),
        "clocks": {"host_clock": HOST_CLOCK, "device_ts": DEVICE_TS, "start_anchor": clock_anchor()},
        "device": {},
        "imu": {"mode": cfg["imu"]["mode"], "frequency_requested_hz": cfg["imu"]["frequency_requested_hz"]},
        "processing": {},
        "labels": {"provisional_parameters": "all thresholds are provisional engineering defaults, "
                                             "not validated hardware or ergonomic limits"},
    }


def session_dir_name(meta: dict) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}_{meta['condition']}_{meta['mounting']}_{meta['session_id'][:8]}"
