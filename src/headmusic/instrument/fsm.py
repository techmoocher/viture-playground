"""GestureFSM: dwell-to-commit chord selection from yaw regions (docs/phase2-proposal.md §3–§4).

transitions = "via_neutral" (the protocol §6 machine):
    inactive ─► unarmed ─(neutral zone, rearm hold)─► neutral ─(leave)─► aiming ─(enter region i,
    cooldown over)─► dwell_armed(i) ─(dwell_ms of device time)─► [commit] ─► return_to_neutral ─► neutral

transitions = "direct" (MVP iteration 2, docs/mvp-iteration-2.md): no return to neutral between chords.
    neutral/aiming ─(enter region i ≠ selected)─► dwell_armed(i) ─(stable dwell)─► [commit] ─► engaged(i)
    engaged(i) ─(leave)─► aiming/neutral; entering the selected chord's region gives engaged, never a re-trigger.
    After an interruption or a release, the region under the head is blocked (unarmed) until it is left.

playback = "latch": the selected chord stays selected until another commit, a release or an interruption.
playback = "hold": leaving the selected chord's region releases it (chord_release, reason left_region).

Pure and deterministic: no clock is read. Dwell, cooldown and re-arm hold are device-time differences
within one connection. Inputs are processed samples with the TrackingGate status at their arrival, plus
connection events, commands, neutral-capture results and logged live interruptions.

Safety rule: any interruption (gate unusable, new connection, new neutral, neutral capture, sample gap,
late processing, disable, panic) cancels the gesture. Returning needs a deliberate visit to the neutral zone,
and a freshness watermark keeps data produced before the interruption from arming anything.
"""
from __future__ import annotations

from typing import Optional

from headmusic.instrument.events import (AIMING, DWELL_ARMED, ENGAGED, INACTIVE, NEUTRAL, RETURN_TO_NEUTRAL,
                                         UNARMED, InteractionEvent)
from headmusic.instrument.regions import InstrumentConfig, yaw_elevation_deg
from headmusic.orientation.flags import INVALIDATING, TS_DUPLICATE
from headmusic.tracking.gate import GateStatus
from headmusic.types import ProcessedSample

GAP_FLAG = "gap_before"


class GestureFSM:
    def __init__(self, cfg: InstrumentConfig) -> None:
        self.cfg = cfg
        self._dwell_ns = int(round(cfg.dwell_ms * 1e6))
        self._cooldown_ns = int(round(cfg.cooldown_ms * 1e6))
        self._rearm_ns = int(round(cfg.rearm_hold_ms * 1e6))
        self._rest_ns = int(round(cfg.neutral_rest_release_ms * 1e6))
        self.direct = cfg.transitions == "direct"
        self.enabled = cfg.start_enabled
        self.suspended = False  # a neutral capture is in progress
        self.state = INACTIVE
        self.inactive_reason: Optional[str] = None if self.enabled else "disabled"
        self._key: Optional[tuple] = None  # (connection_id, neutral_calibration_id) of the current frame
        self._region: Optional[int] = None
        self._dwell_start_d: Optional[int] = None
        self._neutral_since_d: Optional[int] = None
        self._last_commit: Optional[tuple[int, int]] = None  # (connection_id, device_ts)
        self._watermark: Optional[int] = None  # host ns; data produced at or before it never arms
        self.last_commit_chord: Optional[str] = None
        self._selected: Optional[int] = None  # index of the selected (sounding, per the FSM) chord
        self._blocked: Optional[int] = None  # direct: region that may not be selected until it is left
        self._block_pending = True  # direct: block the region under the head at the next fresh sample
        self._dwell_anchor: Optional[float] = None  # yaw_rel where the current dwell (re)started
        self._rest_since_d: Optional[int] = None
        self.progress: Optional[float] = None
        self.yaw_rel_deg: Optional[float] = None
        self.elevation_deg: Optional[float] = None

    # ------------------------------------------------------------------ properties
    @property
    def region_chord(self) -> Optional[str]:
        return self.cfg.regions[self._region].chord if self._region is not None else None

    @property
    def selected_chord(self) -> Optional[str]:
        return self.cfg.regions[self._selected].chord if self._selected is not None else None

    def snapshot(self) -> dict:
        return {"state": self.state, "region": self.region_chord, "progress": self.progress,
                "selected": self.selected_chord, "transitions": self.cfg.transitions, "playback": self.cfg.playback,
                "yaw_rel_deg": self.yaw_rel_deg, "elevation_deg": self.elevation_deg,
                "inactive_reason": self.inactive_reason if self.state == INACTIVE else None,
                "enabled": self.enabled, "suspended": self.suspended, "last_commit_chord": self.last_commit_chord}

    # ------------------------------------------------------------------ inputs
    def on_sample(self, ps: ProcessedSample, gs: GateStatus, produced_ns: Optional[int],
                  late: bool = False) -> list[InteractionEvent]:
        ev: list[InteractionEvent] = []
        yaw = elev = None
        if ps.quat_rel is not None:
            yaw, elev = yaw_elevation_deg(ps.quat_rel)
        self.yaw_rel_deg, self.elevation_deg = yaw, elev
        ctx = {"seq": ps.seq, "connection_id": ps.connection_id, "neutral_calibration_id": ps.neutral_calibration_id,
               "device_ts_raw": ps.device_ts_raw, "host_rx_monotonic_ns": ps.host_rx_monotonic_ns,
               "produced_host_ns": produced_ns, "yaw_rel_deg": yaw}
        wm = produced_ns if produced_ns is not None else ps.host_rx_monotonic_ns

        if not self.enabled:
            self._inactive("disabled", ctx, ev, wm)
            return ev
        if self.suspended:
            self._inactive("neutral_capture", ctx, ev, wm)
            return ev
        if late:
            self._inactive("late_processing", ctx, ev, wm)
            return ev
        if (self.cfg.duplicate_timestamp == "skip" and self.state != INACTIVE
                and INVALIDATING.intersection(ps.flags) == {TS_DUPLICATE}
                and tuple(gs.reasons) == ("last_sample_invalid",)
                and (ps.connection_id, ps.neutral_calibration_id) == self._key):
            # Research question Q12, option "skip": a sample whose ONLY fault is a duplicate device timestamp
            # (G0: distinct values ~1 ms after the previous sample) is ignored. It neither advances nor resets
            # the gesture; every other fault, staleness and frame change stays strict.
            ev.append(self._ev("sample_skipped", ctx, reason=TS_DUPLICATE))
            return ev
        if not gs.usable:
            self._inactive("|".join(gs.reasons), ctx, ev, wm)
            return ev

        key = (ps.connection_id, ps.neutral_calibration_id)
        if self._key is not None and key != self._key:
            reason = "new_connection" if key[0] != self._key[0] else "new_neutral"
            self._key = key
            self._reset(reason, UNARMED, ctx, ev, wm)
            return ev  # this sample is not used
        self._key = key
        if self.cfg.reset_on_gap_before and GAP_FLAG in ps.flags:
            self._reset("gap", UNARMED, ctx, ev, wm)
            return ev
        if self._watermark is not None and produced_ns is not None and produced_ns <= self._watermark:
            return ev  # produced before the last interruption: never used
        if self.state == INACTIVE:
            self._set_state(UNARMED, ctx, ev, reason="tracking_usable")
        self._advance(ps.device_ts_raw, yaw, elev, ctx, ev)
        return ev

    def interrupt(self, reason: str, host_ns: int) -> list[InteractionEvent]:
        """A live interruption between samples (logged and replayed), e.g. reason 'stale_tick'."""
        ev: list[InteractionEvent] = []
        self._inactive(reason, {"input_host_ns": host_ns}, ev, host_ns)
        return ev

    def on_connection_event(self, kind: str, host_ns: int) -> list[InteractionEvent]:
        ev: list[InteractionEvent] = []
        reason = "disconnect" if kind == "device_disconnected" else "new_connection"
        self._inactive(reason, {"input_host_ns": host_ns}, ev, host_ns)
        return ev

    def on_command(self, kind: str, host_ns: int) -> list[InteractionEvent]:
        ev: list[InteractionEvent] = []
        ctx = {"input_host_ns": host_ns}
        if kind == "capture_neutral":
            self.suspended = True
            self._inactive("neutral_capture", ctx, ev, host_ns)
        elif kind == "instrument_disable":
            self.enabled = False
            ev.append(self._ev("instrument_disabled", ctx))
            self._inactive("disabled", ctx, ev, host_ns)
        elif kind == "instrument_enable":
            if not self.enabled:
                self.enabled = True
                ev.append(self._ev("instrument_enabled", ctx))
        elif kind == "release_chord":
            self._release_selected("intentional", ctx, ev, block_if_inside=True)
        elif kind == "panic":
            self.enabled = False
            ev.append(self._ev("panic", ctx))
            self._inactive("panic", ctx, ev, host_ns)
        return ev

    def on_neutral_capture_result(self, record: dict) -> list[InteractionEvent]:
        if "capture_in_progress" in (record.get("reasons") or []):
            return []  # a second request was refused; the first capture is still running
        if not self.suspended:
            return []
        self.suspended = False
        reason = "accepted" if record.get("accepted") else "rejected:" + "|".join(record.get("reasons") or [])
        return [self._ev("neutral_capture_end", {}, reason=reason)]

    # ------------------------------------------------------------------ internals
    def _ev(self, event_type: str, ctx: dict, **kw) -> InteractionEvent:
        return InteractionEvent(event_type=event_type, state=self.state, **ctx, **kw)

    def _set_state(self, new: str, ctx: dict, ev: list, reason: Optional[str] = None) -> None:
        if new != self.state:
            prev, self.state = self.state, new
            ev.append(InteractionEvent("state_change", state=new, prev_state=prev, reason=reason, **ctx))

    def _clear_gesture(self) -> None:
        self._region = None
        self._dwell_start_d = None
        self._neutral_since_d = None
        self._dwell_anchor = None
        self._rest_since_d = None
        self.progress = None

    def _release_selected(self, reason: str, ctx: dict, ev: list, block_if_inside: bool = False) -> None:
        """Release the selected chord on purpose (not a safety interruption): chord_release → engine note-off."""
        if self._selected is None:
            return
        chord = self.selected_chord
        inside = self.state == ENGAGED
        self._selected = None
        self._rest_since_d = None
        ev.append(self._ev("chord_release", ctx, chord=chord, reason=reason))
        if inside and block_if_inside and self.direct:
            self._blocked, self._region = self._region, None  # no re-trigger while staying in its region
            self._set_state(UNARMED, ctx, ev, reason="released_in_region")

    def _bump_watermark(self, wm: Optional[int]) -> None:
        if wm is not None and (self._watermark is None or wm > self._watermark):
            self._watermark = wm

    def _reset(self, reason: str, to_state: str, ctx: dict, ev: list, wm: Optional[int]) -> None:
        prev = self.state
        if prev == DWELL_ARMED:
            ev.append(self._ev("dwell_cancel", ctx, chord=self.region_chord, reason=reason))
        if prev not in (INACTIVE, UNARMED) or self._selected is not None:
            # a gesture reset makes the chord engine release whatever sounds (safety interruption)
            ev.append(self._ev("gesture_reset", ctx, chord=self.region_chord, reason=reason))
        self._clear_gesture()
        self._selected = None  # the engine releases on gesture_reset / inactive
        self._blocked = None
        self._block_pending = True
        self._bump_watermark(wm)
        self._set_state(to_state, ctx, ev, reason=reason)

    def _inactive(self, reason: str, ctx: dict, ev: list, wm: Optional[int]) -> None:
        if self.state != INACTIVE:
            self._reset(reason, INACTIVE, ctx, ev, wm)
            self.inactive_reason = reason
            return
        self._bump_watermark(wm)
        if reason != self.inactive_reason:
            self.inactive_reason = reason
            ev.append(self._ev("inactive_reason", ctx, reason=reason))

    def _cooldown_over(self, conn: int, d: int) -> bool:
        lc = self._last_commit
        return lc is None or lc[0] != conn or d - lc[1] >= self._cooldown_ns

    def _advance(self, d: int, yaw: Optional[float], elev: Optional[float], ctx: dict, ev: list) -> None:
        cfg, h = self.cfg, self.cfg.hysteresis_deg
        eligible = yaw is not None and abs(elev) <= cfg.max_elevation_deg
        if self._selected is not None:
            stays_selected = eligible and cfg.regions[self._selected].stays(yaw, h)
            if cfg.playback == "hold" and not stays_selected:
                self._release_selected("left_region", ctx, ev)
            elif cfg.playback == "latch" and self._rest_ns > 0:
                if eligible and abs(yaw) <= cfg.neutral_yaw_deg:  # the neutral zone proper, not a key's edge
                    if self._rest_since_d is None:
                        self._rest_since_d = d
                    elif d - self._rest_since_d >= self._rest_ns:
                        self._release_selected("neutral_rest", ctx, ev)
                else:
                    self._rest_since_d = None
        if self.direct:
            self._advance_direct(d, yaw, eligible, ctx, ev)
        else:
            self._advance_via_neutral(d, yaw, elev, ctx, ev)

    def _advance_via_neutral(self, d: int, yaw: Optional[float], elev: Optional[float], ctx: dict,
                             ev: list) -> None:
        cfg, h = self.cfg, self.cfg.hysteresis_deg
        eligible = yaw is not None and abs(elev) <= cfg.max_elevation_deg
        in_n_enter = eligible and abs(yaw) <= cfg.neutral_yaw_deg
        in_n_stay = eligible and abs(yaw) <= cfg.neutral_yaw_deg + h

        if self.state in (UNARMED, RETURN_TO_NEUTRAL):
            self.progress = None
            if in_n_enter or (self._neutral_since_d is not None and in_n_stay):
                if self._neutral_since_d is None:
                    self._neutral_since_d = d
                if d - self._neutral_since_d >= self._rearm_ns:
                    self._neutral_since_d = None
                    self._set_state(NEUTRAL, ctx, ev, reason="rearmed")
                    ev.append(self._ev("return_neutral", ctx))
            else:
                self._neutral_since_d = None
            return

        if self.state == NEUTRAL:
            if in_n_stay:
                return
            self._set_state(AIMING, ctx, ev, reason="left_neutral")

        if self.state == DWELL_ARMED:
            r = cfg.regions[self._region]
            elapsed = d - self._dwell_start_d
            if eligible and r.stays(yaw, h):
                self.progress = min(1.0, elapsed / self._dwell_ns)
                if elapsed >= self._dwell_ns:
                    ev.append(self._ev("dwell_complete", ctx, chord=r.chord, dwell_elapsed_ns=elapsed))
                    ev.append(self._ev("raw_commit", ctx, chord=r.chord, dwell_elapsed_ns=elapsed))
                    self._last_commit = (ctx["connection_id"], d)
                    self.last_commit_chord = r.chord
                    self._selected = self._region
                    self._clear_gesture()
                    self._set_state(RETURN_TO_NEUTRAL, ctx, ev, reason="committed")
                return
            ev.append(self._ev("dwell_cancel", ctx, chord=r.chord, reason="left_region", dwell_elapsed_ns=elapsed))
            ev.append(self._ev("aim_exit", ctx, chord=r.chord))
            self._clear_gesture()
            self._set_state(AIMING, ctx, ev, reason="left_region")

        # aiming
        self.progress = None
        if self._region is not None and not (eligible and cfg.regions[self._region].stays(yaw, h)):
            ev.append(self._ev("aim_exit", ctx, chord=self.region_chord))
            self._region = None
        if self._region is None and eligible:
            i = cfg.region_entered(yaw)
            if i is not None:
                self._region = i
                ev.append(self._ev("aim_enter", ctx, chord=self.region_chord))
        if self._region is None:
            if in_n_enter:
                self._set_state(NEUTRAL, ctx, ev, reason="entered_neutral")
            return
        if self._cooldown_over(ctx["connection_id"], d):
            self._dwell_start_d = d
            self.progress = 0.0
            self._set_state(DWELL_ARMED, ctx, ev, reason="dwell_start")
            ev.append(self._ev("dwell_start", ctx, chord=self.region_chord, dwell_elapsed_ns=0))

    # ------------------------------------------------------------------ transitions = "direct"
    def _advance_direct(self, d: int, yaw: Optional[float], eligible: bool, ctx: dict, ev: list) -> None:
        cfg, h = self.cfg, self.cfg.hysteresis_deg
        regions = cfg.regions

        def stays(i: Optional[int]) -> bool:
            return i is not None and eligible and regions[i].stays(yaw, h)

        if self._block_pending:  # first fresh, usable sample after a reset: block the region under the head
            self._block_pending = False
            self._blocked = next((i for i in range(len(regions)) if stays(i)), None)
        if self._blocked is not None:
            if stays(self._blocked):
                self._region, self.progress = None, None
                self._set_state(UNARMED, ctx, ev, reason="blocked_region")
                return
            self._blocked = None  # left the blocked region: re-armed (no neutral needed)

        if self.state == ENGAGED:
            if stays(self._region):
                return
            ev.append(self._ev("aim_exit", ctx, chord=self.region_chord))
            self._region = None
            self._set_state(AIMING, ctx, ev, reason="left_region")

        if self.state == DWELL_ARMED:
            r = regions[self._region]
            elapsed = d - self._dwell_start_d
            if stays(self._region):
                stab = cfg.dwell_stability_deg
                if stab > 0 and abs(yaw - self._dwell_anchor) > stab:
                    self._dwell_start_d, self._dwell_anchor, self.progress = d, yaw, 0.0
                    ev.append(self._ev("dwell_restart", ctx, chord=r.chord, reason="unstable", dwell_elapsed_ns=elapsed))
                    return
                self.progress = min(1.0, elapsed / self._dwell_ns) if self._dwell_ns else 1.0
                if elapsed >= self._dwell_ns:
                    self._commit_direct(d, ctx, ev, elapsed)
                return
            ev.append(self._ev("dwell_cancel", ctx, chord=r.chord, reason="left_region", dwell_elapsed_ns=elapsed))
            ev.append(self._ev("aim_exit", ctx, chord=r.chord))
            self._region, self._dwell_start_d, self._dwell_anchor, self.progress = None, None, None, None
            self._set_state(AIMING, ctx, ev, reason="left_region")

        # neutral, aiming or unarmed (just unblocked)
        self.progress = None
        if self._region is not None and not stays(self._region):  # was waiting for the cooldown in a region
            ev.append(self._ev("aim_exit", ctx, chord=self.region_chord))
            self._region = None
        if self._region is None and eligible:
            i = cfg.region_entered(yaw)
            if i is not None:
                self._region = i
                ev.append(self._ev("aim_enter", ctx, chord=self.region_chord))
        if self._region is None:
            in_n_enter = eligible and abs(yaw) <= cfg.neutral_yaw_deg
            in_n_stay = eligible and abs(yaw) <= cfg.neutral_yaw_deg + h
            if self.state == NEUTRAL and in_n_stay or in_n_enter:
                if self.state != NEUTRAL:
                    self._set_state(NEUTRAL, ctx, ev, reason="rest")
                    ev.append(self._ev("return_neutral", ctx))  # protocol §10.3 event; here a rest, not a gate
            else:
                self._set_state(AIMING, ctx, ev, reason="between_regions")
            return
        if self._region == self._selected:
            if self.state != ENGAGED:
                self._set_state(ENGAGED, ctx, ev, reason="selected_region")
                ev.append(self._ev("engaged_enter", ctx, chord=self.region_chord, reason="no_retrigger"))
            return
        if self._cooldown_over(ctx["connection_id"], d):
            self._dwell_start_d, self._dwell_anchor, self.progress = d, yaw, 0.0
            self._set_state(DWELL_ARMED, ctx, ev, reason="dwell_start")
            ev.append(self._ev("dwell_start", ctx, chord=self.region_chord, dwell_elapsed_ns=0))
            if self._dwell_ns == 0:  # immediate keys (MVP iteration 2): sound on entry
                self._commit_direct(d, ctx, ev, 0)
        else:
            self._set_state(AIMING, ctx, ev, reason="cooldown")

    def _commit_direct(self, d: int, ctx: dict, ev: list, elapsed: int) -> None:
        r = self.cfg.regions[self._region]
        ev.append(self._ev("dwell_complete", ctx, chord=r.chord, dwell_elapsed_ns=elapsed))
        ev.append(self._ev("raw_commit", ctx, chord=r.chord, dwell_elapsed_ns=elapsed))
        self._last_commit = (ctx["connection_id"], d)
        self.last_commit_chord = r.chord
        self._selected = self._region
        self._dwell_start_d, self._dwell_anchor, self.progress = None, None, None
        self._set_state(ENGAGED, ctx, ev, reason="committed")
