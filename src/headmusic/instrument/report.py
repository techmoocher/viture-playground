"""Instrument session summary for smoke tests (Phase 2D): what was selected, what was cancelled or reset and why,
and the software-side timing. All latencies are ESTIMATED from host timestamps: they exclude the SDK filter lag,
the synth and the audio device. Physical audio-output latency is not measured (O4).
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Optional

from headmusic.recording.reader import read_jsonl


def _pct(values: list[float], q: float) -> Optional[float]:
    if not values:
        return None
    v = sorted(values)
    return v[min(len(v) - 1, int(round(q * (len(v) - 1))))]


def _ms(values: list[int]) -> str:
    if not values:
        return "—"
    ms = [x / 1e6 for x in values]
    return (f"n={len(ms)}  p50 {_pct(ms, 0.5):.2f} ms  p95 {_pct(ms, 0.95):.2f} ms  max {max(ms):.2f} ms")


def _ms_s(values: list[int]) -> str:
    if not values:
        return "—"
    s = [x / 1e9 for x in values]
    return f"n={len(s)}  median {_pct(s, 0.5):.2f} s  min {min(s):.2f} s  max {max(s):.2f} s"


def summarize(session: Path) -> dict:
    session = Path(session)
    ev = read_jsonl(session / "interaction_events.jsonl")
    inputs = read_jsonl(session / "instrument_inputs.jsonl")
    itiming = {r["event_id"]: r for r in read_jsonl(session / "interaction_timing.jsonl")}
    music = read_jsonl(session / "music_events.jsonl")
    mtiming = read_jsonl(session / "music_timing.jsonl")
    events = read_jsonl(session / "events.jsonl")
    commits = [e for e in ev if e["event_type"] == "raw_commit"]
    decision = [itiming[e["event_id"]]["decision_host_ns"] - e["produced_host_ns"] for e in commits
                if e["event_id"] in itiming and e.get("produced_host_ns") is not None]
    note_on_lat = [t["estimated_software_latency_ns"] for t in mtiming
                   if t.get("kind") == "note_on" and "estimated_software_latency_ns" in t]
    send_dur = [t["send_end_host_ns"] - t["send_begin_host_ns"] for t in mtiming if "send_end_host_ns" in t]
    held, on = [], {}
    for t in mtiming:  # physical note-on → note-off on the chord channel, from the send log
        if "send_end_host_ns" not in t:
            continue
        if t.get("kind") == "note_on":
            on[t["data1"]] = t["send_end_host_ns"]
        elif t.get("kind") in ("note_off",) and t["data1"] in on:
            held.append(t["send_end_host_ns"] - on.pop(t["data1"]))
    programs = sorted({t["data1"] for t in mtiming if t.get("kind") == "program_change"})
    return {
        "commits": [e["chord"] for e in commits],
        "commits_per_chord": dict(Counter(e["chord"] for e in commits)),
        "dwell_starts": sum(1 for e in ev if e["event_type"] == "dwell_start"),
        "dwell_cancels": dict(Counter(e["reason"] for e in ev if e["event_type"] == "dwell_cancel")),
        "resets": dict(Counter(e["reason"] for e in ev if e["event_type"] == "gesture_reset")),
        "inactive_reasons": dict(Counter(e["reason"] for e in ev if e["event_type"] == "inactive_reason")),
        "live_inputs": dict(Counter(r["kind"] for r in inputs)),
        "panics": [m.get("reason") for m in music if m["event_type"] == "panic"],
        "releases": dict(Counter(m.get("reason") for m in music if m["event_type"] == "midi_note_off")),
        "output_errors": [t for t in mtiming if "error" in t or t.get("kind") == "emergency"],
        "consumer_errors": [e for e in events if e["kind"] == "consumer_error"],
        "disconnects": sum(1 for e in events if e["kind"] == "device_disconnected"),
        "decision_latency_ns": decision,
        "note_on_estimated_latency_ns": note_on_lat,
        "midi_send_duration_ns": send_dur,
        "note_held_ns": held,
        "programs_sent": programs,
        "dwell_restarts": sum(1 for e in ev if e["event_type"] == "dwell_restart"),
        "intentional_releases": dict(Counter(e["reason"] for e in ev if e["event_type"] == "chord_release")),
    }


def report_text(session: Path) -> str:
    s = summarize(session)
    lines = [
        f"# Instrument report: {Path(session).name}",
        "",
        f"- commits ({len(s['commits'])}): {' '.join(s['commits']) or '—'}   per chord: {s['commits_per_chord']}",
        f"- dwell starts: {s['dwell_starts']}   cancelled: {s['dwell_cancels'] or '—'}",
        f"- gesture resets by reason: {s['resets'] or '—'}",
        f"- inactive reasons seen: {s['inactive_reasons'] or '—'}",
        f"- live inputs (logged for replay): {s['live_inputs'] or '—'}",
        f"- disconnects: {s['disconnects']}   panics: {s['panics'] or '—'}",
        f"- chord releases by reason: {s['releases'] or '—'}",
        f"- releases requested by the FSM (hold exit, R, neutral rest): {s['intentional_releases'] or '—'}",
        f"- dwell restarts (stability rule): {s['dwell_restarts']}",
        f"- patch (program change sent): {s['programs_sent'] or 'none: synth default (GM 0, piano, decays)'}",
        f"- notes held on (note-on to note-off): {_ms_s(s['note_held_ns'])}",
        f"- output errors: {len(s['output_errors'])}   consumer errors: {len(s['consumer_errors'])}",
        "",
        "Timing (ESTIMATED from host timestamps; excludes SDK filter lag, synth and audio device; "
        "physical audio latency is not measured):",
        f"- commit decision after sample production: {_ms(s['decision_latency_ns'])}",
        f"- chord note-on sent after sample production: {_ms(s['note_on_estimated_latency_ns'])}",
        f"- MIDI send call duration: {_ms(s['midi_send_duration_ns'])}",
    ]
    return "\n".join(lines) + "\n"
