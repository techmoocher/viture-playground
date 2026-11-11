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
