# Data format (schema 1.0.0)

One directory per session: `data/sessions/<UTC>_<condition>_<mounting>_<id8>/`. All of `data/` is git-ignored.

| File | Content |
|---|---|
| `session.json` | Normalised metadata, rewritten atomically (see below) |
| `raw_pose.csv` | Pose callbacks exactly as delivered |
| `raw_imu.csv` | Raw-mode sessions only |
| `processed_pose.csv` | Derived values; regenerable from raw by `replay --reprocess` |
| `events.jsonl` | Stream and device events: `kind`, `host_monotonic_ns`, `last_seq`, `data` |
| `commands.jsonl` | Operator commands: `kind`, `after_seq`, `host_monotonic_ns`, `data`. Replay re-injects them after `after_seq` |
| `calibration_neutral.jsonl` | One record per neutral-capture attempt |
| `sdk_log.txt` | SDK log hook output (level 1 = errors), host timestamped |
| `analysis/` | `report.json`, `report.md` |
| `export/` | Denormalised export and its manifest |

Files are flushed at least once per second (`io.flush_interval_s`). Readers tolerate a truncated last row or line after a crash.

## Columns

**`raw_pose.csv`:** `seq, connection_id, host_rx_monotonic_ns, device_ts_raw, sdk_roll_deg, sdk_pitch_deg, sdk_yaw_deg, sdk_qw, sdk_qx, sdk_qy, sdk_qz`
- `seq` is assigned in the native shim, so gaps in `seq` mean data was lost in our pipeline. Expected: 0.
- SDK float32 values are written with 9 significant digits. Readers round back to float32, which reproduces the live values bit-exactly (tested over 20 000 random float32 patterns).

**`raw_imu.csv`:** `seq, connection_id, host_rx_monotonic_ns, device_ts_raw, vsync_raw, gyro_x..z, accel_x..z, mag_x..z, temperature`. Units are undocumented by the SDK.

**`processed_pose.csv`:** `seq, connection_id, host_rx_monotonic_ns, device_ts_raw, dt_device_ns, dt_host_ns, quat_w..z, quat_rel_w..z, euler_display_yaw_deg, euler_display_pitch_deg, euler_display_roll_deg, valid, sample_quality, neutral_calibration_id, gap_est_missing`
- Doubles are written with `repr` (exact round trip). Missing values are empty strings.
- `dt_*` are measured from the previous *received* sample.

## `session.json` (normalised metadata)

| Group | Fields |
|---|---|
| Identity | `schema_version`, `session_id` (UUID), `participant_id` (always `null` in Phase 1), `condition` (`bench`), `mounting` (`fixture` \| `worn`; `synthetic` for generated data), `stationary`, `notes` (no personal information) |
| Source | `source.kind`: `live` \| `replay` \| `synthetic` |
| Provenance | Package version, git commit and dirty flag, Python and numpy versions, platform, command line, SHA-256 of `glasses.dll` and `capture_shim.dll`, shim `BUILDINFO` |
| Configuration | `config` (full snapshot) and `config_sha256` |
| Clocks | Host clock and device timestamp descriptions, `start_anchor` / `end_anchor` |
| Device | Market name, PID, device type, firmware, SDK version, SN hash (equipment identifier), native DOF, frequency selection |
| IMU | Mode, `frequency_requested_hz`, `frequency_selected_hz`, `frequency_selection_reason`, support table |
| Processing | Resolved gap reference (`gap_reference_used`, `reference_rate_hz` or adaptive parameters). Replay uses these values, not today's defaults |
| At close | `summary` counters, `shim_stats`, `files.row_counts` |

## Mapping to protocol §10 and the denormalised export

`headmusic export <session>` writes `export/pose_samples_denormalized.csv`.
- Every row carries the §10 fields: `schema_version, participant_id, session_id, trial_id, condition, software_build, sdk_version`, firmware, clock descriptions, and `neutral_calibration_id` with its `neutral_q0_wxyz_*`.
- Then the per-sample fields follow.
- `trial_id` is the label of the bench segment (`segment_start` / `segment_end` commands) that contains the sample.
- `export_manifest.json` lists the SHA-256 of every input.
- The same inputs give a byte-identical CSV.

| Protocol §10.1 | Export column(s) | Normalised source |
|---|---|---|
| `device_ts_raw` | `device_ts_raw` | raw and processed |
| `host_rx_monotonic_ns` | `host_rx_monotonic_ns` | raw and processed |
| `quat_wxyz` | `quat_wxyz_w/x/y/z` | processed `quat_*` |
| `quat_neutral_relative_wxyz` | `quat_neutral_relative_wxyz_w/x/y/z` | processed `quat_rel_*` |
| `euler_display_deg` | `euler_display_deg_yaw/pitch/roll` | processed `euler_display_*` |
| `sample_quality` | `sample_quality` (flag set, see quality-and-metrics.md) | processed |
| `neutral_calibration_id` | `neutral_calibration_id`, `neutral_q0_wxyz_*` | processed + `calibration_neutral.jsonl` |

Decision D2 refines §10.1's single `sample_quality` enum: a sample may carry several flags; `recenter` and `stale` are
events, not sample values; and `discontinuity` maps to the `ts_backward`, `ts_duplicate` and `angular_jump` flags.
