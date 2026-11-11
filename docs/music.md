# Music engine (Phase 2B)

The design is in [phase2-proposal.md](phase2-proposal.md) §5. The engine consumes instrument events ([instrument.md](instrument.md)) and never sees sensor samples.

**Every value on this page is a provisional engineering default.** Each is configurable under `[music]` in `src/headmusic/defaults.toml` and recorded in `session.json` → `music`.

## Code

| Module | Role |
|---|---|
| `music/config.py` | `MusicConfig`: chords, channel, accompaniment; validation (every instrument chord needs a voicing) |
| `music/engine.py` | `ChordEngine`: chord logic, note pairing, interruptions, panic, accompaniment, quantization |
| `music/scheduler.py` | Timer thread for clicks and quantized onsets (real-time use only) |
| `music/backends/` | `NullBackend` (no sound; records messages) and `WinmmBackend` (Windows MIDI out through `ctypes`; the music package's only hardware boundary) |
| `music/log.py` | `music_events.jsonl` (deterministic) and `music_timing.jsonl` (sends) |
| `stack.py` | Builds instrument consumer → engine for every entry point |

## Behaviour

| Instrument event | Engine |
|---|---|
| `raw_commit` | Sends note-off for the sounding chord, then note-on for the new one. If `allow_same_chord_recommit = false`, re-committing the sounding chord logs `commit_ignored` |
| `gesture_reset`, or `state_change` → `inactive` | **Releases** the sounding chord (`release_on_interruption`, default true). Mutes the accompaniment if `on_interruption = "mute"` |
| `return_neutral` | Unmutes. Auto-starts the accompaniment the first time (if enabled) |
| `panic` (command, from the CLI or later the HUD) | Every note off, then CC 123 and CC 120 on the chord and click channels and `midiOutReset`. Accompaniment stopped, schedule cleared. The FSM is disabled until `instrument_enable` |

- **Every stop path** ends in `ChordEngine.close()`, which is idempotent: normal stop, Ctrl-C, end of replay, an exception while processing (`try/finally` in the CLI), and a consumer exception.
  - On a consumer exception, the pipeline guard calls `on_failure`, detaches the consumers, logs `consumer_error` and keeps recording.
  - After a backend send failure, only silencing messages are attempted.
- **Note pairing:** the engine tracks which notes are physically on, per channel and note, so each note-on gets exactly one note-off. Tests check this on every scenario.

## Default voicings and accompaniment

- **Chords:** C = 60 64 67, G = 55 59 62, Am = 57 60 64, F = 53 57 60 (MIDI notes; 60 = C4). Channel 1, velocity 100.
- **Accompaniment:** off by default. When enabled: 80 BPM (the protocol's candidate), 4/4, General MIDI wood blocks on channel 10 (accent on beat 1), 50 ms clicks.
  - Beat 0 is the production time of the first `return_neutral` (`auto_start`), or the time of an `accompaniment_start` command.
  - `on_interruption`: `"continue"` by default (it is a time reference), or `"mute"`.
- **Quantization:** off by default. When on, an onset moves to the next beat at or after the committing sample's production time. `scheduled_onset` logs the scheduled time; the raw commit time in `interaction_events.jsonl` is unchanged. An interruption before the onset cancels it (`scheduled_onset_cancelled`).

## Logs (schema 1.2.0)

| File | Deterministic | Content |
|---|---|---|
| `music_events.jsonl` | yes | `music_event_id`, `event_type`, the causing instrument event (`cause_event_id`, its type, `seq`, `produced_host_ns`, `input_host_ns`), `chord`, `notes`, `reason`, `scheduled_host_ns` |
| `music_timing.jsonl` | no, real-time runs only | every MIDI send: kind, bytes, `due`, `send_begin_host_ns`, `send_end_host_ns`, `lateness_ns`, **`estimated_software_latency_ns`** (send end − production time of the deciding sample), errors |

**Event types:** `midi_note_on`, `midi_note_off`, `scheduled_onset`, `scheduled_onset_cancelled`, `commit_ignored`, `accompaniment_start`, `accompaniment_stop`, `accompaniment_mute`, `accompaniment_unmute`, `panic`, `engine_stop`.

**Latency:** the estimated software latency covers neither the SDK filter, the synth nor the audio device. **Physical audio-output latency is not measured by the software** (2D, O4). Clicks and other sends are only in the timing log; the beat grid follows from `accompaniment_start` (`scheduled_host_ns`, `bpm`).

After a backend failure or a consumer exception, the engine's later decisions can differ from a replay. Those runs are recorded in the timing log and in `session.json` → `music_failed`.

## Commands

```bash
headmusic midi-devices
```

```bash
headmusic midi-test
```

```bash
headmusic replay <session> --instrument --speed 1
```

- `midi-devices` lists the Windows MIDI outputs. Device 0 is usually "Microsoft GS Wavetable Synth", which is audible but has noticeable, unmeasured latency.
- `midi-test` plays C, G, Am and F once (`--audio`, `--midi-device`, `--seconds`), with no glasses needed.
- `replay --instrument --speed 1` replays a recorded session **in real time with sound** through the instrument. The logged inputs are applied, so the decisions are the recorded ones.
- `headmusic replay <session> --reprocess --instrument` runs offline with no sound and checks both logs byte for byte.
