"""Interaction events: the deterministic output of the gesture FSM (and, from 2B, of the chord engine).

Event types use the protocol §10.3 names where they exist (aim_enter, dwell_start, dwell_complete,
raw_commit, return_neutral) plus: aim_exit, dwell_cancel, gesture_reset, state_change, inactive_reason,
instrument_enabled, instrument_disabled, panic, neutral_capture_end, sample_skipped, and (MVP iteration 2)
dwell_restart, engaged_enter, chord_release.

Active and candidate chord (transitions = "direct"): the ACTIVE chord is the last confirmed chord, which keeps
sounding (latch); the CANDIDATE is the chord of the region being confirmed (dwell_armed). The candidate events
dwell_start, dwell_restart, dwell_cancel, dwell_complete and raw_commit carry `chord` = the candidate and
`active_chord` = the chord sounding at that moment (on raw_commit: the chord it replaces). `active_chord` is
written only when set, so records of the protocol machine and of earlier sessions are unchanged.

Timestamps (docs/phase2-proposal.md §6.2). For an event decided on a pose sample:
- device_ts_raw, host_rx_monotonic_ns: that sample's device timestamp and host arrival time;
- produced_host_ns: its estimated production time on the host timebase (device_ts + o_min, TrackingGate),
  comparable across connections. The default "raw commit time" for analysis (research question Q13).
For an event caused by another input (event, command, live tick): input_host_ns is that input's host time.
All fields are deterministic: replaying the same session reproduces them exactly. Processing and send
times are not here; they go to interaction_timing.jsonl.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# FSM states (protocol §6 names, plus inactive and unarmed)
INACTIVE = "inactive"
UNARMED = "unarmed"
NEUTRAL = "neutral"
AIMING = "aiming"
DWELL_ARMED = "dwell_armed"
RETURN_TO_NEUTRAL = "return_to_neutral"  # transitions = "via_neutral" only
ENGAGED = "engaged"  # transitions = "direct": in the region of the selected chord (never re-triggers)
STATES = (INACTIVE, UNARMED, NEUTRAL, AIMING, DWELL_ARMED, RETURN_TO_NEUTRAL, ENGAGED)


@dataclass(frozen=True, slots=True)
class InteractionEvent:
    event_type: str
    state: str  # FSM state after the event
    prev_state: Optional[str] = None
    seq: Optional[int] = None
    connection_id: Optional[int] = None
    neutral_calibration_id: Optional[int] = None
    device_ts_raw: Optional[int] = None
    host_rx_monotonic_ns: Optional[int] = None
    produced_host_ns: Optional[int] = None
    input_host_ns: Optional[int] = None
    chord: Optional[str] = None
    reason: Optional[str] = None
    dwell_elapsed_ns: Optional[int] = None
    yaw_rel_deg: Optional[float] = None
    active_chord: Optional[str] = None  # direct mode, candidate events only (see above)

    def record(self, event_id: int, mapping_version: str) -> dict:
        r = {"event_id": event_id, "event_type": self.event_type, "state": self.state,
                "prev_state": self.prev_state, "seq": self.seq, "connection_id": self.connection_id,
                "neutral_calibration_id": self.neutral_calibration_id, "device_ts_raw": self.device_ts_raw,
                "host_rx_monotonic_ns": self.host_rx_monotonic_ns, "produced_host_ns": self.produced_host_ns,
                "input_host_ns": self.input_host_ns, "chord": self.chord, "reason": self.reason,
                "dwell_elapsed_ns": self.dwell_elapsed_ns, "yaw_rel_deg": self.yaw_rel_deg,
                "mapping_version": mapping_version}
        if self.active_chord is not None:
            r["active_chord"] = self.active_chord
        return r
