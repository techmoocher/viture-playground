# Phase 2 — Basic Four-Chord Instrument: Engineering Proposal

**Revision:** 1 (2026-11-11). **Status:** proposal for your review. **Nothing in it is implemented.** Implementation starts only after you approve it, with your decisions on §9.
**Scope:** a basic, head-controlled four-chord instrument built on the Phase 1 pipeline, tested on the bench and with synthetic and replayed data. No experiment, no participants, no comfort model (§8).

| Input | Status |
|---|---|
| Protocol v1.0 (`docs/research/Head_Controlled_Music_Experiment_and_Calibration_Protocol_v1.md`) | Read in full. §6 (chord layout, state machine), §8 (interaction outcomes), §10.3 (`interaction_events`), §11 (gates G1, G2, technical tests) apply directly |
| [phase1-proposal.md](phase1-proposal.md) (D1–D7, O1–O6) | Read. D2 ("invalid or stale tracking must never trigger musical commands") is the central constraint |
| [bench-report.md](bench-report.md) (G0) | Read. Findings used in §4 |
| [conventions.md](conventions.md), [quality-and-metrics.md](quality-and-metrics.md), [threats-to-validity.md](threats-to-validity.md), [data-format.md](data-format.md) | Read; authoritative for frames, flags, gate and file formats |
| Code in `src/headmusic/` | Read: `tracking/gate.py`, `pipeline.py`, `orientation/processor.py`, `acquisition/replay_source.py`, `acquisition/synthetic.py`, `recording/writer.py`, `viewer/app.py`, `cli.py` |
| Research report (O1) | **Still missing.** This proposal must be re-checked against it when it arrives |

**Terminology.** As in Phase 1: head orientation *relative to the tracking frame* (`q_WH`) and *relative to the neutral reference* (`q_rel`). Directions are described as "turn left/right", "nose up/down" and "tilt right/left side down", in the display convention of conventions.md. No anatomical terms.

**Every angle, time and radius in this document is a provisional engineering default** to be set by the research team. None is an ergonomic, comfort or safety claim, and none is presented as validated.

---

## 1. Summary

- A new package `headmusic.instrument` plugs into the existing pipeline as a **consumer** of processed samples, events and commands. Acquisition, processing (`quat_rel`), recording, replay and `TrackingGate` are reused unchanged. The pipeline gains one small, additive hook (a consumer list, §2.2).
- Chord selection uses the protocol's **single dwell-to-commit state machine** (`neutral → aiming → dwell-armed → committed → return-to-neutral → neutral`, protocol §6). Targets are four neutral-relative quaternions; a sample is "on" a target by **geodesic angle**, with hysteresis. A trigger gesture is listed as an option but not proposed (protocol §6 makes it a future extension).
- **Safety rule:** the recogniser re-checks the gate on every sample. Any interruption (gate unusable, connection change, new neutral, neutral capture in progress) resets the gesture state and requires a fresh return to neutral before anything can be committed again.
- **Determinism:** the recogniser is a pure function of its inputs. Its only time-dependent live input (an interruption detected between samples) is logged at its `seq` position, like an operator command, and re-injected on replay. Replayed decisions are then byte-identical to live ones.
- **Output:** chord events go to a backend interface. Proposed baseline: Windows' built-in MIDI API (`winmm`) through `ctypes`, with no new dependency, plus a null/log backend for tests. Audio synthesis is optional and later.
- **Blockers:** wearing the glasses to try the instrument waits for **O3**. Everything else in this proposal can be built and tested without anyone wearing them.

---

## 2. Reuse and integration

### 2.1 What is reused, unchanged

| Component | Role in Phase 2 |
|---|---|
| `acquisition/` (`VitureSdkSource`, capture shim, `ReplaySource`, `SyntheticSource`) | Unchanged. Still the only package that touches the glasses' DLL |
| `orientation/OrientationProcessor` | Unchanged. Supplies `ProcessedSample.quat_rel` (= `conj(q0) ⊗ q_WH`, canonical `w ≥ 0`), `valid`, `flags`, `connection_id`, `neutral_calibration_id` |
| `tracking/TrackingGate` | Unchanged. The **only** source of "usable for control" (data-age staleness, validity, connection, neutral) |
| `recording/SessionWriter` | Unchanged for existing files. The instrument writes its own files next to them (§5.4) through the same flush policy |
| Neutral capture (`capture_neutral` command, stability check, retries) | Unchanged. The instrument never captures a neutral itself; it reacts to the result |
| Viewer | Reused as the host for a HUD panel (§3.6); its existing status display stays |

### 2.2 How it plugs in

```
 acquisition ──► queue ──► [pipeline thread] ──► raw writer → processor → processed writer
                                                        │
                                                        ├─► gate.on_sample(ps)
                                                        │
                                                        └─► consumers: instrument.on_sample(ps, gate.status(ps.host_rx))  ← new hook
                              events  ──► gate.on_event ──► instrument.on_event(e)
                              commands ──► processor     ──► instrument.on_command(c)
                              idle tick (queue timeout, ≤ 20 ms) ──► instrument.on_tick(gate.status(now))
                                                        │
                                       instrument ──► InteractionEvents ──► interaction writer
                                                                       └──► output backend (MIDI / null)
```

- **The one change to existing code:** `Pipeline` accepts an optional list of consumers and calls them after the gate, in the pipeline thread. Today it calls `gate.on_sample` directly and has no consumer list (Phase 1 §4 rule 7 named the extension point but did not build it). About 20 lines, additive; Phase 1 behaviour and outputs are unchanged when the list is empty, and the existing replay byte-identity tests guard that.
- **Acquisition stays separate from processing.** The instrument never imports `acquisition`, ctypes for the glasses, or the DLL. The import-graph test gains: `instrument` may import `types`, `orientation.quaternion` (math only) and `tracking`; `instrument.output` is the second, separate hardware boundary (it touches `winmm.dll`), and nothing but the CLI imports it.
- **One thread, one order.** The instrument runs in the pipeline thread, so it sees samples, events and commands in exactly the order they were processed and recorded. That order is what replay reproduces.
- **Same entry points.** `headmusic play` (live) and `headmusic replay <session> --instrument` (offline or real time) build the same pipeline with the instrument as a consumer.

### 2.3 Inputs the recogniser sees

| Input | Content | Deterministic? |
|---|---|---|
| `on_sample(ps, gs)` | Processed sample and the gate status evaluated at `now = ps.host_rx_monotonic_ns`, i.e. the data age at arrival | Yes: both depend only on recorded samples and events |
| `on_event(e)` | `device_connected`, `device_disconnected` | Yes: already recorded and replayed |
| `on_command(c)` | `capture_neutral` (start of a capture), instrument commands (`instrument_enable`, `instrument_disable`, `all_notes_off`) | Yes: recorded in `commands.jsonl` with `after_seq` |
| `on_tick(gs)` | Live only: the gate became unusable *between* samples (a pause, a PC sleep) | **No, live timing.** So each tick that changes the recogniser's state is **logged as an input** with `after_seq` and re-injected on replay (§5.3). Ticks that change nothing are not logged |
| `on_late_processing` | Live only: the pipeline thread processed a sample more than `T_stale` after its arrival (for example a long Python pause) | No. Same treatment: the suppression is logged as an input and replayed (§4.2) |

The recogniser reads no clock. Its only notion of time is the sample timestamps (§3.4).

---

## 3. Head-pose-to-chord mapping

### 3.1 What the protocol fixes

From protocol §6, followed here without change:
- Four chords: **C major, G major, A minor, F major**; deterministic MIDI chord-on/chord-off events; optional software synthesis.
- Input is **neutral-relative head rotation**; computation uses **quaternions** (protocol §0, §2.2). Euler angles are for display only.
- **One shared state machine:** `neutral → aiming → dwell-armed → committed → return-to-neutral → neutral`, with dwell, hysteresis and cooldown. Dwell candidate **400–600 ms**, "calibrated through a separate pilot" (protocol §6, §11).
- **No repeated nodding** to play beats; a **return-to-neutral gate** before the next commit.
- Targets are **stable for a whole block**; a minimum **geodesic** separation between targets.
- A **head-locked HUD** with target names, cursor, selection progress and a neutral indicator; not world-anchored, not gaze.
- Nod trigger, roll modulation, beat-synchronous chords and continuous pitch bend are **future extensions** (protocol §6).
- Record the **unquantized** commit time; quantization is optional and separate.

Target placement by Models A/B/C and the optimiser is experiment work (§8). Phase 2 takes the four targets from a **configuration file**.

### 3.2 Options for selecting a chord

| Option | How it works | For | Against | Protocol |
|---|---|---|---|---|
| **S1. Geodesic target zones (proposed)** | Each chord has a target quaternion `t_i` (relative to neutral). The sample is in zone *i* if `θ(q_rel, t_i) ≤ r_enter`; it leaves when `θ > r_exit` (`r_exit > r_enter`, hysteresis). Nearest target wins if two qualify (cannot happen when separation > 2·r_exit, which config validation enforces) | Parameterisation-free; sign-invariant; matches the protocol's geodesic separation and the optimiser's `q_i` per chord; works for any target set B/C might produce later | Includes roll (tilt) in the distance, which the 2-D cursor cannot show (see §3.5) | Consistent |
| S2. Euler boxes | Zone = yaw/pitch/roll intervals from display Euler | Easy to explain and draw | Uses Euler for computation, which the protocol reserves for display; boxes distort away from neutral; TV1 parameterisation issue | **Conflicts** with protocol §0/§2.2. Not proposed |
| S3. Direction sectors | Zone = the direction in which the forward axis moved (angle in the "turn / nose" plane) beyond a minimum angle | Few parameters; four sectors suit four chords | Not a target per chord, so it does not fit the optimiser's `q_i` per chord; ignores roll entirely | Partial fit; would need research-team agreement |
| S4. Forward-axis distance | Like S1, but the angle between the rotated forward axes (ignores tilt about the forward axis) | Matches what the 2-D cursor shows | Two poses differing only by tilt are the same target; a different separation metric than the protocol's quaternion geodesic | Open question for the research team (§9, P2) |

### 3.3 Options for triggering (committing) a chord

| Option | How it works | For | Against | Protocol |
|---|---|---|---|---|
| **T1. Dwell (proposed)** | Commit when the sample stays in the same zone for `T_dwell` of device time | Single mechanism, no extra movement; the protocol's choice | Adds `T_dwell` to selection time; Midas-touch risk from incidental holds, mitigated by the neutral gate | The protocol's state machine |
| T2. Trigger gesture (nod or short return movement) | Select by zone, confirm with a quick gesture | Faster, fewer false activations from holds | Repeated nodding is ruled out by protocol §6; more movement; needs a gesture detector and its own thresholds | Future extension (§6); §12 item 2 leaves it open. **Not proposed** |
| T3. Dwell + confirmation | Dwell arms; a small confirmation commits | Lowest false activation | Most complex; same objection as T2 | §12 item 2: "Do not change only one condition". Not proposed |
| T4. Zone entry, no dwell | Commit on entering a zone | Fastest | Every passage through a zone commits | Contradicts the dwell state machine. Not proposed |

### 3.4 Proposed state machine (S1 + T1)

States follow the protocol; `unarmed` is added as the state after any reset (it is the protocol's `return-to-neutral` with nothing sounding committed in this attempt).

| State | Meaning | Leaves to |
|---|---|---|
| `inactive` | Instrument disabled, or gate not usable | `unarmed` when the gate becomes usable |
| `unarmed` | After any reset: waiting for the head to be in the neutral zone | `neutral` when `θ(q_rel, 1) ≤ r_neutral` |
| `neutral` | In the neutral zone; armed | `aiming` when `θ(q_rel, 1) > r_neutral_exit` |
| `aiming` | Out of neutral, in no target zone | `dwell-armed` on entering zone *i*; `neutral` on re-entering the neutral zone |
| `dwell-armed(i)` | In zone *i*; dwell timer running from the first in-zone sample `d_start` | `committed(i)` when `d − d_start ≥ T_dwell`; `aiming` when leaving the zone (`> r_exit`) |
| `committed(i)` | Chord *i* committed: `raw_commit`, then chord-on (previous chord off) | `return-to-neutral` immediately |
| `return-to-neutral` | Chord sounds; no new selection possible until the neutral zone is entered and `T_cooldown` has passed since the commit | `neutral` |

Rules:
- **Dwell time is device time** (`device_ts_raw` differences within one connection). It is deterministic, measures production rather than delivery, and the device clock restart on reconnect does not matter because a reconnect resets the state anyway.
- **A commit needs an unbroken run** of samples, all with the gate usable, all in zone *i*, on the same `connection_id` and `neutral_calibration_id`, spanning `T_dwell`. This invariant is what the tests check (§6).
- **Commit granularity is one sample period** (4.94 ms at 240 Hz requested, 16.8 ms at 60 Hz; G0). The default remains 240 Hz requested.
- **Same chord again:** after a return to neutral, committing the chord that is already sounding re-triggers it (chord-off, chord-on). Prompted selection may need a commit even for a repeated chord. Open point P5 (§9).
- **Chord-off** happens on the next commit, on `all_notes_off`, on stop, and (proposed default) on any interruption (§4.3, P1).

### 3.5 Provisional engineering defaults

Each value goes into `defaults.toml` under `[instrument]`, is copied into `session.json`, and is labelled there as a provisional engineering default.

| Parameter | Default | Basis |
|---|---|---|
| `targets` | C: turn left 20°; G: turn right 20°; Am: nose up 15°; F: nose down 15°. All other components 0. Stored as quaternions built once from the display convention (conventions.md), with the definition kept in the config | **Chosen only so that targets are clearly separated for bench testing by hand or on a turntable fixture.** Not an ergonomic layout; the protocol's layout comes from Model A/B/C (§8) |
| `r_enter_deg` / `r_exit_deg` | 7° / 9° | Engineering: smallest separation in the default layout is ≈ 25° (between a turn and a nose target), so `2·r_exit` = 18° leaves margin. Config validation rejects any layout with separation ≤ `2·r_exit` |
| `r_neutral_deg` / `r_neutral_exit_deg` | 4° / 5° | Engineering; must be well below the target distance |
| `dwell_ms` | 500 | Middle of the protocol's 400–600 ms candidate range, which the protocol says must be piloted and frozen first |
| `cooldown_ms` | 300 | Placeholder; the protocol names a cooldown but no value |
| `release_on_interruption` | `true` | See §4.3 and P1 |
| `reset_on_gap_before` | `true` | See §4.2 and P3 |

Sensor noise does not drive these values. The G0 fixture jitter is about 0.0008° RMS, four orders of magnitude below any radius here, so hysteresis is for **movement near a boundary**, not for noise. Worn behaviour is uncharacterised (O3).

### 3.6 HUD (minimal)

- A panel in the existing tkinter viewer: neutral marker, four target circles with chord names, a cursor, dwell progress, the current chord, and the gate status with its reason.
- **Cursor:** where the forward axis of `q_rel` points, projected onto the panel (display only). Tilt (roll) is shown as a separate small indicator, because S1 counts it (§3.2).
- **Head-locked display:** the VITURE Pro is itself a display, so showing the viewer on the glasses gives a head-locked HUD without any 3-D rendering. Doing that means wearing them: **blocked by O3**. On the bench the panel is shown on the PC screen.
- The HUD reads the recogniser's state snapshot; it never decides anything.

---

## 4. Safety and robustness

### 4.1 Reset rule

**Reset** = cancel any dwell, discard the zone, go to `inactive` (gate unusable) or `unarmed` (gate usable), and emit a `gesture_reset` event with its reason. After a reset, a commit needs a return to the neutral zone first, so a head already resting in a target zone after a pause, a reconnect or a new neutral cannot commit.

| Trigger | Detected by | Reason code |
|---|---|---|
| Gate not usable on a sample (`disconnected`, `no_valid_sample`, `last_sample_invalid`, `stale`, `no_neutral`) | `gs.usable` with `now = host_rx` | the gate's reasons |
| Gate becomes unusable between samples (pause, sleep) | `on_tick` (live), replayed input | `stale_tick` |
| `device_disconnected` / `device_connected` | event | `disconnect` / `new_connection` |
| `connection_id` differs from the dwell's | sample | `new_connection` |
| `neutral_calibration_id` differs from the dwell's (new neutral = new reference frame) | sample | `new_neutral` |
| `capture_neutral` requested (the instrument stays `inactive` until the capture is accepted or rejected) | command | `neutral_capture` |
| `gap_before` on a sample, even if below `T_stale` | sample flag | `gap` |
| Late processing in the pipeline thread | live guard, replayed input | `late_processing` |
| `instrument_disable`, stop, end of replay | command / shutdown | `disabled` / `stop` |

**No musical command fires on invalid or stale tracking.** "Command" here means a selection: `dwell_start`, `raw_commit` and chord-on. A **release** (chord-off, all-notes-off) is always allowed, because it stops sound rather than selecting it. That reading of D2 is P1 in §9.

### 4.2 G0 findings and how the design handles each

| G0 finding | Consequence | Design response |
|---|---|---|
| **Device pauses of ≈ 300 or 600 ms** (cause unknown; R6a, R6c, R9) | The device produces nothing; the gate goes stale after 100 ms | Live: the idle tick (≤ 20 ms granularity) sees `stale` → reset and (default) chord-off within about `T_stale` + 20 ms of the last production. On the next sample, `gap_before` resets again, so the decision on the sample stream does not depend on tick timing. A dwell can never complete across a pause |
| **Short gap ≈ 50 ms 2–3 s after each (re)connect** (R7, R8) | Below `T_stale`, so the gate stays usable | `reset_on_gap_before = true` resets anyway. Cost is low: a new connection needs a new neutral first, and untouched fixture runs had 0 gaps in 35 min. Whether sub-stale gaps should reset is P3 |
| **Cable movement can disconnect** (11 s outage, power cycle; R8) | `device_disconnected`, then a new connection with no neutral | Reset, chord-off, `inactive` until a new neutral is accepted on the new connection. The instrument shows "re-capture neutral". What a *scored block* does is O5 |
| **Device clock restarts per connection** (R7) | Device times of different connections are not comparable | Dwell uses device time only within one connection; every interaction event also carries the host-timebase production time (`device_ts + o_min`, as the gate estimates it), which is comparable across connections |
| **Late samples after a PC sleep** (29.9 s late, then a burst up to 316 ms late; R9) | Old data arrives as if new | The per-sample gate check uses data age, so these samples are `stale` and reset the state; no dwell can start until arrivals are < 100 ms late. `headmusic play` also asks Windows not to sleep while it runs (`SetThreadExecutionState`, a per-process request, not a settings change) |
| **Duplicate timestamps** (0.01–0.05 %, invalidating) | `last_sample_invalid` for one sample | Resets the dwell. Expected cost, from G0 fixture rates, assuming independence: a 500 ms dwell is interrupted with probability ≈ 5 % at 240 Hz (61 in 600 s), ≈ 1.3 % at 120 Hz, ≈ 0.5 % at 90 Hz and ≈ 0.8 % at 60 Hz. The user sees the dwell restart. This is the "duplicate timestamps" decision (§9) |
| **Strong SDK smoothing, unknown filter latency** (TV4) | `q_rel` lags the head by an unknown amount; overshoot settles slowly | The lag adds to selection time and to the latency budget (§5.2) and cannot be measured with the glasses alone. Hysteresis tolerates slow settling near a boundary. No compensation (prediction) is proposed: it would change what the user sees and is a methodology choice |
| **Achieved rates 59.4 / 84.6 / 112.3 / 202.5 Hz** (TV10) | Fewer samples per dwell than nominal | Dwell is measured in time, never in sample counts. At 202.5 Hz a 500 ms dwell spans ≈ 101 samples; at 59.4 Hz ≈ 30. Default stays 240 Hz requested |
| **Late processing** (TV6: Python-side latency unmeasured) | A sample may be acted on long after it arrived | Live guard: if `now − host_rx > T_stale` when the pipeline handles a sample, the instrument treats it as stale and logs a `late_processing` input, which replay re-applies. The pipeline's maximum queue depth is already logged |

### 4.3 What happens to a sounding chord on an interruption

- **Proposed default: release.** An interruption sends chord-off, so sound never continues on tracking the system no longer trusts, and the silence makes the loss audible.
- **Alternative: hold.** The chord keeps sounding until the next valid commit or stop, so a 300 ms pause does not cut the music.
- Either way, no new chord can start until tracking is usable and the head has returned to neutral. The choice affects what a participant hears during the G0 pauses, so it is the research team's (P1, together with O5).
- **On every stop path** (normal stop, Ctrl-C, exception, end of replay, output backend error), all-notes-off is sent and logged. This is protocol §11's "MIDI note-off on termination" test.

---

## 5. Audio and MIDI output

### 5.1 Options (minimal dependencies first)

| Option | Dependencies | Latency | For | Against |
|---|---|---|---|---|
| **O-A. Windows MIDI out (`winmm.midiOutShortMsg`) via `ctypes` (proposed baseline)** | None (Windows built-in) | The call itself is short (to be measured); the sound latency depends on the receiving synth | No new dependency; deterministic MIDI messages; the user can route to any synth | The built-in "Microsoft GS Wavetable Synth" is known for noticeable latency (not measured here); a low-latency synth needs a user-installed loopback port and synth |
| O-B. `mido` + `python-rtmidi` | Two packages, one compiled | Like O-A | Portable; virtual ports on some platforms | Adds dependencies for no capability needed now |
| O-C. Built-in synthesis, numpy + `sounddevice` (PortAudio, WASAPI) | One package with a bundled DLL | Buffer-dependent; can be low with WASAPI | Self-contained sound; the audio scheduling time is known to us | A dependency; buffer tuning; an audio callback thread to keep real-time |
| O-D. Built-in synthesis via `winmm.waveOut` and `ctypes` | None | Typically higher than WASAPI | No dependency | Buffer handling by hand; latency likely worse than O-C |
| **O-N. Null / log backend (always present)** | None | — | Tests, replay, headless runs: events only | No sound |

**Proposal:** O-A plus O-N in Phase 2. Fixed MIDI mapping (channel 1, velocity 100; C = C4-E4-G4, G = G3-B3-D4, Am = A3-C4-E4, F = F3-A3-C4; configurable). O-C can follow if built-in sound is wanted (P6). An optional metronome click on MIDI channel 10 at a fixed tempo supports bench trials of rhythmic play; quantization is off by default and, when on, never replaces the raw commit time.

### 5.2 Latency budget (from head movement to sound)

The dwell is intentional and excluded; the budget runs from the sample that completes the dwell to sound.

| Stage | Known | Status |
|---|---|---|
| Sensor and SDK fusion filter | Strong smoothing (G0) | **Unknown.** Not measurable with the glasses alone (TV4) |
| Device → host arrival | Relative lateness p99 ≈ 2.2 ms, arrival residual SD ≈ 0.44 ms (relative, not absolute) | Absolute part unknown (TV6) |
| Device timestamp resolution | 1 ms | Measured |
| Shim ring drain | ≤ `drain_interval_ms` = 5 ms | Configured |
| Queue, processing, recogniser | Not measured (TV6) | Phase 2 logs `decision_host_ns − host_rx` per commit and reports its distribution |
| MIDI call | Not measured | Phase 2 logs host time before and after each send |
| Synth and audio device | Unknown; backend-dependent | Needs an external measurement (for example a microphone loopback). **Not in Phase 2** without O4 |
| Commit granularity | ≤ one sample period: 4.94 ms (240 Hz req.), 16.8 ms (60 Hz req.) | Measured rates |

Whether this is good enough is **O4**: the protocol sets no timing precision target. Phase 2 measures and reports the software stages; it makes no adequacy claim. Following protocol §10, the MIDI send time is never reported as acoustic onset.

### 5.3 Recording for deterministic replay

New files in the session directory (additive; schema 1.2.0; existing files unchanged):

| File | Content |
|---|---|
| `interaction_events.jsonl` | **Deterministic** recogniser outputs, one per line: `event_type` (protocol §10.3 names: `aim_enter`, `dwell_start`, `dwell_complete`, `raw_commit`, `midi_note_on`, `midi_note_off`, `return_neutral`, plus `gesture_reset`, `instrument_state`), `seq` (the deciding sample), `connection_id`, `neutral_calibration_id`, `device_ts_raw`, `host_rx_monotonic_ns`, `event_host_monotonic_ns` (= estimated production time of the deciding sample, host timebase), `chord_observed`, `selected_target_id`, `recognizer_state`, `reset_reason`, `mapping_version`, `quantization_enabled`; the protocol's `chord_expected`, `model_id` and `optimizer_seed` stay `null` (no cues, no models in Phase 2) |
| `instrument_inputs.jsonl` | The live-only inputs of §2.3 (`stale_tick`, `late_processing`), each with `after_seq` and host time. Replay re-injects them at those positions, like `commands.jsonl` |
| `output_log.jsonl` | **Non-deterministic** output facts: backend, MIDI bytes, host time before and after each send, decision time (`decision_host_ns`), errors. Joined to `interaction_events` by an event id. Never compared on replay |
| `session.json` | Gains an `instrument` section: config snapshot, target table (quaternions and their display definitions), backend and port, `mapping_version` (hash of the target table and parameters) |

Replay: `replay <session> --instrument --reprocess` recomputes `interaction_events.jsonl` from `raw_pose.csv`, `events.jsonl`, `commands.jsonl` and `instrument_inputs.jsonl` with the session's own config, and must reproduce it byte for byte on the same platform and versions (protocol gate G1). Replay with an audio backend replays the recorded events through it, for listening; it never alters the recorded files.

---

## 6. Testing (no glasses needed)

All new tests run with `glasses.dll` absent and the null backend, like the Phase 1 suite.

**Synthetic traces** (an extension of `acquisition/synthetic.py`: scripted head motion as piecewise holds and slerp movements between `q_rel` poses, on a real `r_ref` rate and 1 ms timestamp quantisation):
- Happy path: neutral → each target → hold `T_dwell` → return, for all four chords; exactly one commit each, at the first sample with elapsed ≥ `T_dwell`.
- Boundaries: hold for `T_dwell − 1 sample period` (no commit); oscillation across `r_enter`/`r_exit` (hysteresis: one dwell); pass through a zone faster than `T_dwell` (no commit); move target A → target B without neutral (dwell on B only; no second commit without neutral after a commit); cooldown.
- **Every reset trigger of §4.1, injected in every state** (`neutral`, `aiming`, `dwell-armed` at its start, middle and one sample before completion, `return-to-neutral` with a chord sounding): duplicate timestamp, `ts_backward`, NaN, zero norm, `angular_jump`, 300 ms and 600 ms pauses (G0 pattern, including the 600 + 300 ms pair), a 50 ms gap, disconnect → reconnect with the device clock restarted, a new neutral, a capture request, the R9 sleep pattern (one 29.9 s late sample, then a late burst), no neutral at start.
  Each must: reset, emit `gesture_reset` with the right reason, commit nothing, release a sounding chord (when `release_on_interruption`), and require a return to neutral before the next commit, including when the head rests in a target zone throughout the interruption.
- Quaternion edge cases at a target: SDK sign flip (`hemisphere_flip`) while dwelling; yaw near ±180° relative to the tracking frame (irrelevant to `q_rel`, still tested).
- **Invariant check on every test trace:** each `raw_commit` is preceded by an unbroken, gate-usable, in-zone run of ≥ `T_dwell` on one connection and one neutral, which started after a neutral-zone visit. Run also on randomised fault traces (seeded).
- Midas-touch characterisation: a seeded slow random-wander trace counts unintended commits. This is a software regression measure, not an estimate of human behaviour.

**Determinism and replay:**
- Live simulation (threaded pipeline, fake clock, ticks during injected pauses) versus offline replay of the recorded session: `interaction_events.jsonl` byte-identical.
- The G0 sessions (R6a movements, R7 unplug, R8 cable disconnect, R9 sleep) replayed through the instrument as local smoke tests. They are git-ignored data, so they are not in CI; small excerpts could become fixtures only with your approval.
- With no consumers, Phase 1 replay output stays byte-identical (existing tests).

**Output:**
- A fake `winmm` records messages; chord-on/off pairing; all-notes-off on each stop path, including an exception inside the recogniser and a backend error.
- Config validation: target separation ≤ `2·r_exit`, `r_exit ≤ r_enter`, a target closer to neutral than `r_neutral_exit + r_exit` (the default layout has 15° > 14°), unknown chord names: all rejected with a clear message.
- The import-graph test extended to the rules in §2.2.

---

## 7. Implementation plan (after approval)

| Step | Deliverable | Verified by |
|---|---|---|
| 1 | `Pipeline` consumer hook (additive) | Phase 1 tests unchanged and byte-identical |
| 2 | `instrument/mapping.py` (targets, geodesic zones, config validation) and `instrument/recognizer.py` (pure state machine) | Unit tests §6 |
| 3 | Synthetic motion scripts and fault injection; invariant checker | Fault matrix §6 |
| 4 | Interaction recording (three files, schema 1.2.0), `replay --instrument`, input logging for ticks and late processing | Live-simulation vs replay byte identity |
| 5 | Output: null backend, `winmm` MIDI backend, all-notes-off on every stop path, optional metronome | Fake-`winmm` tests; one bench check you approve (MIDI to the built-in synth, glasses on the table, not worn) |
| 6 | HUD panel in the viewer, `headmusic play` | Manual check from replay, then live on the bench (approved run, glasses handled or on a fixture, not worn) |
| 7 | Docs: `docs/instrument.md` (state machine, parameters), data-format 1.2.0, threats-to-validity entries | Review with you |

Any step that opens the glasses needs your approval of its setup first, as in G0.

---

## 8. Out of scope

- Comfort, effort or discomfort models (Models B and C), the optimiser, Model A's "pre-piloted" layout.
- Participant calibration, rating UI, candidate-pose sampling.
- Formal experiments: cues, prompted-selection blocks, scored blocks, counterbalancing, false-activation statistics, any participant data (IRB gate).
- ML of any kind.
- Trigger gestures, roll modulation, continuous control (protocol §6 future extensions).
- Torso tracking, world-anchored UI, gaze.
- Absolute audio-onset measurement (needs O4 and an external method).

The `interaction_events` schema leaves room for cues and models (null fields), so a later experiment phase does not need a schema break.

---

## 9. Open decisions and blockers

### Existing open items

| # | Item | Effect on Phase 2 |
|---|---|---|
| **O3** | Developer self-testing while wearing the glasses: is it outside the human-subjects gate? | **Blocks trying the instrument on the head** and showing the HUD in the glasses. Steps 1–5 and bench checks of 6 do not depend on it |
| **O4** | Timing precision target | Phase 2 measures the software stages (§5.2) and makes no adequacy claim. Needed before choosing between output options on latency grounds, and before any audio-onset measurement |
| **O5** | Disconnects (and pauses) during a block | The instrument resets, releases (default) and waits for a new neutral. What a *block* does (abort, pause, re-capture, mark trials) is an experiment-procedure decision |
| **O6** | `tau_stab_deg` (placeholder 2.0°) | Decides how readily a re-capture after a reconnect is accepted, so how long the instrument stays `inactive` |
| **Duplicate timestamps** | Keep them invalidating? | With the strict gate, a 500 ms dwell restarts in ≈ 5 % of attempts at 240 Hz (≈ 0.5–1.3 % at 60–120 Hz), from fixture rates. Options: keep (safe, visible restarts); treat a `ts_duplicate` sample as "skip without reset" in the recogniser only; or reclassify the flag. The gate is not changed without your decision |
| **O1** | Research report missing | This proposal must be re-checked against it, especially §3 (mapping) and §5 (timing) |

### New decisions raised by this proposal

| # | Decision | Proposed default |
|---|---|---|
| **P1** | On an interruption, release the sounding chord or hold it? And is a release allowed on untrusted tracking (it stops sound; it selects nothing)? | Release; releases always allowed |
| **P2** | Zone distance: full geodesic angle including tilt (S1) or forward-axis angle ignoring tilt (S4)? | S1, the protocol's geodesic |
| **P3** | Reset on sub-stale gaps (`gap_before`), or only when the gate becomes unusable? | Reset on any gap |
| **P4** | The provisional values in §3.5: dwell (protocol range 400–600 ms; 500 proposed), radii, cooldown, the bench layout | As in §3.5, explicitly placeholders until the research team sets them |
| **P5** | Re-committing the chord already sounding: re-trigger or ignore? | Re-trigger |
| **P6** | Output backend: `winmm` MIDI only, or also built-in synthesis (`sounddevice`, one dependency)? | `winmm` MIDI + null now; synthesis later if wanted |
| **P7** | Request "no sleep" from Windows while the instrument runs? | Yes, per process, released on exit |

### Points where the protocol is silent or could conflict

- **Chord-off:** the protocol names chord-on/chord-off events but not when a chord ends. This proposal: on the next commit, on release triggers, on stop.
- **Single timestamp per event:** protocol §10.3 has one `event_host_monotonic_ns`. This proposal stores the deciding sample's arrival time, its estimated production time and (non-deterministically) the decision and send times, so the timing rule of §10 ("preserve … separately") can be met. Which one the analysis calls "raw commit time" is the research team's choice; the default `event_host_monotonic_ns` is the production estimate.
- **Euler boxes** (option S2) would conflict with the protocol's quaternion-only computation. Not proposed.
- **Recenter:** the protocol allows it only between tasks. Phase 2 has no tasks; the instrument simply suspends during a capture and resets after.
- **HUD in the glasses** is worn use, so it falls under O3, not just an engineering choice.
