# Bench report (G0) — in progress

**Status:** preliminary. Every hardware run listed here happened on 2026-11-10, **before the operator-approval rule was in
place**. The glasses' physical state during these runs was not confirmed, and in at least one run they were being moved.
Use these numbers only to plan the approved runs in [bench-checklist.md](bench-checklist.md). They are not
characterisation results.

## Runs so far (conditions unconfirmed)

| Run | What | Result | Caveat |
|---|---|---|---|
| Read-only probe (Python ctypes, 5 s pose + 2 s raw) | Identity, capability table, timestamp units | Pro / Gen1 / fw `07.0.03.013_20250422`; pose ≤ 240 Hz; 240 → 202.5 Hz; device ts in ns with 1 ms resolution | Glasses stationary (orientation constant), placement unknown |
| Toolchain comparison (5 × 20 s) | Native C++ vs Python callback vs Python + C shim, idle and under synthetic GIL load | Python callback under load lost 58% of samples; the shim and native C++ lost none (proposal §3.5) | Glasses stationary, placement unknown |
| `pytest --hardware` (4 × 10 s) | Streaming at 60/90/120/240 Hz | All passed; occasional `ts_duplicate` reports | Conditions unknown |
| Record, 10 s at 60 Hz | Invalid-sample investigation | One real duplicate-timestamp report (seq 185: 16 → 0 → 17 ms, values differ); live vs replay byte-identical | Stationary, placement unknown |
| **Viewer + record, 30 s at 240 Hz** | GUI smoke test | Viewer ran without errors; 200.6 Hz; arrival residual SD 0.46 ms; one 297 ms device-side gap at about 3 s; neutral capture correctly rejected (gap + 81° dispersion) | **Glasses moved about 100–178° from 3 s on (picked up or worn).** Labelled `fixture`/`stationary` in its `session.json`, but that label is **wrong**: its stationary metrics are meaningless |
| Rate measurement, 4 × 15 s, no data stored | Achieved rate per frequency | 60 → 59.40; 90 → 84.67; 120 → 112.29; 240 → 202.61 Hz; no gaps or overflow; 0–2 duplicate-ts reports per run | Started without the operator's approval; conditions unknown |

The viewer session is in `data/sessions/20261111T012132Z_bench_fixture_8bd58367/` (git-ignored). Its labels are
incorrect, as noted above. Deleting it, or keeping it as a known-bad example, is the operator's decision.

## Software checks that need no hardware conditions

- 107 unit tests pass (no glasses): math, flags, neutral capture, gate, recording round trip, replay byte-identity on 5
  synthetic scenarios, export reproducibility, metric recovery, module boundaries, SDK prototypes vs headers, and the shim.
- On real data, live and replayed processed output are byte-identical (10 s, 60 Hz session, including a real `ts_duplicate`).

## To do (each run only after the operator approves it)

Checklist steps 1–13. Then replace the `[flags.r_ref_hz.pose]` defaults with the fixture-measured rates.
