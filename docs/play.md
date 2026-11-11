# Play window and `headmusic play` (Phase 2C)

The integrated instrument: glasses → pipeline → gesture FSM ([instrument.md](instrument.md)) → chord engine ([music.md](music.md)) → MIDI, with a HUD.

**Before any live run:** describe the setup to the operator and wait for approval, as in G0. Worn use, and showing the HUD inside the glasses, wait for **O3** (faculty/IRB guidance). The regions, dwell and every other threshold are **provisional engineering defaults**, not ergonomic limits.

## Commands

| Command | What it does |
|---|---|
| `headmusic play` | Live instrument with the play window, recorded by default |
| `headmusic play --audio null --no-record` | Live without sound and without recording |
| `headmusic replay <session> --instrument --view --speed 1` | Replays a recorded session through the instrument, with the play window and sound. No glasses needed |
| `headmusic synth chords --instrument` | Writes a synthetic session to try the replay with |

**`play` options:**
- the usual live options: `--freq`, `--mounting`, `--capture-neutral-at S`, `--notes`;
- `--audio winmm|null` and `--midi-device`;
- `--no-record`, `--no-keep-awake`, `--close-after S`.

While playing, Windows is asked not to sleep (`SetThreadExecutionState`, per process; released on exit; G0 R9). The request's result is stored in `session.json` → `keep_awake_requested`.

## Keys and buttons

| Key | Action | How |
|---|---|---|
| **Esc** (red button) | **Emergency stop**: everything silenced, instrument disabled | `panic` command. If the sound has not stopped within 300 ms, the window silences the engine directly, as a last resort that is logged |
| **N** | Capture neutral | `capture_neutral` |
| **E** | Enable the instrument (after an emergency stop or disable) | `instrument_enable`. Arming then still needs a return to neutral |
| **A** | Accompaniment start / stop | Only if `[music.accompaniment] enabled = true` |

- Every action is a pipeline command, so it is recorded in `commands.jsonl` and replayed.
- **The window decides nothing.** It reads snapshots of the FSM, the engine and the gate; an architecture test checks its imports.
- Closing the window sends `panic` (reason `window_closed`) before the slow device teardown, so nothing can sound or be selected during it.
- In replay, only Esc is active, because the other commands come from the recording.

## What the HUD shows

| Element | Meaning |
|---|---|
| Top line | `TRACKING USABLE` or `TRACKING NOT USABLE: <gate reasons>`, or `NOT CONNECTED` |
| Large text | The sounding chord, or `silent`. With quantization, the chord waiting for the next beat |
| State line | `INACTIVE`, `NOT ARMED`, `NEUTRAL: armed`, `AIMING`, `DWELL <chord> nn%` or `PLAYED: return to neutral` |
| Hint | What to do next, for example "press N to capture one", "return to the neutral zone to arm", or "EMERGENCY STOP: press E to enable again" |
| Yaw track | The neutral zone and the four regions on the `yaw_rel` axis, with **turn left on the left**. Highlights: region under the cursor, dwelling region, sounding chord. The cursor is grey when the pose is ignored (beyond `max_elevation_deg`) |
| Progress bar | Dwell progress |
| Bottom lines | `yaw_rel` value, accompaniment state, output state (`OUTPUT FAILED: …` after a backend error), recent commits, and a reminder that the parameters are provisional |

## Logs

A `play` session holds everything a Phase 1 recording does, plus:
- `interaction_events.jsonl`, `instrument_inputs.jsonl`, `interaction_timing.jsonl`;
- `music_events.jsonl`, `music_timing.jsonl`;
- the `instrument` and `music` sections of `session.json`.

`replay <session> --reprocess --instrument` checks that the decisions are reproduced byte for byte.
