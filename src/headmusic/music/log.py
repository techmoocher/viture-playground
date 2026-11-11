"""Music log files (schema 1.2.0):
- music_events.jsonl   deterministic engine decisions (chord on/off, scheduled onsets, accompaniment state,
                       panic), each with the instrument event that caused it; byte-identical on replay
- music_timing.jsonl   non-deterministic: every MIDI send with due, begin and end host times, lateness, the
                       ESTIMATED software latency (send end − production time of the deciding sample), errors.
                       Physical audio-output latency is not measured by the software.
"""
from __future__ import annotations

import json
from pathlib import Path

EVENTS_FILE = "music_events.jsonl"
TIMING_FILE = "music_timing.jsonl"


def _dumps(obj: dict) -> str:
    return json.dumps(obj, separators=(",", ":"), allow_nan=False)


class MusicLog:
    def __init__(self, directory: Path, write_timing: bool = True) -> None:
        self.dir = Path(directory)
        self._events = (self.dir / EVENTS_FILE).open("w", encoding="utf-8", newline="\n")
        self._timing = (self.dir / TIMING_FILE).open("w", encoding="utf-8", newline="\n") if write_timing else None
        self.rows = {"events": 0, "timing": 0}
        self._closed = False

    def write_event(self, record: dict) -> None:
        self._events.write(_dumps(record) + "\n")
        self._events.flush()
        self.rows["events"] += 1

    def write_timing(self, record: dict) -> None:
        if self._timing is not None and not self._closed:
            self._timing.write(_dumps(record) + "\n")
            self.rows["timing"] += 1

    def flush(self) -> None:
        for f in (self._events, self._timing):
            if f is not None and not self._closed:
                f.flush()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            for f in (self._events, self._timing):
                if f is not None:
                    f.close()
