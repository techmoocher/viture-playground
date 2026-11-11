# MVP iteration 2: play continuously, like a gesture instrument

**Date:** 2026-11-11. **Status:** implemented on `phase2/mvp-iteration-2`.

This is an iteration of the Phase 2 MVP after the operator's hands-on trial. It does **not** change the Experiment & Calibration Protocol.
- The protocol's state machine (§6: `neutral → aiming → dwell-armed → committed → return-to-neutral`, 500 ms dwell) is kept unchanged as `config/profiles/via_neutral.toml`.
- Which machine a formal experiment uses is a research decision (research question Q17).

Every value is a provisional engineering default, configurable and recorded in `session.json`.

## 1. What the operator asked for, and why

- **Calibrate once, then play continuously.** "Neutral once at the start, then C → G → F → Am → C continuously, without going back to the neutral point." The first MVP required a return to neutral after every chord, which felt like navigating a menu.
- **Sound as soon as the cursor enters a key, like hand-gesture music players.** The first MVP waited for a 500 ms dwell.
- **No gaps between the keys.**
- **Neutral is for calibrating, and for silence.**
- **Chords should sustain.** The R2D-1 data showed two causes:
  - No program change was sent, so the synth played *General MIDI 0, Acoustic Grand Piano*, which decays by itself while the notes are held. Notes were held 1.5–12.3 s (median 3.1 s), but the sound faded sooner.
  - Interruptions really ended 6 of 22 chords (4 duplicate timestamps, 2 device pauses).
  - No unexplained note-off was found.
- **Later:** sub-regions within a key (for example sus chords).

## 2. Defaults now (`[instrument]` and `[music]` in `defaults.toml`)

| Setting | Value | Effect |
|---|---|---|
| `transitions` | `"direct"` | Move straight from one key to the next; neutral is never required between chords |
| `dwell_ms` / `cooldown_ms` | **0 / 0** | **Immediate keys:** the chord sounds on the first sample inside its key |
| Keys | **contiguous**: F −40…−18°, Am −18…−5°, neutral ±5°, G 5…18°, C 18…40° | No gaps. At each shared edge, hysteresis (1.5°) keeps the current key until the cursor is clearly past the edge, so there is no flicker |
| `playback` | `"latch"` | The chord keeps sounding until another key is entered, R is pressed, or a safety interruption happens |
| `neutral_rest_release_ms` | 150 | **Neutral = silence:** resting in the neutral zone releases the chord. The 150 ms debounce lets a fast sweep across neutral (a left key to a right key) keep sounding |
| `[music] program` | **16, Drawbar Organ** | Sustains while held, starts at once. Alternatives: 19 Church Organ, 48 Strings, 89 Warm Pad (slow attack), 0 Piano (decays) |

**Profiles** (use `headmusic --config config/profiles/<name>.toml …`):

| Profile | What it changes |
|---|---|
| `hold.toml` | `playback = "hold"`: a chord sounds only while the cursor is on its key; leaving releases it |
| `confirm.toml` | 500 ms dwell, 300 ms cooldown and the 3° stability rule. Keys crossed on the way stay silent, and a chord sounds 0.5 s after you stop on it |
| `via_neutral.toml` | The protocol §6 machine with the 2A layout (with gaps), exactly as in the first MVP |
| `layout_2a_gaps.toml` | Only the 2A layout with gaps |
| `small_yaw.toml` | Contiguous keys within ±24°, no comfort claim |

**Consequence of immediate keys:** a key the cursor *crosses* sounds briefly, like sliding a finger over piano keys.
- With this layout, G → F crosses Am, and Am → C crosses G (the sweep through neutral is too fast to silence).
- If crossings should stay silent, use `confirm.toml`, or a short dwell such as `dwell_ms = 100` with `dwell_stability_deg = 3`.
- The key order is a layout choice, for the research team or for the later sub-region design.

## 3. State machine (`transitions = "direct"`)

| State | Meaning |
|---|---|
| `inactive` | Disabled, panic, neutral capture running, or tracking unusable (unchanged) |
| `unarmed` | After an interruption or an R release while the cursor is **on a key**: that key is blocked until the cursor leaves it. No return to neutral is needed |
| `neutral` | The neutral zone: calibration and rest. A latched chord is released after `neutral_rest_release_ms` |
| `aiming` | Outside neutral and keys (only with gapped layouts), or waiting for a cooldown |
| `dwell_armed(i)` | On key *i*, confirming (only when `dwell_ms > 0`). Restarts if the cursor moves more than `dwell_stability_deg` |
| `engaged(i)` | On the key of the sounding (selected) chord. Staying, wobbling or re-entering never re-triggers it |

Entering key *i*:
- *i* is the selected chord → `engaged`, with no re-trigger;
- *i* is blocked → `unarmed`;
- otherwise → commit now (`dwell_ms = 0`), or after the dwell.

## 4. Safety (unchanged)

- Every genuine interruption releases all notes. That covers: stale tracking, device pauses, disconnects, a new connection or neutral, neutral capture, invalid data, late processing, panic, stop.
- The freshness watermark still blocks old or queued samples.
- After recovery, the key under the cursor stays silent until the cursor leaves it.
- Esc (emergency stop) is unchanged.
- **Deterministic replay:** sessions recorded before this iteration (R2D-1, the 2D demos) replay with all logs byte-identical. Missing keys mean the earlier behaviour (tested).

## 5. MIDI and diagnostics

| | |
|---|---|
| Program Change | Sent at start and after every panic or reset (timing log; the patch is in `session.json`) |
| Release reasons | `chord_change`, `neutral_rest`, `intentional` (R), `left_region` (hold), `interruption:<reason>`, `panic`, `stop` |
| HUD | The MIDI notes on, the patch, the last release and its reason, transitions and playback mode. `PLAYING <chord>` |
| `instrument-report` | How long notes were held, the patch sent, FSM releases, dwell restarts |
| Sound check | `headmusic midi-test --program 16 --seconds 3` holds each chord 3 s, to compare against `--program 0` (piano) |

## 6. Tests added (`tests/test_instrument_direct.py`)

- **Immediate keys:**
  - neutral once, then C → G → F → Am → C continuously, never silenced;
  - sound on the first sample inside a key;
  - no flicker at a shared edge;
  - wobbling within a key never re-triggers;
  - hold mode;
  - neutral silences;
  - recovery needs leaving the key;
  - the `continuous` demo.
- **Confirmed switching** (`confirm.toml`):
  - G → C without neutral;
  - G latched while travelling across other keys;
  - passing through keys at 8–120°/s plays only the destination;
  - the stability rule;
  - a fresh confirmed target;
  - no re-trigger on re-entry.
- **Releases:**
  - R, in and out of a key;
  - neutral rest;
  - hold mode.
- **Interruption recovery** (7 triggers × 3 situations) and old queued samples.
- **MIDI:**
  - the program change is sent first;
  - no note-off while latched across movement;
  - release reasons;
  - the replayable R command.

## 7. Demos (no glasses)

```bash
.venv\Scripts\headmusic replay data/sessions/20261111T192238Z_bench_synthetic_2ea38bfa --instrument --view --speed 1
```

```bash
.venv\Scripts\headmusic replay data/sessions/20261111T192239Z_bench_synthetic_82a6ddc2 --instrument --view --speed 1
```

- The first is the operator's flow (`continuous`, latch): neutral once, then C → G → F → Am → C, then a rest (silence).
- The second is the same motion in **hold** mode: each chord stops when its key is left.

Regenerate them with:

```bash
headmusic synth continuous --instrument
```

```bash
headmusic --config config/profiles/hold.toml synth continuous --instrument
```

Use `synth transitions` with `confirm.toml` for confirmed switching.
