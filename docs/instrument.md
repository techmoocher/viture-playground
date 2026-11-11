# Instrument: gesture state machine (Phase 2A)

The design and its reasons are in [phase2-proposal.md](phase2-proposal.md). The open methodological questions are in [research/phase2-open-questions.md](research/phase2-open-questions.md). This page is the reference for what is implemented.

**Every value on this page is a provisional engineering default.** Each is configurable under `[instrument]` in `src/headmusic/defaults.toml` (override with `--config`), and each session records it in `session.json` → `instrument`. None is a validated ergonomic, comfort or safety limit.

## Code

| Module | Role |
|---|---|
| `instrument/regions.py` | Region coordinate, `YawRegion`, `InstrumentConfig` (loading, validation, `mapping_version`) |
| `instrument/fsm.py` | `GestureFSM`. Pure and deterministic: it reads no clock and imports no acquisition, audio or UI code |
| `instrument/events.py` | `InteractionEvent` and the state names |
| `instrument/consumer.py` | `InstrumentConsumer`, the pipeline adapter: gate check, live-only inputs, logging |
| `instrument/log.py` | The three log files |

`Pipeline(..., consumers=[...])` calls each consumer in the pipeline thread: `on_sample`, `on_event`, `on_command`, `on_calibration` and `on_tick`. With no consumers, Phase 1 output is unchanged (tested).

## Region coordinate

`f = rotate(q_rel, (1, 0, 0))` is the glasses' forward axis in the neutral head frame. From it:
- `yaw_rel = atan2(f_y, f_x)`: + = turn left. It equals the display yaw of conventions.md exactly.
- `elevation = asin(f_z)`: + = nose up.

A sample counts for the regions and the neutral zone only if `|elevation| ≤ max_elevation_deg`.

## Regions and zones

- A region is entered when `yaw_min ≤ yaw_rel ≤ yaw_max`, and left when `yaw_rel` is outside `[yaw_min − h, yaw_max + h]`.
- The neutral zone is entered when `|yaw_rel| ≤ neutral_yaw_deg`, and left beyond `neutral_yaw_deg + h`.
- **Validation** rejects:
  - regions that overlap the neutral zone plus hysteresis;
  - neighbouring regions not more than `h` apart;
  - duplicate chords;
  - `dwell_ms ≤ 0`;
  - negative or non-finite values;
  - `max_elevation_deg` outside (0, 90].

| Parameter | Default |
|---|---|
| Regions (+ = left) | C [22, 40] · G [8, 18] · Am [−18, −8] · F [−40, −22] (bench layout only) |
| `neutral_yaw_deg` / `hysteresis_deg` | 4.0 / 1.5 |
| `dwell_ms` / `cooldown_ms` / `rearm_hold_ms` | 500 / 300 / 0 |
| `max_elevation_deg` | 89.0 (numeric guard) |
| `reset_on_gap_before` / `start_enabled` | true / true |

## States

| State | Leaves to |
|---|---|
| `inactive` (disabled, panic, neutral capture running, or gate unusable) | `unarmed` on the first usable, fresh sample |
| `unarmed` | `neutral` after `rearm_hold_ms` in the neutral zone |
| `neutral` | `aiming` on leaving the zone |
| `aiming` | `dwell_armed` on entering a region (once the cooldown is over) · `neutral` on re-entering the zone |
| `dwell_armed` | commit after `dwell_ms` of device time → `return_to_neutral` · `aiming` on leaving the region |
| `return_to_neutral` | `neutral` (re-armed) |

- A commit emits `dwell_complete` and `raw_commit` on the first sample whose elapsed device time since the dwell start is at least `dwell_ms`.
- Nothing commits again until the neutral zone is re-entered.
- Switching regions restarts the dwell.

## Resets

These inputs cancel the gesture and move the FSM to `inactive` or `unarmed`:
- gate unusable at the sample's arrival time (its reasons);
- `stale_tick`;
- `late_processing`;
- disconnect or connect;
- a new `connection_id` or `neutral_calibration_id`;
- `capture_neutral` (suspended until the capture ends);
- `gap_before`;
- `instrument_disable`, `panic`;
- end of stream.

Each reset raises a freshness watermark. Samples produced (by the gate's estimate) at or before it are ignored, so queued or late data cannot arm anything.

## Determinism and replay

- Two inputs are live-only: `stale_tick` (the gate became unusable between samples) and `late_processing` (more than `T_stale` between arrival and processing).
- Each is logged to `instrument_inputs.jsonl` at `(after_seq, k)`: after the sample with that seq and `k` further connection events or commands.
- `replay --reprocess --instrument` re-injects them there and reproduces `interaction_events.jsonl` byte for byte (tested with simulated live timing).

## Log files (schema 1.2.0)

| File | Deterministic | Content |
|---|---|---|
| `interaction_events.jsonl` | yes | `event_id`, `event_type`, `state`, `prev_state`, the deciding sample (`seq`, `connection_id`, `neutral_calibration_id`, `device_ts_raw`, `host_rx_monotonic_ns`, `produced_host_ns`), `input_host_ns` for non-sample inputs, `chord`, `reason`, `dwell_elapsed_ns`, `yaw_rel_deg`, `mapping_version` |
| `instrument_inputs.jsonl` | yes (as recorded) | `stale_tick` and `late_processing` with positions |
| `interaction_timing.jsonl` | no | `event_id`, `decision_host_ns` (processing time); live runs only |

**Event types:**
- target entry `aim_enter`, and `aim_exit`;
- dwell initiation `dwell_start`, and `dwell_cancel`;
- gesture recognition `dwell_complete`;
- chord commitment `raw_commit`;
- `return_neutral`, `gesture_reset`, `state_change`, `inactive_reason`;
- `instrument_enabled`, `instrument_disabled`, `panic`, `neutral_capture_end`.

## Commands

`capture_neutral` (existing), `instrument_enable`, `instrument_disable` and `panic`. All of them go through `commands.jsonl` and are replayed.

## Sound

The chord engine is in [music.md](music.md) (2B).

## MVP iteration 2

The defaults are now direct switching between contiguous, immediate keys, with latch playback and neutral = silence. See [mvp-iteration-2.md](mvp-iteration-2.md). This page's states and parameters describe the protocol §6 machine (`config/profiles/via_neutral.toml`).

## Play window

`headmusic play` and the HUD are described in [play.md](play.md) (2C). Hardware runs are 2D.
