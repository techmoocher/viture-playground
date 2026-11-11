"""Guided bench scripts for the viewer: one key (Space) per action, labels filled in automatically.

Added after both R6a attempts on 2026-11-11 produced no segment marks: typing labels and clicking Start/End
while handling the glasses was error-prone, and the N shortcut could fire while typing a label.

Each segment step works like this:
1. The step is shown. The operator presses Space and takes their hands off.
2. The segment starts at once, and the viewer counts down `hold_s` seconds of "hold still". That stillness falls
   inside the segment, where the segment report takes its start window.
3. The operator does the movement, lets go, and presses Space.
4. Another `hold_s` countdown runs, inside the segment, and then the segment is closed.

A neutral step requests a capture and waits for its result: it advances when the capture is accepted, and
otherwise offers a retry. The machine is pure: time is passed in, and it returns the commands for the
pipeline. No threshold is applied here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

Command = tuple[str, dict]


@dataclass(frozen=True)
class Step:
    kind: str  # "neutral" | "segment"
    label: str
    setup: str  # what to arrange before pressing Space
    move: str = ""  # segment only: the movement after the first hold


class GuidedScript:
    def __init__(self, name: str, steps: list[Step], hold_s: float = 2.0) -> None:
        if not steps:
            raise ValueError("a script needs at least one step")
        self.name, self.steps, self.hold_s = name, steps, float(hold_s)
        self.i = 0
        self.phase = "ready"  # ready | hold_start | moving | hold_end | capturing | done
        self.t_phase = 0.0
        self.last_attempt_seen = 0
        self._attempt_at_request = 0
        self.note = ""  # e.g. the outcome of the previous neutral attempt

    # ------------------------------------------------------------------ inputs
    @property
    def step(self) -> Optional[Step]:
        return self.steps[self.i] if self.i < len(self.steps) else None

    def press(self, now: float) -> list[Command]:
        """Space pressed. Presses during a countdown or a capture are ignored."""
        s = self.step
        if s is None:
            return []
        if self.phase == "ready" and s.kind == "segment":
            self.phase, self.t_phase, self.note = "hold_start", now, ""
            return [("segment_start", {"label": s.label, "script": self.name, "step": self.i + 1})]
        if self.phase == "ready" and s.kind == "neutral":
            self.phase, self.t_phase = "capturing", now
            self._attempt_at_request = self.last_attempt_seen
            return [("capture_neutral", {})]
        if self.phase == "moving":
            self.phase, self.t_phase = "hold_end", now
        return []

    def tick(self, now: float) -> list[Command]:
        """Advance countdowns; returns the commands that are due."""
        if self.phase == "hold_start" and now - self.t_phase >= self.hold_s:
            self.phase = "moving"
        elif self.phase == "hold_end" and now - self.t_phase >= self.hold_s:
            self._advance()
            return [("segment_end", {})]
        return []

    def observe_neutral(self, record: Optional[dict]) -> None:
        """Pass the pipeline's latest neutral-capture record (or None) on every refresh."""
        if not record:
            return
        attempt = int(record.get("attempt") or 0)
        new = attempt > self.last_attempt_seen
        self.last_attempt_seen = max(self.last_attempt_seen, attempt)
        if self.phase == "capturing" and new and attempt > self._attempt_at_request:
            if record.get("accepted"):
                self.note = f"Neutral accepted (attempt {attempt})."
                self._advance()
            else:
                self.note = f"Neutral REJECTED ({', '.join(record.get('reasons') or [])}). Press Space to retry."
                self.phase = "ready"

    def _advance(self) -> None:
        self.i += 1
        self.phase = "ready" if self.i < len(self.steps) else "done"

    # ------------------------------------------------------------------ display
    def text(self, now: float) -> str:
        n = len(self.steps)
        s = self.step
        if s is None or self.phase == "done":
            return f"{self.name}: all {n} steps done. Close this window to finish the recording."
        head = f"{self.name} · step {self.i + 1} of {n} · {s.label}"
        if self.phase == "ready":
            body = (f"{s.setup}\nThen press SPACE and take your hands off." if s.kind == "segment"
                    else f"{s.setup}\nPress SPACE and keep your hands off for about 3 s.")
            return "\n".join(x for x in (self.note, head, body) if x)
        if self.phase in ("hold_start", "hold_end"):
            left = max(0.0, self.hold_s - (now - self.t_phase))
            return f"{head}\nHOLD STILL, hands off… {left:.1f} s"
        if self.phase == "moving":
            return f"{head}\nNOW: {s.move}\nThen let go of the glasses and press SPACE."
        return f"{head}\nCapturing neutral… hold still"


# ---------------------------------------------------------------------- bench scripts (docs/bench-checklist.md)
_FLAT_A = "Glasses upright, flat on the table on line A (lenses facing along the line)."

SCRIPTS: dict[str, list[Step]] = {
    "r6a": [
        Step("neutral", "neutral", _FLAT_A),
        Step("segment", "yaw_left_90", _FLAT_A,
             "turn the glasses 90° LEFT (counter-clockwise seen from above), flat on the table, from line A to line B."),
        Step("segment", "yaw_right_90", "Glasses flat on line B (where step 2 ended).",
             "turn them 90° RIGHT (clockwise seen from above), flat on the table, back to line A."),
        Step("segment", "pitch_down", _FLAT_A,
             "set them on the wedge NOSE-DOWN: lenses lower than the arm tips."),
        Step("segment", "roll_right_down", "Put the glasses back flat on line A.",
             "set them on the wedge with the WEARER'S RIGHT SIDE LOWER."),
    ],
    "r6b": [
        Step("segment", "u1_pitched_about_vertical",
             "Glasses resting NOSE-DOWN on the wedge (lenses lower), the wedge flat on the table.",
             "turn the WHOLE WEDGE about 90° LEFT on the table, keeping the wedge flat on the table and the glasses "
             "fixed on it."),
        Step("segment", "u1_rolled_about_vertical",
             "Glasses resting on the wedge with the WEARER'S RIGHT SIDE LOWER, the wedge flat on the table.",
             "turn the WHOLE WEDGE about 90° LEFT on the table, keeping the wedge flat on the table and the glasses "
             "fixed on it."),
    ],
    "r6c": [
        Step("neutral", "neutral_1", _FLAT_A),
        Step("segment", "recenter_turn_45", _FLAT_A,
             "turn the glasses about 45° LEFT, flat on the table."),
        Step("neutral", "neutral_2", "Leave the glasses where step 2 ended (turned about 45°)."),
    ],
}


SCRIPTS["r7"] = [  # step 9: unplug / replug
    Step("neutral", "neutral_before", _FLAT_A),
    Step("segment", "unplug_replug", "Glasses flat on the table, untouched. Keep them untouched for the whole step.",
         "unplug the USB cable at the PC end, wait about 5 s, plug it back in, and wait until the status line shows "
         "CONNECTED again (a few seconds)."),
    Step("neutral", "neutral_after", "Glasses still untouched where they were."),
]
SCRIPTS["r8"] = [  # step 9b: what causes the ~300 / ~600 ms device-side pauses while the glasses are handled?
    Step("segment", "cable_move", "Glasses flat on line A, untouched.",
         "move the USB cable gently near the PC end for about 10 s, without touching the glasses or the table near them."),
    Step("segment", "hand_near", "Glasses flat on line A, untouched.",
         "hold your hand about 5 cm in front of the lenses, then near the inner side of the nose bridge, for about 10 s "
         "in total, without touching anything."),
    Step("segment", "lift_and_back", "Glasses flat on line A.",
         "lift the glasses off the table by the frame, hold them in the air for about 5 s (do not put them on), and put "
         "them back flat on line A."),
]


def make_script(name: str, hold_s: float = 2.0) -> GuidedScript:
    return GuidedScript(name, SCRIPTS[name], hold_s)
