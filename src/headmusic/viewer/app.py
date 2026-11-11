"""Live yaw/pitch/roll viewer (tkinter). Reads pipeline snapshots at ~30 Hz; never runs in a callback.

Shows neutral-relative Z-Y'-X'' angles (display only). Before a neutral is accepted it shows the
same angles of the absolute tracking-frame quaternion, labelled as such.
"""
from __future__ import annotations

import time
import tkinter as tk
from typing import Callable, Optional

from headmusic.orientation.euler import direction_words, zyx_from_quat
from headmusic.orientation.quaternion import up_axis_tilt_deg

COLORS = {"yaw": "#1f77b4", "pitch": "#2ca02c", "roll": "#d62728"}
BG, GRID, TEXT, MUTED, OK, BAD = "#111418", "#2a3038", "#e8eaed", "#9aa0a6", "#34a853", "#ea4335"


def tilt_text(tilt_deg) -> str:
    """Display-only description of the glasses' tilt from upright (no threshold is applied anywhere)."""
    if tilt_deg is None:
        return "tilt from upright: —"
    text = f"tilt from upright: {tilt_deg:5.1f}°  (0° upright, 180° upside down; display only)"
    if tilt_deg > 90.0:  # geometric fact, not a limit: the up axis points below the horizontal plane
        text += "  ⚠ up axis points below horizontal: upside down?"
    return text


def fit_geometry(screen_w: int, screen_h: int, want_w: int = 1000, want_h: int = 700) -> str:
    """Window size and position that fit the screen, leaving room for the title bar and the taskbar.

    The viewer once opened at 1000x700 on a 1280x800 screen with a 752 px working area; the control bar at the
    bottom was off-screen, so no neutral capture or segment could be marked (R6a, 2026-11-11)."""
    w = max(640, min(want_w, screen_w - 40))
    h = max(420, min(want_h, screen_h - 140))
    return f"{w}x{h}+20+10"


def command_feedback(segment_label, last_command) -> str:
    """Text that confirms the operator's last button press in the viewer."""
    seg = f"segment OPEN: {segment_label}" if segment_label else "no segment open"
    return f"{seg}  ·  last: {last_command}" if last_command else seg


class ViewerApp:
    def __init__(self, pipeline, title: str, on_close: Callable[[], None], window_s: float = 10.0,
                 refresh_ms: int = 33, script=None, clock: Optional[Callable[[], float]] = None) -> None:
        self.p = pipeline
        self.script = script  # GuidedScript or None (manual controls)
        self.clock = clock or time.monotonic
        self.on_close = on_close
        self.window_s = window_s
        self.refresh_ms = refresh_ms
        self.root = tk.Tk()
        self.root.title(title)
        self.root.configure(bg=BG)
        self.root.geometry(fit_geometry(self.root.winfo_screenwidth(), self.root.winfo_screenheight()))
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        # Controls first, at the top: widgets packed last are the first to be cut off when the window is
        # taller than the visible screen area.
        bar = tk.Frame(self.root, bg=BG)
        if script is None:
            bar.pack(fill="x", padx=12, pady=(10, 4))
        else:  # guided mode: one large instruction panel; the manual controls and the N shortcut are off
            self.guide = tk.Label(self.root, text="", bg="#1b2733", fg=TEXT, font=("Segoe UI", 14, "bold"),
                                  anchor="w", justify="left", padx=12, pady=10, wraplength=900)
            self.guide.pack(fill="x", padx=12, pady=(10, 4))
        top = tk.Frame(self.root, bg=BG)
        top.pack(fill="x", padx=12, pady=(4, 4))
        self.status = tk.Label(top, text="starting…", bg=BG, fg=TEXT, font=("Segoe UI", 11), anchor="w", justify="left")
        self.status.pack(side="left", fill="x", expand=True)
        self.gate = tk.Label(top, text="", bg=BG, fg=BAD, font=("Segoe UI", 11, "bold"))
        self.gate.pack(side="right")
        self.canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        btn = dict(bg="#2a3038", fg=TEXT, activebackground="#3c4450", activeforeground=TEXT, relief="flat",
                   padx=10, pady=4)
        tk.Button(bar, text="Capture neutral  [N]", command=self.capture, **btn).pack(side="left")
        tk.Label(bar, text="   segment label:", bg=BG, fg=MUTED).pack(side="left")
        self.seg_label = tk.Entry(bar, width=22, bg="#1b1f24", fg=TEXT, insertbackground=TEXT, relief="flat")
        self.seg_label.pack(side="left", padx=4)
        tk.Button(bar, text="Start segment", command=self.seg_start, **btn).pack(side="left", padx=4)
        tk.Button(bar, text="End segment", command=self.seg_end, **btn).pack(side="left")
        self.info = tk.Label(bar, text="", bg=BG, fg=MUTED, anchor="e")
        self.info.pack(side="right")
        self.feedback = tk.Label(self.root, text=command_feedback(None, None), bg=BG, fg="#fbbc04",
                                 font=("Segoe UI", 11, "bold"), anchor="w")
        self.feedback.pack(fill="x", padx=12, before=top)
        if script is None:
            self.root.bind("<Key-n>", lambda e: self.capture() if e.widget is not self.seg_label else None)
        else:
            self.root.bind("<space>", lambda e: self.guided_press())
        self.segment_open = False
        self.open_label = None

    def _feedback(self, last: str) -> None:
        self.feedback.config(text=command_feedback(self.open_label, last))

    # ------------------------------------------------------------------ actions
    def capture(self) -> None:
        self.p.submit_command("capture_neutral", window_s=float(self.p.cfg["neutral"]["window_s"]),
                              tau_stab_deg=float(self.p.cfg["neutral"]["tau_stab_deg"]))
        self._feedback("neutral capture requested")

    def seg_start(self) -> None:
        if self.segment_open:
            self.seg_end()
        label = self.seg_label.get().strip() or "segment"
        self.p.submit_command("segment_start", label=label)
        self.segment_open, self.open_label = True, label
        self._feedback(f"started '{label}'")

    def seg_end(self) -> None:
        if self.segment_open:
            label = self.open_label
            self.p.submit_command("segment_end")
            self.segment_open, self.open_label = False, None
            self._feedback(f"ended '{label}'")

    def guided_press(self) -> None:
        self._submit_guided(self.script.press(self.clock()))

    def _submit_guided(self, commands) -> None:
        for kind, data in commands:
            if kind == "capture_neutral":
                self.capture()
            elif kind == "segment_start":
                self.p.submit_command("segment_start", **data)
                self.segment_open, self.open_label = True, data["label"]
                self._feedback(f"started '{data['label']}'")
            elif kind == "segment_end":
                self.seg_end()

    def _guided_refresh(self, last_neutral) -> None:
        now = self.clock()
        self.script.observe_neutral(last_neutral)
        self._submit_guided(self.script.tick(now))
        self.guide.config(text=self.script.text(now))

    def _close(self) -> None:
        if self.script is not None and self.segment_open:
            self.seg_end()  # never leave a guided segment open in the recording
        self.on_close()
        self.root.destroy()

    def run(self) -> None:
        self.root.after(self.refresh_ms, self._tick)
        self.root.mainloop()

    # ------------------------------------------------------------------ drawing
    def _tick(self) -> None:
        try:
            self._draw()
        finally:
            self.root.after(self.refresh_ms, self._tick)

    def _draw(self) -> None:
        hist, st, gate = self.p.snapshot(self.window_s)
        dev = st.get("device") or {}
        rate = st.get("observed_rate_hz")
        lines = [
            f"{'CONNECTED' if st['connected'] else 'NOT CONNECTED'}  ·  {dev.get('market_name') or '—'} "
            f"{dev.get('pid') or ''}  fw {dev.get('firmware') or '—'}  ·  connection {st.get('connection_id')}",
            f"pose: requested {dev.get('frequency_requested_hz')} Hz, selected {dev.get('frequency_selected_hz')} Hz, "
            f"observed {rate:.1f} Hz" if rate else "pose: no samples yet",
            f"samples {st['pose_samples']}  valid {st['valid']}  invalid {st['invalid']}  gaps {st['gaps']} "
            f"(≈{st['est_missing']} missing)  ·  queue max {st['max_queue']}",
        ]
        last_q = next((p.quat for p in reversed(hist) if p.quat is not None), None)
        lines.append(tilt_text(up_axis_tilt_deg(last_q) if last_q is not None else None))
        ln = st.get("last_neutral")
        if ln:
            outcome = (f"ACCEPTED id {ln['neutral_calibration_id']}" if ln["accepted"]
                       else "REJECTED " + ", ".join(ln["reasons"]))
            extra = ""
            if ln.get("dispersion_max_deg") is not None:
                extra += f"  dispersion max {ln['dispersion_max_deg']:.3f}°"
            if ln.get("q0_tilt_from_upright_deg") is not None:
                extra += f"  tilt at capture {ln['q0_tilt_from_upright_deg']:.1f}°"
            lines.append(f"neutral attempt {ln['attempt']}: {outcome}{extra}")
        self.status.config(text="\n".join(lines))
        if self.script is not None:
            self._guided_refresh(st.get("last_neutral"))
        self.gate.config(text="TRACKING USABLE" if gate.usable else "NOT USABLE: " + ", ".join(gate.reasons),
                         fg=OK if gate.usable else BAD)
        self.info.config(text="angles are display-only Z-Y′-X″ of head orientation (not neck/cervical angles)")

        c = self.canvas
        c.delete("all")
        W, H = max(c.winfo_width(), 200), max(c.winfo_height(), 200)
        left, right_pad = 60, 210
        rows = ("yaw", "pitch", "roll")
        rh = H / 3
        rel = any(p.euler_display is not None for p in hist[-1:])
        series = {k: [] for k in rows}
        if hist:
            t_end = hist[-1].host_rx_monotonic_ns
            for p in hist:
                if p.euler_display is not None:
                    e = p.euler_display
                elif p.quat is not None and not rel:
                    e = zyx_from_quat(p.quat)
                else:
                    continue
                t = (p.host_rx_monotonic_ns - t_end) / 1e9
                for k, v in zip(rows, e):
                    series[k].append((t, v, p.valid))
        latest = {k: (series[k][-1][1] if series[k] else None) for k in rows}
        words = direction_words(*(latest[k] or 0.0 for k in rows))
        label = "relative to neutral" if rel else "ABSOLUTE tracking frame (no neutral yet)"
        for i, k in enumerate(rows):
            y0, y1 = i * rh + 8, (i + 1) * rh - 8
            mid = (y0 + y1) / 2
            vals = [v for _, v, _ in series[k]]
            span = max(5.0, max((abs(v) for v in vals), default=0.0) * 1.15)
            c.create_rectangle(left, y0, W - right_pad, y1, outline=GRID)
            c.create_line(left, mid, W - right_pad, mid, fill=GRID, dash=(2, 4))
            c.create_text(left - 6, y0 + 8, text=f"+{span:.0f}°", fill=MUTED, anchor="e", font=("Segoe UI", 8))
            c.create_text(left - 6, y1 - 8, text=f"−{span:.0f}°", fill=MUTED, anchor="e", font=("Segoe UI", 8))
            c.create_text(left - 6, mid, text=k, fill=COLORS[k], anchor="e", font=("Segoe UI", 10, "bold"))
            pts = []
            x_w = W - right_pad - left
            step = max(1, len(series[k]) // int(x_w))
            for t, v, ok in series[k][::step]:
                x = left + x_w * (1 + t / self.window_s)
                y = mid - (v / span) * (y1 - y0) / 2
                pts.extend((x, y))
                if not ok:
                    c.create_line(x, y0, x, y1, fill=BAD)
            if len(pts) >= 4:
                c.create_line(*pts, fill=COLORS[k], width=2)
            val = latest[k]
            c.create_text(W - right_pad + 14, mid - 10, anchor="w", fill=TEXT, font=("Segoe UI", 18, "bold"),
                          text="—" if val is None else f"{val:+7.2f}°")
            c.create_text(W - right_pad + 14, mid + 16, anchor="w", fill=MUTED, font=("Segoe UI", 9),
                          text=words[i] if val is not None else "")
        c.create_text(left, H - 2, anchor="sw", fill=MUTED, font=("Segoe UI", 9),
                      text=f"last {self.window_s:.0f} s · {label} · red ticks = invalid samples · "
                           f"signs: +yaw left, +pitch down, +roll right ear down")
