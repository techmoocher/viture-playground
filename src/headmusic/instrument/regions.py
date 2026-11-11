"""Yaw target regions relative to the neutral reference, and instrument configuration.

Region coordinate (docs/phase2-proposal.md §3.1), computed from the quaternion:
    f        = rotate(q_rel, (1, 0, 0))          forward axis of the glasses in the neutral head frame
    yaw_rel  = atan2(f_y, f_x)                    heading in the neutral horizontal plane; + = turn left
    elev     = asin(f_z)                          + = nose up, − = nose down
yaw_rel is identical, by construction, to the display yaw of the documented Z-Y'-X'' convention
(conventions.md), so the HUD shows the value that is used. Pitch and roll are not used.

All angles and times here are PROVISIONAL ENGINEERING DEFAULTS, configurable and recorded in session.json.
None is a validated ergonomic, comfort or safety limit.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import Optional, Sequence

from headmusic.orientation.quaternion import rotate


class ConfigError(ValueError):
    pass


def yaw_elevation_deg(q_rel: Sequence[float]) -> tuple[float, float]:
    fx, fy, fz = rotate(q_rel, (1.0, 0.0, 0.0))
    return math.degrees(math.atan2(fy, fx)), math.degrees(math.asin(max(-1.0, min(1.0, fz))))


@dataclass(frozen=True, slots=True)
class YawRegion:
    chord: str
    yaw_min_deg: float
    yaw_max_deg: float

    def enters(self, yaw: float) -> bool:
        return self.yaw_min_deg <= yaw <= self.yaw_max_deg

    def stays(self, yaw: float, h: float) -> bool:
        return self.yaw_min_deg - h <= yaw <= self.yaw_max_deg + h


@dataclass(frozen=True, slots=True)
class InstrumentConfig:
    regions: tuple[YawRegion, ...]
    neutral_yaw_deg: float
    hysteresis_deg: float
    dwell_ms: float
    cooldown_ms: float
    rearm_hold_ms: float
    max_elevation_deg: float
    reset_on_gap_before: bool
    start_enabled: bool
    duplicate_timestamp: str = "reset"  # "reset" (strict) | "skip" (research question Q12)
    # MVP iteration 2 (docs/mvp-iteration-2.md). Defaults here = the earlier behaviour, used for sessions that
    # were recorded before these keys existed; defaults.toml sets the iteration-2 MVP values.
    transitions: str = "via_neutral"  # "via_neutral" (protocol §6 machine) | "direct"
    playback: str = "latch"  # "latch" | "hold"
    dwell_stability_deg: float = 0.0  # dwell restarts if yaw_rel moves more than this from the dwell start; 0 = off
    neutral_rest_release_ms: float = 0.0  # latch: resting in neutral this long releases the chord; 0 = off

    # ------------------------------------------------------------------ construction
    @classmethod
    def from_config(cls, cfg: dict) -> "InstrumentConfig":
        ic = cfg.get("instrument")
        if not ic:
            raise ConfigError("configuration has no [instrument] section")
        try:
            regions = tuple(YawRegion(str(r["chord"]), float(r["yaw_min_deg"]), float(r["yaw_max_deg"]))
                            for r in ic["yaw_regions"])
            out = cls(regions=regions, neutral_yaw_deg=float(ic["neutral_yaw_deg"]),
                      hysteresis_deg=float(ic["hysteresis_deg"]), dwell_ms=float(ic["dwell_ms"]),
                      cooldown_ms=float(ic["cooldown_ms"]), rearm_hold_ms=float(ic["rearm_hold_ms"]),
                      max_elevation_deg=float(ic["max_elevation_deg"]),
                      reset_on_gap_before=bool(ic["reset_on_gap_before"]), start_enabled=bool(ic["start_enabled"]),
                      # absent in sessions recorded before 2026-11-11 evening: those ran with "reset"
                      duplicate_timestamp=str(ic.get("duplicate_timestamp", "reset")),
                      transitions=str(ic.get("transitions", "via_neutral")), playback=str(ic.get("playback", "latch")),
                      dwell_stability_deg=float(ic.get("dwell_stability_deg", 0.0)),
                      neutral_rest_release_ms=float(ic.get("neutral_rest_release_ms", 0.0)))
        except KeyError as e:
            raise ConfigError(f"[instrument] is missing {e}") from None
        out.validate()
        return out

    def validate(self) -> None:
        h, n = self.hysteresis_deg, self.neutral_yaw_deg
        if not self.regions:
            raise ConfigError("at least one yaw region is required")
        for name, v in (("hysteresis_deg", h), ("neutral_yaw_deg", n), ("dwell_ms", self.dwell_ms),
                        ("cooldown_ms", self.cooldown_ms), ("rearm_hold_ms", self.rearm_hold_ms)):
            if not math.isfinite(v) or v < 0:
                raise ConfigError(f"{name} must be a finite value >= 0 (got {v})")
        if self.duplicate_timestamp not in ("reset", "skip"):
            raise ConfigError(f"duplicate_timestamp must be 'reset' or 'skip' (got {self.duplicate_timestamp!r})")
        if self.transitions not in ("via_neutral", "direct"):
            raise ConfigError(f"transitions must be 'via_neutral' or 'direct' (got {self.transitions!r})")
        if self.playback not in ("latch", "hold"):
            raise ConfigError(f"playback must be 'latch' or 'hold' (got {self.playback!r})")
        for name, v in (("dwell_stability_deg", self.dwell_stability_deg),
                        ("neutral_rest_release_ms", self.neutral_rest_release_ms)):
            if not math.isfinite(v) or v < 0:
                raise ConfigError(f"{name} must be a finite value >= 0 (got {v})")
        if self.dwell_ms <= 0 and self.transitions == "via_neutral":
            raise ConfigError("dwell_ms must be > 0 for the protocol machine (transitions = via_neutral)")
        if not 0 < self.max_elevation_deg <= 90:
            raise ConfigError("max_elevation_deg must be in (0, 90]")
        chords = [r.chord for r in self.regions]
        if len(set(chords)) != len(chords) or not all(chords):
            raise ConfigError(f"each chord needs exactly one region with a name (got {chords})")
        for r in self.regions:
            if not (-180.0 < r.yaw_min_deg < r.yaw_max_deg <= 180.0):
                raise ConfigError(f"region {r.chord}: need -180 < yaw_min_deg < yaw_max_deg <= 180")
            if r.yaw_min_deg < n and r.yaw_max_deg > -n:
                raise ConfigError(f"region {r.chord} [{r.yaw_min_deg}, {r.yaw_max_deg}] overlaps the neutral zone "
                                  f"(±{n}); it may start at its edge")
        ordered = sorted(self.regions, key=lambda r: r.yaw_min_deg)
        for a, b in zip(ordered, ordered[1:]):
            if b.yaw_min_deg < a.yaw_max_deg:
                raise ConfigError(f"regions {a.chord} and {b.chord} overlap ({a.yaw_max_deg} > {b.yaw_min_deg}); "
                                  f"they may touch (contiguous keys)")

    # ------------------------------------------------------------------ queries
    def region_entered(self, yaw: float) -> Optional[int]:
        for i, r in enumerate(self.regions):
            if r.enters(yaw):
                return i
        return None

    def to_meta(self) -> dict:
        d = asdict(self)
        d["regions"] = [asdict(r) for r in self.regions]
        d["mapping_version"] = self.mapping_version()
        d["provisional"] = "engineering defaults; not validated ergonomic, comfort or safety limits"
        return d

    # Parameters added after sessions were first recorded, with the value that reproduces the earlier behaviour.
    # They enter the hash only when they differ from it, so earlier sessions keep their mapping_version.
    _LATER_PARAMS = {"duplicate_timestamp": "reset", "transitions": "via_neutral", "playback": "latch",
                     "dwell_stability_deg": 0.0, "neutral_rest_release_ms": 0.0}

    def mapping_version(self) -> str:
        d = asdict(self)
        d["regions"] = [asdict(r) for r in self.regions]
        for k, implicit in self._LATER_PARAMS.items():
            if d.get(k) == implicit:
                del d[k]
        return hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]
