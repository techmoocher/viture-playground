# MVP iteration 2: play continuously, like a gesture instrument

**Date:** 2026-11-11. **Status:** implemented on `phase2/mvp-iteration-2`, with the interaction refinement of §8 (the short settle time, active and candidate chord) as the current default.

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
| `dwell_ms` / `dwell_stability_deg` / `cooldown_ms` | **80 / 2° / 0** (§8) | **Short settle:** a key sounds once the cursor has stayed within 2° for 80 ms. Keys crossed faster than about 25°/s stay silent, and the active chord keeps sounding meanwhile. (First iteration-2 default: 0, immediate keys; now `immediate.toml`) |
| Keys | **contiguous**: F −40…−18°, Am −18…−5°, neutral ±5°, G 5…18°, C 18…40° | No gaps. At each shared edge, hysteresis (1.5°) keeps the current key until the cursor is clearly past the edge, so there is no flicker |
| `playback` | `"latch"` | The chord keeps sounding until another key is entered, R is pressed, or a safety interruption happens |
| `neutral_rest_release_ms` | **0** (§8) | The neutral zone never silences the active chord: it sounds until another chord is confirmed, R, Esc or a safety interruption. Neutral stays the calibration and rest position. (First iteration-2 default: 150 ms, which cut slow crossings of neutral) |
| `[music] program` | **16, Drawbar Organ** | Sustains while held, starts at once. Alternatives: 19 Church Organ, 48 Strings, 89 Warm Pad (slow attack), 0 Piano (decays) |

**Profiles** (use `headmusic --config config/profiles/<name>.toml …`):

| Profile | What it changes |
|---|---|
| `hold.toml` | `playback = "hold"`: a chord sounds only while the cursor is on its key; leaving releases it |
| `immediate.toml` | The first iteration-2 behaviour: dwell 0 (sound on entry, so crossed keys sound briefly) and neutral = silence after 150 ms |
| `confirm.toml` | 500 ms dwell, 300 ms cooldown and the 3° stability rule. Keys crossed on the way stay silent even when crossed slowly, and a chord sounds 0.5 s after you stop on it |
| `via_neutral.toml` | The protocol §6 machine with the 2A layout (with gaps), exactly as in the first MVP |
| `layout_2a_gaps.toml` | Only the 2A layout with gaps |
| `small_yaw.toml` | Contiguous keys within ±24°, no comfort claim |

**Crossed keys:** with immediate keys (`immediate.toml`) a key the cursor *crosses* sounds briefly, like sliding a finger over piano keys (G → F crosses Am, Am → C crosses neutral and G). The default settle time (§8) keeps crossings faster than about 25°/s silent; slower crossings still sound the crossed keys. The key order is a layout choice, for the research team or for the later sub-region design.

## 3. State machine (`transitions = "direct"`)

| State | Meaning |
|---|---|
| `inactive` | Disabled, panic, neutral capture running, or tracking unusable (unchanged) |
| `unarmed` | After an interruption or an R release while the cursor is **on a key**: that key is blocked until the cursor leaves it. No return to neutral is needed |
| `neutral` | The neutral zone: calibration and rest. The active chord keeps sounding (with `neutral_rest_release_ms > 0`, it is released after that rest) |
| `aiming` | Outside neutral and keys (only with gapped layouts), or waiting for a cooldown |
| `dwell_armed(i)` | Key *i* is the **candidate**, being confirmed (only when `dwell_ms > 0`). The **active** chord keeps sounding. Restarts if the cursor moves more than `dwell_stability_deg` |
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

The current defaults (§8):

```bash
.venv\Scripts\headmusic replay data/sessions/20261111T194225Z_bench_synthetic_4dea90e4 --instrument --view --speed 1
```

```bash
.venv\Scripts\headmusic replay data/sessions/20261111T194225Z_bench_synthetic_b867f756 --instrument --view --speed 1
```

- The first is the operator's flow (`continuous`): neutral once, then C → G → F → Am → C with every crossed key silent and no gap. Then a rest in neutral (C keeps sounding), then R. Commits: C, G, F, Am, C.
- The second is `traverse`: F → C at 60°/s, C → F at 30°/s, F → C at 15°/s, then R. Commits: F, C, F, then Am, G, C on the 15°/s pass (the known limitation).

The same `traverse` motion, to compare by ear:

```bash
.venv\Scripts\headmusic replay data/sessions/20261111T194226Z_bench_synthetic_b78cb845 --instrument --view --speed 1
```

```bash
.venv\Scripts\headmusic replay data/sessions/20261111T194226Z_bench_synthetic_be16ef71 --instrument --view --speed 1
```

- The first uses `immediate.toml`: every crossed key sounds (11 commits).
- The second uses `confirm.toml`: none does (F, C, F, C), but each chord starts about 0.5 s after the stop.

Regenerate them with `headmusic [--config config/profiles/<profile>.toml] synth continuous|traverse --instrument`. `hold.toml` gives hold mode, and `synth transitions` with `confirm.toml` shows confirmed switching.

The first iteration-2 demos are kept: `20261111T192238Z_bench_synthetic_2ea38bfa` (latch) and `20261111T192239Z_bench_synthetic_82a6ddc2` (hold), both with immediate keys.
- The hold demo replays byte-identically.
- In the latch demo, replay now adds the `active_chord` field to 24 candidate events; every other field is identical (checked).
- The R2D-1 session replays with all logs byte-identical.

## 8. Interaction refinement: active and candidate chord, short settle time

**Phase 2 MVP interaction refinement, 2026-11-11.** This is not a protocol change: the protocol §6 machine is unchanged as `via_neutral.toml`, and which machine the formal experiment uses remains Q17. All values are provisional engineering defaults, configurable, recorded in `session.json`, with no ergonomic or comfort claim.

**Requirement (operator):** the last confirmed chord keeps sounding while the application determines the next one. For G → C:
1. G sounds.
2. The head starts towards C: G sounds.
3. The cursor crosses another key: G sounds.
4. The cursor reaches C and the 80 ms / 2° confirmation begins: G sounds.
5. Only when C is confirmed is G released and C started, in one step.
6. If the confirmation fails, restarts, or the head turns away, G continues uninterrupted.

**Active and candidate chord** (`fsm.active_chord`, `fsm.candidate_chord`, also in `snapshot()`):
- The **active** chord is the last confirmed chord, which sounds in latch mode.
- The **candidate** is the chord of the key being confirmed (`dwell_armed`).
- Only a confirmation changes the active chord. The engine then sends the old chord's note-offs (reason `chord_change`) and the new chord's note-ons for the same `raw_commit` event, so there is no silent sample between them.
- **Logs:**
  - The candidate events `dwell_start`, `dwell_restart`, `dwell_cancel`, `dwell_complete` and `raw_commit` carry `chord` (the candidate) and `active_chord`: the chord sounding at that moment, or on `raw_commit` the chord it replaces.
  - `active_chord` is written only when set, so the protocol machine's logs are unchanged.
  - The audio events are the existing `midi_note_on` / `midi_note_off`, with their reasons.
- **HUD:**
  - `SOUNDING: G` in large text;
  - the state `CONFIRMING C  50%`, with the line `candidate: C  confirming 50%` under the progress bar;
  - the hint "G keeps sounding until C is confirmed";
  - on the yaw track, the active key is green and the candidate key blue.

**Defaults changed:**
- `dwell_ms = 80`, `dwell_stability_deg = 2.0`. The stability rule restarts the dwell when the cursor moves more than 2° from where it started, so a crossing never settles but a stop does. The cut-off speed is about stability ÷ dwell = 2° / 0.08 s ≈ 25°/s.
- `neutral_rest_release_ms = 0`: the neutral zone no longer silences a latched chord. With 150 ms, a slow crossing of neutral cut the sound.

**Unchanged safety:**
- **R** releases the active chord. If a candidate is pending, R cancels it too and blocks the key under the cursor until it is left, so R really means silence (nothing starts 80 ms later).
- **Esc** (panic) silences everything.
- Genuine tracking interruptions release all notes as before, also while a candidate is pending. These are staleness, device pauses, invalid data, disconnects, a new neutral and late processing.

**Synthetic comparison** (`scripts/compare_settle.py`). This is the outcome of a script, not a measurement with people.
- Setup: the direct FSM at 200 Hz; an F → C traverse crossing Am, neutral and G; cooldown 0.
- "Onset" is the time from the cursor stopping on C to C sounding, arriving at 60°/s.
- The noise columns add white per-sample yaw noise while holding still. That is only a crude stand-in for head sway, which is unmeasured (O3).

| dwell / stability | crossed keys sounding at 10 / 15 / 20 / 25 / 30 / 45 / 60 / 120 / 240 °/s | onset after stop | onset, noise σ 0.3° (median of 20) | σ 0.6° (median of 20) |
|---|---|---|---|---|
| immediate | 2 / 2 / 2 / 2 / 2 / 2 / 2 / 2 / 2 | on entry | on entry | on entry |
| 60 ms / 2° | 2 / 2 / 2 / 2 / 2 / 0 / 0 / 0 / 0 | 45 ms | 45 ms | 45 ms |
| 80 ms / 1.5° | 2 / 2 / 0 / 0 / 0 / 0 / 0 / 0 / 0 | 70 ms | 70 ms | 155 ms |
| **80 ms / 2° (default)** | **2 / 2 / 2 / 2 / 0 / 0 / 0 / 0 / 0** | **65 ms** | **65 ms** | **65 ms** |
| 80 ms / 3° | 2 / 2 / 2 / 2 / 2 / 0 / 0 / 0 / 0 | 55 ms | 55 ms | 55 ms |
| 100 ms / 2° | 2 / 2 / 2 / 0 / 0 / 0 / 0 / 0 / 0 | 85 ms | 85 ms | 130 ms |
| 120 ms / 2° | 2 / 2 / 0 / 0 / 0 / 0 / 0 / 0 / 0 | 105 ms | 105 ms | 225 ms |
| 150 ms / 3° | 2 / 2 / 2 / 0 / 0 / 0 / 0 / 0 / 0 | 125 ms | 125 ms | 125 ms |
| 500 ms / 3° (`confirm.toml`) | 0 / 0 / 0 / 0 / 0 / 0 / 0 / 0 / 0 | 475 ms | 475 ms | 475 ms |

What it shows:
- A smaller band or a longer dwell silences slower crossings, but costs onset time. With noise, onset grows fast: at σ 0.6°, 80 ms / 1.5° and 120 ms / 2° start much later.
- 80 ms / 2° keeps a 65 ms onset in all three columns.
- The real trade-off needs the live try: the sway of a turning head is not white noise, and its size is unknown.

**Known limitation:** crossings slower than about 25°/s still activate the crossed keys, because a slow crossing looks the same as a deliberate placement.
- Only a long confirmation (`confirm.toml`) separates them, at the cost of an onset of about 0.5 s.
- `test_very_slow_crossings_may_still_activate_intermediate_keys` pins this behaviour.
- It can be heard in the `traverse` demo (§7).

**Tests** (`tests/test_instrument_direct.py`, section "the MVP default"):
- F → C with no audible gap at 30–240°/s through Am, neutral and G: the engine sounds F on every sample until C, and the note events are exactly F on, F off, C on;
- a slow (10°/s) pass across neutral keeps Am;
- G sustains while C is pending, and the candidate events name G as active;
- a cancelled or restarted confirmation never releases G;
- a confirmed chord switches the sound exactly once;
- 15 s of movement inside one key never re-triggers;
- the slow-crossing limitation;
- R while a candidate is pending;
- R, panic, a device pause and a disconnect, each with the chord active and with a candidate pending;
- the `continuous` and `traverse` demos for three profiles;
- record-and-replay identity with the new field;
- the HUD (`tests/test_play_hud.py`).

**Next:** a short live hardware test of the defaults. It needs the operator's approval, the setup done together and a placement check first. Worn use waits for O3.
