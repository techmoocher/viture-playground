"""Command-line interface: headmusic devices | info | check-placement | record | view | replay | analyze | export | synth."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from headmusic.config import REPO_ROOT, load_config
from headmusic.orientation.processor import OrientationProcessor, ProcessorConfig
from headmusic.pipeline import Pipeline
from headmusic.provenance import clock_anchor, new_session_meta, session_dir_name
from headmusic.recording.writer import SessionWriter
from headmusic.tracking.gate import TrackingGate

DEFAULT_SDK_DIR = REPO_ROOT / "vendor" / "viture" / "windows_x86_64" / "bin"
DEFAULT_SHIM = REPO_ROOT / "native" / "build" / "capture_shim.dll"
DEFAULT_DATA = REPO_ROOT / "data"


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _cfg(args) -> dict:
    overrides: dict = {"imu": {}}
    if getattr(args, "mode", None):
        overrides["imu"]["mode"] = args.mode
    if getattr(args, "freq", None):
        overrides["imu"]["frequency_requested_hz"] = args.freq
    return load_config(args.config, overrides)


def _sdk(args):
    from headmusic.acquisition.viture_sdk import VitureSdk
    return VitureSdk(args.sdk_dir)


# --------------------------------------------------------------------------- devices / info
def cmd_devices(args) -> int:
    from headmusic.acquisition.usb_enum import find_viture_pids
    sdk = _sdk(args)
    pids = find_viture_pids(sdk.is_product_id_valid)
    print(f"VITURE SDK {sdk.version()} — {len(pids)} device(s)")
    for pid in pids:
        print(f"  PID 0x{pid:04X}  {sdk.market_name(pid)}  native_dof={sdk.supports_native_dof(pid)}")
        for mode, table in sdk.frequency_table(pid).items():
            print(f"    {mode:4s} supported Hz: {', '.join(hz for hz, ok in table.items() if ok)}")
    return 0 if pids else 1


def cmd_info(args) -> int:
    from headmusic.acquisition.usb_enum import find_viture_pids
    from headmusic.acquisition.viture_sdk import DEVICE_TYPES, SdkError
    sdk = _sdk(args)
    sdk.set_log_level(1)
    pids = find_viture_pids(sdk.is_product_id_valid)
    if not pids:
        print("no VITURE device found", file=sys.stderr)
        return 1
    pid = args.pid or pids[0]
    h = None
    try:
        h = sdk.create(pid)
        dtype = sdk.device_type(h)
        sdk.initialize(h)
        sdk.start(h)
        info = {"sdk_version": sdk.version(), "pid": f"0x{pid:04X}", "market_name": sdk.market_name(pid),
                "device_type": f"{dtype} ({DEVICE_TYPES.get(dtype)})", "firmware": sdk.glasses_version(h),
                "native_dof": sdk.supports_native_dof(pid), "frequency_support": sdk.frequency_table(pid)}
        print(json.dumps(info, indent=2))
        return 0
    except SdkError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    finally:
        if h:
            sdk.stop(h)
            sdk.shutdown(h)
            sdk.destroy(h)


# --------------------------------------------------------------------------- placement check
def cmd_check_placement(args) -> int:
    """Stream for a few seconds without writing anything; print stillness and tilt for the operator."""
    from headmusic.acquisition.capture_shim import CaptureShim
    from headmusic.acquisition.viture_source import VitureSdkSource
    from headmusic.metrics.placement import format_summary, placement_summary
    from headmusic.types import RawPoseSample
    cfg = _cfg(args)
    if cfg["imu"]["mode"] != "pose":
        print("check-placement uses pose mode", file=sys.stderr)
        return 2
    sdk = _sdk(args)
    shim = CaptureShim(args.shim)
    items: list = []
    lock = threading.Lock()
    count = [0]

    def sink(x) -> None:
        with lock:
            items.append(x)
            if isinstance(x, RawPoseSample):
                count[0] += 1

    source = VitureSdkSource(sdk, shim, cfg, sink, time.perf_counter_ns, pid=args.pid)
    source.start()
    t_start, t_stream = time.monotonic(), None
    try:
        while True:
            time.sleep(0.1)
            now = time.monotonic()
            if t_stream is None and count[0]:
                t_stream = now
            if t_stream is None and now - t_start > args.connect_timeout:
                print("no samples within --connect-timeout; is the device connected and not used by another app?",
                      file=sys.stderr)
                break
            if source.finished.is_set() or (t_stream is not None and now - t_stream >= args.seconds):
                break
    except KeyboardInterrupt:
        print("\ninterrupted")
    finally:
        source.stop(timeout=15)
    with lock:
        collected = list(items)
    if not count[0]:
        if source.last_error:
            print(f"error: {source.last_error}", file=sys.stderr)
        return 2
    print(format_summary(placement_summary(collected, cfg)))
    return 0


# --------------------------------------------------------------------------- live record / view
def _live(args, view: bool) -> int:
    if view and getattr(args, "script", None) and not args.record:
        print("--script needs --record (a guided bench run is always recorded)", file=sys.stderr)
        return 2
    from headmusic.acquisition.capture_shim import CaptureShim
    from headmusic.acquisition.viture_source import VitureSdkSource
    cfg = _cfg(args)
    sdk = _sdk(args)
    shim = CaptureShim(args.shim)
    clock = time.perf_counter_ns
    writer = None
    record = (not view) or args.record
    if record:
        buildinfo = args.shim.with_name("BUILDINFO.txt")
        meta = new_session_meta(cfg, condition="bench", mounting=args.mounting, source_kind="live", argv=sys.argv,
                                stationary=args.stationary, notes=args.notes or "",
                                extra_files={"glasses_dll": sdk.dll_path, "capture_shim_dll": shim.path})
        meta["provenance"]["capture_shim_buildinfo"] = buildinfo.read_text().splitlines() if buildinfo.exists() else None
        out = Path(args.data) / "sessions" / session_dir_name(meta)
        writer = SessionWriter(out, meta, cfg["io"]["flush_interval_s"], write_raw_pose=cfg["imu"]["mode"] == "pose",
                               write_raw_imu=cfg["imu"]["mode"] == "raw", write_processed=cfg["imu"]["mode"] == "pose")
        print(f"recording to {out}")
    processor = OrientationProcessor(ProcessorConfig.from_config(cfg))
    gate = TrackingGate.from_config(cfg)
    pipe = Pipeline(cfg, processor, gate, writer, clock)
    source = VitureSdkSource(sdk, shim, cfg, pipe.put, clock, pid=args.pid)
    pipe.start()
    source.start()
    stop = threading.Event()
    if args.segment:
        pipe.submit_command("segment_start", label=args.segment)

    def neutral_timer():
        if args.capture_neutral_at is None:
            return
        while not stop.is_set() and not pipe.snapshot(0.1)[1]["pose_samples"]:
            stop.wait(0.1)
        if not stop.wait(args.capture_neutral_at):
            pipe.submit_command("capture_neutral", window_s=float(cfg["neutral"]["window_s"]),
                                tau_stab_deg=float(cfg["neutral"]["tau_stab_deg"]))
    threading.Thread(target=neutral_timer, daemon=True).start()

    try:
        if view:
            from headmusic.viewer.app import ViewerApp
            script = None
            if args.script:
                from headmusic.viewer.guided import make_script
                script = make_script(args.script)
                pipe.submit_command("script_start", name=args.script, steps=[st.label for st in script.steps])
            app = ViewerApp(pipe, "headmusic — VITURE head orientation (Phase 1)", on_close=stop.set, script=script)
            if args.close_after:
                app.root.after(int(args.close_after * 1000), app._close)
            app.run()
        else:
            _wait_recording(pipe, source, args, stop)
    except KeyboardInterrupt:
        print("\ninterrupted — stopping")
    finally:
        stop.set()
        if args.segment:
            pipe.submit_command("segment_end")
        source.stop(timeout=15)
        pipe.stop(timeout=15)
        hist, st, _ = pipe.snapshot()
        if writer:
            writer.close(clocks={**writer.meta["clocks"], "end_anchor": clock_anchor()},
                         summary={k: st[k] for k in ("pose_samples", "imu_samples", "valid", "invalid", "gaps",
                                                     "est_missing", "neutral_attempts", "neutral_accepted",
                                                     "max_queue")},
                         shim_stats=shim.stats(), source_last_error=source.last_error)
            print(f"session closed: {writer.dir}")
            if not view and args.analyze:
                from headmusic.metrics.report import analyze_session
                analyze_session(writer.dir)
                print(f"report: {writer.dir / 'analysis' / 'report.md'}")
    if source.last_error and not st.get("pose_samples") and not st.get("imu_samples"):
        print(f"error: {source.last_error}", file=sys.stderr)
        return 2
    return 0


def cmd_play(args) -> int:
    """Live instrument: glasses → pipeline → gesture FSM → chord engine → MIDI, with the play window.

    Recorded by default (raw data, processing, interaction and music logs). Every hardware run needs the
    operator's approval of the setup first; worn use waits for O3 (docs/phase2-proposal.md §7, 2D)."""
    from headmusic.acquisition import power
    from headmusic.acquisition.capture_shim import CaptureShim
    from headmusic.acquisition.viture_source import VitureSdkSource
    from headmusic.music.config import midi_device_arg
    cfg = _cfg(args)
    sdk = _sdk(args)
    shim = CaptureShim(args.shim)
    clock = time.perf_counter_ns
    writer = None
    if args.record:
        meta = new_session_meta(cfg, condition="bench", mounting=args.mounting, source_kind="live", argv=sys.argv,
                                notes=args.notes or "",
                                extra_files={"glasses_dll": sdk.dll_path, "capture_shim_dll": shim.path})
        out = Path(args.data) / "sessions" / session_dir_name(meta)
        writer = SessionWriter(out, meta, cfg["io"]["flush_interval_s"])
        print(f"recording to {out}")
    processor = OrientationProcessor(ProcessorConfig.from_config(cfg))
    gate = TrackingGate.from_config(cfg)
    stack = _stack(cfg, gate, writer, clock=clock, audio=args.audio, midi_device=midi_device_arg(args.midi_device),
                   realtime=True)
    print(f"audio output: {stack.engine.backend.describe()}")
    pipe = Pipeline(cfg, processor, gate, writer, clock, consumers=stack.consumers)
    source = VitureSdkSource(sdk, shim, cfg, pipe.put, clock, pid=args.pid)
    awake = power.keep_awake() if args.keep_awake else False
    if writer:
        writer.update_meta(keep_awake_requested=awake)
    stop = threading.Event()
    pipe.start()
    source.start()

    def neutral_timer():
        if args.capture_neutral_at is None:
            return
        while not stop.is_set() and not pipe.snapshot(0.1)[1]["pose_samples"]:
            stop.wait(0.1)
        if not stop.wait(args.capture_neutral_at):
            pipe.submit_command("capture_neutral", window_s=float(cfg["neutral"]["window_s"]),
                                tau_stab_deg=float(cfg["neutral"]["tau_stab_deg"]))
    threading.Thread(target=neutral_timer, daemon=True).start()
    try:
        from headmusic.viewer.play import PlayApp
        app = PlayApp(pipe, stack, "headmusic — four-chord instrument (Phase 2)", on_close=stop.set)
        if args.close_after:
            app.root.after(int(args.close_after * 1000), app._close)
        app.run()
    except KeyboardInterrupt:
        print("interrupted — stopping")
    finally:
        stop.set()
        pipe.submit_command("panic", reason="window_closed")  # silence and disable before the slow teardown
        source.stop(timeout=15)
        pipe.stop(timeout=15)
        stack.close("play_end")
        if awake:
            power.release()
        _, st, _ = pipe.snapshot()
        commits = [e["chord"] for e in stack.instrument.events if e["event_type"] == "raw_commit"]
        print(f"commits: {commits}; all notes off")
        if writer:
            writer.close(clocks={**writer.meta["clocks"], "end_anchor": clock_anchor()},
                         summary={k: st[k] for k in ("pose_samples", "valid", "invalid", "gaps", "est_missing",
                                                     "neutral_attempts", "neutral_accepted", "max_queue")},
                         shim_stats=shim.stats(), source_last_error=source.last_error)
            print(f"session closed: {writer.dir}")
    return 0


def _wait_recording(pipe: Pipeline, source, args, stop: threading.Event) -> None:
    t_start = time.monotonic()
    t_stream: Optional[float] = None
    last_print = 0.0
    while not stop.is_set():
        time.sleep(0.2)
        _, st, gate = pipe.snapshot(1.0)
        now = time.monotonic()
        if t_stream is None and (st["pose_samples"] or st["imu_samples"]):
            t_stream = now
            print(f"streaming: {st['device']}")
        if t_stream is None and now - t_start > args.connect_timeout:
            print("no samples within --connect-timeout; is the device connected and not used by another app?",
                  file=sys.stderr)
            return
        if source.finished.is_set():
            print("acquisition stopped")
            return
        if t_stream is not None and now - last_print >= 5.0:
            last_print = now
            rate = st.get("observed_rate_hz")
            print(f"  t={now - t_stream:6.1f}s  samples={st['pose_samples'] or st['imu_samples']}  "
                  f"rate={rate and round(rate, 2)} Hz  invalid={st['invalid']}  gaps={st['gaps']}  "
                  f"gate={'usable' if gate.usable else ','.join(gate.reasons)}")
        if t_stream is not None and args.duration and now - t_stream >= args.duration:
            return


# --------------------------------------------------------------------------- instrument (Phase 2)
def _stack(cfg: dict, gate, writer=None, **kw):
    from headmusic.stack import build_stack
    return build_stack(cfg, gate, writer, **kw)


def cmd_midi_devices(args) -> int:
    from headmusic.music.backends.winmm import describe_devices
    print(describe_devices())
    return 0


def cmd_midi_test(args) -> int:
    """Play C, G, Am, F once through the chord engine (no glasses). Sound check for the chosen output."""
    from headmusic.instrument.events import InteractionEvent
    from headmusic.music.backends import make_backend
    from headmusic.music.config import MusicConfig, midi_device_arg
    from headmusic.music.engine import ChordEngine
    cfg = _cfg(args)
    mcfg = MusicConfig.from_config(cfg, required_chords=["C", "G", "Am", "F"])
    dev = midi_device_arg(args.midi_device)
    backend = make_backend(args.audio, mcfg.midi_device if dev is None else dev)
    print(f"output: {backend.describe()}")
    engine = ChordEngine(mcfg, backend, clock=time.perf_counter_ns)
    try:
        for i, chord in enumerate(("C", "G", "Am", "F")):
            print(f"  {chord}")
            engine.on_interaction(InteractionEvent("raw_commit", "return_to_neutral", chord=chord,
                                                   produced_host_ns=time.perf_counter_ns()), i + 1)
            time.sleep(args.seconds)
    except KeyboardInterrupt:
        print("interrupted")
    finally:
        engine.close("midi_test_end")
    print("all notes off")
    return 0


# --------------------------------------------------------------------------- replay
def cmd_replay(args) -> int:
    from headmusic.acquisition.replay_source import ReplaySource
    src_dir = Path(args.session)
    src = ReplaySource(src_dir, speed=None if args.speed == "max" else float(args.speed))
    cfg = load_config(args.config) if args.config else (src.config_snapshot or load_config())
    processor = OrientationProcessor(ProcessorConfig.from_config(cfg))
    gate = TrackingGate.from_config(cfg)
    if args.reprocess:
        meta = copy.deepcopy(src.meta)
        meta["source"] = {"kind": "replay", "replay_of_session_id": src.meta.get("session_id"),
                          "replay_of_dir": str(src_dir), "config_override": str(args.config) if args.config else None}
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out = Path(args.out) if args.out else Path(args.data) / "replays" / f"{src_dir.name}_reprocessed_{stamp}"
        writer = SessionWriter(out, meta, cfg["io"]["flush_interval_s"], write_raw_pose=False)
        stack = None
        if args.instrument:
            from headmusic.instrument.log import read_inputs
            from headmusic.stack import with_phase2_sections
            cfg = with_phase2_sections(cfg)
            stack = _stack(cfg, gate, writer, recorded_inputs=read_inputs(src_dir), audio="null")
        pipe = Pipeline(cfg, processor, gate, writer, clock=None, fixed_stream_config=src.stream_config,
                        consumers=stack.consumers if stack else [])
        t0 = time.perf_counter()
        try:
            pipe.process_all(src.items())
        finally:
            if stack:
                stack.close("end_of_stream")
        writer.close()
        dt = time.perf_counter() - t0
        a, b = src_dir / "processed_pose.csv", out / "processed_pose.csv"
        print(f"reprocessed {pipe.stats['pose_samples']} samples in {dt:.2f}s -> {out}")
        if a.exists() and not args.config:
            same = _sha256(a) == _sha256(b)
            same_cal = _sha256(src_dir / "calibration_neutral.jsonl") == _sha256(out / "calibration_neutral.jsonl")
            print(f"processed_pose.csv identical to the original: {same}")
            print(f"calibration_neutral.jsonl identical to the original: {same_cal}")
            same_int = True
            for name in ("interaction_events.jsonl", "music_events.jsonl"):
                orig = src_dir / name
                if args.instrument and orig.exists():
                    same = _sha256(orig) == _sha256(out / name)
                    same_int = same_int and same
                    print(f"{name} identical to the original: {same}")
            return 0 if (same and same_cal and same_int) else 3
        return 0
    speed = 1.0 if args.speed == "max" and args.view else (None if args.speed == "max" else float(args.speed))
    src = ReplaySource(src_dir, speed=speed)
    stack = None
    if args.instrument:
        from headmusic.instrument.log import read_inputs
        from headmusic.music.config import midi_device_arg
        from headmusic.stack import with_phase2_sections
        cfg = with_phase2_sections(cfg)
        stack = _stack(cfg, gate, None, clock=src.clock, recorded_inputs=read_inputs(src_dir), audio=args.audio,
                       midi_device=midi_device_arg(args.midi_device), realtime=True)
        print(f"instrument replay with audio output {stack.engine.backend.describe()}")
    pipe = Pipeline(cfg, processor, gate, None, clock=src.clock, fixed_stream_config=src.stream_config,
                    consumers=stack.consumers if stack else [])
    src.sink = pipe.put
    pipe.start()
    src.start()
    stop = threading.Event()
    try:
        if args.view and stack:
            from headmusic.viewer.play import PlayApp
            PlayApp(pipe, stack, f"headmusic — REPLAY {src_dir.name} (instrument)", on_close=stop.set,
                    live_commands=False).run()
        elif args.view:
            from headmusic.viewer.app import ViewerApp
            ViewerApp(pipe, f"headmusic — REPLAY {src_dir.name}", on_close=stop.set).run()
        else:
            while not src.finished.is_set():
                time.sleep(0.2)
    except KeyboardInterrupt:
        print("interrupted")
    finally:
        src.stop()
        pipe.stop()
        if stack:
            stack.close("end_of_replay")
            commits = [e["chord"] for e in stack.instrument.events if e["event_type"] == "raw_commit"]
            print(f"instrument commits: {commits}; all notes off")
    print(f"replayed {pipe.stats['pose_samples']} pose samples")
    return 0


# --------------------------------------------------------------------------- analyze / export / synth
def cmd_analyze(args) -> int:
    from headmusic.metrics.report import analyze_session
    stationary = True if args.stationary else None
    analyze_session(Path(args.session), stationary=stationary, reference_rate_hz=args.reference_rate_hz)
    print((Path(args.session) / "analysis" / "report.md").read_text(encoding="utf-8"))
    return 0


def cmd_export(args) -> int:
    from headmusic.recording.export import export_denormalized
    out = export_denormalized(Path(args.session), Path(args.out) if args.out else None)
    print(f"wrote {out} and {out.with_name('export_manifest.json')}")
    return 0


def cmd_synth(args) -> int:
    from headmusic.acquisition.synthetic import SCENARIOS
    cfg = load_config(args.config)
    trace = SCENARIOS[args.scenario]()
    meta = new_session_meta(cfg, condition="bench", mounting="synthetic", source_kind="synthetic", argv=sys.argv,
                            stationary=args.scenario == "stationary", notes=json.dumps(trace.info))
    stream = {"selected_hz": 240, "reference_rate_hz": 202.5}
    out = Path(args.out) if args.out else Path(args.data) / "sessions" / session_dir_name(meta)
    writer = SessionWriter(out, meta, cfg["io"]["flush_interval_s"])
    processor = OrientationProcessor(ProcessorConfig.from_config(cfg))
    gate = TrackingGate.from_config(cfg)
    stack = _stack(cfg, gate, writer, audio="null") if args.instrument else None
    pipe = Pipeline(cfg, processor, gate, writer, clock=None, fixed_stream_config=stream,
                    consumers=stack.consumers if stack else [])
    writer.update_meta(processing=pipe.stream_info, imu={"frequency_selected_hz": 240})
    try:
        pipe.process_all(trace.items())
    finally:
        if stack:
            stack.close("end_of_stream")
    if stack:
        commits = [e["chord"] for e in stack.instrument.events if e["event_type"] == "raw_commit"]
        print(f"instrument commits: {commits}")
    writer.close()
    print(f"synthetic '{args.scenario}' session: {out} ({pipe.stats['pose_samples']} samples)")
    return 0


# --------------------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="headmusic", description=__doc__)
    ap.add_argument("--sdk-dir", type=Path, default=DEFAULT_SDK_DIR, help="folder containing glasses.dll")
    ap.add_argument("--shim", type=Path, default=DEFAULT_SHIM, help="path to capture_shim.dll")
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA, help="data root (sessions/, replays/)")
    ap.add_argument("--config", type=Path, default=None, help="TOML file overriding defaults.toml")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("devices", help="list connected VITURE glasses and SDK frequency support")
    p = sub.add_parser("info", help="connect and print device identity (no streaming)")
    p.add_argument("--pid", type=lambda s: int(s, 0))

    p = sub.add_parser("check-placement", help="stream a few seconds, write nothing, print stillness and tilt")
    p.add_argument("--pid", type=lambda s: int(s, 0))
    p.add_argument("--freq", type=int, help="requested IMU frequency in Hz (default from config: 240)")
    p.add_argument("--seconds", type=float, default=15.0, help="seconds of streaming (default 15)")
    p.add_argument("--connect-timeout", type=float, default=15.0)

    def live_args(p):
        p.add_argument("--pid", type=lambda s: int(s, 0))
        p.add_argument("--mode", choices=["pose", "raw"])
        p.add_argument("--freq", type=int, help="requested IMU frequency in Hz (default from config: 240)")
        p.add_argument("--mounting", choices=["fixture", "worn"], default="fixture",
                       help="fixture = rigid stationary support (intrinsic characterisation); worn = on a head")
        p.add_argument("--stationary", action="store_true", help="declare the recording stationary (angular metrics)")
        p.add_argument("--segment", help="label one segment covering the whole recording (becomes trial_id)")
        p.add_argument("--notes", help="free-text notes (no personal information)")
        p.add_argument("--capture-neutral-at", type=float, help="request a neutral capture S seconds after streaming starts")
        p.add_argument("--connect-timeout", type=float, default=15.0)

    p = sub.add_parser("record", help="headless recording")
    live_args(p)
    p.add_argument("--duration", type=float, default=60.0, help="seconds of streaming (0 = until Ctrl+C)")
    p.add_argument("--no-analyze", dest="analyze", action="store_false")
    p = sub.add_parser("view", help="live viewer")
    live_args(p)
    p.add_argument("--record", action="store_true", help="also record the session")
    p.add_argument("--close-after", type=float, help="close the viewer after S seconds (unattended checks)")
    p.add_argument("--script", choices=["r6a", "r6b", "r6c", "r7", "r8"],
                   help="guided bench script (docs/bench-checklist.md): Space for every action, labels automatic")

    p = sub.add_parser("play", help="live four-chord instrument with the play window (glasses needed)")
    live_args(p)
    p.add_argument("--audio", choices=["winmm", "null"], default="winmm")
    p.add_argument("--midi-device", help="MIDI output device index or name substring (default: [music] config)")
    p.add_argument("--no-record", dest="record", action="store_false", help="do not record the session")
    p.add_argument("--no-keep-awake", dest="keep_awake", action="store_false",
                   help="do not ask Windows to stay awake while playing")
    p.add_argument("--close-after", type=float, help="close after S seconds (unattended checks)")

    p = sub.add_parser("replay", help="replay a recorded session without glasses")
    p.add_argument("session")
    p.add_argument("--speed", default="1", help="playback speed factor, or 'max'")
    p.add_argument("--view", action="store_true")
    p.add_argument("--reprocess", action="store_true", help="re-run processing offline and compare with the original")
    p.add_argument("--instrument", action="store_true",
                   help="run the Phase 2 instrument: with --reprocess, offline and compared with the original; "
                        "otherwise in real time with audio output (--audio)")
    p.add_argument("--audio", choices=["winmm", "null"], default="winmm", help="real-time replay output")
    p.add_argument("--midi-device", help="MIDI output device index or name substring (default: [music] config)")
    p.add_argument("--out")
    p = sub.add_parser("analyze", help="timing / jitter / drift report")
    p.add_argument("session")
    p.add_argument("--stationary", action="store_true", help="compute stationary angular metrics")
    p.add_argument("--reference-rate-hz", type=float,
                   help="re-check a candidate r_ref: use it for the timing metrics instead of the recorded value")
    p = sub.add_parser("export", help="denormalised per-row export (protocol §10 fields)")
    p.add_argument("session")
    p.add_argument("--out")
    p = sub.add_parser("midi-devices", help="list Windows MIDI output devices")
    p = sub.add_parser("midi-test", help="play C, G, Am, F once through the chord engine (sound check, no glasses)")
    p.add_argument("--audio", choices=["winmm", "null"], default="winmm")
    p.add_argument("--midi-device")
    p.add_argument("--seconds", type=float, default=0.8)
    p = sub.add_parser("synth", help="write a deterministic synthetic session")
    p.add_argument("scenario", choices=["stationary", "sign_flip", "yaw_wrap", "dropped", "sustained_loss",
                                        "faults", "reconnect", "chords"])
    p.add_argument("--instrument", action="store_true", help="also run the Phase 2 gesture FSM")
    p.add_argument("--out")
    return ap


def main(argv: Optional[list[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles default to cp1252
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    cmds = {"devices": cmd_devices, "info": cmd_info, "check-placement": cmd_check_placement,
            "record": lambda a: _live(a, view=False),
            "view": lambda a: _live(a, view=True), "replay": cmd_replay, "analyze": cmd_analyze,
            "export": cmd_export, "synth": cmd_synth, "midi-devices": cmd_midi_devices, "midi-test": cmd_midi_test,
            "play": cmd_play}
    return cmds[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
