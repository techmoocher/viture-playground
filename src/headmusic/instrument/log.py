"""Instrument log files in a session directory (schema 1.2.0, additive; docs/data-format.md).

- interaction_events.jsonl   deterministic FSM (and later engine) events; byte-identical on replay
- instrument_inputs.jsonl    live-only inputs (stale ticks, late processing) with their stream positions;
                             replay re-injects them there
- interaction_timing.jsonl   non-deterministic: processing ("decision") host time per event, later MIDI
                             send times. Written live only, never compared on replay
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

EVENTS_FILE = "interaction_events.jsonl"
INPUTS_FILE = "instrument_inputs.jsonl"
TIMING_FILE = "interaction_timing.jsonl"


def dumps(obj: dict) -> str:
    return json.dumps(obj, separators=(",", ":"), allow_nan=False)


class InteractionLog:
    def __init__(self, directory: Path, write_timing: bool = True) -> None:
        self.dir = Path(directory)
        self._events = (self.dir / EVENTS_FILE).open("w", encoding="utf-8", newline="\n")
        self._inputs = (self.dir / INPUTS_FILE).open("w", encoding="utf-8", newline="\n")
        self._timing = (self.dir / TIMING_FILE).open("w", encoding="utf-8", newline="\n") if write_timing else None
        self.rows = {"events": 0, "inputs": 0, "timing": 0}
        self._closed = False

    def write_event(self, record: dict) -> None:
        self._events.write(dumps(record) + "\n")
        self.rows["events"] += 1
        if record["event_type"] in ("raw_commit", "gesture_reset", "panic"):
            self._events.flush()

    def write_input(self, record: dict) -> None:
        self._inputs.write(dumps(record) + "\n")
        self._inputs.flush()
        self.rows["inputs"] += 1

    def write_timing(self, record: dict) -> None:
        if self._timing is not None:
            self._timing.write(dumps(record) + "\n")
            self.rows["timing"] += 1

    def flush(self) -> None:
        for f in (self._events, self._inputs, self._timing):
            if f is not None:
                f.flush()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for f in (self._events, self._inputs, self._timing):
            if f is not None:
                f.close()


def read_inputs(session_dir: Path) -> list[dict]:
    from headmusic.recording.reader import read_jsonl
    return read_jsonl(Path(session_dir) / INPUTS_FILE)


def read_events(session_dir: Path) -> list[dict]:
    from headmusic.recording.reader import read_jsonl
    return read_jsonl(Path(session_dir) / EVENTS_FILE)


def events_path(session_dir: Path) -> Optional[Path]:
    p = Path(session_dir) / EVENTS_FILE
    return p if p.exists() else None
