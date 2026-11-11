"""Chord engine (2B): voicings, note pairing, interruptions, panic, failures, accompaniment, quantization."""
import time

import pytest

from headmusic.acquisition import synthetic as syn
from headmusic.cli import main
from headmusic.config import load_config
from headmusic.instrument.events import InteractionEvent
from headmusic.music.backends import BackendError, NullBackend
from headmusic.music.backends import winmm
from headmusic.music.config import MusicConfig, MusicConfigError
from headmusic.music.engine import ChordEngine
from headmusic.music.scheduler import Scheduler
from headmusic.orientation.processor import OrientationProcessor, ProcessorConfig
from headmusic.pipeline import Pipeline
from headmusic.stack import build_stack
from headmusic.tracking.gate import TrackingGate
from headmusic.types import Command, RawPoseSample

STREAM = {"selected_hz": 240, "reference_rate_hz": 202.5}
VOICING = {"C": [60, 64, 67], "G": [55, 59, 62], "Am": [57, 60, 64], "F": [53, 57, 60]}


def cfg_with(music=None, accompaniment=None):
    cfg = load_config()
    cfg["music"] = {**cfg["music"], **(music or {})}
    cfg["music"]["accompaniment"] = {**cfg["music"]["accompaniment"], **(accompaniment or {})}
    return cfg


def run(items, cfg=None, fail_after=None, breaker=None):
    cfg = cfg or cfg_with()
    gate = TrackingGate.from_config(cfg)
    stack = build_stack(cfg, gate, audio="null")
    if fail_after is not None:
        stack.engine.backend = NullBackend(fail_after=fail_after)
    if breaker:
        breaker(stack)
    pipe = Pipeline(cfg, OrientationProcessor(ProcessorConfig.from_config(cfg)), gate, None, clock=None,
                    fixed_stream_config=STREAM, consumers=stack.consumers)
    try:
        pipe.process_all(items)
    finally:
        stack.close("end_of_stream")
    return stack, pipe


def msgs(stack):
    return stack.engine.backend.messages


def note_ons(stack):
    return [(s & 0x0F, n) for s, n, v in msgs(stack) if s & 0xF0 == 0x90 and v > 0]


def check_pairing(messages):
    """Every note-on is followed by exactly one note-off before the same note starts again; nothing is left on."""
    on = set()
    for s, n, v in messages:
        key = (s & 0x0F, n)
        if s & 0xF0 == 0x90 and v > 0:
            assert key not in on, f"double note-on {key}"
            on.add(key)
        elif s & 0xF0 == 0x80 or (s & 0xF0 == 0x90 and v == 0):
            assert key in on, f"note-off without note-on {key}"
            on.discard(key)
    assert not on, f"left sounding: {on}"


def mev(stack, t=None):
    return [e for e in stack.engine.events if t is None or e["event_type"] == t]


def tour_items(yaws=(31.0, 13.0, -13.0, -31.0), drop=None, commands=()):
    keys, end = syn.chord_tour(yaws=yaws)
    s = syn.generate(end + 0.5, orientation=syn.keyframes(keys))
    if drop:
        a, n = drop
        s = syn.resequence(s[:a] + s[a + n:])
    return syn.Trace(s, [syn.capture_command(20, window_s=0.5), *commands], [syn.connected_event(1)]).items()


# ---------------------------------------------------------------------------- 2B-1 chords and pairing
def test_chord_tour_plays_correct_voicings_with_paired_notes():
    stack, _ = run(tour_items())
    chords = [e["chord"] for e in mev(stack, "midi_note_on")]
    assert chords == ["C", "G", "Am", "F"]
    ons = [n for _, n in note_ons(stack)]
    assert ons == VOICING["C"] + VOICING["G"] + VOICING["Am"] + VOICING["F"]
    check_pairing(msgs(stack))
    # emergency silencing at stop: CC 123 and CC 120 on the chord and click channels
    ccs = {(s, c) for s, c, _ in msgs(stack) if s & 0xF0 == 0xB0}
    assert ccs == {(0xB0, 123), (0xB0, 120), (0xB9, 123), (0xB9, 120)}


def test_chord_change_turns_the_previous_chord_off_first():
    stack, _ = run(tour_items())
    m = msgs(stack)
    i_g = m.index((0x90, 55, 100))
    assert {(0x80, n, 0) for n in VOICING["C"]} <= set(m[:i_g])


@pytest.mark.parametrize("allow, expected", [(True, 2), (False, 1)])
def test_same_chord_recommit(allow, expected):
    stack, _ = run(tour_items(yaws=(31.0, 31.0)), cfg_with({"allow_same_chord_recommit": allow}))
    assert len([e for e in stack.instrument.events if e["event_type"] == "raw_commit"]) == 2
    assert len(mev(stack, "midi_note_on")) == expected
    assert len(mev(stack, "commit_ignored")) == 2 - expected
    check_pairing(msgs(stack))


# ---------------------------------------------------------------------------- 2B-2 interruptions, panic
PAUSE_AFTER_C_COMMIT = (int(2.45 * 202.5), int(0.3 * 202.5))  # C is still held, already committed


def test_interruption_releases_the_sounding_chord():
    stack, _ = run(tour_items(drop=PAUSE_AFTER_C_COMMIT))
    offs = mev(stack, "midi_note_off")
    assert offs[0]["chord"] == "C" and offs[0]["reason"].startswith("interruption:")
    assert offs[0]["cause_event_type"] in ("gesture_reset", "state_change")
    check_pairing(msgs(stack))


def test_hold_through_interruption_when_configured():
    stack, _ = run(tour_items(drop=PAUSE_AFTER_C_COMMIT), cfg_with({"release_on_interruption": False}))
    offs = mev(stack, "midi_note_off")
    assert offs[0]["chord"] == "C" and offs[0]["reason"] == "chord_change"


def test_panic_silences_everything_and_disables_selection():
    panic = Command("panic", 0, {}, after_seq=int(2.5 * 202.5))
    stack, _ = run(tour_items(commands=[panic]))
    assert [e["chord"] for e in mev(stack, "midi_note_on")] == ["C"]  # nothing after the panic
    assert len(mev(stack, "panic")) == 1
    m = msgs(stack)
    i_panic_cc = m.index((0xB0, 123, 0))
    assert {(0x80, n, 0) for n in VOICING["C"]} <= set(m[:i_panic_cc])
    check_pairing(m)
    assert stack.instrument.fsm.enabled is False


# ---------------------------------------------------------------------------- 2B-3 every stop path
def test_consumer_exception_silences_output_and_keeps_the_pipeline_running():
    def breaker(stack):
        orig = stack.instrument.fsm.on_sample

        def boom(ps, *a, **k):
            if ps.seq == int(2.5 * 202.5):
                raise RuntimeError("simulated FSM bug")
            return orig(ps, *a, **k)
        stack.instrument.fsm.on_sample = boom
    stack, pipe = run(tour_items(), breaker=breaker)
    assert pipe.consumers == [] and "simulated FSM bug" in pipe.stats["consumer_error"]["error"]
    assert pipe.stats["pose_samples"] > int(2.5 * 202.5) + 100  # processing continued
    check_pairing(msgs(stack))
    assert [e["chord"] for e in mev(stack, "midi_note_on")] == ["C"]


def test_backend_failure_does_not_crash_and_stops_sending():
    stack, _ = run(tour_items(), fail_after=4)  # fails on the 5th message (during C → G)
    assert stack.engine.failed and "simulated" in stack.engine.failed
    assert len(msgs(stack)) == 4


def test_close_is_idempotent_and_silences():
    mcfg = MusicConfig.from_config(cfg_with())
    be = NullBackend()
    eng = ChordEngine(mcfg, be)
    eng.on_interaction(InteractionEvent("raw_commit", "return_to_neutral", chord="Am", produced_host_ns=1), 1)
    eng.close("test")
    n = len(be.messages)
    eng.close("again")
    assert len(be.messages) == n and be.closed
    check_pairing(be.messages)
    assert mev_types(eng)[-2:] == ["midi_note_off", "engine_stop"]


def mev_types(eng):
    return [e["event_type"] for e in eng.events]


def test_stack_close_runs_even_if_processing_raises():
    cfg = cfg_with()
    gate = TrackingGate.from_config(cfg)
    stack = build_stack(cfg, gate, audio="null")
    pipe = Pipeline(cfg, OrientationProcessor(ProcessorConfig.from_config(cfg)), gate, None, clock=None,
                    fixed_stream_config=STREAM, consumers=stack.consumers)
    items = list(tour_items())[:600]
    with pytest.raises(KeyboardInterrupt):
        try:
            pipe.process_all(items)
            raise KeyboardInterrupt
        finally:
            stack.close("interrupted")
    check_pairing(msgs(stack))
    assert stack.engine.stopped


# ---------------------------------------------------------------------------- accompaniment, quantization
def test_quantized_onset_is_on_the_next_beat_and_raw_commit_is_unchanged():
    cfg = cfg_with(accompaniment={"enabled": True, "quantize": True})
    stack, _ = run(tour_items(), cfg)
    start = mev(stack, "accompaniment_start")[0]
    t0, p = start["scheduled_host_ns"], int(round(60e9 / 80.0))
    first_neutral = next(e for e in stack.instrument.events if e["event_type"] == "return_neutral")
    assert t0 == first_neutral["produced_host_ns"]
    onsets = mev(stack, "scheduled_onset")
    commits = [e for e in stack.instrument.events if e["event_type"] == "raw_commit"]
    assert [o["chord"] for o in onsets] == [c["chord"] for c in commits] == ["C", "G", "Am", "F"]
    for o, c in zip(onsets, commits):
        assert o["produced_host_ns"] == c["produced_host_ns"]  # raw commit time is kept
        assert (o["scheduled_host_ns"] - t0) % p == 0
        assert 0 <= o["scheduled_host_ns"] - c["produced_host_ns"] < p
    check_pairing(msgs(stack))


def test_accompaniment_mute_on_interruption():
    cfg = cfg_with(accompaniment={"enabled": True, "on_interruption": "mute"})
    stack, _ = run(tour_items(drop=PAUSE_AFTER_C_COMMIT), cfg)
    types = mev_types(stack.engine)
    assert "accompaniment_mute" in types
    assert types.index("accompaniment_unmute") > types.index("accompaniment_mute")


def test_accompaniment_continues_by_default():
    cfg = cfg_with(accompaniment={"enabled": True})
    stack, _ = run(tour_items(drop=PAUSE_AFTER_C_COMMIT), cfg)
    assert "accompaniment_mute" not in mev_types(stack.engine)


# ---------------------------------------------------------------------------- real-time scheduling
def test_scheduler_orders_and_cancels():
    sch = Scheduler(time.perf_counter_ns)
    out = []
    now = time.perf_counter_ns()
    sch.at(now + 30_000_000, lambda late: out.append("c"))
    sch.at(now + 10_000_000, lambda late: out.append("a"))
    tok = sch.at(now + 20_000_000, lambda late: out.append("b"))
    sch.cancel(tok)
    time.sleep(0.1)
    sch.stop()
    assert out == ["a", "c"]


def test_realtime_clicks_and_cancelled_quantized_onset():
    cfg = cfg_with(accompaniment={"enabled": True, "quantize": True, "bpm": 300.0, "duration_ms": 20.0})
    mcfg = MusicConfig.from_config(cfg)
    be = NullBackend()
    clock = time.perf_counter_ns
    eng = ChordEngine(mcfg, be, clock=clock, realtime=True)
    eng.on_command(Command("accompaniment_start", clock(), {}))
    time.sleep(0.45)  # ~2 beats at 300 BPM
    clicks = [m for m in be.messages if m[0] == 0x99]
    assert len(clicks) >= 2
    # a commit is scheduled for the next beat; an interruption before it cancels it: no chord ever sounds
    eng.on_interaction(InteractionEvent("raw_commit", "return_to_neutral", chord="G", produced_host_ns=clock()), 1)
    eng.on_interaction(InteractionEvent("gesture_reset", "inactive", reason="stale_tick"), 2)
    time.sleep(0.25)
    eng.close("test")
    assert "scheduled_onset_cancelled" in mev_types(eng)
    assert not [m for m in be.messages if m[0] == 0x90]
    check_pairing(be.messages)


# ---------------------------------------------------------------------------- winmm backend (fake DLL)
class FakeWinmm:
    def __init__(self, names=("Fake GS Synth", "Loop Port"), fail_send=False):
        self.names, self.sent, self.calls, self.fail_send = list(names), [], [], fail_send

    def midiOutGetNumDevs(self):
        return len(self.names)

    def midiOutGetDevCapsW(self, i, ref, size):
        ref._obj.szPname = self.names[i]
        return 0

    def midiOutOpen(self, ref, index, cb, inst, flags):
        ref._obj.value = 1000 + index
        self.calls.append(("open", index))
        return 0

    def midiOutShortMsg(self, h, dword):
        if self.fail_send:
            return 11
        self.sent.append(dword)
        return 0

    def midiOutReset(self, h):
        self.calls.append(("reset",))
        return 0

    def midiOutClose(self, h):
        self.calls.append(("close",))
        return 0


def test_winmm_message_packing():
    assert winmm.pack(0x90, 60, 100) == 0x643C90
    assert winmm.pack(0xB9, 123, 0) == 0x7BB9


def test_winmm_backend_with_fake_dll():
    fake = FakeWinmm()
    be = winmm.WinmmBackend("loop", dll=fake)
    assert be.device_index == 1 and fake.calls[0] == ("open", 1)
    be.send(0x90, 60, 100)
    assert fake.sent == [0x643C90]
    be.close()
    assert ("close",) in fake.calls
    with pytest.raises(BackendError):
        be.send(0x80, 60, 0)
    with pytest.raises(BackendError, match="no MIDI output device matching"):
        winmm.WinmmBackend("nothing", dll=FakeWinmm())
    with pytest.raises(BackendError, match="does not exist"):
        winmm.WinmmBackend(5, dll=FakeWinmm())
    with pytest.raises(BackendError, match="failed"):
        winmm.WinmmBackend(0, dll=FakeWinmm(fail_send=True)).send(0x90, 60, 1)
    assert winmm.describe_devices(FakeWinmm()) == "0: Fake GS Synth\n1: Loop Port"


# ---------------------------------------------------------------------------- config and CLI
@pytest.mark.parametrize("music, acc, msg", [
    ({"chords": {"C": [60]}}, None, "no voicing"),
    ({"channel": 17}, None, "channel"),
    ({"chords": {**VOICING, "C": [60, 128]}}, None, "0..127"),
    ({"backend": "alsa"}, None, "backend"),
    (None, {"on_interruption": "pause"}, "on_interruption"),
    (None, {"duration_ms": 900.0}, "shorter than one beat"),
    (None, {"bpm": 0.0}, "bpm"),
])
def test_invalid_music_config(music, acc, msg):
    with pytest.raises(MusicConfigError, match=msg):
        MusicConfig.from_config(cfg_with(music, acc), required_chords=["C", "G", "Am", "F"])


def test_midi_test_cli_with_null_output(capsys):
    assert main(["midi-test", "--audio", "null", "--seconds", "0"]) == 0
    assert "all notes off" in capsys.readouterr().out


def test_synth_writes_music_log_and_replay_reproduces_it(tmp_path, capsys):
    s = tmp_path / "s"
    assert main(["synth", "chords", "--instrument", "--out", str(s)]) == 0
    assert (s / "music_events.jsonl").stat().st_size > 0
    assert main(["replay", str(s), "--reprocess", "--instrument", "--out", str(tmp_path / "r")]) == 0
    assert "music_events.jsonl identical to the original: True" in capsys.readouterr().out


def test_duplicate_timestamp_skip_keeps_the_chord_sounding():
    """R2D-1 finding: in "reset" mode a duplicate device timestamp releases the sounding chord; in "skip" it does not."""
    keys, end = syn.chord_tour()
    s = syn.generate(end + 0.5, orientation=syn.keyframes(keys))
    i = int(2.45 * 202.5)  # C committed and sounding, head still in C
    # a real duplicate (G0, R2D-1) is an EXTRA sample ~1 ms after the previous one, same device timestamp
    prev = s[i - 1]
    extra = RawPoseSample(0, 1, prev.host_rx_monotonic_ns + 1_000_000, prev.device_ts_raw, prev.values)
    s = syn.resequence(s[:i] + [extra] + s[i:])
    items = syn.Trace(s, [syn.capture_command(20, window_s=0.5)], [syn.connected_event(1)]).items()
    strict, _ = run(items)
    cfg = cfg_with()
    cfg["instrument"] = {**cfg["instrument"], "duplicate_timestamp": "skip"}
    skip, _ = run(items, cfg)
    reasons = lambda st: [e.get("reason") for e in mev(st, "midi_note_off")]  # noqa: E731
    assert "interruption:last_sample_invalid" in reasons(strict)
    assert reasons(skip)[0] == "chord_change"
    check_pairing(msgs(skip))
