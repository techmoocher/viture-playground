"""Music configuration ([music] in defaults.toml). Provisional engineering defaults, recorded in session.json."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Iterable, Optional

ON_INTERRUPTION = ("continue", "mute")


class MusicConfigError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AccompanimentConfig:
    enabled: bool
    auto_start: bool
    bpm: float
    beats_per_bar: int
    channel: int
    note: int
    accent_note: int
    velocity: int
    duration_ms: float
    on_interruption: str
    quantize: bool


@dataclass(frozen=True, slots=True)
class MusicConfig:
    backend: str
    midi_device: object  # int index or str name substring
    channel: int
    velocity: int
    release_on_interruption: bool
    allow_same_chord_recommit: bool
    chords: tuple[tuple[str, tuple[int, ...]], ...]
    accompaniment: AccompanimentConfig
    program: Optional[int] = None  # General MIDI program (0-based) sent at start; None = synth default (piano)

    @classmethod
    def from_config(cls, cfg: dict, required_chords: Iterable[str] = ()) -> "MusicConfig":
        m = cfg.get("music")
        if not m:
            raise MusicConfigError("configuration has no [music] section")
        try:
            a = m["accompaniment"]
            acc = AccompanimentConfig(enabled=bool(a["enabled"]), auto_start=bool(a["auto_start"]),
                                      bpm=float(a["bpm"]), beats_per_bar=int(a["beats_per_bar"]),
                                      channel=int(a["channel"]), note=int(a["note"]),
                                      accent_note=int(a["accent_note"]), velocity=int(a["velocity"]),
                                      duration_ms=float(a["duration_ms"]), on_interruption=str(a["on_interruption"]),
                                      quantize=bool(a["quantize"]))
            out = cls(backend=str(m["backend"]), midi_device=m["midi_device"], channel=int(m["channel"]),
                      velocity=int(m["velocity"]), release_on_interruption=bool(m["release_on_interruption"]),
                      allow_same_chord_recommit=bool(m["allow_same_chord_recommit"]),
                      chords=tuple((str(k), tuple(int(n) for n in v)) for k, v in m["chords"].items()),
                      accompaniment=acc,
                      # absent in sessions recorded before MVP iteration 2: no program change was sent then
                      program=None if m.get("program") is None else int(m["program"]))
        except KeyError as e:
            raise MusicConfigError(f"[music] is missing {e}") from None
        out.validate(required_chords)
        return out

    def validate(self, required_chords: Iterable[str] = ()) -> None:
        def midi7(name, v):
            if not 0 <= v <= 127:
                raise MusicConfigError(f"{name} must be 0..127 (got {v})")
        if self.backend not in ("null", "winmm"):
            raise MusicConfigError(f"backend must be 'null' or 'winmm' (got {self.backend!r})")
        for name, ch in (("channel", self.channel), ("accompaniment.channel", self.accompaniment.channel)):
            if not 1 <= ch <= 16:
                raise MusicConfigError(f"{name} must be 1..16 (got {ch})")
        midi7("velocity", self.velocity)
        if self.program is not None:
            midi7("program", self.program)
        for chord, notes in self.chords:
            if not notes:
                raise MusicConfigError(f"chord {chord} has no notes")
            for n in notes:
                midi7(f"chord {chord} note", n)
        missing = set(required_chords) - {c for c, _ in self.chords}
        if missing:
            raise MusicConfigError(f"no voicing in [music.chords] for {sorted(missing)}")
        a = self.accompaniment
        if not (math.isfinite(a.bpm) and a.bpm > 0):
            raise MusicConfigError("accompaniment.bpm must be > 0")
        if a.beats_per_bar < 1:
            raise MusicConfigError("accompaniment.beats_per_bar must be >= 1")
        for name, v in (("note", a.note), ("accent_note", a.accent_note), ("velocity", a.velocity)):
            midi7(f"accompaniment.{name}", v)
        if not (math.isfinite(a.duration_ms) and 0 < a.duration_ms < 60_000 / a.bpm):
            raise MusicConfigError("accompaniment.duration_ms must be > 0 and shorter than one beat")
        if a.on_interruption not in ON_INTERRUPTION:
            raise MusicConfigError(f"accompaniment.on_interruption must be one of {ON_INTERRUPTION}")

    def notes(self, chord: str) -> tuple[int, ...]:
        return dict(self.chords)[chord]

    @property
    def beat_ns(self) -> int:
        return int(round(60e9 / self.accompaniment.bpm))

    def to_meta(self) -> dict:
        d = asdict(self)
        d["chords"] = {c: list(n) for c, n in self.chords}
        d["provisional"] = "engineering defaults; not validated musical, timing or ergonomic choices"
        return d


def midi_device_arg(value: Optional[str]) -> object:
    if value is None:
        return None
    return int(value) if value.lstrip("-").isdigit() else value
