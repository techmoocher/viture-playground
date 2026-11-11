"""HUD model for the play window (Phase 2C): everything the HUD shows, computed from snapshots.

Pure and testable without a window. It decides nothing: the gesture FSM and the chord engine decide, and this
module only describes their published state (fsm.snapshot(), engine.snapshot(), the TrackingGate status).

Horizontal axis: yaw_rel with + (turn left) drawn on the LEFT, so the cursor moves the way the head turns.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from headmusic.instrument.events import AIMING, DWELL_ARMED, INACTIVE, NEUTRAL, RETURN_TO_NEUTRAL, UNARMED
from headmusic.instrument.regions import InstrumentConfig

OK, WARN, BAD, MUTED = "ok", "warn", "bad", "muted"


@dataclass(frozen=True)
class RegionBox:
    chord: str
    x0: float  # fractions of the axis width, left to right
    x1: float
    role: str  # "" | "target" (cursor inside) | "dwell" | "sounding"


@dataclass(frozen=True)
class HudModel:
    tracking_text: str
    tracking_level: str
    state_text: str
    state_level: str
    hint: str
    regions: tuple[RegionBox, ...]
    neutral_x0: float
    neutral_x1: float
    cursor_x: Optional[float]  # None: no neutral-relative orientation
    cursor_eligible: bool
    yaw_text: str
    progress: Optional[float]
    sounding_text: str
    accompaniment_text: str
    output_text: str
    output_level: str
    recent_commits: tuple[str, ...] = field(default_factory=tuple)
    axis_ticks: tuple[tuple[float, str], ...] = field(default_factory=tuple)


def axis_half_range(icfg: InstrumentConfig) -> float:
    ext = max(max(abs(r.yaw_min_deg), abs(r.yaw_max_deg)) for r in icfg.regions)
    return float(min(180.0, 10.0 * round((ext + 10.0) / 10.0)))


def yaw_to_x(yaw: float, half: float) -> float:
    return min(1.0, max(0.0, (half - yaw) / (2.0 * half)))


INACTIVE_HINTS = {
    "disabled": "instrument disabled: press E to enable",
    "panic": "EMERGENCY STOP: press E to enable again",
    "neutral_capture": "capturing neutral: hold still",
    "no_neutral": "no neutral reference: press N to capture one",
    "disconnected": "glasses disconnected: waiting for the device",
    "disconnect": "glasses disconnected: waiting for the device",
    "new_connection": "new connection: press N to capture a neutral",
    "no_valid_sample": "waiting for valid samples",
    "stale": "tracking stale (no recent data)",
    "stale_tick": "tracking stale (no recent data)",
    "last_sample_invalid": "invalid sample",
    "late_processing": "data processed late",
    "stop": "stopped",
}


def _hint_for(reason: Optional[str]) -> str:
    if not reason:
        return "waiting for tracking"
    for part in reason.split("|"):
        if part in INACTIVE_HINTS:
            return INACTIVE_HINTS[part]
    return reason


def hud_model(icfg: InstrumentConfig, fsm: dict, engine: dict, gate_usable: bool, gate_reasons: Sequence[str],
              connected: bool, recent_commits: Sequence[str] = (), accompaniment_enabled: bool = False) -> HudModel:
    half = axis_half_range(icfg)
    state = fsm.get("state")
    region = fsm.get("region")
    sounding = engine.get("chord")

    if not connected:
        tracking, tlevel = "NOT CONNECTED", BAD
    elif gate_usable:
        tracking, tlevel = "TRACKING USABLE", OK
    else:
        tracking, tlevel = "TRACKING NOT USABLE: " + ", ".join(gate_reasons), BAD

    progress = None
    if state == INACTIVE:
        reason = fsm.get("inactive_reason")
        st, lvl, hint = "INACTIVE", BAD if reason == "panic" else MUTED, _hint_for(reason)
    elif state == UNARMED:
        st, lvl, hint = "NOT ARMED", WARN, "return to the neutral zone to arm"
    elif state == NEUTRAL:
        st, lvl, hint = "NEUTRAL: armed", OK, "turn toward a chord and hold to play it"
    elif state == AIMING:
        st, lvl = "AIMING", OK
        hint = f"in {region}: waiting for the cooldown" if region else "turn into a chord region"
    elif state == DWELL_ARMED:
        progress = fsm.get("progress") or 0.0
        st, lvl, hint = f"DWELL {region}  {progress * 100:3.0f}%", OK, f"hold to play {region}"
    elif state == RETURN_TO_NEUTRAL:
        st, lvl, hint = "PLAYED: return to neutral", OK, "return to the neutral zone before the next chord"
    else:
        st, lvl, hint = str(state), MUTED, ""

    boxes = []
    for r in icfg.regions:
        role = ""
        if r.chord == sounding:
            role = "sounding"
        if r.chord == region:
            role = "dwell" if state == DWELL_ARMED else ("target" if role == "" else role)
        boxes.append(RegionBox(r.chord, yaw_to_x(r.yaw_max_deg, half), yaw_to_x(r.yaw_min_deg, half), role))

    yaw, elev = fsm.get("yaw_rel_deg"), fsm.get("elevation_deg")
    cursor = yaw_to_x(yaw, half) if yaw is not None else None
    eligible = yaw is not None and elev is not None and abs(elev) <= icfg.max_elevation_deg
    if yaw is None:
        yaw_text = "yaw_rel —"
    else:
        side = "left" if yaw > 0 else "right" if yaw < 0 else ""
        yaw_text = f"yaw_rel {yaw:+6.1f}° {side}".rstrip()
        if not eligible:
            yaw_text += f"  (outside ±{icfg.max_elevation_deg:g}° of the neutral plane: ignored)"

    pend = engine.get("pending")
    sounding_text = f"SOUNDING: {sounding}" if sounding else "silent"
    if pend:
        sounding_text += f"  (next beat: {pend})"
    acc = engine.get("accompaniment") or "off"
    acc_text = f"accompaniment: {acc}" if accompaniment_enabled else "accompaniment: disabled in config"
    failed = engine.get("failed")
    out_text, out_level = (f"OUTPUT FAILED: {failed}", BAD) if failed else ("output ok", MUTED)
    n = icfg.neutral_yaw_deg
    ticks = tuple((yaw_to_x(v, half), f"{v:+.0f}°") for v in (half, half / 2, 0.0, -half / 2, -half))
    return HudModel(tracking, tlevel, st, lvl, hint, tuple(boxes), yaw_to_x(n, half), yaw_to_x(-n, half), cursor,
                    eligible, yaw_text, progress, sounding_text, acc_text, out_text, out_level,
                    tuple(recent_commits[-8:]), ticks)
