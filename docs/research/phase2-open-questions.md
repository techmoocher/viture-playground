# Phase 2: open methodological questions

**For:** the research team. **From:** the engineering side, 2026-11-11.
**Status:** open. This file does **not** change the Experiment & Calibration Protocol v1.0. It lists where the Phase 2 instrument ([phase2-proposal.md](../phase2-proposal.md)) needs a decision the protocol does not make, or where it simplifies the protocol for the MVP. Each item names the engineering default in use meanwhile. Every default is provisional and configurable, and each session records it in `session.json`.

## Simplifications of the protocol in the Phase 2 MVP

| # | Topic | Protocol | Phase 2 MVP (engineering default) | Question |
|---|---|---|---|---|
| Q1 | Target geometry | One target orientation `q_i` per chord, chosen from a candidate set, with a minimum geodesic separation (§6) | Yaw intervals only, measured as the heading of the forward axis relative to the neutral (equal to the documented display yaw). Pitch and tilt are ignored | Are yaw-only regions acceptable for the MVP? When should full-orientation targets (geodesic zones) replace them? |
| Q2 | Layout | Model A: "pre-piloted" fixed layout; B/C: optimised (§5–6) | A bench layout: C +22…+40°, G +8…+18°, Am −18…−8°, F −40…−22° (+ = turn left); neutral ±4°; hysteresis 1.5°. Chosen only for bench separation | Who sets the MVP layout, and from what? |
| Q3 | Dwell | 400–600 ms candidate, piloted and frozen before comparison (§6, §11) | 500 ms | Which value for MVP use? |
| Q4 | Cooldown | Named, with no value (§6) | 300 ms after a commit | Value? |
| Q5 | Re-arming | Return-to-neutral gate (§6) | Entering the neutral zone re-arms, with no hold (`rearm_hold_ms = 0`) | Should a hold time be required? |
| Q6 | Large vertical deviation | Not addressed | A sample counts for selection whenever the forward axis is within 89° of the neutral horizontal plane (a numeric guard only) | Should strongly nose-up or nose-down poses be excluded from selection? |

## Behaviour the protocol does not specify

| # | Topic | Engineering default | Question |
|---|---|---|---|
| Q7 | When a chord ends | It ends at the next commit, on an interruption, on emergency stop and on stop | Is a sustain-until-next-commit model what the study wants? |
| Q8 | Sound during an interruption (≈ 300/600 ms device pauses, disconnects) | The chord is released (silenced) on every interruption | Release or hold through short pauses? Does a release count as a "command" under the rule that invalid or stale tracking never triggers commands? We treat it as always allowed, because it selects nothing |
| Q9 | Accompaniment during an interruption | It continues (it is a time reference); "mute" is available | Continue or mute? |
| Q10 | Re-committing the sounding chord | Allowed after a return to neutral; the chord re-triggers | Re-trigger or ignore? |
| Q11 | Sub-stale gaps (for example ≈ 50 ms after reconnecting) | Any flagged gap resets the gesture | Reset on any gap, or only when tracking becomes unusable? |
| Q12 | Duplicate device timestamps | Stay invalidating (`duplicate_timestamp = "reset"`). **R2D-1 (live bench, 2026-11-11):** 24 in 293 s caused 9 gesture resets, 4 chord releases, 1 rejected neutral capture, and about 20 s without response. A `"skip"` option exists: it ignores only samples whose sole fault is a duplicate timestamp; in a replay of R2D-1 it removed all 9 resets ([phase2d-guide.md](../phase2d-guide.md) §5) | Keep invalidating, use `"skip"`, or reclassify the flag? |
| Q13 | "Raw commit time" for analysis | Logged: arrival time, estimated production time, processing time, MIDI send time | Which one is the protocol's raw commit time? Default field: estimated production time of the committing sample |
| Q14 | Timing precision target (O4) | Software-side latency is reported as *estimated*. Physical audio latency is not measured | What precision is needed, and how should acoustic onset be measured? |

## Found while preparing 2D (2026-11-11)

| # | Topic | Engineering default | Question |
|---|---|---|---|
| Q15 | Passing through inner regions | Four chords on one yaw axis: reaching C or F passes through G or Am. A turn slower than region width ÷ dwell (10° / 0.5 s = 20°/s by default) commits the inner chord ([phase2d-guide.md](../phase2d-guide.md) U1) | Accept, or change the layout (two axes?), the dwell, or add a speed condition? |
| Q16 | Smaller demo layout | Optional `config/profiles/small_yaw.toml` (regions within ±24°, otherwise the same). Not a default, no comfort claim | Should a worn exploratory demo (after O3) use it, or values set by the team? |

## Carried over from Phase 1

- **O1:** the research report is missing; Q1–Q14 should be re-checked against it.
- **O3:** developer self-testing while worn, which blocks worn smoke tests (milestone 2D).
- **O5:** disconnects during a block.
- **O6:** `tau_stab_deg`.
