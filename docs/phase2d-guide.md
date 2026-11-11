# Phase 2D: demo guide, smoke-test plan and issue log

**Status (2026-11-11):**
- **Done:** synthetic replay demos, and the end-to-end `play` test with a simulated device.
- **Waiting for the operator's approval:** live bench run R2D-1 (glasses on the table, not worn).
- **Waiting for O3:** worn use.

**Every angle and time below is a provisional engineering default**, not an ergonomic claim. No participant or research data is collected in Phase 2.

## 1. Readiness of `phase2/2c-play-app`

| Item | State |
|---|---|
| Code | 2A gesture FSM, 2B chord engine and MIDI, 2C play window and `headmusic play`, plus the 2D preparation below |
| Device files | `vendor/viture/.../glasses.dll` and `native/build/capture_shim.dll` present (built 2026-11-10) |
| Audio | Windows MIDI device 0, "Microsoft GS Wavetable Synth". `midi-test` audible (operator, 2026-11-11) |
| Tests | Unit, fault-matrix, replay and window tests, plus **`test_play_e2e.py`**: the full `play` command with a simulated device in real time. It covers neutral capture, two chords, a live-detected 300 ms pause, panic on close, recording, `replay --reprocess` identity and the report. No glasses |
| Not yet run | `headmusic play` with the real glasses (R2D-1) |

## 2. Synthetic replay demos (no glasses)

The sessions are already in `data/sessions/` (git-ignored). Run each in a terminal; the play window opens with sound. Esc silences everything at any time; it is the only key active in replay.

**Demo A, the four chords:**

```bash
headmusic replay data/sessions/20261111T181339Z_bench_synthetic_1b6cadbf --instrument --view --speed 1
```

The neutral is captured, then C, G, Am and F each play once, with the dwell bar filling for 0.5 s. Between chords the state reads "PLAYED: return to neutral". On the way to C and F, the cursor briefly lights up G or Am: see U1.

**Demo B, the safety behaviour with G0 fault patterns** (`synth chords_faults`):

```bash
headmusic replay data/sessions/20261111T183715Z_bench_synthetic_3aa63bdc --instrument --view --speed 1
```

| What happens in the trace | What you should see and hear |
|---|---|
| C commits, then a 300 ms device pause while the head stays in C | C stops. Nothing re-commits until a return to neutral |
| A duplicate device timestamp during the G dwell | The G dwell cancels; G is not played on this visit |
| Am | Plays normally |
| Disconnect during the F dwell; reconnect with the head still at F | Silence and `NOT CONNECTED`, then "press N to capture a neutral". Nothing plays at F |
| New neutral captured, return to neutral, F again | F plays |

Expected commits: **C, Am, F**. `headmusic instrument-report <session>` prints the summary: resets `gap`, `last_sample_invalid`, `disconnect`.

To regenerate either session:

```bash
headmusic synth chords --instrument
```

```bash
headmusic synth chords_faults --instrument
```

## 3. Emergency stop and note release (confirmed before live use)

| Behaviour | Evidence |
|---|---|
| Esc / red button → `panic`: every sounding note off, CC 123 and CC 120 on the chord and click channels, `midiOutReset`, accompaniment stopped, FSM disabled until E | `test_panic_silences_everything_and_disables_selection`; window test `test_play_window_draws_and_sends_only_commands` |
| If the pipeline does not act on Esc within 300 ms, the window silences the engine directly | `test_emergency_stop_fallback_silences_when_the_pipeline_does_not_act` |
| Every note-on gets exactly one note-off, in every scenario | `check_pairing` in all engine tests |
| Release on any interruption (pause, invalid sample, disconnect, new neutral, capture, stop) | `test_interruption_releases_the_sounding_chord`; e2e test (live stale tick → `interruption:stale_tick`) |
| Closing the play window sends panic before the slow device teardown | e2e test: `panic` is the last command and the last music events are `panic`, `engine_stop` |
| Exception in the FSM or engine → silence; recording continues | `test_consumer_exception_silences_output_and_keeps_the_pipeline_running` |
| MIDI backend error → no crash, no further sound | `test_backend_failure_does_not_crash_and_stops_sending` |
| Ctrl-C or an exception during processing → all notes off | `test_stack_close_runs_even_if_processing_raises` |

**Manual check in Demo A:** press Esc while a chord sounds. The sound should stop at once, and the window should say the emergency stop was applied.

## 4. Gesture angles: review

| Finding | Consequence |
|---|---|
| The default layout reaches **±40°** (C +22…+40°, F −40…−22°). It was chosen for bench separation | Fine for R2D-1, where the glasses are turned by hand on a table. For any worn demonstration (after O3), 40° turns are large next to the protocol's "comfortable small head movements" (§3) |
| **U1 (usability, found here):** four chords on one yaw axis means reaching C or F passes through G or Am. A turn slower than *region width ÷ dwell* stays in the inner region long enough to commit it: 10° / 0.5 s = **20°/s** with the defaults, and 6° / 0.5 s = 12°/s with the small profile | Pinned by `test_slow_turn_through_an_inner_region_commits_it`: 40 and 25°/s pass, 18°/s commits G |
| Fixture jitter (≈ 0.0008°) is far below every radius | Region sizes are not limited by sensor noise. Worn head motion is unmeasured (O3) |

**Optional profile `config/profiles/small_yaw.toml`:** C +16…+24°, G +6…+12°, Am −12…−6°, F −24…−16°; neutral ±3°, hysteresis 1°; dwell unchanged at 500 ms.
- It reduces the turn needed. It is **not** shown to be easier or more comfortable.
- Its narrower regions will likely cancel more dwells.
- Use it with `headmusic --config config/profiles/small_yaw.toml play …`.
- It is a candidate for the research team (Q2–Q5, Q15), not a default.

**Options for U1** (research decisions; nothing has been changed):
- a longer dwell;
- narrower inner regions or wider gaps;
- a two-axis layout, for example turn for two chords and nose up/down for two, as in proposal revision 1;
- ignoring dwell time while the head moves faster than some speed, which adds a new threshold.

## 5. Live hardware smoke test R2D-1 (needs your approval first)

| | |
|---|---|
| Goal | The real stream drives the instrument: chords from turns, release on emergency stop and unplug, recovery, logs |
| Mounting | `fixture`: glasses upright on the hard table, arms open, cable taped as in R2–R10. **Not worn.** Turned by hand, flat on the table, about the vertical (as in R6a) |
| Audio | Windows MIDI device 0, at a comfortable volume |
| Profile | Defaults (the ±40° bench layout suits table turns). An optional second short run can use `small_yaw` |
| Data | Recorded to `data/sessions/…_bench_fixture_…`, `participant_id = null`. Engineering data only |
| Duration | About 5 minutes |

| Step | Operator action | Pass if |
|---|---|---|
| 0 | `headmusic check-placement` (15 s, nothing recorded), glasses untouched | tilt about 5°, 0 invalid, no gaps |
| 1 | `headmusic play --capture-neutral-at 3 --notes "R2D-1 bench, hand-turned on table"` and keep your hands off | HUD: tracking usable → capturing → `NEUTRAL: armed` |
| 2 | Turn the glasses about 30° left and hold about 1 s, then back to the centre. Repeat for about 13° left, about 13° right and about 30° right | C, G, Am, F each sound once. HUD dwell bar, then "PLAYED" |
| 3 | Turn to G and hold. While it sounds, press **Esc** | Silence at once. HUD: EMERGENCY STOP |
| 4 | Press **E**, return to the centre, then play Am | Am sounds only after the return |
| 5 | Turn to C and hold it. Unplug the USB cable at the PC for about 5 s, then plug it back in | Silence on unplug. `NOT CONNECTED`, then "press N". Nothing plays while the glasses are at C |
| 6 | Hands off, press **N**, wait for neutral; return to the centre; play F | F sounds |
| 7 | Close the window | Silence; the session closes |
| After | `headmusic instrument-report <session>` and `headmusic replay <session> --reprocess --instrument` | Commits as performed; both logs identical on replay |

**Also note during the run (subjective, not a measurement):**
- whether the sound seems late relative to the HUD;
- any chord that played or did not play unexpectedly;
- any pauses, which show as "tracking stale" on the HUD.

The report gives the estimated software-side timing. Audio-output latency is not measured (O4).

## 6. Human data stays separate until O3

- `headmusic play --mounting worn` **refuses to run** unless `--o3-cleared` is given. When it is given, the session notes say "worn developer self-test under O3 guidance; not participant or research data" (tested).
- All Phase 2 sessions have `condition = bench` and `participant_id = null`. There are no participant IDs, consent or rating fields in Phase 2.
- Phase 1's `record` and `view` still accept `--mounting worn`, as before. Their use also waits for O3 (operator rule).

## 7. Issue log

| ID | Kind | Description | Status |
|---|---|---|---|
| U1 | Usability | Slow turns through G or Am to reach C or F commit the inner chord (threshold about 20°/s with the defaults) | Open; research decision (Q15). Characterised by a test |
| U2 | Usability | The `small_yaw` profile's 6–8° regions likely cancel more dwells | Unverified; check in a later run |
| A1 | Audio | The GS Wavetable Synth has noticeable output latency (known; not measured here) | Open. Options: a loopback MIDI port with a low-latency synth, or built-in synthesis (`sounddevice`, P6). Measurement needs O4 |
| T1 | Tracking | Duplicate device timestamps cancel a dwell: an estimated 5 % of 500 ms dwells at 240 Hz requested | Open (Q12). Check the count of `last_sample_invalid` cancels in the R2D-1 report |
| T2 | Tracking | 300/600 ms device pauses and cable-movement disconnects (G0) | Handled by design (reset, release); to be observed in R2D-1 |
| B1 | Bug, fixed | The engine's stop reason was written to the deterministic log, so a live session and its replay differed | Fixed here: the reason goes to the timing log. Covered by the e2e test |
| H1 | Display | The HUD is on the PC monitor. Showing it in the glasses means wearing them | Waits for O3 |
| P1 | Process | CI does not run: the token lacks the Workflows permission, so `ci/unit-tests` is unpushed | Open (your decision) |

Add rows for anything found in R2D-1.

## 8. Merging the stacked PRs (#3 → #4 → #5 → #6)

The repository does not delete merged branches (`delete_branch_on_merge = false`), so GitHub will not retarget the stacked PRs. A plain retarget would conflict on `docs/phase2-proposal.md` (add/add, found by a dry run). The procedure below needs **no force push**: after each squash merge, main's content equals the merged branch's content, so the next branch takes main's history with an `ours` merge that keeps its own files.

1. Squash-merge **#3** into `main`.
2. In `phase2/2a-gesture-fsm`:
   1. Fetch, then check that main's tree equals `origin/phase2/proposal`'s tree (no other changes in main).
   2. Merge main with `git merge -s ours origin/main`.
   3. Push.
   4. Retarget: `gh pr edit 4 --base main`.
   5. Squash-merge **#4**.
3. Repeat for `phase2/2b-music-engine` (**#5**, check against 2A's tree) and `phase2/2c-play-app` (**#6**, check against 2B's tree).

The dry run of the whole chain, done with commit objects only and no branch changed:
- the retargeted PRs show exactly their own milestone (2A 20 files, 2B 19, 2C 11);
- the final main tree equals the 2C branch tree.

Each push and merge goes through your approval hook.
