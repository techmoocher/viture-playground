"""ChordEngine: turns instrument events into MIDI (docs/phase2-proposal.md §5).

It listens to InteractionEvents (never to sensor samples) and is also a pipeline consumer for its own commands
(accompaniment_start, accompaniment_stop).

| Instrument event                               | Engine                                                   |
|------------------------------------------------|----------------------------------------------------------|
| raw_commit(chord)                              | sounding chord off, new chord on (quantized if enabled)   |
| gesture_reset, state_change → inactive         | release the sounding chord (release_on_interruption);    |
|                                                | mute the accompaniment if on_interruption = "mute"        |
| return_neutral                                 | unmute; auto-start the accompaniment (first time)         |
| panic                                          | everything off, accompaniment stopped, schedule cleared   |

Two kinds of state:
- logical: decided in the pipeline thread from deterministic inputs and logged to music_events.jsonl;
- physical: the notes actually on at the device, tracked per (channel, note) so every note-on gets exactly one
  note-off whatever happens (release, panic, failure, stop).

Releasing sound is always allowed; it selects nothing (research question Q8).
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

from headmusic.instrument.events import INACTIVE, InteractionEvent
from headmusic.music.config import MusicConfig
from headmusic.music.log import MusicLog
from headmusic.music.scheduler import Scheduler

NOTE_ON, NOTE_OFF, CC = 0x90, 0x80, 0xB0
CC_ALL_SOUND_OFF, CC_ALL_NOTES_OFF = 120, 123


class ChordEngine:
    def __init__(self, cfg: MusicConfig, backend, log: Optional[MusicLog] = None,
                 clock: Optional[Callable[[], int]] = None, realtime: bool = False) -> None:
        self.cfg = cfg
        self.backend = backend
        self.log = log
        self.clock = clock
        self._lock = threading.RLock()
        self.sched = Scheduler(clock, on_error=lambda e: self._emergency("scheduler_error", repr(e))) \
            if (realtime and clock is not None) else None
        self._ch = cfg.channel - 1
        self._click_ch = cfg.accompaniment.channel - 1
        # logical state (deterministic)
        self.chord: Optional[str] = None
        self._pending: Optional[tuple[int, str, Optional[str]]] = None  # quantized onset: (token, chord, previous)
        self.accomp_running = False
        self.accomp_t0: Optional[int] = None
        self.accomp_muted = False
        self._auto_started = False
        self._next_id = 1
        self.events: list[dict] = []
        # physical state
        self._phys: set[tuple[int, int]] = set()
        self._click_token: Optional[int] = None
        self.failed: Optional[str] = None
        self.stopped = False

    # ------------------------------------------------------------------ pipeline consumer API
    def on_sample(self, ps) -> None:
        pass

    def on_event(self, e) -> None:
        pass

    def on_calibration(self, r) -> None:
        pass

    def on_tick(self, now) -> None:
        pass

    def on_command(self, c) -> None:
        if c.kind == "accompaniment_start" and self.cfg.accompaniment.enabled and not self.accomp_running:
            self._start_accompaniment(c.host_monotonic_ns, cause=None, reason="command")
        elif c.kind == "accompaniment_stop" and self.accomp_running:
            self._stop_accompaniment(cause=None, reason="command")

    def on_failure(self, exc: BaseException) -> None:
        self._emergency("consumer_error", repr(exc))

    # ------------------------------------------------------------------ instrument events
    def on_interaction(self, e: InteractionEvent, event_id: int) -> None:
        with self._lock:  # the play window may call panic() from the UI thread
            self._on_interaction(e, event_id)

    def _on_interaction(self, e: InteractionEvent, event_id: int) -> None:
        if self.stopped:
            return
        t = e.event_type
        if t == "raw_commit":
            self._commit(e, event_id)
        elif t == "panic":
            self.panic(cause=(event_id, e))
        elif t == "gesture_reset" or (t == "state_change" and e.state == INACTIVE):
            if self.cfg.release_on_interruption:
                self._release(f"interruption:{e.reason}", (event_id, e))
            if self.accomp_running and not self.accomp_muted and self.cfg.accompaniment.on_interruption == "mute":
                self.accomp_muted = True
                self._log("accompaniment_mute", (event_id, e), reason=e.reason)
        elif t == "return_neutral":
            if self.accomp_muted:
                self.accomp_muted = False
                self._log("accompaniment_unmute", (event_id, e))
            a = self.cfg.accompaniment
            if a.enabled and a.auto_start and not self._auto_started and not self.accomp_running:
                self._start_accompaniment(e.produced_host_ns, cause=(event_id, e), reason="auto_start")

    # ------------------------------------------------------------------ controls
    def panic(self, cause=None, reason: str = "panic") -> None:
        """Emergency stop: every note off, accompaniment stopped, nothing scheduled."""
        with self._lock:
            self._cancel_pending()
            if self.sched:
                self.sched.cancel_all()
            self._click_token = None
            self.accomp_running = False
            self.chord = None
            self._log("panic", cause, reason=reason)
            self._all_notes_off(reason)

    def close(self, reason: str = "stop") -> None:
        """Every stop path ends here (normal stop, Ctrl-C, exceptions, end of replay). Idempotent."""
        with self._lock:
            if self.stopped:
                return
            if self.chord is not None or self._pending is not None:
                self._release("stop", None)  # deterministic log: constant reason (see engine_stop below)
            if self.accomp_running:
                self._stop_accompaniment(None, "stop")
            self.stopped = True
        if self.sched:
            self.sched.cancel_all()
            self.sched.stop()
        with self._lock:
            self._all_notes_off(reason)
            try:
                self.backend.close()
            except Exception as exc:  # noqa: BLE001
                self._timing({"kind": "backend_close_error", "error": repr(exc)})
            # the stop reason depends on how the run ended (window, Ctrl-C, end of replay), so it goes to the timing
            # log only; the deterministic log stays identical between a live run and its replay
            self._log("engine_stop", None)
            self._timing({"kind": "engine_stop", "reason": reason})
        if self.log:
            self.log.flush()

    def snapshot(self) -> dict:
        return {"chord": self.chord, "pending": self._pending[1] if self._pending else None,
                "accompaniment": "muted" if self.accomp_muted else ("running" if self.accomp_running else "off"),
                "failed": self.failed}

    # ------------------------------------------------------------------ chord logic (deterministic)
    def _commit(self, e: InteractionEvent, eid: int) -> None:
        with self._lock:
            chord = e.chord
            if chord == self.chord and not self.cfg.allow_same_chord_recommit:
                self._log("commit_ignored", (eid, e), chord=chord, reason="same_chord")
                return
            notes = self.cfg.notes(chord)
            a = self.cfg.accompaniment
            if a.quantize and self.accomp_running and e.produced_host_ns is not None:
                p = self.cfg.beat_ns
                k = -((self.accomp_t0 - e.produced_host_ns) // p)  # ceil((produced − t0) / p)
                onset = self.accomp_t0 + k * p
                old = self._pending[2] if self._pending else self.chord  # what is physically sounding
                self._cancel_pending()
                mev = self._log("scheduled_onset", (eid, e), chord=chord, notes=list(notes),
                                scheduled_host_ns=onset, previous_chord=old)
                self.chord = chord
                if self.sched:
                    token = self.sched.at(onset, lambda late, c=chord, m=mev: self._do_change(c, m, onset))
                    self._pending = (token, chord, old)
                else:
                    self._do_change(chord, mev, onset)
                return
            if self.chord is not None:
                self._log("midi_note_off", (eid, e), chord=self.chord, notes=list(self.cfg.notes(self.chord)),
                          reason="chord_change")
            self._cancel_pending()
            mev = self._log("midi_note_on", (eid, e), chord=chord, notes=list(notes))
            self.chord = chord
            self._do_change(chord, mev, None, produced=e.produced_host_ns)

    def _release(self, reason: str, cause) -> None:
        with self._lock:
            if self._pending is not None:
                self._log("scheduled_onset_cancelled", cause, chord=self._pending[1], reason=reason)
                self.chord = self._pending[2]  # the onset never happened: the previous chord is still on
                self._cancel_pending()
            if self.chord is None:
                if any(ch == self._ch for ch, _ in self._phys):  # a cancelled onset left the old chord on
                    self._do_release(None, reason)
                return
            mev = self._log("midi_note_off", cause, chord=self.chord, notes=list(self.cfg.notes(self.chord)),
                            reason=reason)
            self.chord = None
            self._do_release(mev, reason)

    def _cancel_pending(self) -> None:
        if self._pending is not None:
            if self.sched:
                self.sched.cancel(self._pending[0])
            self._pending = None

    # ------------------------------------------------------------------ accompaniment
    def _start_accompaniment(self, t0: int, cause, reason: str) -> None:
        with self._lock:
            self.accomp_running, self.accomp_t0, self.accomp_muted = True, int(t0), False
            self._auto_started = True
            a = self.cfg.accompaniment
            self._log("accompaniment_start", cause, reason=reason, scheduled_host_ns=int(t0), bpm=a.bpm,
                      beats_per_bar=a.beats_per_bar)
            if self.sched:
                now = self.clock()
                p = self.cfg.beat_ns
                k = max(0, -((self.accomp_t0 - now) // p))
                self._schedule_click(k)

    def _stop_accompaniment(self, cause, reason: str) -> None:
        with self._lock:
            self.accomp_running = False
            if self.sched and self._click_token is not None:
                self.sched.cancel(self._click_token)
            self._click_token = None
            self._log("accompaniment_stop", cause, reason=reason)

    def _schedule_click(self, k: int) -> None:
        due = self.accomp_t0 + k * self.cfg.beat_ns
        self._click_token = self.sched.at(due, lambda late, k=k, due=due: self._click(k, due))

    def _click(self, k: int, due: int) -> None:
        with self._lock:
            if not self.accomp_running or self.stopped:
                return
            a = self.cfg.accompaniment
            if not self.accomp_muted:
                note = a.accent_note if k % a.beats_per_bar == 0 else a.note
                self._send(NOTE_ON | self._click_ch, note, a.velocity, {"kind": "click_on", "beat": k, "due": due})
                off_due = due + int(a.duration_ms * 1e6)
                self.sched.at(off_due, lambda late, n=note, d=off_due: self._click_off(n, d))
            self._schedule_click(k + 1)

    def _click_off(self, note: int, due: int) -> None:
        with self._lock:
            if (self._click_ch, note) in self._phys:
                self._send(NOTE_OFF | self._click_ch, note, 0, {"kind": "click_off", "due": due})

    # ------------------------------------------------------------------ physical output
    def _do_change(self, chord: str, mev: Optional[int], due: Optional[int], produced: Optional[int] = None) -> None:
        with self._lock:
            if self._pending is not None and self._pending[1] == chord and due is not None:
                self._pending = None  # this is the scheduled onset executing
            for ch, n in sorted(self._phys):
                if ch == self._ch:
                    self._send(NOTE_OFF | ch, n, 0, {"kind": "note_off", "music_event_id": mev, "due": due})
            for n in self.cfg.notes(chord):
                self._send(NOTE_ON | self._ch, n, self.cfg.velocity,
                           {"kind": "note_on", "music_event_id": mev, "chord": chord, "due": due,
                            "produced_host_ns": produced})

    def _do_release(self, mev: Optional[int], reason: str) -> None:
        for ch, n in sorted(self._phys):
            if ch == self._ch:
                self._send(NOTE_OFF | ch, n, 0, {"kind": "note_off", "music_event_id": mev, "reason": reason})

    def _all_notes_off(self, reason: str) -> None:
        for ch, n in sorted(self._phys):
            self._send(NOTE_OFF | ch, n, 0, {"kind": "note_off", "reason": reason}, force=True)
        self._phys.clear()
        for ch in sorted({self._ch, self._click_ch}):
            for ctl in (CC_ALL_NOTES_OFF, CC_ALL_SOUND_OFF):
                self._send(CC | ch, ctl, 0, {"kind": "all_off", "reason": reason}, force=True)
        try:
            self.backend.reset()
        except Exception as exc:  # noqa: BLE001
            self._timing({"kind": "backend_reset_error", "error": repr(exc)})

    def _send(self, status: int, d1: int, d2: int, meta: dict, force: bool = False) -> None:
        """One MIDI message. After a backend failure only forced (silencing) messages are attempted."""
        if self.failed and not force:
            return
        t0 = self.clock() if self.clock else None
        try:
            self.backend.send(status, d1, d2)
        except Exception as exc:  # noqa: BLE001
            first = self.failed is None
            self.failed = self.failed or repr(exc)
            self._timing({**meta, "status": status, "data1": d1, "data2": d2, "error": repr(exc)})
            if first and not force:
                self._emergency("backend_error", repr(exc))
            return
        t1 = self.clock() if self.clock else None
        kind = status & 0xF0
        key = (status & 0x0F, d1)
        if kind == NOTE_ON and d2 > 0:
            self._phys.add(key)
        elif kind == NOTE_OFF or (kind == NOTE_ON and d2 == 0):
            self._phys.discard(key)
        if t0 is not None:
            rec = {**meta, "status": status, "data1": d1, "data2": d2, "send_begin_host_ns": t0,
                   "send_end_host_ns": t1}
            if meta.get("due") is not None:
                rec["lateness_ns"] = t0 - meta["due"]
            if meta.get("produced_host_ns") is not None:
                rec["estimated_software_latency_ns"] = t1 - meta["produced_host_ns"]
            self._timing(rec)

    def _emergency(self, reason: str, detail: str = "") -> None:
        with self._lock:
            self._cancel_pending()
            if self.sched:
                self.sched.cancel_all()
            self.accomp_running = False
            self.chord = None
            self._timing({"kind": "emergency", "reason": reason, "detail": detail})
            self._all_notes_off(reason)

    # ------------------------------------------------------------------ logging
    def _log(self, event_type: str, cause, **fields) -> int:
        mid = self._next_id
        self._next_id += 1
        rec = {"music_event_id": mid, "event_type": event_type}
        if cause is not None:
            eid, e = cause
            rec.update({"cause_event_id": eid, "cause_event_type": e.event_type, "seq": e.seq,
                        "produced_host_ns": e.produced_host_ns, "input_host_ns": e.input_host_ns})
        else:
            rec.update({"cause_event_id": None, "cause_event_type": None, "seq": None, "produced_host_ns": None,
                        "input_host_ns": None})
        rec.update(fields)
        self.events.append(rec)
        if len(self.events) > 2000:
            del self.events[:1000]
        if self.log:
            self.log.write_event(rec)
        return mid

    def _timing(self, rec: dict) -> None:
        if self.log:
            self.log.write_timing(rec)
