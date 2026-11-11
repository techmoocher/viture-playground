"""Builds the Phase 2 consumer stack for a pipeline: InstrumentConsumer (gesture FSM) → ChordEngine (MIDI).

Used by the CLI for synth, replay and (2C) play, so every entry point wires them the same way. The order is
fixed: the instrument consumer runs first and notifies the engine of each event synchronously.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from headmusic.config import load_config
from headmusic.instrument.consumer import InstrumentConsumer
from headmusic.instrument.fsm import GestureFSM
from headmusic.instrument.log import InteractionLog
from headmusic.instrument.regions import InstrumentConfig
from headmusic.music.backends import make_backend
from headmusic.music.config import MusicConfig
from headmusic.music.engine import ChordEngine
from headmusic.music.log import MusicLog


def with_phase2_sections(cfg: dict) -> dict:
    """A (possibly Phase 1) config snapshot with today's [instrument]/[music] defaults where missing."""
    defaults = None
    out = dict(cfg)
    for section in ("instrument", "music"):
        if not out.get(section):
            defaults = defaults or load_config()
            out[section] = defaults[section]
    return out


@dataclass
class Phase2Stack:
    instrument: InstrumentConsumer
    engine: ChordEngine
    instrument_log: Optional[InteractionLog]
    music_log: Optional[MusicLog]
    writer: object = None
    _closed: bool = False

    @property
    def consumers(self) -> list:
        return [self.instrument, self.engine]

    def close(self, reason: str = "stop") -> None:
        """Every stop path: FSM stopped, sound off, logs closed. Idempotent; never raises."""
        if self._closed:
            return
        self._closed = True
        try:
            self.instrument.finish()
        finally:
            try:
                self.engine.close(reason)
            finally:
                for log in (self.instrument_log, self.music_log):
                    if log:
                        log.close()
                if self.writer:
                    self.writer.update_meta(music_output=self.engine.backend.describe()
                                            if hasattr(self.engine.backend, "describe") else None,
                                            music_failed=self.engine.failed)


def build_stack(cfg: dict, gate, writer=None, clock: Optional[Callable[[], int]] = None,
                recorded_inputs: Optional[Iterable[dict]] = None, audio: str = "null", midi_device=None,
                realtime: bool = False, extra_listeners: Iterable = ()) -> Phase2Stack:
    icfg = InstrumentConfig.from_config(cfg)
    mcfg = MusicConfig.from_config(cfg, required_chords=[r.chord for r in icfg.regions])
    live_timing = clock is not None and recorded_inputs is None
    ilog = InteractionLog(writer.dir, write_timing=live_timing) if writer else None
    mlog = MusicLog(writer.dir, write_timing=clock is not None and realtime) if writer else None
    backend = make_backend(audio, mcfg.midi_device if midi_device is None else midi_device)
    engine = ChordEngine(mcfg, backend, mlog, clock=clock, realtime=realtime)
    consumer = InstrumentConsumer(GestureFSM(icfg), gate, ilog, clock=clock, recorded_inputs=recorded_inputs,
                                  listeners=[engine.on_interaction, *extra_listeners])
    if writer:
        writer.update_meta(instrument=icfg.to_meta(), music=mcfg.to_meta())
    return Phase2Stack(consumer, engine, ilog, mlog, writer)
