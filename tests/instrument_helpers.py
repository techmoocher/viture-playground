"""Helpers for driving the GestureFSM directly with exact, synthetic inputs."""
from __future__ import annotations

from headmusic.config import load_config
from headmusic.instrument.fsm import GestureFSM
from headmusic.instrument.regions import InstrumentConfig, YawRegion
from headmusic.orientation.euler import quat_from_zyx
from headmusic.tracking.gate import GateStatus
from headmusic.types import ProcessedSample

DT_NS = 5_000_000  # sample period used by the driver (exact, so dwell arithmetic is easy to check)
H0 = 1_000_000_000_000
D0 = 5_000_000_000_000
YAW = {"C": 31.0, "G": 13.0, "Am": -13.0, "F": -31.0, "neutral": 0.0, "between": 20.0}


def make_cfg(**overrides) -> InstrumentConfig:
    cfg = load_config()
    ic = dict(cfg["instrument"])
    regions = overrides.pop("regions", None)
    ic.update(overrides)
    cfg["instrument"] = ic
    out = InstrumentConfig.from_config(cfg)
    if regions is not None:
        import dataclasses
        out = dataclasses.replace(out, regions=tuple(YawRegion(*r) for r in regions))
        out.validate()
    return out


class Driver:
    """Feeds samples at DT_NS; records every input for the invariant checker."""

    def __init__(self, **overrides) -> None:
        self.cfg = make_cfg(**overrides)
        self.fsm = GestureFSM(self.cfg)
        self.seq = 0
        self.d = D0
        self.h = H0
        self.conn = 1
        self.nid = 1
        self.events = []
        self.inputs = []  # ("sample", dict) | ("interrupt", reason)

    # ---------------------------------------------------------------- samples
    def sample(self, yaw: float, pitch: float = 0.0, usable: bool = True, reasons=(), flags=(), late=False,
               produced_offset_ns: int = 0, dt_ns: int = DT_NS, rel: bool = True):
        self.d += dt_ns
        self.h += dt_ns
        q = quat_from_zyx(yaw, pitch, 0.0) if rel else None
        ps = ProcessedSample(seq=self.seq, connection_id=self.conn, host_rx_monotonic_ns=self.h,
                             device_ts_raw=self.d, dt_device_ns=dt_ns, dt_host_ns=dt_ns, quat=q, quat_rel=q,
                             euler_display=None, valid=usable or "last_sample_invalid" not in reasons,
                             flags=tuple(sorted(flags)), neutral_calibration_id=self.nid if rel else None)
        gs = GateStatus(usable=usable, reasons=tuple(reasons) if not usable else (), age_ns=0)
        produced = self.h + produced_offset_ns
        ev = self.fsm.on_sample(ps, gs, produced, late=late)
        self.inputs.append(("sample", {"seq": self.seq, "d": self.d, "yaw": yaw, "pitch": pitch, "usable": usable,
                                       "flags": tuple(flags), "late": late, "conn": self.conn, "nid": self.nid,
                                       "n_events_before": len(self.events)}))
        self.events.extend(ev)
        self.seq += 1
        return ev

    def hold(self, yaw: float, ms: float, **kw):
        out = []
        for _ in range(int(round(ms * 1e6 / DT_NS))):
            out += self.sample(yaw, **kw)
        return out

    def move(self, yaw_from: float, yaw_to: float, ms: float):
        n = max(1, int(round(ms * 1e6 / DT_NS)))
        out = []
        for i in range(1, n + 1):
            out += self.sample(yaw_from + (yaw_to - yaw_from) * i / n)
        return out

    # ---------------------------------------------------------------- other inputs
    def _record(self, kind, ev):
        self.inputs.append((kind, {"n_events_before": len(self.events)}))
        self.events.extend(ev)
        return ev

    def interrupt(self, reason="stale_tick", host_ns=None):
        return self._record("interrupt", self.fsm.interrupt(reason, self.h if host_ns is None else host_ns))

    def connection(self, kind):
        return self._record("interrupt", self.fsm.on_connection_event(kind, self.h))

    def command(self, kind):
        return self._record("interrupt" if kind != "instrument_enable" else "command",
                            self.fsm.on_command(kind, self.h))

    def capture_result(self, accepted=True, reasons=()):
        return self._record("command", self.fsm.on_neutral_capture_result(
            {"accepted": accepted, "reasons": list(reasons)}))

    # ---------------------------------------------------------------- queries
    def commits(self, events=None):
        return [e.chord for e in (self.events if events is None else events) if e.event_type == "raw_commit"]

    def types(self, events=None):
        return [e.event_type for e in (self.events if events is None else events)]

    def arm(self):
        """Neutral rest until armed."""
        self.hold(0.0, 50)
        assert self.fsm.state == "neutral", self.fsm.state


def check_invariant(drv: Driver) -> int:
    """Every raw_commit follows an unbroken, usable, in-region run of >= dwell on one connection and one
    neutral, with no interruption inside it, which started after a visit to the neutral state.
    Returns the number of commits checked."""
    cfg, ev = drv.cfg, drv.events
    dwell_ns = int(round(cfg.dwell_ms * 1e6))
    samples = [d for k, d in drv.inputs if k == "sample"]
    by_seq = {s["seq"]: s for s in samples}
    interrupts_at = [d["n_events_before"] for k, d in drv.inputs if k == "interrupt"]
    n = 0
    for idx, e in enumerate(ev):
        if e.event_type != "raw_commit":
            continue
        n += 1
        start_idx = max(i for i in range(idx) if ev[i].event_type == "dwell_start")
        s0, s1 = ev[start_idx].seq, e.seq
        region = next(r for r in cfg.regions if r.chord == e.chord)
        assert ev[start_idx].chord == e.chord
        assert not any(ev[i].event_type in ("dwell_cancel", "gesture_reset") for i in range(start_idx, idx))
        assert not any(start_idx < p <= idx for p in interrupts_at), "interruption inside the dwell"
        run = [by_seq[q] for q in range(s0, s1 + 1)]
        assert all(r["usable"] and not r["late"] for r in run)
        assert all("gap_before" not in r["flags"] for r in run[1:]) or not cfg.reset_on_gap_before
        assert len({(r["conn"], r["nid"]) for r in run}) == 1
        assert all(region.stays(r["yaw"], cfg.hysteresis_deg) for r in run)
        assert run[-1]["d"] - run[0]["d"] >= dwell_ns
        # a neutral visit after the previous commit / reset, before the dwell started
        prev = [i for i in range(start_idx) if ev[i].event_type in ("raw_commit", "gesture_reset")
                or (ev[i].event_type == "state_change" and ev[i].state in ("inactive", "unarmed"))]
        lo = prev[-1] if prev else -1
        assert any(ev[i].event_type == "state_change" and ev[i].state == "neutral" for i in range(lo + 1, start_idx))
    return n
