# G0 bench checklist (protocol §2.3, gate G0)

Engineering characterisation of the device. These are **not** participant procedures. Worn recordings by developers wait for
open item O3 (IRB/faculty confirmation).

**Every run is set up together with the operator, then approved.**
1. The person running the software describes what will run, how long it takes, and the physical setup: support, placement
   and cable.
2. The operator sets it up and says when it is ready. A one-click confirmation is not enough: R2 on 2026-11-10 started
   that way and recorded moving glasses as "stationary".
3. Before a recording, a **placement check** runs: `headmusic check-placement`, ~15 s, writes no files. It shows the tilt from
   upright and how much the orientation moved. The operator decides from those numbers whether to start; no pass threshold
   is applied.
4. If the data during a run shows the setup is wrong, the run is stopped and the operator is told.

Close VITURE's own apps first.

**Standard "fixture" placement:**
- The glasses are **upright**: arms open, lenses facing forward, nose bridge down.
- The support is **rigid**. Two options:
  - **upright on a hard, flat table**, resting on the bottom of the frame and the arm tips. This is the default;
  - a stand, such as a head form or a box with the arms resting on it.

  The glasses must not be held, worn, or on anything soft.
- The USB cable lies slack and is taped to the table a few centimetres from the glasses, so it cannot pull them.
- **Never lying upside down or folded.** Earlier unannounced runs were upside down; the SDK then reported pitch ≈ −170°,
  which is not representative of use.
- During a stationary run, nobody touches or leans on the table, nobody types on it, and no fan blows on the glasses.
  If the glasses are moved, say so, and the run is re-labelled or discarded.
- Neutral captures (`--capture-neutral-at`, or `N` in the viewer) happen only after the placement check.
- **Tilt from upright** (placement check, viewer, and `q0_tilt_from_upright_deg` stored with each neutral capture):
  - A value far above 90° means the glasses are upside down.
  - Upright on a table, they lean back by some degrees compared with being worn. The value is recorded with the run, not
    corrected.
  - The readout is a placement aid only.

## Equipment

- A hard, flat table that nothing else touches during the runs (keep the keyboard elsewhere), and tape for the cable.
  A stand is optional.
- A 90° yaw reference on the table: two tape lines at a right angle, or a carpenter's square against the stand.
- A wedge of roughly 15–25° with a non-slip top (a ramp, or a book propped on a block). The exact angle does not matter:
  the tilt readout measures it. The glasses must not slide on it while it is moved.
- Optional: a turntable (lazy Susan) that can be tilted, for the second U1 variant.

## Run plan (one approval per run)

Commands are `.venv\Scripts\python -m headmusic …`. Every run writes a session to `data/sessions/` and is analysed with
`headmusic analyze <session>` (add `--stationary` only for runs declared stationary).

| Run | Steps | Command | Duration | Placement | Operator action |
|---|---|---|---|---|---|
| R1 | 1 | `info` | ~5 s, no streaming | Connected; any placement | None |
| R2 | 3, and 2 at 240 Hz | `check-placement`, then `record --freq 240 --duration 600 --mounting fixture --stationary --capture-neutral-at 2` | 15 s + 10 min | Upright on the table (or stand), room quiet | Set up, then leave the table untouched |
| R3–R5 | 2 at 60, 90, 120 Hz | `record --freq F --duration 300 --mounting fixture --stationary --capture-neutral-at 2` | 3 × 5 min | Same | Untouched |
| R6 | 4–8 | `view --record --mounting fixture` | ~15 min | Stand and wedge on the table | Follow the segment script below |
| R7 | 9 | `view --record --mounting fixture --segment unplug` | ~2 min | Stand | Unplug the USB cable for ~5 s, replug |
| R8 | 9b | `view --record --mounting fixture --segment pickup` | ~2 min | Stand | Lift the glasses off the stand, hold ~5 s, put back (not worn) |
| R9 | 10 | `view --record --mounting fixture --segment sleep` | ~3 min | Stand | Put the PC to sleep ~30 s, wake it |
| R10 | 11 | `view` twice | ~1 min | Stand | None |
| R11 | 12 | `view --record --close-after 600 --mounting fixture --stationary --capture-neutral-at 2` | 10 min | Upright on the stand | Untouched |
| R12 | 13 (optional) | `record --mode raw --freq 500 --duration 120 --mounting fixture --stationary` | 2 min | Stand | Untouched |

R2 covers both step 3 and the 240 Hz part of step 2, which saves one 5-minute run. Each stationary run (R2–R5, R11, R12)
starts with the 15-second placement check.

## Steps

| # | Step | Setup the operator confirms | Command (example) | Pass / record |
|---|---|---|---|---|
| 1 | Identity | Glasses connected | `headmusic info` | PID, model "Pro", Gen1, firmware, SDK 2.4.2 written in the report |
| 2 | Rate per frequency | Glasses resting still on a rigid fixture, not worn | `headmusic record --freq F --duration 300 --mounting fixture --stationary --capture-neutral-at 2` for F = 60, 90, 120 (240 from step 3) | Requested / selected / achieved table; candidate `r_ref` per frequency (see below) |
| 3 | Stationary ≥ 60 s and 10 min | Same fixture, untouched, room quiet | `record --freq 240 --duration 600 --mounting fixture --stationary --capture-neutral-at 2` | Angular jitter, apparent drift (per axis and geodesic), arrival jitter, per-minute stability |
| 4 | Axis and sign: yaw | Stand turned by hand on the table against the 90° reference | Segments `yaw_left_90`, `yaw_right_90` (R6) | Segment report: `P_head` yaw ≈ +90 for a left (counter-clockwise from above) turn, ≈ −90 for a right turn; axis near vertical |
| 5 | Axis and sign: pitch | Glasses tilted nose-down onto the wedge | Segment `pitch_down` (R6) | `P_head` pitch > 0; axis near the head-frame +Y (≈ 90° from vertical) |
| 6 | Axis and sign: roll | Glasses tilted right lens down onto the wedge | Segment `roll_right_down` (R6) | `P_head` roll > 0; axis near the head-frame +X |
| 7 | Quaternion direction (U1) | Glasses fixed on the wedge (pitched), the whole wedge turned ~90° on the table | Segments `u1_pitched_about_vertical`, `u1_rolled_about_vertical` (R6) | See "Reading the U1 result" below |
| 8 | Recenter behaviour | Fixture | In the viewer: capture neutral, rotate, capture again (R6) | Raw stream has no jump at the recenter; `neutral_calibration_id` increments; rejected attempts carry reasons |
| 9 | Unplug / replug | Fixture | `view --record`, unplug the USB cable for about 5 s, replug | `device_disconnected` then `device_connected` with a new `connection_id`; gate not usable until a new neutral; no samples valid during the outage |
| 9b | Pick-up pause | Fixture, then the operator lifts the glasses off the stand and puts them back, without wearing them | `view --record --segment pickup` | Is the 297 ms device-side pause seen at pickup reproducible? Is it cable movement or something on the device? Is it flagged as a gap, with the gate not usable? |
| 10 | Sleep / wake | Fixture | `view --record`, put the PC to sleep for about 30 s | Behaviour documented (reconnect or error); no stale data used |
| 11 | Second process | Fixture | Run `view` twice | The second instance fails cleanly with the single-process hint |
| 12 | Headless vs viewer timing | Fixture | Step 3 headless, then `view --record --close-after 600` of the same length | Arrival-time jitter and loss compared (U7) |
| 13 | Raw mode (optional) | Fixture | `record --mode raw --freq 500 --duration 120 --mounting fixture` | Achieved raw rate; channel statistics (units undocumented) |

## Segment script for R6 (steps 4–8)

The segment report (`headmusic analyze`, section "Segments") compares the mean orientation of the **first** and **last**
second of each segment (`metrics.segment_window_s`). So in every segment: **hold still ≥ 2 s, move, hold still ≥ 2 s.**
The report shows the dispersion of both windows, so a window that was not still is visible.

In the viewer: type the label, press **Start segment**, do the movement, press **End segment**.

1. Glasses upright on the stand, aligned with the first tape line. Press **N** and wait until the capture is accepted.
2. `yaw_left_90`: turn the stand 90° counter-clockwise (seen from above) to the second line, keeping it flat on the table.
3. `yaw_right_90`: turn it back 90° clockwise.
4. `pitch_down`: from upright, tilt the glasses nose-down onto the wedge.
5. `roll_right_down`: from upright, tilt the glasses right lens down onto the wedge.
6. `u1_pitched_about_vertical`: glasses resting nose-down on the wedge. Turn the **whole wedge** ~90° counter-clockwise on the
   table, keeping the wedge flat on the table and the glasses fixed on it.
7. `u1_rolled_about_vertical`: the same with the glasses resting right lens down on the wedge.
8. Optional `u1_own_up_axis`: glasses flat on a turntable that is itself tilted on the wedge; turn the turntable ~90°.
9. Step 8 (recenter): glasses upright on the stand. Press **N**, turn the stand ~45°, press **N** again.

## Reading the U1 result

For each segment the report gives two products of the start and end orientations, `P_head = conj(q_s) ⊗ q_e` and
`P_track = q_e ⊗ conj(q_s)`. For each product it also shows the angle between the product's rotation axis and the vertical.

- **Turning the wedge on the table** is a rotation about the tracking-frame vertical (segments 6 and 7). Two outcomes are possible:
  - `P_track` is near vertical (≈ 0°) and `P_head` is off vertical by about the start tilt. This means the SDK quaternion maps
    head → tracking frame (`q_WH`), as `docs/conventions.md` assumes.
  - The reverse: `P_head` is near vertical and `P_track` is off vertical by about the start tilt. This means the SDK reports
    the inverse (tracking → head).
- **Turning a tilted turntable** is a rotation about the glasses' own up axis (segment 8), so the roles swap:
  - under `q_WH`, `P_head` is near vertical;
  - under the inverse, `P_track` is near vertical.

The two candidates are separated by the start tilt (≈ the wedge angle), and this test only relies on the tracking frame's
+Z being up (SDK NWU). Both outcomes are reproduced with synthetic data in `tests/test_segments.py`. The result is read from the
recorded numbers; no threshold is applied.

If the inverse reading is found: stop before any further runs. `quat_rel`, Euler and the sign checks depend on it.
Correcting it changes processing and requires reprocessing every session. The raw files are unaffected.

Steps 4–6 are interpreted under the reading that U1 establishes. Under the inverse reading, the expected signs of `P_head` flip.

## Deriving `r_ref` (steps 2–3)

`r_ref` is the reference rate used to detect gaps (`[flags.r_ref_hz.pose]`). The only current value is 202.5 Hz for 240 Hz.
It came from a preliminary run whose placement was unknown, and the other frequencies have no value (they fall back to the adaptive reference).

- **Candidate per frequency:** the achieved device-clock rate over the **longest gap-free stretch** of the stationary fixture
  run at that frequency. `analyze` reports it as "longest gap-free stretch: rate / duration".
- **Adopt** the candidate in `defaults.toml`, with a comment naming the session id, the stretch duration and the value. Keep the
  preliminary value in `bench-report.md` for comparison.
- **Re-check.** The stretch depends on the `r_ref` used to find the gaps. Analyse the run with the candidate value
  (`analyze <session> --reference-rate-hz <candidate>`) and confirm the gap count and the stretch do not change.
  Then analyse it again without the option, so the stored report is the standard one.
  `replay --reprocess` cannot do this check: it reuses the reference rate recorded in the session.

After each run, write the outcome into [bench-report.md](bench-report.md) and update the "Status" column of
[conventions.md](conventions.md). Choosing the `tau_stab_deg` value (O6) is a research-team decision, informed by steps 3 and 8.
