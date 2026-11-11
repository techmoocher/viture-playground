"""InstrumentConsumer: plugs the GestureFSM into the Phase 1 pipeline (docs/phase2-proposal.md §1–§2).

Runs in the pipeline thread, so it sees samples, events and commands in recorded order. For each sample it
evaluates the TrackingGate at the sample's arrival time (deterministic), then feeds the FSM.

Two live-only inputs depend on wall-clock timing and are therefore logged with their stream position and
re-injected on replay:
- stale_tick:      the gate became unusable between samples (device pause, PC sleep);
- late_processing: the pipeline handled a sample more than T_stale after its arrival.
Position = (after_seq, k): after the sample with that seq and k further consumer-visible items
(device_connected / device_disconnected events and commands), which ReplaySource reproduces.

Live mode: recorded_inputs=None, clock given. Replay mode: recorded_inputs = the session's logged inputs;
live checks are off, and the logged inputs are applied at their positions.
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional

from headmusic.instrument.events import INACTIVE, InteractionEvent
from headmusic.instrument.fsm import GestureFSM
from headmusic.instrument.log import InteractionLog
from headmusic.tracking.gate import TrackingGate
from headmusic.types import Command, Event, ProcessedSample

POSITION_EVENTS = ("device_connected", "device_disconnected")


class InstrumentConsumer:
    def __init__(self, fsm: GestureFSM, gate: TrackingGate, log: Optional[InteractionLog] = None,
                 clock: Optional[Callable[[], int]] = None, recorded_inputs: Optional[Iterable[dict]] = None,
                 listeners: Iterable[Callable[[InteractionEvent, int], None]] = ()) -> None:
        self.fsm = fsm
        self.gate = gate
        self.log = log
        self.clock = clock
        self.replay = recorded_inputs is not None
        self._pending = sorted((dict(r) for r in (recorded_inputs or [])),
                               key=lambda r: (r["after_seq"], r.get("k", 0)))
        self._late = {r["seq"]: r for r in self._pending if r["kind"] == "late_processing"}
        self._pending = [r for r in self._pending if r["kind"] != "late_processing"]
        self.listeners = list(listeners)
        self.t_stale_ns = gate.t_stale_ns
        self._last_seq = -1
        self._last_host = 0  # host arrival of the last sample: the deterministic "end of stream" time
        self._k = 0
        self._mapping_version = fsm.cfg.mapping_version()
        self._next_id = 1
        self.events: list[dict] = []  # kept in memory for tests and the HUD's recent history (bounded)
        self.max_events_kept = 2000
        self.snapshot = fsm.snapshot()

    # ------------------------------------------------------------------ pipeline consumer API
    def on_sample(self, ps: ProcessedSample) -> None:
        if self.replay:
            self._apply_pending(before_seq=ps.seq)
        self._last_seq, self._k = ps.seq, 0
        self._last_host = ps.host_rx_monotonic_ns
        late = False
        if self.replay:
            if ps.seq in self._late:
                late = True
                self._log_input(self._late[ps.seq])
        elif self.clock is not None:
            now = self.clock()
            if now - ps.host_rx_monotonic_ns > self.t_stale_ns:
                late = True
                self._log_input({"kind": "late_processing", "after_seq": ps.seq, "k": 0, "seq": ps.seq,
                                 "host_ns": now, "late_ms": round((now - ps.host_rx_monotonic_ns) / 1e6, 3)})
        gs = self.gate.status(ps.host_rx_monotonic_ns)
        produced = ps.host_rx_monotonic_ns - gs.age_ns if gs.age_ns is not None else None
        self._emit(self.fsm.on_sample(ps, gs, produced, late=late))
        self._after_item()

    def on_event(self, e: Event) -> None:
        if e.kind not in POSITION_EVENTS:
            return
        self._emit(self.fsm.on_connection_event(e.kind, e.host_monotonic_ns))
        self._k += 1
        self._after_item()

    def on_command(self, c: Command) -> None:
        self._emit(self.fsm.on_command(c.kind, c.host_monotonic_ns))
        self._k += 1
        self._after_item()

    def on_calibration(self, record: dict) -> None:
        self._emit(self.fsm.on_neutral_capture_result(record))

    def on_tick(self, now: int) -> None:
        if self.replay or self.fsm.state == INACTIVE:
            return
        gs = self.gate.status(now)
        if "stale" not in gs.reasons:
            return  # ticks catch time passing without data; sample-level faults are handled on the sample itself
        self._log_input({"kind": "stale_tick", "after_seq": self._last_seq, "k": self._k, "host_ns": now,
                         "reasons": list(gs.reasons)})
        self._emit(self.fsm.interrupt("stale_tick", now))

    def on_failure(self, exc: BaseException) -> None:
        """A consumer failed (pipeline guard): nothing may be selected any more."""
        self.fsm.enabled = False
        if self.log:
            self.log.flush()

    def finish(self) -> None:
        """End of stream: apply any remaining logged inputs (replay), then stop the instrument."""
        if self.replay:
            self._apply_pending(before_seq=None)
        if self.fsm.state != INACTIVE:
            self._emit(self.fsm.interrupt("stop", self._last_host))
        if self.log:
            self.log.flush()

    # ------------------------------------------------------------------ internals
    def _after_item(self) -> None:
        if self.replay:
            while self._pending and (self._pending[0]["after_seq"], self._pending[0].get("k", 0)) == \
                    (self._last_seq, self._k):
                self._apply(self._pending.pop(0))

    def _apply_pending(self, before_seq: Optional[int]) -> None:
        while self._pending and (before_seq is None or self._pending[0]["after_seq"] < before_seq):
            self._apply(self._pending.pop(0))

    def _apply(self, r: dict) -> None:
        if r["kind"] == "stale_tick":
            self._log_input(r)
            self._emit(self.fsm.interrupt("stale_tick", int(r["host_ns"])))

    def _log_input(self, r: dict) -> None:
        if self.log:
            self.log.write_input(r)

    def _emit(self, events: list[InteractionEvent]) -> None:
        if events:
            decision = self.clock() if (self.clock and not self.replay) else None
            mv = self._mapping_version
            for e in events:
                eid = self._next_id
                self._next_id += 1
                rec = e.record(eid, mv)
                if self.log:
                    self.log.write_event(rec)
                    if decision is not None:
                        self.log.write_timing({"event_id": eid, "event_type": e.event_type,
                                               "decision_host_ns": decision})
                self.events.append(rec)
                for fn in self.listeners:
                    fn(e, eid)
            if len(self.events) > self.max_events_kept:
                del self.events[: len(self.events) - self.max_events_kept]
        self.snapshot = self.fsm.snapshot()
