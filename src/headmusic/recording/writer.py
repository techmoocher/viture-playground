"""Session writer: one directory per session, crash-tolerant streaming files.

All writes happen on the pipeline thread. Files are flushed at least every io.flush_interval_s,
so a crash loses at most that much data. session.json is rewritten atomically (temp + replace).
"""
from __future__ import annotations

import csv
import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from headmusic.orientation import flags as F
from headmusic.recording import schema as S
from headmusic.types import Command, Event, ProcessedSample, RawImuSample, RawPoseSample


def _json_default(o):
    if isinstance(o, (set, frozenset, tuple)):
        return list(o)
    if isinstance(o, Path):
        return str(o)
    raise TypeError(f"not JSON serialisable: {type(o)}")


def write_json_atomic(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=_json_default) + "\n", encoding="utf-8")
    os.replace(tmp, path)


class _Csv:
    def __init__(self, path: Path, columns: list[str]) -> None:
        self.f = path.open("w", newline="", encoding="utf-8")
        self.w = csv.writer(self.f, lineterminator="\n")
        self.w.writerow(columns)
        self.rows = 0

    def row(self, values: list[str]) -> None:
        self.w.writerow(values)
        self.rows += 1


class _Jsonl:
    def __init__(self, path: Path) -> None:
        self.f = path.open("w", encoding="utf-8", newline="\n")
        self.rows = 0

    def write(self, obj: dict) -> None:
        self.f.write(json.dumps(obj, sort_keys=True, default=_json_default) + "\n")
        self.rows += 1


def raw_pose_row(s: RawPoseSample) -> list[str]:
    return [str(s.seq), str(s.connection_id), str(s.host_rx_monotonic_ns), str(s.device_ts_raw)] + \
           [S.fmt_f32(v) for v in s.values]


def raw_imu_row(s: RawImuSample) -> list[str]:
    return [str(s.seq), str(s.connection_id), str(s.host_rx_monotonic_ns), str(s.device_ts_raw),
            str(s.vsync_raw)] + [S.fmt_f32(v) for v in s.values]


def processed_row(p: ProcessedSample) -> list[str]:
    q = p.quat or (None,) * 4
    r = p.quat_rel or (None,) * 4
    e = p.euler_display or (None,) * 3
    return [str(p.seq), str(p.connection_id), str(p.host_rx_monotonic_ns), str(p.device_ts_raw),
            S.fmt_int(p.dt_device_ns), S.fmt_int(p.dt_host_ns),
            *[S.fmt_f64(v) for v in q], *[S.fmt_f64(v) for v in r], *[S.fmt_f64(v) for v in e],
            "1" if p.valid else "0", F.encode(p.flags), S.fmt_int(p.neutral_calibration_id),
            str(p.gap_est_missing)]


def command_record(c: Command) -> dict:
    return {"kind": c.kind, "after_seq": c.after_seq, "host_monotonic_ns": c.host_monotonic_ns, "data": c.data}


def event_record(e: Event, last_seq: Optional[int]) -> dict:
    return {"kind": e.kind, "host_monotonic_ns": e.host_monotonic_ns, "last_seq": last_seq, "data": e.data}


class SessionWriter:
    """Writes one session directory. Call close() exactly once."""

    def __init__(self, directory: Path, meta: dict, flush_interval_s: float = 1.0,
                 write_raw_pose: bool = True, write_raw_imu: bool = False, write_processed: bool = True) -> None:
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=False)
        self.meta = meta
        self.flush_interval_s = float(flush_interval_s)
        self._last_flush = time.monotonic()
        self.raw_pose = _Csv(self.dir / "raw_pose.csv", S.RAW_POSE_COLUMNS) if write_raw_pose else None
        self.raw_imu = _Csv(self.dir / "raw_imu.csv", S.RAW_IMU_COLUMNS) if write_raw_imu else None
        self.processed = _Csv(self.dir / "processed_pose.csv", S.PROCESSED_COLUMNS) if write_processed else None
        self.events = _Jsonl(self.dir / "events.jsonl")
        self.commands = _Jsonl(self.dir / "commands.jsonl")
        self.calibration = _Jsonl(self.dir / "calibration_neutral.jsonl")
        self.sdk_log = (self.dir / "sdk_log.txt").open("w", encoding="utf-8", newline="\n")
        self._closed = False
        self.write_meta()

    # ---------------------------------------------------------------- streams
    def write_raw_pose(self, s: RawPoseSample) -> None:
        if self.raw_pose:
            self.raw_pose.row(raw_pose_row(s))
            self._maybe_flush()

    def write_raw_imu(self, s: RawImuSample) -> None:
        if self.raw_imu:
            self.raw_imu.row(raw_imu_row(s))
            self._maybe_flush()

    def write_processed(self, p: ProcessedSample) -> None:
        if self.processed:
            self.processed.row(processed_row(p))
            self._maybe_flush()

    def write_event(self, e: Event, last_seq: Optional[int]) -> None:
        if e.kind == "sdk_log":
            self.sdk_log.write(f"{e.host_monotonic_ns}\t{e.data.get('level')}\t{e.data.get('tag')}\t"
                               f"{e.data.get('message')}\n")
        else:
            self.events.write(event_record(e, last_seq))
        self._maybe_flush()

    def write_command(self, c: Command) -> None:
        self.commands.write(command_record(c))
        self.flush()  # operator actions are rare and important

    def write_calibration(self, record: dict) -> None:
        self.calibration.write(record)
        self.flush()

    # ---------------------------------------------------------------- metadata
    def update_meta(self, **sections: Any) -> None:
        for k, v in sections.items():
            if isinstance(v, dict) and isinstance(self.meta.get(k), dict):
                self.meta[k].update(v)
            else:
                self.meta[k] = v
        self.write_meta()

    def write_meta(self) -> None:
        write_json_atomic(self.dir / "session.json", self.meta)

    # ---------------------------------------------------------------- lifecycle
    def _files(self):
        for c in (self.raw_pose, self.raw_imu, self.processed, self.events, self.commands, self.calibration):
            if c is not None:
                yield c.f
        yield self.sdk_log

    def _maybe_flush(self) -> None:
        now = time.monotonic()
        if now - self._last_flush >= self.flush_interval_s:
            self.flush()

    def flush(self) -> None:
        for f in self._files():
            f.flush()
        self._last_flush = time.monotonic()

    def row_counts(self) -> dict:
        out = {}
        for name in ("raw_pose", "raw_imu", "processed", "events", "commands", "calibration"):
            obj = getattr(self, name)
            if obj is not None:
                out[name] = obj.rows
        return out

    def close(self, **final_meta: Any) -> None:
        if self._closed:
            return
        self._closed = True
        self.flush()
        for f in self._files():
            f.close()
        final_meta.setdefault("files", {})
        final_meta["files"].update({"row_counts": self.row_counts()})
        self.update_meta(**final_meta)
