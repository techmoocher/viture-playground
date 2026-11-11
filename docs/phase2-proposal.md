# Phase 2 — Playable Four-Chord Instrument: Engineering Proposal

**Revision:** 2 (2026-11-11). It incorporates your Phase 2 brief (§0). Revision 1 is in this file's git history.
**Status:** approved direction. **2A implemented** (gesture FSM, logs, replay; see [instrument.md](instrument.md)); 2B–2D follow in order (§7).
**Scope:** a playable, real-time, head-controlled instrument with four chords (C, G, Am, F) on the Phase 1 pipeline. No comfort models, no participant calibration, no formal experiments and no ML (§8).

**Every angle, time and radius in this document and in `defaults.toml` is a provisional engineering default.** Each one is configurable and recorded in `session.json`. None is an ergonomic, comfort or safety claim, and none is validated. The fixture results from G0 describe the device on a table, **not** worn use or usability.

**Terminology** follows [conventions.md](conventions.md): head orientation relative to the tracking frame (`q_WH`) or to the neutral reference (`q_rel`). Directions are given as turn left/right, nose up/down and tilt. No anatomical terms.

---

## 0. Decision log (your Phase 2 brief, 2026-11-11)

| Decision | Where it lands |
|---|---|
| Phase 1 is validated enough to start Phase 2. Fixture measurements are not human usability measurements | §4.2; [threats-to-validity.md](threats-to-validity.md) TV12 |
| **Selection by configurable yaw target regions** relative to the calibrated neutral | §3.2. This replaces revision 1's geodesic target zones. Those stay a later option and are listed as a research question |
| Dwell activation with visual progress | §3.3, 2C |
| **Audible playback** with correct note-on/note-off | §5, 2B |
| A clear neutral (idle) state where the user can rest | §3.3 (`neutral`, `unarmed`, `inactive`) |
| Configurable targets, dwell, hysteresis and re-arming | §3.4 |
| Emergency stop / silence | §5.3 (`panic`) |
| Live feedback: tracking validity, selected chord, progress, sounding chord | 2C |
| Structured event logs for later analysis | §6 |
| Synthetic input and replay of recorded sessions | §6, every milestone |
| Docs and automated tests | each milestone (§7) |
| Reuse the Phase 1 modules; recognition is independent of acquisition and audio; an explicit FSM; quaternions internally | §2, §3 |
| Cancel pending gestures on invalid, stale or disconnected tracking, or on a neutral change; old queued data never triggers; re-arm deliberately; a fresh neutral after reconnect | §4 |
| Stop sounding notes on an interruption; define accompaniment behaviour | §5.3 |
| Separate timestamps: target entry, dwell start, recognition, commit, MIDI/audio dispatch, quantized onset. Estimated and measured latency kept apart | §6.2 |
| Four milestones 2A–2D with acceptance criteria and tests | §7 |
| The protocol stays unchanged; methodological questions go to the research docs | [research/phase2-open-questions.md](research/phase2-open-questions.md) |

---

## 1. Architecture

```
 acquisition (unchanged) ──► queue ──► [pipeline thread]
                                         raw writer → OrientationProcessor → processed writer
                                         TrackingGate.on_sample / on_event
                                         consumers (new, additive hook):
                                           InstrumentConsumer ──► GestureFSM (pure)  ──► InteractionEvents
                                                     │                                    │
                                                     ├─ logs live-only inputs              ├─► interaction log (deterministic)
                                                     │  (stale ticks, late processing)     └─► ChordEngine (2B) ──► OutputBackend
                                                     └─ gate.status(at sample arrival)                              (winmm MIDI | null)
                                         idle tick (≤ 20 ms) ──► consumers.on_tick(now)
 viewer / HUD (2C) reads snapshots only
```

| Package | Role | May import |
|---|---|---|
| `instrument/regions.py` | Yaw regions, neutral zone, the region coordinate, config validation | `types`, `orientation.quaternion` |
| `instrument/fsm.py` | `GestureFSM`: explicit finite-state machine; pure, reads no clock | the above, `tracking.gate` (for `GateStatus`) |
| `instrument/consumer.py` | Pipeline adapter: gate check, live/replay inputs, logging | the above |
| `instrument/log.py` | `interaction_events.jsonl`, `instrument_inputs.jsonl`, `interaction_timing.jsonl` | stdlib |
| `music/` (2B) | `ChordEngine` (chord table, note on/off pairing, accompaniment, panic) and backends | `instrument` event types only |
| `music/backends/winmm.py` (2B) | Windows MIDI out through `ctypes` | the **second hardware boundary**; imported only by the CLI |

- **Unchanged:** acquisition, processor, recording, replay, `TrackingGate`. The one change to existing code is an optional `consumers` list in `Pipeline`, plus a calibration-record callback. With no consumers, Phase 1 output is byte-identical; the existing tests check this.
- **The recogniser never touches sensors or audio.** It consumes `ProcessedSample` and `GateStatus`, and it emits events. The chord engine consumes those events and never sees samples.
- **The import-graph test** is extended: `instrument` must not import `acquisition`, `ctypes`, `tkinter`, `pipeline` or `music`; only `acquisition` and `music/backends` may use `ctypes`.

### Dependencies

| Need | Choice | New dependency |
|---|---|---|
| Recognition, logging, replay | stdlib + existing code | none |
| MIDI output | `winmm.midiOutShortMsg` via `ctypes` (Windows built-in) | none |
| Audible sound | The built-in "Microsoft GS Wavetable Synth" (default MIDI device), or any synth on a user-chosen MIDI port | none |
| Lower-latency built-in sound (optional, later) | numpy synthesis + `sounddevice` (PortAudio/WASAPI) as an optional extra | one optional package, only if the built-in synth's latency proves inadequate (O4) |
| HUD | `tkinter`, already used by the viewer | none |

---

## 2. Inputs to the recogniser and determinism

| Input | Deterministic? | Handling |
|---|---|---|
| Processed samples, with the gate status evaluated at the sample's arrival time (`now = host_rx`) | yes | Recomputed identically on replay |
| `device_connected` / `device_disconnected` | yes | Already recorded and replayed |
| Commands: `capture_neutral`, `instrument_enable`, `instrument_disable`, `panic` | yes | Recorded in `commands.jsonl` with `after_seq` |
| Neutral-capture results | yes | Regenerated by the processor on replay |
| **Stale tick:** the gate becomes unusable *between* samples (pause, PC sleep) | live timing | Logged in `instrument_inputs.jsonl` at its position (after `seq` *s*, after *k* further items), and re-injected there on replay |
| **Late processing:** the pipeline thread handles a sample more than `T_stale` after it arrived | live timing | Logged and re-applied the same way |

The FSM reads no clock: dwell and cooldown are measured in device time within one connection. **Replaying a recorded session reproduces `interaction_events.jsonl` byte for byte** (protocol gate G1).

---

## 3. Chord selection: yaw regions and the state machine

### 3.1 The region coordinate (from quaternions, documented)

- `f = rotate(q_rel, (1, 0, 0))`: the glasses' forward axis expressed in the neutral head frame.
- **`yaw_rel = atan2(f_y, f_x)`**: the heading of the forward axis in the neutral frame's horizontal plane. +yaw = turn left, as in conventions.md.
- `elev = asin(f_z)`: how far the forward axis points above (+, nose up) or below (−, nose down) that plane.
- **This is exactly the display yaw of the Z-Y′-X″ convention** (same formula), so the HUD shows the value that is used. It is computed by rotating a vector with the quaternion, and it is independent of tilt. Pitch and roll are not used.
- **Eligibility:** a sample counts for regions and the neutral only if `|elev| ≤ max_elevation_deg`. The default 89° is a numeric guard against an undefined heading, not a limit on movement. Whether a tighter value is wanted is a research question.

### 3.2 Regions

- Each chord has a yaw interval `[yaw_min, yaw_max]`. The neutral zone is `|yaw_rel| ≤ neutral_yaw_deg`.
- **Hysteresis `h`:** a sample *enters* a region inside `[yaw_min, yaw_max]` and *stays* while inside `[yaw_min − h, yaw_max + h]`. The neutral zone likewise enters at `neutral_yaw_deg` and leaves beyond `neutral_yaw_deg + h`.
- **Validation:** regions may not overlap. Neighbouring regions must be more than `h` apart, so a region is always left before the next is entered. Every region must begin beyond the neutral exit (`neutral_yaw_deg + h`). Each chord appears once.
- Yaw-only regions are a Phase 2 simplification of the protocol's per-chord target orientations `q_i` (protocol §6). See the research questions.

### 3.3 State machine (`GestureFSM`)

| State | Meaning | Transitions |
|---|---|---|
| `inactive` | Disabled, after `panic`, or the gate is not usable (reason shown) | → `unarmed` on the first usable, fresh sample (when enabled) |
| `unarmed` | After any reset: waiting for the neutral zone | → `neutral` after `rearm_hold_ms` inside the neutral zone |
| `neutral` | Idle and armed. Resting here never plays anything | → `aiming` on leaving the neutral zone |
| `aiming` | Out of neutral, in no region, or in a region while the cooldown runs | → `dwell_armed(i)` on entering region *i* (cooldown over) · → `neutral` on re-entering it |
| `dwell_armed(i)` | In region *i*; progress = elapsed device time / `dwell_ms` | → `return_to_neutral` (commit) when elapsed ≥ `dwell_ms` · → `aiming` on leaving the region (dwell cancelled) |
| `return_to_neutral` | Chord *i* committed. No new selection until the neutral zone is re-entered | → `neutral` (after `rearm_hold_ms` in the zone) |

The protocol's `committed` state is the instant of the commit. It is logged as the `dwell_complete` and `raw_commit` events on that sample.

**Repeat and switching rules:**
- **No repeated activation from one pose:** after a commit, staying in, or returning to, any region does nothing until the neutral zone is entered.
- **Target switching:** moving from region A to region B while dwelling cancels A, so B's dwell starts from zero.
- **Rapid movement:** passing through a region faster than `dwell_ms` commits nothing.
- **Cooldown:** no dwell starts within `cooldown_ms` of the last commit, even after a fast return to neutral.
- **Same chord again:** after returning to neutral, the sounding chord can be committed again (`allow_same_chord_recommit`). The chord engine re-triggers it.

### 3.4 Provisional defaults (`[instrument]` in `defaults.toml`)

| Parameter | Default | Basis |
|---|---|---|
| Regions (+ = left) | C `[+22, +40]`, G `[+8, +18]`, Am `[−18, −8]`, F `[−40, −22]` (degrees `yaw_rel`) | **Bench layout only**: clear separation for testing by hand or on a fixture. Not an ergonomic layout |
| `neutral_yaw_deg` | 4.0 | Engineering; below the nearest region |
| `hysteresis_deg` | 1.5 | Engineering. G0 fixture jitter (≈ 0.0008° RMS) is far below it, so it addresses movement near a boundary, not sensor noise. Worn behaviour is unmeasured (O3) |
| `dwell_ms` | 500 | Middle of the protocol's 400–600 ms candidate range, which the protocol says must be piloted and frozen |
| `cooldown_ms` | 300 | Placeholder; the protocol names a cooldown but gives no value |
| `rearm_hold_ms` | 0 | Entering the neutral zone re-arms. Any hold is a research choice |
| `max_elevation_deg` | 89.0 | Numeric guard (§3.1) |
| `reset_on_gap_before` | true | §4.1 |
| `allow_same_chord_recommit` | true | §3.3. Implemented in the chord engine (2B, `[music]`): the FSM always reports the commit |
| `start_enabled` | true | — |

---

## 4. Safety and robustness

### 4.1 Reset rule

A **reset** cancels any dwell and forgets the region. It moves to `inactive` (gate unusable or disabled) or `unarmed` (usable), and it logs `gesture_reset` with its reason. The next commit then needs a deliberate return to neutral. So a head that rests in a region through a pause, a reconnect or a recenter cannot commit when tracking returns.

| Trigger | Reason |
|---|---|
| Gate unusable on a sample at its arrival time: `disconnected`, `no_valid_sample`, `last_sample_invalid`, `stale`, `no_neutral` | the gate's reasons |
| Gate unusable between samples (logged live input) | `stale_tick` |
| Disconnect or connect event; a sample from another `connection_id` | `disconnect`, `new_connection` |
| `neutral_calibration_id` changed (new reference frame) | `new_neutral` |
| `capture_neutral` requested: stays `inactive` until the capture is accepted or rejected | `neutral_capture` |
| `gap_before` on a sample, even below `T_stale` | `gap` |
| Late processing (logged live input) | `late_processing` |
| `instrument_disable`, `panic`, end of stream | `disabled`, `panic`, `stop` |

**Old queued data cannot trigger anything after an interruption.** Every reset sets a *freshness watermark* on the host timebase. Samples whose estimated production time (the gate's `device_ts + o_min`) is not later than the watermark cannot arm or advance the FSM. With the gate's data-age check, this covers samples that were already queued, delivered late after a PC sleep (G0 R9), or processed late.

A reconnect always needs a new neutral: the processor already gives a new connection no neutral, so the gate reports `no_neutral`, which keeps the FSM `inactive` until a capture on the new connection is accepted.

### 4.2 G0 findings and the design response

| Finding (fixture, not worn) | Response |
|---|---|
| Device pauses of ≈ 300/600 ms | Live: a stale tick resets the FSM and releases sound within ≈ `T_stale` + 20 ms of the last production. The next sample carries `gap_before` and resets again |
| ≈ 50 ms gap after (re)connecting | Reset by `reset_on_gap_before`; the new connection has no neutral anyway |
| Cable movement → disconnect, power cycle | Reset, release, `inactive` until a new neutral is accepted (O5 for blocks) |
| Device clock restarts per connection | Dwell compares device times only within one connection; logged times also carry the host-timebase production estimate |
| Late samples after a PC sleep | Stale by data age; freshness watermark; the app asks Windows not to sleep while it runs (per process, released on exit) |
| Duplicate timestamps (invalidating) | A dwell is interrupted: ≈ 5 % of 500 ms dwells at 240 Hz requested, 0.5–1.3 % at 60–120 Hz (fixture rates, assumed independent). Kept strict pending the research decision |
| Strong SDK smoothing, unknown filter lag | Adds unmeasured lag before the dwell starts and to the latency budget. No prediction is applied (a methodology choice) |
| Achieved rates 59.4 / 84.6 / 112.3 / 202.5 Hz | Dwell is in time, never in sample counts. Commit granularity is one sample period (4.9 ms at 240 Hz requested); 240 Hz stays the default |

**Worn latency and jitter are unknown.** Nothing here assumes the fixture values hold when the glasses are worn.

---

## 5. Music engine (2B)

### 5.1 Chords and MIDI

- MIDI channel 1, velocity 100 (configurable). Voicings: C = C4 E4 G4, G = G3 B3 D4, Am = A3 C4 E4, F = F3 A3 C4.
- A commit sends note-off for the sounding chord, then note-on for the new one. The engine keeps the set of sounding notes, so every note-on has exactly one note-off.

### 5.2 Accompaniment (optional, off by default)

- A fixed-tempo click on MIDI channel 10 (default 80 BPM, the protocol's *candidate*), optionally with beat quantization of chord onsets.
- With quantization on, the raw commit time is still logged, and the scheduled onset is logged separately.

### 5.3 Interruptions and emergency stop

| Situation | Chord | Accompaniment |
|---|---|---|
| Interruption (any reset, §4.1) | **Released** (note-off), default `release_on_interruption = true` | **Continues** by default (`accompaniment.on_interruption = "continue"`; `"mute"` available). It is a time reference, not a head-controlled command |
| `panic` (key, button, CLI) | All notes off, plus MIDI CC 123 "all notes off" on every used channel | Stopped |
| Normal stop, Ctrl-C, exception, end of replay, backend error | All notes off | Stopped |

Releasing is always allowed: it stops sound and selects nothing. Release versus hold during short pauses, and the accompaniment behaviour, are research questions. The defaults above are engineering choices.

---

## 6. Logging and timing

### 6.1 Files (schema 1.2.0, additive)

| File | Content |
|---|---|
| `interaction_events.jsonl` | **Deterministic** FSM and engine decisions: `event_id`, `event_type`, `seq`, `connection_id`, `neutral_calibration_id`, `device_ts_raw`, `host_rx_monotonic_ns`, `produced_host_ns`, `state`, `chord`, `region`, `reason`, `dwell_elapsed_ms`, `mapping_version` |
| `instrument_inputs.jsonl` | Live-only inputs (§2) with their positions |
| `interaction_timing.jsonl` | **Non-deterministic:** processing time of each decision, MIDI send times before and after each call, backend errors. Joined by `event_id` and never compared on replay |
| `session.json` | `instrument` (and in 2B `music`) section: the full parameter snapshot, regions, `mapping_version` (a hash), backend and port |

### 6.2 Timestamps per chord selection

| Moment | `event_type` | Timestamp(s) |
|---|---|---|
| Target entry | `aim_enter` | deciding sample: `device_ts_raw`, `host_rx`, `produced_host_ns` |
| Dwell initiation | `dwell_start` | same fields (it may be later than entry, because of the cooldown) |
| Gesture recognition | `dwell_complete` | same fields, plus `decision_host_ns` (processing time, timing log) |
| Chord commitment | `raw_commit` | same sample; the protocol's unquantized commit |
| MIDI dispatch | `midi_note_on` / `midi_note_off` (2B) | `send_begin_host_ns`, `send_end_host_ns` (timing log) |
| Quantized onset | `scheduled_onset` (2B, only when quantizing) | scheduled host time |
| Audio output | — | **Not measured** by the software. A *measured* physical latency needs an external method (2D, O4). Reports always label software-side values `estimated` |

Software-estimated latency is `send_end − produced_host_ns`. It excludes the SDK filter lag, the synth and the audio device.

---

## 7. Milestones and acceptance criteria

### 2A — Gesture selection and state machine (no audio)

| # | Criterion | Test |
|---|---|---|
| 2A-1 | The FSM implements §3.3 exactly; regions and neutral use the §3.1 coordinate with hysteresis | Unit tests per transition; coordinate equals display yaw on a grid |
| 2A-2 | **Every reset trigger of §4.1, injected in every state** (including one sample before a dwell completes), commits nothing, logs the reason, and requires a return to neutral, even if the head stays in a region | Synthetic fault matrix |
| 2A-3 | Repeated dwell, target switching, passing through and cooldown behave as in §3.3 | Synthetic motion scripts |
| 2A-4 | Invariant on every test trace and on seeded random fault traces: each commit follows an unbroken, gate-usable, fresh, in-region run of ≥ `dwell_ms` on one connection and one neutral, which started after a neutral visit | Invariant checker |
| 2A-5 | Live-simulated run (with stale ticks and late processing) and offline replay give byte-identical `interaction_events.jsonl`; Phase 1 outputs unchanged without consumers | Replay tests |
| 2A-6 | Invalid configs are rejected with a clear message; the full parameter set is in `session.json` | Config tests |
| 2A-7 | The import-graph rules of §1 hold | Architecture test |
| 2A-8 | `synth chords` and `replay <session> --reprocess --instrument` produce sessions with interaction logs | CLI tests |

### 2B — Music/MIDI engine

| # | Criterion | Test |
|---|---|---|
| 2B-1 | Correct chord voicings; every note-on paired with one note-off; re-trigger of the same chord | Fake backend |
| 2B-2 | Release on interruption and accompaniment behaviour as in §5.3; `panic` silences everything | Fake backend with the 2A fault matrix |
| 2B-3 | All notes off on every stop path (normal, Ctrl-C, exception in FSM or engine, backend error) | Fault injection |
| 2B-4 | Timing log carries send times; optional quantization logs raw and scheduled times separately | Unit tests |
| 2B-5 | Audible output through the default Windows MIDI synth from a **replayed** session (no glasses) | Manual check you approve |

### 2C — Integrated visual application

| # | Criterion | Test |
|---|---|---|
| 2C-1 | `headmusic play` (live) and `replay --instrument --view`: HUD with regions, `yaw_rel` cursor, neutral zone, dwell progress, selected and sounding chord, gate status and reason, FSM state | Text/state tests for the HUD model; manual check from replay |
| 2C-2 | Emergency-stop key and button; enable/disable; neutral capture and retry as in the viewer | Command tests |
| 2C-3 | The HUD never decides anything; it reads snapshots only | Architecture test |

### 2D — Hardware and usability smoke tests

| # | Criterion | Condition |
|---|---|---|
| 2D-1 | Live bench run with the glasses on the table or handled by hand (not worn): turns select chords, pauses and an unplug reset safely, sound stops | Each run's setup approved by you first, as in G0 |
| 2D-2 | Software-side timing report (estimated latency distribution) | Same |
| 2D-3 | A physical audio-output latency measurement | Needs a method and a target (O4) |
| 2D-4 | Worn smoke tests and any usability impression | **Only after faculty/IRB guidance (O3).** No participants |

---

## 8. Out of scope (Phase 2)

Comfort, effort or discomfort models (B, C), the optimiser and the Model A layout; participant calibration and ratings; formal experiments (cues, scored blocks, counterbalancing, statistics); ML; trigger gestures, roll modulation, continuous control; torso tracking; world-anchored UI.

---

## 9. Open items

The methodological questions, with the engineering defaults used meanwhile, are in [research/phase2-open-questions.md](research/phase2-open-questions.md). Blocking or affecting Phase 2:

| # | Item | Effect |
|---|---|---|
| **O3** | Developer self-testing while worn | Blocks 2D-4 and showing the HUD in the glasses |
| **O4** | Timing precision target | Decides whether the built-in synth is adequate, and the 2D-3 method |
| **O5** | Disconnects during a block | Instrument behaviour is defined (§4); block behaviour is not |
| **O6** | `tau_stab_deg` | How easily a neutral is re-captured after a reconnect |
| Duplicate timestamps | Stay invalidating? | ≈ 5 % of dwells interrupted at 240 Hz requested (§4.2) |
| **O1** | Research report missing | Re-check §3 and §5 when it arrives |
