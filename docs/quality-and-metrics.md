# Sample quality, tracking gate, neutral capture and metrics

Every threshold below is a **provisional engineering default**. None is a validated hardware or
ergonomic limit. All are configurable in `src/headmusic/defaults.toml` (override with `--config file.toml`), and
each session's values are copied into `session.json`.

## Sample flags (per pose sample, device clock, deterministic)

Notation:
- sample *i* has device time `dᵢ`, SDK quaternion `q̃ᵢ`, and normalised `qᵢ`;
- `d_ref` is the device time of the most recent sample whose timestamp was in order;
- `m` is the reference interval (see Gap reference below).

| Flag | Exact definition | Class |
|---|---|---|
| `nonfinite` | Any of the 7 SDK values is NaN or ±Inf | **invalidating** |
| `zero_norm` | ‖q̃ᵢ‖ < `eps_zero` (1e-6) | **invalidating** |
| `ts_duplicate` | dᵢ = d_ref | **invalidating** |
| `ts_backward` | dᵢ < d_ref | **invalidating** |
| `angular_jump` | θ(q_prev_finite, qᵢ) > `tau_jump_deg` **and** θ(q_last_valid, qᵢ) > `tau_jump_deg` (20°). A sensor-glitch detector, not a head-motion limit | **invalidating** |
| `norm_deviation` | \|‖q̃ᵢ‖ − 1\| > `tau_norm` (1e-3); the sample is still normalised and used | informational |
| `gap_before` | dᵢ − d_ref > `k_gap`·m + `ts_resolution_ns` (1.5·m + 1 ms). The row also stores `gap_est_missing = round((dᵢ − d_ref)/m) − 1` | informational |
| `hemisphere_flip` | The SDK quaternion sign changed vs the previous finite SDK sample: ⟨q̃ᵢ, q̃ᵢ₋₁⟩ < 0 | informational |
| `euler_near_singular` | \|display pitch\| > `euler_singular_deg` (89°) | informational |
| `no_neutral` | No accepted neutral for this connection, so `quat_rel` and Euler are empty | informational (blocks the gate) |

How the flags combine:
- `valid` is true iff there are no invalidating flags.
- Invalid rows are always written, never dropped.
- `sample_quality` is the sorted flag set joined with `|`, or `valid` if there are none.

Why each comparison point was chosen:
- **Timestamp checks use `d_ref`, not the last valid sample.** A sample with bad values but an in-order timestamp then does not cause a false gap: gaps count missing callbacks, not invalid values.
- **The jump rule requires both conditions.** A one-sample glitch then flags one sample, and a persistent jump (such as a filter reset) also flags only one.
- **Recentering and disconnects are events (`events.jsonl`), not flags.** Rows carry `connection_id` and `neutral_calibration_id` for joining.

### Gap reference `m`

- **`measured` (default):** `m = 10⁹ / r_ref`, where `r_ref` is the measured rate for the selected mode and frequency (`[flags.r_ref_hz]`).
- **`adaptive` (used when no `r_ref` exists):** the 25th percentile of the last 200 in-order intervals, or `10⁹/f_selected` during the first 20 intervals.
- The mode used is stored under `processing` in `session.json`.
- On the real lossy trace (58% loss), the measured reference estimated 2352 of ≈2354 missing samples and the adaptive one ≥ 80%. The original running-median rule caught only 338. There were no false gaps on clean traces. Both checks are regression tests.

## Staleness and the tracking gate (consumer side, host clock)

- `stale(now) := now − host_rx(last valid sample) > t_stale_ms` (100 ms). Evaluated on query, never stored on samples. The pipeline logs `stale_begin`/`stale_end` events for diagnostics.
- `usable_for_control(now) := connected ∧ a valid sample on this connection ∧ last sample valid ∧ ¬stale ∧ neutral accepted`. The reasons reported are `disconnected`, `no_valid_sample`, `last_sample_invalid`, `stale`, `no_neutral`.
- Any future command-producing module must use `TrackingGate`. **Invalid or stale tracking must never trigger musical commands.** Phase 1 displays and logs the gate only.
- A new connection invalidates the neutral, so a new capture is required (open item O5 in the proposal).

## Neutral capture

1. The operator requests a capture (viewer key `N`, or `--capture-neutral-at`). Samples after the request are collected until the device-clock span since the first collected sample exceeds `window_s` (3 s).
2. **Accepted iff:**
   - (a) every window sample is valid;
   - (b) no `gap_before` inside the window;
   - (c) no connection change before the window closes;
   - (d) dispersion `max θ(qᵢ, q0) ≤ tau_stab_deg`.

   `tau_stab_deg` is set to 2.0° as a **placeholder**, to be chosen from bench data (O6). It is not a statement about human stillness.
3. If accepted, `q0` = the sign-aligned mean, and the neutral applies from the first sample after the window (`applies_from_seq`).
4. Every attempt, accepted or rejected (with reasons, `n`, max and RMS dispersion), is written to `calibration_neutral.jsonl`. Retries are unlimited and operator-initiated. A request during an active capture is rejected with `capture_in_progress`.
5. Parameters given in a command (the viewer and CLI always send them) are recorded and take precedence on replay.

## Metrics (`headmusic analyze`)

All metrics are computed per connection on valid samples, overall and per 60 s segment. Fixture and worn recordings are
never pooled; reports carry the `mounting` label.

| Metric | Definition |
|---|---|
| Achieved rate | (N−1)/(t_last − t_first) on the device clock and on the host clock |
| **Sampling-interval jitter** | Distribution of consecutive intervals (device Δd and host Δh): min, p1, p5, p50, p95, p99, max, mean, SD. Summaries are SD and p99−p1. Device intervals are floored by the 1 ms resolution |
| **Arrival-time jitter** | Least-squares fit host = a + b·device. Reported: skew (b−1)·10⁶ ppm; residual SD and p99−p1; relative lateness = residual − min(residual). **Relative, not absolute, latency** |
| Loss | Gap count, longest gap, estimated missing samples; loss fraction = 1 − N/(span·r_ref + 1); pipeline seq gaps; shim ring overflow |
| **Angular jitter** (stationary only) | ref = mean of the first `w_ref_s` (5 s); v(t) = rotation vector of conj(ref) ⊗ q(t) in degrees (sequence-free). Jitter = per-component SD of v minus its centred moving average over `w_jitter_s` (1 s), plus geodesic RMS. Cross-check: RMS of consecutive geodesic steps / √2 |
| **Apparent drift** (stationary only) | Least-squares slope of each v component and of θ(ref, q) vs device time (°/min); net change between the first and last `w_ref_s` means; maximum excursion. "Apparent" because sensor bias, SDK filter and fixture creep cannot be separated |

Angular metrics are computed only when the session is declared stationary (`record --stationary` or `analyze --stationary`).
The declaration must reflect a setup the operator confirmed. A worn recording includes natural head movement.
