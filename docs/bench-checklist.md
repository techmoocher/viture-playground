# G0 bench checklist (protocol §2.3, gate G0)

Engineering characterisation of the device. These are **not** participant procedures. Worn recordings by developers wait for
open item O3 (IRB/faculty confirmation).

**Before every step, the operator approves the run.** The person running the software states what will run, how long it
takes, and how the glasses must be placed. Recordings start only after the operator confirms the setup.
Close VITURE's own apps first.

| # | Step | Setup the operator confirms | Command (example) | Pass / record |
|---|---|---|---|---|
| 1 | Identity | Glasses connected | `headmusic info` | PID, model "Pro", Gen1, firmware, SDK 2.4.2 written in the report |
| 2 | Rate per frequency | Glasses resting still on a rigid fixture, not worn | `headmusic record --freq F --duration 300 --mounting fixture --stationary --capture-neutral-at 2` for F = 60, 90, 120, 240 | Requested / selected / achieved table; set `[flags.r_ref_hz.pose]` from these values |
| 3 | Stationary ≥ 60 s and 10 min | Same fixture, untouched, room quiet | `record --duration 600 --mounting fixture --stationary --capture-neutral-at 2` | Angular jitter, apparent drift (per axis and geodesic), arrival jitter, per-minute stability |
| 4 | Axis and sign: yaw | Glasses on a flat surface, rotated by hand against a square edge | `view --record --segment yaw_left_90` | Rotate 90° to the left: displayed yaw ≈ +90 and the rotation axis is +Z of the neutral frame. Repeat to the right |
| 5 | Axis and sign: pitch | Glasses tilted nose-down on a wedge or protractor | `view --record --segment pitch_down` | Nose down: pitch > 0 |
| 6 | Axis and sign: roll | Glasses tilted so the right lens goes down | `view --record --segment roll_right_down` | Right side down: roll > 0 |
| 7 | Quaternion direction (U1) | Capture neutral with the glasses **pitched about 20°**, then rotate about the glasses' **own up axis** | `view --record --segment u1_yaw_from_pitched` | Under the correct head→world reading, `q_rel` shows (nearly) pure yaw; under the inverse it would mix in pitch and roll. Repeat from a rolled start |
| 8 | Recenter behaviour | Fixture | In the viewer: capture neutral, rotate, capture again | Raw stream has no jump at the recenter; `neutral_calibration_id` increments; rejected attempts carry reasons |
| 9 | Unplug / replug | Fixture | `view --record`, unplug the USB cable for about 5 s, replug | `device_disconnected` then `device_connected` with a new `connection_id`; gate not usable until a new neutral; no samples valid during the outage |
| 10 | Sleep / wake | Fixture | `view --record`, put the PC to sleep for about 30 s | Behaviour documented (reconnect or error); no stale data used |
| 11 | Second process | Fixture | Run `view` twice | The second instance fails cleanly with the single-process hint |
| 12 | Headless vs viewer timing | Fixture | Step 3 headless, then `view --record --duration` of the same length | Arrival-time jitter and loss compared (U7) |
| 13 | Raw mode (optional) | Fixture | `record --mode raw --freq 500 --duration 120 --mounting fixture` | Achieved raw rate; channel statistics (units undocumented) |

After each step, write the outcome into [bench-report.md](bench-report.md) and update the "Status" column of
[conventions.md](conventions.md). Choosing the `tau_stab_deg` value (O6) is a research-team decision, informed by steps 3 and 8.
