"""Readers that reconstruct samples exactly as the live pipeline saw them."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterator, Optional

from headmusic.orientation import flags as F
from headmusic.recording import schema as S
from headmusic.types import ProcessedSample, RawImuSample, RawPoseSample


def load_meta(session_dir: Path) -> dict:
    return json.loads((Path(session_dir) / "session.json").read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    break  # truncated last line after a crash
    return out


def _rows(path: Path) -> Iterator[list[str]]:
    with Path(path).open(newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        header = next(r, None)
        for row in r:
            if header is not None and len(row) != len(header):
                break  # truncated last row after a crash
            yield row


def iter_raw_pose(path: Path) -> Iterator[RawPoseSample]:
    for row in _rows(path):
        yield RawPoseSample(seq=int(row[0]), connection_id=int(row[1]), host_rx_monotonic_ns=int(row[2]),
                            device_ts_raw=int(row[3]), values=tuple(S.to_f32(v) for v in row[4:11]))


def iter_raw_imu(path: Path) -> Iterator[RawImuSample]:
    for row in _rows(path):
        yield RawImuSample(seq=int(row[0]), connection_id=int(row[1]), host_rx_monotonic_ns=int(row[2]),
                           device_ts_raw=int(row[3]), vsync_raw=int(row[4]),
                           values=tuple(S.to_f32(v) for v in row[5:15]))


def _quad(vals) -> Optional[tuple]:
    if vals[0] == "":
        return None
    return tuple(float(v) for v in vals)


def iter_processed(path: Path) -> Iterator[ProcessedSample]:
    for row in _rows(path):
        yield ProcessedSample(
            seq=int(row[0]), connection_id=int(row[1]), host_rx_monotonic_ns=int(row[2]), device_ts_raw=int(row[3]),
            dt_device_ns=S.parse_int(row[4]), dt_host_ns=S.parse_int(row[5]),
            quat=_quad(row[6:10]), quat_rel=_quad(row[10:14]), euler_display=_quad(row[14:17]),
            valid=row[17] == "1", flags=F.decode(row[18]), neutral_calibration_id=S.parse_int(row[19]),
            gap_est_missing=int(row[20]))
