"""Play window (Phase 2C, tkinter): HUD for the four-chord instrument. Reads snapshots at ~30 Hz.

It never decides anything. Every action is a pipeline command, so it is logged and replayed:
    N      capture neutral              Esc    EMERGENCY STOP (panic: silence, instrument disabled)
    E      enable the instrument        A      accompaniment start / stop (if enabled in config)
    R      release the sounding chord (intentional release, MVP iteration 2)
If the pipeline does not process the emergency stop within `fallback_ms`, the window silences the engine
directly as a last resort (logged; such a run is no longer replay-identical).
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

from headmusic.viewer.app import BAD, BG, GRID, MUTED, OK, TEXT, fit_geometry
from headmusic.viewer.hud import hud_model

LEVEL = {"ok": OK, "warn": "#fbbc04", "bad": BAD, "muted": MUTED}
ROLE_FILL = {"": "#1f2630", "target": "#26415c", "dwell": "#2f6b9a", "sounding": "#2e7d4f"}


class PlayApp:
    def __init__(self, pipeline, stack, title: str, on_close: Callable[[], None], refresh_ms: int = 33,
                 fallback_ms: int = 300, live_commands: bool = True) -> None:
        self.p, self.stack = pipeline, stack
        self.icfg = stack.instrument.fsm.cfg
        self.acc_enabled = stack.engine.cfg.accompaniment.enabled
        self.on_close, self.refresh_ms, self.fallback_ms = on_close, refresh_ms, fallback_ms
        self.live_commands = live_commands  # replay: commands come from the recording, not the keyboard
        self.root = tk.Tk()
        self.root.title(title)
        self.root.configure(bg=BG)
        self.root.geometry(fit_geometry(self.root.winfo_screenwidth(), self.root.winfo_screenheight()))
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        bar = tk.Frame(self.root, bg=BG)  # controls at the top (lesson from G0 R6a)
        bar.pack(fill="x", padx=12, pady=(10, 4))
        btn = dict(bg="#2a3038", fg=TEXT, activebackground="#3c4450", activeforeground=TEXT, relief="flat",
                   padx=10, pady=4)
        self.stop_btn = tk.Button(bar, text="EMERGENCY STOP  [Esc]", command=self.emergency_stop, bg="#b3261e",
                                  fg="white", activebackground="#d93025", activeforeground="white", relief="flat",
                                  padx=14, pady=6, font=("Segoe UI", 11, "bold"))
        self.stop_btn.pack(side="left")
        state = "normal" if live_commands else "disabled"
        tk.Button(bar, text="Capture neutral  [N]", command=self.capture, state=state, **btn).pack(side="left", padx=6)
        tk.Button(bar, text="Release chord  [R]", command=self.release, state=state, **btn).pack(side="left")
        tk.Button(bar, text="Enable  [E]", command=self.enable, state=state, **btn).pack(side="left", padx=6)
        tk.Button(bar, text="Accompaniment  [A]", command=self.toggle_accompaniment,
                  state=state if self.acc_enabled else "disabled", **btn).pack(side="left", padx=6)
        self.feedback = tk.Label(self.root, text="", bg=BG, fg="#fbbc04", font=("Segoe UI", 11, "bold"), anchor="w")
        self.feedback.pack(fill="x", padx=12)
        self.tracking = tk.Label(self.root, text="", bg=BG, fg=BAD, font=("Segoe UI", 12, "bold"), anchor="w")
        self.tracking.pack(fill="x", padx=12)
        self.canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=12, pady=(4, 8))
        self.root.bind("<Escape>", lambda e: self.emergency_stop())
        if live_commands:
            self.root.bind("<Key-n>", lambda e: self.capture())
            self.root.bind("<Key-e>", lambda e: self.enable())
            self.root.bind("<Key-r>", lambda e: self.release())
            self.root.bind("<Key-a>", lambda e: self.toggle_accompaniment())
        self._acc_on = False
        self.model = None

    # ------------------------------------------------------------------ actions (all are pipeline commands)
    def _say(self, text: str) -> None:
        self.feedback.config(text=text)

    def emergency_stop(self) -> None:
        if self.live_commands:
            self.p.submit_command("panic")
        self._say("EMERGENCY STOP sent: everything silenced, instrument disabled (E to enable)")
        self.root.after(self.fallback_ms, self._stop_fallback)

    def _stop_fallback(self) -> None:
        eng = self.stack.engine
        snap = eng.snapshot()
        if not self.live_commands or snap["chord"] is not None or snap["pending"] is not None:
            eng.panic(reason="ui_direct")  # the pipeline did not act in time (or replay): silence directly
            self._say("EMERGENCY STOP applied directly by the window")

    def capture(self) -> None:
        cfg = self.p.cfg["neutral"]
        self.p.submit_command("capture_neutral", window_s=float(cfg["window_s"]), tau_stab_deg=float(cfg["tau_stab_deg"]))
        self._say("neutral capture requested: hold still at your neutral pose")

    def release(self) -> None:
        self.p.submit_command("release_chord")
        self._say("release requested")

    def enable(self) -> None:
        self.p.submit_command("instrument_enable")
        self._say("instrument enabled: return to neutral to arm")

    def toggle_accompaniment(self) -> None:
        if not self.acc_enabled:
            return
        self._acc_on = not self._acc_on
        self.p.submit_command("accompaniment_start" if self._acc_on else "accompaniment_stop")
        self._say("accompaniment " + ("start" if self._acc_on else "stop") + " requested")

    def _close(self) -> None:
        self.on_close()
        self.root.destroy()

    def run(self) -> None:
        self.root.after(self.refresh_ms, self._tick)
        self.root.mainloop()

    # ------------------------------------------------------------------ drawing
    def _tick(self) -> None:
        try:
            self.draw()
        finally:
            self.root.after(self.refresh_ms, self._tick)

    def build_model(self):
        _, st, gate = self.p.snapshot(0.1)
        commits = [e["chord"] for e in list(self.stack.instrument.events) if e["event_type"] == "raw_commit"]
        return hud_model(self.icfg, self.stack.instrument.snapshot, self.stack.engine.snapshot(), gate.usable,
                         gate.reasons, st["connected"], commits, self.acc_enabled)

    def draw(self) -> None:
        m = self.model = self.build_model()
        self.tracking.config(text=m.tracking_text, fg=LEVEL[m.tracking_level])
        c = self.canvas
        c.delete("all")
        W, H = max(c.winfo_width(), 400), max(c.winfo_height(), 300)
        pad = 40
        x = lambda f: pad + f * (W - 2 * pad)  # noqa: E731
        # big status
        c.create_text(pad, 16, anchor="nw", text=m.sounding_text, fill=OK if "SOUNDING" in m.sounding_text else MUTED,
                      font=("Segoe UI", 28, "bold"))
        c.create_text(pad, 66, anchor="nw", text=m.state_text, fill=LEVEL[m.state_level], font=("Segoe UI", 18, "bold"))
        c.create_text(pad, 100, anchor="nw", text=m.hint, fill=TEXT, font=("Segoe UI", 12))
        # yaw track
        y0, y1 = 150, min(H - 120, 300)
        c.create_rectangle(x(0), y0, x(1), y1, outline=GRID)
        c.create_rectangle(x(m.neutral_x0), y0, x(m.neutral_x1), y1, fill="#2a2f36", outline="#5f6873")
        c.create_text(x((m.neutral_x0 + m.neutral_x1) / 2), y1 + 12, text="neutral", fill=MUTED, font=("Segoe UI", 9))
        for b in m.regions:
            c.create_rectangle(x(b.x0), y0, x(b.x1), y1, fill=ROLE_FILL[b.role], outline="#5f6873")
            c.create_text(x((b.x0 + b.x1) / 2), (y0 + y1) / 2, text=b.chord, fill=TEXT, font=("Segoe UI", 22, "bold"))
        for fx, label in m.axis_ticks:
            c.create_line(x(fx), y1, x(fx), y1 + 4, fill=MUTED)
            c.create_text(x(fx), y1 + 26, text=label, fill=MUTED, font=("Segoe UI", 8))
        c.create_text(x(0), y0 - 10, anchor="w", text="← turn left", fill=MUTED, font=("Segoe UI", 9))
        c.create_text(x(1), y0 - 10, anchor="e", text="turn right →", fill=MUTED, font=("Segoe UI", 9))
        if m.cursor_x is not None:
            cx = x(m.cursor_x)
            c.create_line(cx, y0 - 4, cx, y1 + 4, fill="#fbbc04" if m.cursor_eligible else MUTED, width=4)
        # dwell progress
        py = y1 + 44
        c.create_rectangle(x(0), py, x(1), py + 14, outline=GRID)
        if m.progress is not None:
            c.create_rectangle(x(0), py, x(m.progress), py + 14, fill="#2f6b9a", outline="")
        c.create_text(x(0), py + 18, anchor="nw", text="dwell progress", fill=MUTED, font=("Segoe UI", 9))
        # status lines
        lines = [m.yaw_text, m.notes_text, m.mode_text + "   ·   " + m.accompaniment_text, m.output_text,
                 "recent commits: " + (" ".join(m.recent_commits) or "—"),
                 "regions, dwell and all thresholds are provisional engineering defaults, not ergonomic limits"]
        c.create_text(pad, H - 8, anchor="sw", text="\n".join(lines), fill=MUTED, font=("Segoe UI", 10))
