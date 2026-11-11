# Bench report (G0) — in progress

**Status:** preliminary. Every hardware run listed here happened on 2026-11-10, **before the operator-approval rule was in
place**, so the glasses' placement was not agreed beforehand.

The operator later confirmed that the glasses were **lying upside down on the table**, and that during the viewer run they
were picked up and worn. The data agrees: in the stationary runs the glasses' up axis points down (z ≈ −0.98 in the
tracking frame) and the SDK pitch reads about −168° to −172°.

How to use these runs:
- Timing and rate figures are usable as preliminary values.
- Orientation results (stability, drift) come from an upside-down placement that is not representative of use.
- None of them are characterisation results. Use them only to plan the approved runs in [bench-checklist.md](bench-checklist.md).

## Runs so far (conditions unconfirmed)

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

## Software checks that need no hardware conditions

- 107 unit tests pass (no glasses): math, flags, neutral capture, gate, recording round trip, replay byte-identity on 5
  synthetic scenarios, export reproducibility, metric recovery, module boundaries, SDK prototypes vs headers, and the shim.
- On real data, live and replayed processed output are byte-identical (10 s, 60 Hz session, including a real `ts_duplicate`).
- In the viewer run, the processing behaved as designed:
  - the gap was flagged;
  - the capture whose window spanned the pickup was rejected with both reasons;
  - the SDK sign jumps during the movement were made continuous;
  - no `q_rel` was produced without an accepted neutral.

## To do (each run only after the operator approves it)

Checklist steps 1–13. Then replace the `[flags.r_ref_hz.pose]` defaults with the fixture-measured rates.
