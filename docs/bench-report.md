# Bench report (G0) — in progress

## Approved runs (run plan in [bench-checklist.md](bench-checklist.md))

Each run below was approved by the operator before it started, with its setup stated.

| Run | Date | Step | Setup | Result |
|---|---|---|---|---|
| R1 | 2026-11-10 | 1 Identity | Glasses connected; no streaming | SDK 2.4.2; PID 0x101D; market name "Pro"; device type 0 (GEN1); firmware `07.0.03.013_20250422`; native DOF false. Frequencies supported: pose 60/90/120/240 Hz (not 500/1000); raw 60/90/120/240/500 Hz (not 1000). Identical to the earlier probe |
| R2, first attempt | 2026-11-10 | 3, and 2 at 240 Hz | Approved as upright on a rigid stand, untouched; neutral capture at 2 s | **Aborted after 455 s, not stationary: not a characterisation result.**<br>Neutral capture rejected (`dispersion_exceeds_tau_stab`, 7.0° within the 3 s window; tilt 8.8°).<br>The orientation kept moving: the spread within 10 s windows was mostly 1–10°, and 23–56° around 410–440 s. An untouched rigid placement earlier stayed within 0.011°.<br>Stopped on the operator's request by ending the process, so `session.json` has no closing summary. The session's `fixture` / `stationary` labels do not match what was recorded.<br>Timing only, preliminary: 92 259 samples, 202.59 Hz achieved over the run.<br>Session `20261111T031659Z_bench_fixture_0dc0ba01` was deleted on the operator's decision, so the figures above are all that remain. To be repeated with a rigid support agreed with the operator and a placement check before recording |
| Placement check before R2 | 2026-11-11 | — | Upright on a hard flat table, cable taped; set up by the operator | 15.1 s, nothing recorded: tilt from upright 4.7°; maximum deviation from the mean 0.015° (RMS 0.003°); 0 invalid samples; **1 gap** (≈ 120 samples missing, 194.4 Hz over the check). The check stores no data, so where the gap fell is unknown. It did not recur in R2 |
| **R2** | 2026-11-11 | 3, and 2 at 240 Hz | Same setup, table untouched; neutral capture at 2 s | **Valid stationary fixture run, 600 s.** Session `20261111T034301Z_bench_fixture_710efe0c`; see "R2 results" below |
| Placement check before R3 | 2026-11-11 | — | Same setup, untouched since R2 | 15.1 s at 60 Hz, nothing recorded: tilt 4.7°; maximum deviation 0.020° (RMS 0.004°); 0 invalid; 0 gaps; 59.4 Hz |
| **R3** | 2026-11-11 | 2 at 60 Hz | Same setup, table untouched; neutral capture at 2 s | **Valid stationary fixture run, 300 s.** Session `20261111T040406Z_bench_fixture_0fd7c040`; see "Rate per frequency" below |
| Placement check before R4 | 2026-11-11 | — | Same setup, untouched | 15.1 s at 90 Hz, nothing recorded: tilt 4.8°; maximum deviation 0.006° (RMS 0.003°); 0 invalid; 0 gaps; 84.6 Hz |
| **R4** | 2026-11-11 | 2 at 90 Hz | Same setup, table untouched; neutral capture at 2 s (accepted, 0.0035°) | **Valid stationary fixture run, 300 s.** Session `20261111T041148Z_bench_fixture_98addf22`; see "Rate per frequency" below |
| Placement check before R5 | 2026-11-11 | — | Same setup, untouched | 15.1 s at 120 Hz, nothing recorded: tilt 4.8°; maximum deviation 0.006° (RMS 0.003°); 0 invalid; 0 gaps; 112.3 Hz |
| **R5** | 2026-11-11 | 2 at 120 Hz | Same setup, table untouched; neutral capture at 2 s (accepted, 0.0031°) | **Valid stationary fixture run, 300 s.** Session `20261111T042104Z_bench_fixture_bcf348a3`; see "Rate per frequency" below |
| R6a, first attempt | 2026-11-11 | 4–6 | Flat table, tape lines, wedge; handled by the operator, not worn | **No result: no neutral capture or segment was marked.** The viewer opened at 1000×700 on a 1280×800 screen (752 px usable), so its control bar at the bottom was off-screen. Fixed: the controls are now at the top, the window fits the screen, and each press is confirmed in the window.<br>Kept for the gap observation: 185 s, 36 672 samples, **9 gaps of 295–599 ms (≈ 776 samples missing)**, all while the glasses were being handled. They are in pairs about 0.4–0.8 s apart, a ≈ 600 ms gap then a ≈ 300 ms gap, at 81.8/82.6 s and 98.3/98.7 s. They fit the 297 ms pause at pickup in the earlier viewer run (step 9b). Session `20261111T043318Z_bench_fixture_bdbf687f` |
| R6a, second attempt | 2026-11-11 | 4–6 | Same; viewer with the controls at the top | **No result: no segment was marked**; the command log holds only 9 neutral captures. The first, on line A, was accepted (0.0029°, tilt 5.1°). Of the other 8, 6 were accepted and 2 rejected (`invalid_samples_in_window`), at tilts from 0.2° to 89.5°. Start/End segment work when invoked directly, so the manual controls were too error-prone while handling the glasses: a label, two clicks per step, and an N shortcut that also fires while typing outside the label box.<br>Replaced by the guided scripts (`view --script r6a`). 0 gaps in 383 s. Session `20261111T043909Z_bench_fixture_026263ce` |
| **R6a (guided)** | 2026-11-11 | 4–6 | Flat table with tape lines A/B and a wedge; guided script `r6a`; not worn | **Valid.** 1 neutral capture (accepted, 0.22°, tilt 5.4°) and 4 segments; 0 gaps in 165 s; 8 duplicate timestamps. Every sign and axis matches the documented conventions; see "R6a results" below. Session `20261111T045253Z_bench_fixture_c19c4fb1` |
| **R6b (guided)** | 2026-11-11 | 7 (U1) | Glasses fixed on the wedge (~55° tilt); the whole wedge turned on the table; guided script `r6b`; not worn | **U1 resolved: the SDK quaternion maps head → tracking frame (`q_WH`)**, as the processing assumes. 2 segments, 0 gaps, 4 duplicate timestamps; see "R6b results" below. Session `20261111T045720Z_bench_fixture_e7add480` |
| **R6c (guided)** | 2026-11-11 | 8 (recenter) | Flat table; guided script `r6c`; not worn | **Step 8 passes.** Neutral 1 accepted (0.0097°, tilt 5.1°), turn of 45.5° (`P_head` yaw +45.34°), neutral 2 accepted (0.105°, tilt 5.8°). At the switch to neutral 2 (seq 12446, the first sample after its window), the raw stream steps by 0.0015°, which is normal, so there is no jump. The relative orientation changes from (45.0, 2.1, −3.0)° to (0.0, 0.08, 0.05)°, and `neutral_calibration_id` goes 1 → 2. **4 gaps** of 296–599 ms; see "Gap pattern" below. Session `20261111T050010Z_bench_fixture_2dc3a853` |
| **R7 (guided)** | 2026-11-11 | 9 (unplug / replug) | Glasses untouched on the table; USB cable unplugged at the PC end for ~5 s; guided script `r7` | **Step 9 passes.**<br>Last sample at 38.11 s, `stale_begin` at 38.22 s, `device_disconnected` (`usb_device_removed`, teardown 14 ms) at 39.12 s, then `waiting_for_device`. `device_connected` with **connection 2** at 47.53 s (outage 9.4 s, including ~5 s unplugged). No samples during the outage, and no pipeline seq gap.<br>Neutral 1 (connection 1) does not carry over. Connection 2 is `no_neutral`, so the gate is not usable, until neutral 2 is accepted on it (0.0057°).<br>**The device clock restarts on replug** (13 228 s → 3.34 s). The processor resets its timestamp reference per connection, so no false `ts_backward` or gap was flagged.<br>SDK log: "Failed to send USB command - MsgID 0x0015, error -1" at removal, and "m_StateCallback is not initialized" ×2 during reconnect; streaming worked. One 52 ms gap 2.7 s after reconnect. Teardown on stop took 2.0 s.<br>Session `20261111T050317Z_bench_fixture_1bfcd8f1` |
| **R8 (guided)** | 2026-11-11 | 9b (pause causes) | Glasses on line A; guided script `r8`: cable moved at the PC end, a hand near the lenses, the glasses lifted and put back; not worn | **Moving the cable at the PC end caused a full USB disconnect** 14 s into `cable_move`: last sample at 22.29 s, `device_disconnected` (`usb_device_removed`) at 23.31 s, reconnected as connection 2 at 34.47 s (11.2 s outage; the device clock restarted, so the glasses power-cycled). Then gaps of 9 ms and 51 ms, 0.1 s and 2.4 s after reconnect.<br>`hand_near` (49 s): **0 gaps**. `lift_and_back` (20 s): **0 gaps**. The 300/600 ms pauses were not reproduced. Session `20261111T050559Z_bench_fixture_1219e7c9` |

### R2 results (240 Hz requested, upright on a table, stationary, 600 s)

Stillness was watched during the run: the maximum deviation was 0.010–0.014° per 2-minute block, and the tilt was 4.7° throughout.

| Quantity | Value |
|---|---|
| Samples | 121 590 delivered; shim ring overflow 0; pipeline seq gaps 0 |
| Invalid | 61 (0.05%), all `ts_duplicate`; no other invalidating flag |
| Achieved rate | 202.483 Hz on the device clock, 202.480 Hz on the host clock (requested and selected 240 Hz) |
| Gaps | 0 (r_ref 202.5 and the candidate 202.483 give the same result). Longest gap-free stretch: 600.2 s at 202.483 Hz |
| Device intervals | 4 ms: 9 804 · 5 ms: 109 372 · 6 ms: 2 352 (1 ms timestamp resolution). p50 5 ms, max 6 ms, SD 0.31 ms |
| Host intervals | p50 4.998 ms, p99 6.007 ms, max 6.478 ms, SD 0.330 ms |
| Clock relation | Skew 14.9 ppm. Arrival residual SD 0.438 ms, p99−p1 1.855 ms. Relative lateness p99 2.15 ms, max 2.64 ms (relative, not absolute, latency) |
| Neutral capture | Accepted: 609 samples, maximum dispersion 0.0051°, RMS 0.0023°, tilt 4.7° |
| Angular jitter (SD of detrended rotation vector) | x 0.000493°, y 0.000588°, z 0.0000414°; geodesic RMS 0.000768° |
| Apparent drift | x 0.00138, y −0.00093, z 0.00011 °/min; geodesic 0.00138 °/min. Net change 0.0174°, maximum excursion 0.0272° over 10 min |
| Change vs time lag (RMS) | 5 ms: 0.00005° · 50 ms: 0.00043° · 250 ms: 0.0013° · 1 s: 0.0026° · 5 s: 0.0044° · 30 s: 0.0059° |

Observations. These are engineering facts about this device, setup and firmware, not validated limits:
- **The SDK output is smooth.** Sample-to-sample changes (first-difference estimate 3.3·10⁻⁵°) are about 15× smaller than
  the 1-s detrended jitter. The residual motion is a slow, correlated wander, not white noise. This is consistent with
  filtering inside the SDK; the filter itself is undocumented.
- **The z component (about the glasses' up axis) is about 10× quieter than x and y,** in both jitter and drift.
- **All 61 duplicate timestamps are distinct samples.** Their values differ from the previous sample. Each arrives
  0.99–1.07 ms after the previous one on the host clock, with normal 4–5 ms device intervals around it. So the device
  delivers an extra sample within the same millisecond, or labels it one millisecond early. They remain invalidating
  (conservative). Whether to keep that is an open question; the rate is about one per 10 s.
- **`stale_begin` appears once, at 600.3 s.** That is when streaming stopped at the end of the run. It is not an interruption.
- **`r_ref` for 240 Hz adopted: 202.483 Hz** (was 202.5, preliminary), following "Deriving r_ref" in the checklist, and
  re-checked with 0 gaps.
- **Reporting fixes found with this run:**
  - `pipeline seq gaps` had counted the invalid samples, which are kept, not lost. It now uses every sample.
  - Small angles printed as 0.0000. They now show significant digits.

### R6a results (steps 4–6: axis signs; guided script, movements by hand)

`P_head = conj(q_s) ⊗ q_e` is the head-frame change under the documented reading (SDK quaternion maps head → tracking frame).

| Segment | Hold dispersion start / end | Tilt start → end | Net angle | `P_head` yaw / pitch / roll | `P_head` axis (head frame) | `P_track` axis from vertical |
|---|---|---|---|---|---|---|
| `yaw_left_90` (A → B, 90° left) | 0.38° / 0.27° | 4.7° → 10.8° | 91.2° | **+90.50** / 10.84 / −2.15 | (−0.112, 0.074, 0.991) | 4.4° (`P_head` 7.7°) |
| `yaw_right_90` (B → A) | 0.22° / 0.40° | 6.2° → 5.9° | 90.4° | **−89.83** / 4.98 / 6.84 | (0.103, −0.016, −0.995) | **0.3°** (`P_head` 6.0°) |
| `pitch_down` (onto the wedge, nose down) | 0.11° / 0.17° | 5.9° → 45.7° | 39.9° | 0.17 / **+39.84** / 1.44 | (0.033, 0.999, −0.008) | 89.2° |
| `roll_right_down` (onto the wedge, right side down) | 0.37° / 0.83° | 8.4° → 55.0° | 55.7° | −7.37 / −0.34 / **+55.25** | (0.990, −0.070, −0.119) | 74.7° |

- **Steps 4–6 pass under the documented reading:**
  - a 90° left turn gives +yaw and a right turn −yaw, about ±Z;
  - nose-down gives +pitch, about +Y;
  - right side down gives +roll, about +X.
- **The off-axis parts reflect the hand movements, not the processing.** They are a few degrees, for example 10.8° of pitch
  at the end of `yaw_left_90`, where the glasses came to rest tilted on line B. The wedge gave about 40° and 55° here,
  steeper than the 15–25° planned; that does not matter for signs.
- **Early U1 evidence:** in `yaw_right_90`, a rotation about the vertical with a 6.2° start tilt, `P_track`'s axis is 0.3°
  from vertical and `P_head`'s 6.0°. That is what the head → tracking reading predicts (`P_head` off vertical by about the
  start tilt); the inverse reading predicts the reverse. `yaw_left_90` is less clean, because the tilt changed during the
  turn. The decisive test with a larger tilt is R6b.
- **The windows were not perfectly still** (dispersion 0.1–0.8°): the glasses settled after being let go. That is small
  against 40–90° movements.
- **No gaps occurred while the glasses were handled,** here or in the second R6a attempt (0 in 383 s). The 9 gaps of
  300–600 ms in the first attempt are therefore not simply caused by handling. To be examined in step 9b.

### R6b results (step 7, quaternion direction U1)

For a rotation about the tracking-frame vertical, the documented reading (head → tracking) predicts that
`P_track = q_e ⊗ conj(q_s)` has a vertical axis and `P_head = conj(q_s) ⊗ q_e` is off vertical by about the start tilt.
The inverse reading predicts the reverse. See bench-checklist.md, "Reading the U1 result".

| Segment | Hold dispersion start / end | Tilt start → end | Net angle | `P_track` axis from vertical | `P_head` axis from vertical | Reading |
|---|---|---|---|---|---|---|
| `u1_pitched_about_vertical` | 0.43° / 1.11° | 55.0° → 58.8° | 161.4° | **2.6°** | **56.6°** | head → tracking, by a margin of > 50° |
| `u1_rolled_about_vertical` | 0.46° / 0.79° | 54.1° → 26.1° | 94.2° | 19.6° | 39.6° | Not clean: the tilt changed by 28° during the turn, so the glasses shifted on the wedge (or the wedge tipped). It points the same way, but is not used quantitatively |

- **The result is decisive.** The clean segment separates the two readings by about the start tilt (55°). The residual
  2.6° is consistent with the 3.8° change in tilt during the turn, and with the table not being perfectly level.
- **It agrees with R6a `yaw_right_90`:** 0.3° against 6.0° at a 6.2° start tilt.
- **Consequence: no processing change is needed.** `quat_rel = conj(q0) ⊗ q_WH` is the head-frame rotation relative to the
  neutral, as documented.
- **The rolled variant could be repeated for completeness.** It does not change the conclusion.

### Gap pattern while the glasses are handled (observation for step 9b)

| Session | Situation | Gaps (device interval) |
|---|---|---|
| R2–R5 (35 min in total) | Untouched on the table | none |
| R6a, first attempt (185 s) | Handled | 9: about 295–299 ms (5×) and 596–599 ms (4×); pairs 0.4–0.8 s apart |
| R6a, second attempt (383 s) and R6a guided (165 s) | Handled | none |
| R6b (92 s) | Wedge turned | none |
| R6c (65 s) | Handled | 4: 599 ms at 2.2 s (before any command); 296 ms at 19.3 s (between the neutral and the turn); 599 + 297 ms at 31.2/31.8 s (during the turn) |
| Earlier viewer run (preliminary) | Picked up | 1: 297 ms at the pickup |
| R7 (unplug test) | Untouched, cable unplugged and replugged | 1: 52 ms, 2.7 s after reconnect |
| R8 (step 9b) | Cable moved at the PC end, hand near, lifted | Cable: **full disconnect** (11 s), then 9 ms and 51 ms after reconnect. Hand near: none. Lift and back: none |

Observations. These are engineering observations; the cause is not established:
- **The gaps last about 300 ms or about 600 ms, never in between.**
- **The device timestamp jumps by the same amount as the host time.** So the device produced no samples in that time.
  This is not delivery delay on the PC side, which would show as a burst of late samples with continuous device timestamps.
- **They occur only in handled sessions, but not in every one.**
- **Step 9b (R8) tested two candidate causes:**
  - **A hand near the lenses and nose bridge** gave no gaps, so it is not supported as a cause.
  - **Moving the cable at the PC end** caused a full disconnect rather than a pause, so the USB connection is
    sensitive to cable movement.

  The 300/600 ms pauses were not reproduced on demand. A cable or connector disturbance remains the more plausible
  explanation, since handling also moves the cable at the glasses end, but it is **not established**.
- **A short gap a few seconds after (re)connecting is reproducible:** 52 ms at 2.7 s in R7, 51 ms at 2.4 s in R8.
- **Practical consequence for worn use:** head movement moves the cable. Expect occasional pauses and possibly
  disconnects, depending on the cable, the port and strain relief. Disconnect handling during a block is open item O5.
- **Relevance for later phases:** a 300–600 ms pause makes the tracking gate stale (> 100 ms). So it must never produce
  a musical command, and gesture state must reset. The processing flags it as `gap_before`.

### Rate per frequency (step 2; stationary on the table, pose mode)

| Requested = selected | Run | Duration | Achieved (device / host) | Device intervals (ms: count) | Gaps | Duplicate ts | Arrival residual SD | Jitter RMS (geodesic) | Apparent drift (geodesic) | `r_ref` adopted |
|---|---|---|---|---|---|---|---|---|---|---|
| 60 Hz | R3 | 300 s | 59.435 / 59.434 Hz | 16: 4 175 · 17: 12 621 · 18: 1 043 · 19: 5 | 0 | 5 (0.03%) | 0.491 ms | 0.000822° | 0.00293°/min | 59.435 |
| 90 Hz | R4 | 300 s | 84.613 / 84.611 Hz | 11: 5 413 · 12: 19 183 · 13: 804 | 0 | 3 (0.01%) | 0.424 ms | 0.000859° | 0.00187°/min | 84.613 |
| 120 Hz | R5 | 300 s | 112.342 / 112.340 Hz | 8: 4 238 · 9: 28 580 · 10: 912 | 0 | 8 (0.02%) | 0.416 ms | 0.000839° | 0.00118°/min | 112.342 |
| 240 Hz | R2 | 600 s | 202.483 / 202.480 Hz | 4: 9 804 · 5: 109 372 · 6: 2 352 | 0 | 61 (0.05%) | 0.438 ms | 0.000768° | 0.00138°/min | 202.483 |

Notes:
- **R3–R5 used the adaptive gap reference in their own processing,** because 60, 90 and 120 Hz had no `r_ref` yet. Their
  gaps were re-checked with the candidates (59.435, 84.613, 112.342 Hz): still 0, and the stretches are unchanged.
- **Duplicate timestamps at 60 Hz behave as at 240 Hz:** distinct values, arriving 0.89–1.15 ms after the previous sample.
- **At 60 Hz the first-difference estimate is 0.00012° (3.3·10⁻⁵° at 240 Hz).** This fits the slow wander seen in R2,
  because samples are farther apart in time.
- **The achieved rate is below the requested rate at every frequency,** as in the preliminary runs:
  - 60 Hz: 99.1% (mean period 16.82 ms);
  - 90 Hz: 94.0% (11.82 ms);
  - 120 Hz: 93.6% (8.90 ms);
  - 240 Hz: 84.4% (4.94 ms).

  The SDK documents the frequency values only as "60/90/120/240 Hz". The cause of the shortfall is not documented.
- **Behaviour is otherwise very similar across frequencies,** with no gaps or loss anywhere:
  - angular jitter RMS 0.00077–0.00086°;
  - apparent drift 0.0012–0.0029°/min;
  - arrival residual SD 0.42–0.49 ms;
  - duplicate timestamps 0.01–0.05%.
- **Step 2 is complete. Step 3 is complete for 240 Hz:** 10 min stationary, per-minute segments in R2's `report.json`.

## Earlier runs (before the approval rule; preliminary)

**Status:** preliminary. Every hardware run in this section happened on 2026-11-10, **before the operator-approval rule was in
place**, so the glasses' placement was not agreed beforehand.

The operator later confirmed that the glasses were **lying upside down on the table**, and that during the viewer run they
were picked up and worn. The data agrees: in the stationary runs the glasses' up axis points down (z ≈ −0.98 in the
tracking frame) and the SDK pitch reads about −168° to −172°.

How to use these runs:
- Timing and rate figures are usable as preliminary values.
- Orientation results (stability, drift) come from an upside-down placement that is not representative of use.
- None of them are characterisation results. Use them only to plan the approved runs in [bench-checklist.md](bench-checklist.md).

### Runs (conditions unconfirmed)

| Run | What | Result | Caveat |
|---|---|---|---|
| Read-only probe (Python ctypes, 5 s pose + 2 s raw) | Identity, capability table, timestamp units | Pro / Gen1 / fw `07.0.03.013_20250422`; pose ≤ 240 Hz; 240 → 202.5 Hz; device ts in ns with 1 ms resolution | Upside down on the table, still (max deviation 0.005°) |
| Toolchain comparison (5 × 20 s) | Native C++ vs Python callback vs Python + C shim, idle and under synthetic GIL load | Python callback under load lost 58% of samples; the shim and native C++ lost none (proposal §3.5) | Upside down on the table, still (max deviation 0.010° in the C++ run) |
| `pytest --hardware` (4 × 10 s) | Streaming at 60/90/120/240 Hz | All passed; occasional `ts_duplicate` reports | Presumably upside down on the table; orientation not stored |
| Record, 10 s at 60 Hz | Invalid-sample investigation | One real duplicate-timestamp report (seq 185: 16 → 0 → 17 ms, values differ); live vs replay byte-identical | Upside down on the table, still (max deviation 0.011°) |
| **Viewer + record, 30 s at 240 Hz** | GUI smoke test | Viewer ran without errors; 200.6 Hz; arrival residual SD 0.46 ms; one 297 ms device-side pause at about 3 s; the automatic neutral capture (started at 2 s) was correctly rejected (gap + 81° dispersion) | **Operator-confirmed: upside down on the table until about 3 s, then picked up and worn.** The pause coincides with the pickup. The session's `fixture`/`stationary` labels are **wrong**, so its stationary metrics are meaningless. It contains worn head-movement data (see O3) |
| Rate measurement, 4 × 15 s, no data stored | Achieved rate per frequency | 60 → 59.40; 90 → 84.67; 120 → 112.29; 240 → 202.61 Hz; no gaps or overflow; 0–2 duplicate-ts reports per run | Started without the operator's approval; placement unknown |

The viewer session is in `data/sessions/20261111T012132Z_bench_fixture_8bd58367/` (git-ignored). Its labels are wrong, and
it holds worn data of the operator's head. Deleting it, or keeping it as a known-bad example, is the operator's decision.

Lessons for the approved runs:
- **Placement is part of the run definition.** The glasses rest upright (arms open, lenses facing forward, as if worn)
  on a rigid stand, never upside down.
- **No automatic neutral capture** unless the operator has confirmed that placement.

### Offline look at existing data (2026-11-10, preliminary)

From the viewer session above, which is mislabelled and only partly on the table. These are observations to check in the approved runs, not results.

- **Duplicate timestamps are separate samples, not repeats.** There were 2 duplicates in 6020 samples (seq 1173 and 5710).
  - In both, the quaternion values differ from the previous sample, which arrived about 1 ms earlier on the host clock.
  - The intervals before and after are normal (4–5 ms), so the device delivered one extra sample inside the same millisecond.
  - They are still flagged `ts_duplicate` (invalidating), which is conservative. Whether to keep that is a question for step 2–3 data.
- **Device intervals at 240 Hz requested:** 4 ms (492), 5 ms (5415) and 6 ms (109), plus the one 297 ms pause at the pickup.

## Software checks that need no hardware conditions

- The unit tests pass without glasses (107 at the first commit; the count grows with the code). They cover:
  - math, flags, neutral capture, the gate and the recording round trip;
  - replay byte-identity on 5 synthetic scenarios and export reproducibility;
  - metric recovery, module boundaries, SDK prototypes vs headers, and the shim;
  - for G0, the segment report recovering yaw, pitch and roll signs, and telling the two quaternion readings apart (U1) in both bench procedures.
- On real data, live and replayed processed output are byte-identical (10 s, 60 Hz session, including a real `ts_duplicate`).
- In the viewer run, the processing behaved as designed:
  - the gap was flagged;
  - the capture whose window spanned the pickup was rejected with both reasons;
  - the SDK sign jumps during the movement were made continuous;
  - no `q_rel` was produced without an accepted neutral.

## To do (each run only after the operator approves it)

Runs R1–R12 of the run plan in [bench-checklist.md](bench-checklist.md), covering steps 1–13. Then replace the
`[flags.r_ref_hz.pose]` defaults with the fixture-measured rates, following "Deriving r_ref". The preliminary
values in this report stay as they are, for comparison.
