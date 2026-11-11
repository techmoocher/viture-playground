"""2D preparation: the whole `headmusic play` command, end to end, with a simulated device in real time.

The glasses, the SDK DLL and the capture shim are replaced by a source that emits a synthetic head-motion
trace at its real timing, through the real pipeline, gate, FSM, chord engine (null output), play window,
recording and stop path. It then checks that the recorded session replays to identical decisions.
"""
import threading
import time

import pytest

from headmusic import cli
from headmusic.acquisition import capture_shim, viture_source
from headmusic.acquisition import synthetic as syn
from headmusic.instrument.log import read_events, read_inputs
from headmusic.recording.reader import read_jsonl
from headmusic.types import Event, RawPoseSample

RATE = 202.5


class FakeSdk:
    def __init__(self, path):
        self.dll_path = path


class FakeShim:
    def __init__(self, path):
        self.path = path

    def stats(self):
        return {"total": 0, "overflow": 0}


def make_fake_source(trace, pause=None):
    class FakeLiveSource:
        def __init__(self, sdk, shim, cfg, sink, clock, pid=None):
            self.sink, self.clock = sink, clock
            self.finished = threading.Event()
            self.last_error = None
            self._stop = threading.Event()
            self._t = threading.Thread(target=self._run, daemon=True)

        def start(self):
            self._t.start()

        def stop(self, timeout=10.0):
            self._stop.set()
            self._t.join(timeout)

        def _run(self):
            self.sink(Event("device_connected", self.clock(), {
                "connection_id": 1, "mode": "pose", "frequency_requested_hz": 240, "frequency_selected_hz": 240,
                "frequency_selection_reason": "requested", "market_name": "Simulated", "pid": "sim"}))
            t0 = time.perf_counter()
            d0 = trace[0].device_ts_raw
            for s in trace:
                t = (s.device_ts_raw - d0) / 1e9
                if pause and pause[0] <= t < pause[1]:
                    continue  # the device produces nothing (G0 300/600 ms pauses)
                delay = t0 + t - time.perf_counter()
                if delay > 0 and self._stop.wait(delay):
                    break
                self.sink(RawPoseSample(s.seq, 1, self.clock(), s.device_ts_raw, s.values))
            self.finished.set()
    return FakeLiveSource


def test_play_end_to_end_with_a_simulated_device(tmp_path, monkeypatch, capsys):
    pytest.importorskip("tkinter")
    keys, end = syn.chord_tour(yaws=(31.0, -13.0))  # C, then Am
    trace = syn.generate(end + 0.5, orientation=syn.keyframes(keys))
    pause = (2.45, 2.75)  # 300 ms device pause while C sounds and the head is still in C
    (tmp_path / "glasses.dll").write_bytes(b"sim")
    (tmp_path / "shim.dll").write_bytes(b"sim")
    monkeypatch.setattr(cli, "_sdk", lambda args: FakeSdk(tmp_path / "glasses.dll"))
    monkeypatch.setattr(capture_shim, "CaptureShim", FakeShim)
    monkeypatch.setattr(viture_source, "VitureSdkSource", make_fake_source(trace, pause))
    conf = tmp_path / "play.toml"
    conf.write_text("[neutral]\nwindow_s = 0.5\n")
    data = tmp_path / "data"
    rc = cli.main(["--data", str(data), "--config", str(conf), "--shim", str(tmp_path / "shim.dll"), "play",
                   "--audio", "null", "--capture-neutral-at", "0.1", "--close-after", str(end + 1.5),
                   "--no-keep-awake"])
    out = capsys.readouterr().out
    assert rc == 0, out
    # MVP defaults (80 ms / 2° settle): the turn to C crosses G without sounding it
    assert "commits: ['C', 'Am']; all notes off" in out
    session = next((data / "sessions").iterdir())

    ev = read_events(session)
    assert [e["chord"] for e in ev if e["event_type"] == "raw_commit"] == ["C", "Am"]
    inputs = [r["kind"] for r in read_inputs(session)]
    assert "stale_tick" in inputs  # the pause was detected live, between samples
    music = read_jsonl(session / "music_events.jsonl")
    offs = [m for m in music if m["event_type"] == "midi_note_off"]
    assert {"chord": "C", "reason": "interruption:stale_tick"}.items() <= next(
        m for m in offs if m["chord"] == "C").items()
    assert [m["event_type"] for m in music][-2:] == ["panic", "engine_stop"]  # closing the window = panic first
    timing = read_jsonl(session / "music_timing.jsonl")
    lat = [t["estimated_software_latency_ns"] for t in timing if "estimated_software_latency_ns" in t]
    assert lat and all(0 <= v < 100_000_000 for v in lat)  # software-side only; not audio latency
    commands = [c["kind"] for c in read_jsonl(session / "commands.jsonl")]
    assert commands[0] == "capture_neutral" and commands[-1] == "panic"

    # the recorded live session replays to byte-identical decisions
    rc = cli.main(["--data", str(data), "replay", str(session), "--reprocess", "--instrument",
                   "--out", str(tmp_path / "replayed")])
    out = capsys.readouterr().out
    assert "interaction_events.jsonl identical to the original: True" in out, out
    assert "music_events.jsonl identical to the original: True" in out, out
    assert rc == 0

    assert cli.main(["instrument-report", str(session)]) == 0
    rep = capsys.readouterr().out
    assert "commits (2): C Am" in rep and "stale_tick" in rep and "ESTIMATED" in rep
    assert (session / "analysis" / "instrument_report.md").exists()


def test_play_refuses_worn_until_o3(capsys):
    assert cli.main(["play", "--mounting", "worn", "--audio", "null"]) == 2
    assert "O3" in capsys.readouterr().err
