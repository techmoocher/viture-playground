# Biomechanically Informed 3DoF Music Interface
## Experiment & Calibration Protocol — v1.0 (research draft)

**Date:** 10 November 2026  
**Hardware:** VITURE Pro XR (Gen1 3DoF)  
**Scope:** Four-chord, head-controlled harmony instrument; glasses-only first, optional torso-tracked extension  
**Status:** Proposed protocol, **not** IRB-approved and **not** a validated medical/ergonomic procedure  
**Implementation:** Claude after protocol and software interfaces are agreed

---

## 0. Decision record

We will evaluate **two distinct claims**:

1. **Predictive claim:** Does a personalized model with cross-axis head-orientation interactions predict held-out subjective effort/discomfort ratings better than a personalized model without those interactions?
2. **Interaction claim:** Does using the coupled model to place chord targets reduce perceived effort and/or discomfort, without degrading recognition accuracy or timing?

These claims must not be conflated. Anatomical coupling in the cervical spine does **not** by itself prove that a coupled model is beneficial for a head-controlled interface.

**Primary comparison:** personalized independent-axis (B) versus personalized coupled-axis (C). A fixed mapping (A) contextualizes the value of personalization overall.

**Conservative design choices:**
- Start with a head-locked status HUD, not a world-stabilized floating keyboard.
- Use the *same* four chords, dwell-to-commit state machine, audiovisual feedback, candidate-pose pool, musical sequences, optimizer, and practice policy for B and C. Only their predicted discomfort/effort model differs.
- Use neutral-relative quaternions for computation. Euler yaw/pitch/roll are for display and interpretable low-amplitude model features after axis validation.
- Treat the participant's stated movement envelope as a **preferred interaction workspace**, not an anatomical or clinically safe envelope.
- Do not infer actual neck joint position from glasses orientation. Full cervical-relative orientation needs torso tracking in a common frame.
- Do not collect data from recruited human participants, even for a publication-oriented pilot, until the relevant Bucknell IRB determination/approval and approved consent/safety procedures are in place.

---

## 1. Research questions and hypotheses

| ID | Question | Hypothesis (to test, not assume) |
|---|---|---|
| RQ1 | Are subjective effort/discomfort ratings better predicted by a model with cross-axis terms? | H1: C has lower held-out prediction error than B. |
| RQ2 | Does a coupled-model mapping reduce task effort? | H2: C has lower post-block perceived physical effort than B. |
| RQ3 | Does C preserve practical interaction quality? | H3: C is not meaningfully worse than B in selection errors, false activations, and unquantized commit timing. |
| RQ4 | How much benefit comes merely from personalization? | Exploratory: B vs A. |
| RQ5 | Do benefits persist after practice and across days? | Exploratory follow-up; not essential to first pilot. |

**Primary pilot decision measures:** (i) held-out mean absolute error (MAE) of the personalized effort/discomfort ratings (calibration), and (ii) a specifically anchored 0–10 **physical effort** rating after each chord-control block (interaction). Neck discomfort change is an important safety and secondary outcome. Before a confirmatory study, preregister one primary outcome per claim, a smallest worthwhile difference, and a multiplicity strategy.

The 0–10 effort/discomfort ratings proposed here are **study-specific**, not validated clinical instruments; they must not be described as diagnostic or validated safety measures.

---

## 2. Measurement model: what we know versus what we cannot measure

### 2.1 Device outputs

The official VITURE Glasses SDK lists **Viture Pro** as a **Gen1, 3DoF, camera-free** device. Its IMU pose callback outputs `[roll, pitch, yaw, qw, qx, qy, qz]` in **North-West-Up (NWU)** coordinates and a device timestamp. Raw and processed-pose modes are separate. The device's supported report frequencies must be queried rather than assumed. The SDK explicitly warns that unsupported frequencies can vary by product/mode. Source: [VITURE XR Glasses SDK](https://www.viture.com/developer/glasses-sdk/glasses).

**Implementation verification requirements:** inspect actual units, axis signs, quaternion handedness/order, host timestamp relation, discontinuities, and recenter behavior with a physical motion checklist. Do not assume library defaults. Store both device timestamp and host monotonic receipt time; SDK documentation identifies the former as device timebase but does not guarantee the units or synchronization to the host clock in this protocol.

For the first prototype, use `VITURE_IMU_MODE_POSE`; raw mode is a later validation option, not a requirement for the instrument.

### 2.2 Geometric distinction

Let `q_WH(t)` be head orientation in a tracking/world reference frame, and `q_WT(t)` torso orientation in the **same reference frame**. Then:

`q_TH(t) = inverse(q_WT(t)) ⊗ q_WH(t)`

Only `q_WH(t)` is directly available on a glasses-only VITURE setup. Calibrating a neutral pose `q0` allows a *reference-relative head orientation*:

`q_rel(t) = inverse(q0) ⊗ q_WH(t)`

This is not equivalent to a cervical joint angle. Users may rotate their torso. For stronger anatomical interpretation, add a synchronized torso sensor, carefully align frames, and validate against a reference.

**Quaternions:** normalize each input; account for `q` and `−q` representing the same orientation; test multiplication order; calculate angular separation using an appropriate quaternion/geodesic metric. Convert to Euler angles only under a documented convention, with angle wrapping and singularity tests.

### 2.3 Bench characterization before human testing

1. Verify the exact glasses model/firmware/SDK version, platform and USB path.
2. Record ≥60 seconds of stationary pose at a comfortable neutral orientation; estimate jitter and low-frequency drift without treating it as anatomical movement.
3. Make distinct, slow right/left, up/down and tilt gestures. Verify signs and axes; repeat at multiple combined orientations to detect convention errors.
4. Recenter and repeat; check whether reset events cause pose jumps or invalid gesture events.
5. Quantify inter-sample times, missing intervals, callback latency **to host arrival** and relative stability over a 10-minute session. Absolute end-to-end audio latency requires a separate measurement method.
6. Test unplug/replug, sleep/wake and SDK errors. No gesture may be committed from stale or invalid sensor data.
7. Capture replayable logs and deterministic synthetic traces (quaternion sign flip, yaw-wrap, dropped samples, neutral recenter, stable dwell, incidental movement).

Report observed device metrics, not SDK frequency constants as if they were achieved throughput.

---

## 3. Human-subject ethics and safety gate

**Institutional requirement:** Bucknell's IRB states that proposed research involving human subjects (including relevant pilot work) must be reviewed/approved as appropriate **before data collection**. Obtain a determination and confirm training, consent, recruitment, retention and reporting procedures with the university. Sources: [Bucknell IRB](https://www.bucknell.edu/azdirectory/office-institutional-research-analytics/institutional-review-board) and [IRB guidance](https://myweb.bucknell.edu/academic-areas/provost/academic-resources/institutional-review-board).

**Pilot eligibility (proposal for IRB review):** adults aged 18+ who can voluntarily perform comfortable small head movements. Do not screen or exclude solely using self-diagnosis; have IRB-approved criteria and instructions for participants with current neck pain/injury, dizziness/vestibular symptoms, recent neck surgery or similar concerns. Do not pressure anyone to disclose medical histories beyond approved screening.

**Participant-controlled stops:** stop immediately for pain, dizziness, nausea, visual distress, or any request to stop. In addition, propose a **conservative procedural stop/pause** if a participant reports discomfort ≥3/10 or an abrupt increase from their baseline; the exact threshold is a *study safeguard to be reviewed*, not a validated medical cut-off. No maximal range-of-motion elicitation, stretching, forced postures, or long static eccentric holds. Include rest and neutral recovery; allow any trial to be skipped without penalty.

**Data stewardship:** pseudonymous participant IDs; consent stored separately from pose/task data; no microphone/camera recording by default; local encryption and access controls; data retention period and sharing governed by approved protocol. A participant should be able to withdraw without explanation, subject to disclosed data-use limitations.

---

## 4. Calibration: measurement objectives and user flow

### 4.1 Exactly what to rate

Capture three distinct self-reports:

- **Movement effort** (0 = no effort, 10 = extremely demanding): how demanding was the movement to that position?
- **Posture discomfort** (0 = no discomfort, 10 = strongest discomfort the person chooses to report): how uncomfortable did the final posture feel during a **brief** hold?
- **Transition preference** (optional second-stage pairwise comparison): which of two paths between chord positions felt easier to repeat?

Keep these distinct. Primary modeling can use *effort* and discomfort can be a guardrail, or vice versa, but the choice must be preregistered before confirmatory testing. The 0–10 scales are custom task ratings, not clinical scales. Also record baseline neck discomfort before each block and after breaks.

### 4.2 Proposed user experience (15–20-minute research calibration; timing to pilot)

1. **Preparation (2 min):** sit comfortably, feet supported, natural upright torso; adjust glasses fit. Explain that the target is *easy, natural movement*, never the largest possible movement. Explain skip and stop controls.
2. **Neutral reference (30–60 sec):** participant rests naturally and initiates recenter; record several seconds of stable orientation. Recenter only between tasks, never during a scored block.
3. **Individual low-amplitude exploration (2–3 min):** visually guide gentle left/right yaw, up/down pitch and roll. Collect participant-accepted comfortable endpoints (which may be asymmetric). No externally imposed angular threshold is described as safe.
4. **Structured sampling (6–10 min):** show a *small* set of sampled combined poses relative to the neutral frame, selected only from the voluntary preferred region; record approach and brief hold (~1–2 seconds), then return to neutral and rate movement effort and posture discomfort. Allow 5–10 seconds of neutral rest or more as requested.
5. **Quality and repeatability (2–3 min):** present a limited subset again in shuffled order, without telling the user they're repeats. Check pose acquisition and rating consistency.
6. **Closure:** baseline recovery check, overall comfort question, any comments, and opt-out/data handling.

**Initial design candidate, not a mandatory quota:** 24–36 usable pose observations, adjustable downward if tiring. A useful candidate set is 1 neutral + 6 single-axis + up to 12 two-axis + up to 8 three-axis **low-amplitude** combinations, plus a handful of repeated anchors. These are *directions/templates*, not forced positions. Scale/skip mixed poses that are not easy for a specific participant. Do not treat absent samples as 'safe' or 'comfortable'.

A fully general three-variable quadratic has 10 coefficients; a handful of observations is insufficient. Evaluate effective sample coverage, repeatability, condition number and held-out predictive error before trusting a personalized coupled fit. If data are sparse or unstable, automatically fall back to simpler models.

### 4.3 Sampling and leakage prevention

- Build a reproducible list of candidate directions using the person's **accepted** low-amplitude ranges. Favor coverage of axis interactions without forcing corners of the independently defined rectangular range.
- Assign samples to **training** and **held-out evaluation** before fitting; ensure held-out poses include mixed-axis combinations.
- Keep all repeated ratings for a given target/pose family together in training or testing when evaluating spatial generalization; otherwise results may be inflated by near-duplicates.
- Consider a second set of ratings after a time gap to estimate stability. Report test error alongside neutral-repeat or same-pose rating variability.
- Log skipped/rejected positions with a reason (`user_skip`, `comfort_stop`, `tracking_failure`) and *do not code skips as zero discomfort*. They are informative missingness and may motivate restricting the candidate region.
- Include a visual 'unknown confidence' mask so the application does not optimize into unsampled space merely because a regression extrapolates a low cost.

---

## 5. Proposed models, held constant except where the hypothesis requires variation

Use a low-amplitude neutral-relative feature vector `x = [y, p, r]ᵀ`, where yaw/pitch/roll extraction is explicitly documented. Scale features by a within-subject characteristic angular scale for numerical conditioning; keep original units for logs.

### Model B: additive independent-axis quadratic

`E_B(x) = β0 + Σ_i (β_i x_i + γ_i x_i²)`

7 coefficients: intercept + 3 linear + 3 squared terms. It can represent individual asymmetry and nonlinear cost by axis but **no cross-axis interactions**.

### Model C: additive terms plus pairwise coupling

`E_C(x) = E_B(x) + δ_yp·y·p + δ_yr·y·r + δ_pr·p·r`

10 coefficients in total. It can capture second-order cross-axis interactions but **not** arbitrary complex surfaces, vertebral biomechanics, or fatigue dynamics. Add ridge regularization; choose regularization from training folds only and report uncertainty and held-out performance. Clip model outputs to an interpretable rating range only after fitting; do not allow extrapolated low predictions to authorize unseen extreme poses.

### Model A: fixed mapping

A pre-piloted, low-amplitude gesture layout and identical dwell trigger for everyone. Keep it as a contextual benchmark rather than a presumed fair default for all participants. Participants can always skip or stop a target.

### Model selection logic

1. Fit B and C to **the same samples** with the same preprocessing and training/validation split.
2. Evaluate per-person held-out MAE and calibration error; summarize `MAE_B − MAE_C`, uncertainty, and stability across sessions. Also compare against a trivial neutral/mean-rating model.
3. If C is poorly conditioned, predicts unstable/unphysical minima, or fails to outperform B on held-out data, use B as the deployed model (and preserve C as an experimental candidate if ethically appropriate).
4. A favorable held-out score is necessary, **not sufficient**, evidence that a coupled map helps actual musical control.

Do **not** make Gaussian processes, deep learning, fatigue prediction or a full SO(3) learning model mandatory for MVP. Those are follow-up alternatives if simple models fail and data justify complexity.

---

## 6. Chord layout and gesture mapping: identical functionality across conditions

**Musical task:** C major, G major, A minor, F major; instrument transmits deterministic MIDI chord-on/chord-off events and optionally a software synthesizer renders audio. Default to an automated accompaniment at a fixed tempo; record **unquantized command time** before optional beat quantization.

**Input convention for the study:** orient an abstract HUD cursor using *neutral-relative* head rotation. A head-locked display shows target names, cursor position, selection progress and a neutral indicator. The whole UI follows the glasses; the cursor moves within it. This is **not** spatial anchoring or gaze tracking.

**One shared state machine:** `neutral → aiming → dwell-armed → committed → return-to-neutral → neutral`, with the same dwell time, hysteresis, cooldown, and audio behavior in A/B/C. Initial engineering candidate: dwell approximately 400–600 ms, calibrated through a *separate* pilot and fixed before the controlled comparison. No repeated nodding is required to play beats. A return-to-neutral gate helps prevent multiple unintentional commits from one prolonged pose.

**Mapping optimizer (shared for B and C):** choose one candidate head orientation `q_i` per chord from a conservative, *measured or locally interpolated* candidate set `Ω`, and minimize

`J({q_i}) = λ1 Σ_i f_i E(q_i) + λ2 Σ_i,j P_ij T(q_i,q_j) + λ3 · classification-risk({q_i})`

subject to:
- A common minimum geodesic angular separation between targets (recognition margin).
- Identical dwell and recognition boundaries for all conditions.
- All targets inside the participant-accepted exploration envelope, with an uncertainty limit; reject skipped/untested regions.
- Identical optimizer, chord-transition probabilities `P_ij`, search seed, allowable target candidates and weights `λ` for B and C.
- Stable targets for the entire task block; do not rearrange chords mid-song.

Here `E` is the **effort cost** predicted by B or C, `T` is a shared observed/geometric transition estimate, and the classification term penalizes overlap/missed targets. `f_i` and `P_ij` are derived from *task design* or a preregistered chord sequence, not optimized post hoc from user outcomes. An initial simpler target-selection algorithm may be preferable to a global optimizer, but it must be the same in B and C.

**Important fairness issue:** If C additionally receives optimized transition costs or larger candidate space, an improvement would not isolate *cross-axis modeling*. A's role is secondary, and A may be less personally comfortable even with conservative small-angle settings.

**Alternative interaction modes** (nod trigger, roll modulation, beat-synchronous chords, continuous pitch-bend) are future extensions, not simultaneous factors in this study.

---

## 7. Participant task and session schedule

**Provisional session:** approximately 45–60 minutes including consent, setup, breaks and rating forms; refine with pilot and IRB feedback. Research calibration may occur in a separate session if 1-day study is too tiring.

| Step | Proposed duration | Output |
|---|---:|---|
| Consent, eligibility, explanation | 5–8 min | Authorized participation and baseline survey |
| Instrument orientation and neutral reference | 3–5 min | Neutral pose and device check |
| Gentle calibration | 12–18 min | Pose + ratings, skips, held-out split |
| Practice A/B/C (per condition) | ~2 min each | Trial familiarity and practice performance |
| Scored block per condition | ~4–5 min each | Event-level performance; fatigue ratings |
| Rest/recovery | ≥2 min between conditions, more on request | Return toward baseline discomfort |
| Post-condition ratings and debrief | ~5 min total, or longer as needed | Physical effort, discomfort, workload, preference |

Each scored block uses the **same** structure and equivalent musical difficulty:

1. **Prompted selection:** ~24 prompted chord selections in a transition-balanced order. Start timer at cue presentation; end at the *raw* command commit, not quantized note onset. Record errors, missed commands and timeouts.
2. **Rhythmic progression:** ~90 seconds at a fixed pilot-chosen tempo (e.g., 80 BPM as a *candidate*). Record raw commitment timing relative to intended beats; let the accompaniment play without forcing a gesture every beat.
3. **No-command interval:** ~45–60 seconds of normal head movement while reading/watching a neutral dashboard prompt. Record unintended chord activations per minute. This explicitly tests the Midas-touch problem.

**Order and learning:** Use all six orders (`ABC`, `ACB`, `BAC`, `BCA`, `CAB`, `CBA`) as evenly as feasible; counterbalance chord sequences across conditions and keep practice exposure comparable. Preserve order as a covariate. Include a consistent practice-criterion policy; log any participants who cannot attain the criterion. A cross-day retention pilot can check learning/muscle-memory effects if resources permit.

---

## 8. Outcomes and operational definitions

### Calibration outcomes

| Metric | Definition |
|---|---|
| Held-out effort MAE | Mean absolute difference between model effort prediction and user rating on held-out pose families; report participant-level paired `B − C`. |
| Held-out discomfort MAE | Same for discomfort if modeled separately; do not substitute effort for discomfort without saying so. |
| Repeatability | Absolute rating difference on same/near-same pose repeated after a gap. |
| Coverage | Proportion of candidate region supported by accepted observations within a predeclared neighborhood; report uncertainty. |
| Calibration burden | Time, completed prompts, skips, reports of tiredness, and preference. |

### Interaction outcomes

| Metric | Definition |
|---|---|
| **Primary pilot outcome: task physical effort** | Participant's immediate 0–10 rating after each condition (custom measure); report order and baseline ratings. |
| Neck discomfort change | Post-block 0–10 localized neck discomfort minus pre-block value; report recovery and any stop events. |
| Valid selection accuracy | Correct first chord commit / number of prompted chord trials. Also report confusion matrix, misses, and timeouts. |
| False activations | Unprompted commits **per minute** in the no-command interval; also precision/recall at event level. |
| Selection time | Cue→raw commit, with distribution/median and timeout policy; exclude no trial silently. |
| Rhythmic error | Raw commit time minus closest intended target beat, in milliseconds. Quantized audio timing is a separate measure. |
| Movement burden | Sum of geodesic quaternion increments (cautiously interpreted), angular peak and median speed, neutral-rest fraction, and time in eccentric measured head poses. |
| Workload | NASA TLX or raw (unweighted) six-item TLX; specify which scoring variant is used, obtain correct instrument, and do not call workload a direct neck safety measure. |
| User preference | Rank conditions, perceived learnability and comments. |

NASA TLX's six workload dimensions are mental, physical, temporal, perceived performance, effort and frustration: [NASA official TLX](https://www.nasa.gov/human-systems-integration-division/nasa-task-load-index-tlx/). The [Cornell Musculoskeletal Discomfort Questionnaire](https://ergo.human.cornell.edu/ahmsquest.html) is aimed at musculoskeletal discomfort patterns over longer timeframes; it is not a drop-in moment-to-moment head-pose comfort rating.

**Decision rule for pilot:** Look for a consistent and practically meaningful reduction in physical effort without a substantial penalty in unquantized timing, false activations, or correctness. Use paired plots and confidence/uncertainty ranges; avoid a binary publication claim from a small pilot. For a later confirmatory design, define the smallest effect worth detecting and any noninferiority margins *before* calculating sample size.

---

## 9. Analysis plan

### 9.1 Calibration

- Fit separate models per participant; both B and C receive the **same** training records.
- Use grouped repeated-target/pattern splits or carefully blocked validation to prevent near-duplicate leakage. Validate that mixed-axis test points are actually represented.
- Report each user's `MAE_B`, `MAE_C`, `ΔMAE = MAE_B − MAE_C`, and rating repeatability; do not pool thousands of pose records as independent participants.
- Inspect errors versus yaw/pitch/roll and proximity to training coverage; visualize confidence/uncertainty.
- Compare with a simple constant-cost baseline and inspect unstable parameter fits. Treat regularization as a model hyperparameter, not a free extra treatment.

### 9.2 Interaction

- The unit of inference is the **participant**, not the individual pose sample or chord. First examine within-participant B↔C differences in effort, discomfort, timing, accuracy and false activations.
- Summarize paired differences with plots and intervals. For a larger confirmatory study, consider a repeated-measures or mixed-effects model accounting for condition, task block/order, and participant, with suitable distributions for counts/proportions and explicitly specified multiplicity control.
- Missing/aborted sessions and skipped poses are reported, not silently dropped. Do not assume missingness is random.
- Report model-calibration costs as part of total usability burden, even if C performs better during a scored block.
- Do not claim a 'safe' interface from lower workload ratings or absence of short-term discomfort.

**Sample-size plan:** An IRB-approved pilot of roughly 6–10 participants may establish feasibility, protocol burden and variance, but not a definitive efficacy claim. Use pilot variance and a prespecified minimally meaningful effect to compute a confirmatory sample-size/power or precision target. The earlier idea of 24–36 or 30–36 participants is a planning illustration, **not** a validated power calculation. If feasible, distribute each of the six counterbalancing orders evenly.

---

## 10. Event model and implementation-agnostic data contract

All rows must include `schema_version`, `participant_id` (pseudonymous), `session_id`, `trial_id`, `condition` (`A|B|C|calibration|bench`), software build identifier, SDK version, and clock metadata. Keep high-rate IMU logs separate from lower-rate event and rating logs.

### 10.1 `pose_samples`

| Field | Type / note |
|---|---|
| `device_ts_raw` | Original SDK timestamp; raw units annotated in session metadata, not assumed. |
| `host_rx_monotonic_ns` | Host monotonic sample receipt timestamp. |
| `quat_wxyz` | Normalized full head orientation with documented source frame and convention. |
| `quat_neutral_relative_wxyz` | Neutral-relative orientation after checked conversion. |
| `euler_display_deg` | `[yaw,pitch,roll]` for diagnostics only. |
| `sample_quality` | `valid|gap|discontinuity|recenter|stale|nonfinite`. |
| `neutral_calibration_id` | Stable identifier and recenter version. |

### 10.2 `calibration_trials`

`target_id`, `target_quat_wxyz`, `actual_mean_quat_wxyz`, `reach_start_ts`, `hold_start_ts`, `hold_end_ts`, `return_neutral_ts`, `effort_0to10`, `discomfort_0to10`, `skipped`, `skip_reason`, `train_or_holdout`, `sample_family_id`, `notes`.

### 10.3 `interaction_events`

`event_type` (`cue|aim_enter|dwell_start|dwell_complete|raw_commit|midi_note_on|midi_note_off|audio_onset_estimate|return_neutral|false_trigger|timeout|error|rest|stop`), `event_host_monotonic_ns`, `chord_expected`, `chord_observed`, `selected_target_id`, `recognizer_state`, `model_id`, `mapping_version`, `optimizer_seed`, `quantization_enabled`.

### 10.4 `ratings` and `sessions`

`rating_type`, `rating_value`, `anchor_text`, `time_relative_to_block`, `condition`, `participant_comment`; in session metadata: firmware, platform, sensor reporting mode and supported/selected frequency, user fit notes, consent version, task sequence/order, software hash, room/posture description, excluded periods and reasons.

**Timing rule:** Preserve raw host `cue`, `gesture-commit`, audio scheduling and observed sound onset (if instrumented) separately. Do **not** infer true acoustic onset from a MIDI command timestamp. Inverse clock mapping requires its own calibration.

---

## 11. Failure handling and acceptance gates for Claude

| Gate | Requirement before progressing |
|---|---|
| G0 — SDK feasibility | Device identified as Pro Gen1; live pose and timestamp logged; coordinate frame, recenter and axis signs checked. |
| G1 — Replayability | Recorded and synthetic traces reproduce identical feature extraction and gesture decisions; invalid/stale data inhibit triggering. |
| G2 — Usable baseline | Four chords play with common dwell/return-to-neutral recognition; correct chords and MIDI event timing are logged. |
| G3 — Ethical calibration UI | Neutral/rest/skip/stop are prominent; no forced maximal movements; no research participants until IRB gate. |
| G4 — Model integrity | B has no interaction terms; C only adds declared interaction terms; same training samples and preprocessor; validation split frozen. |
| G5 — Fair condition comparison | A/B/C use identical output, recognizer, HUD, sequence, timing and practice policy. B and C use same optimizer and candidate pool. |
| G6 — Data completeness | One row per cued trial including errors/timeouts; raw and quantized timestamps separately recorded; exports are pseudonymous and versioned. |
| G7 — Pilot readiness | Trial dry-run, tested disconnect/abort behavior, approved protocol, consent and collection procedure. |

**Technical tests:** zero/nonfinite quaternion, quaternion sign inversion, 360° wrap, low-rate and bursty samples, drift, sudden recenter, no-device startup, mid-trial disconnect, duplicate callbacks, long dwell, unintended head motion, aborted trials, synthetic chord replay and MIDI note-off on termination.

**Proposed, unvalidated parameters:** 400–600 ms dwell; 1–2-second calibration holds; 24–36 calibration observations; 5–10-second or longer neutral rests; ~80 BPM musical demo; 4–5-minute scored blocks. Pilot these and freeze them **before** a comparative study. Do not claim medically safe ranges, a hardware latency guarantee, or a validated minimum angle from these values.

---

## 12. Highest-priority unresolved decisions

1. **Target variable:** Is primary modeling based on brief *movement effort*, *hold discomfort*, or separately fitted functions? Recommendation: separate functions; treat effort as initial optimizer objective and discomfort as a hard user-reported guardrail. Verify with pilot.
2. **Dwell recognition:** Does it give adequate command timing and acceptable false-activation rate, or do we need a small intentional confirmation gesture? Do not change only one condition.
3. **Model sample adequacy:** Do 24–36 gentle trials produce identifiable and repeatable cross-axis effects? If not, simplify or redesign calibration before adding complexity.
4. **Glasses-only limitation:** How much torso compensation occurs during the chosen movements? A torso IMU would strengthen anatomical claims but complicate the prototype. Keep the first publication claim about *head-pose interaction* unless torso data are measured.
5. **Research burden:** Does the time needed to calibrate C outweigh its usability gains? Record total calibration time and setup errors as key costs.
6. **Generalization:** Does any advantage survive repeat sessions and re-calibration? Defer until MVP is stable.
7. **Scientific framing:** Show that interaction terms predict *subjective ratings* and improve *task experience*; do not use the label 'biomechanically optimal' without direct biomechanical validation.

---

## 13. Immediate non-participant tasks and next phase

**Now, before IRB participant data collection:**
- Prototype/log the exact hardware stream and document conventions with an engineering test rig.
- Draft the study protocol and questionnaires for faculty/IRB feedback.
- Generate synthetic/calibration replay traces, event schema and model fitting tests.
- Define the trial UI and common interaction state machine.
- Establish a version-controlled research repository, preregistration draft and source bibliography.

**After approval, in sequence:**
- Conduct pilot to test burden, task validity and sensor stability.
- Revise and freeze parameters based on pilot findings.
- Perform main calibration and within-subject comparison.
- Analyze both predictive and interaction claims with transparent uncertainty.

The next handoff should be a **Software Requirements Specification (SRS)** derived from this protocol, not a request for Claude to invent experiment details.

---

## 14. Selected verified sources and relevance

1. **VITURE XR Glasses SDK** (official). Pro Gen1 3DoF, pose callbacks, NWU coordinate system, quaternion layout, frequency capability query. https://www.viture.com/developer/glasses-sdk/glasses
2. **Bucknell Institutional Review Board** (official). Human-subject research and pilot-review obligations; contact and submission. https://www.bucknell.edu/azdirectory/office-institutional-research-analytics/institutional-review-board
3. **Bucknell IRB Guidance** (official). Human-subject research determination, classroom/publishable distinction, approval before research data collection. https://myweb.bucknell.edu/academic-areas/provost/academic-resources/institutional-review-board/guidance-faqs
4. **NASA Task Load Index** (official). Six workload dimensions; use only to characterize perceived task workload, not cervical comfort. https://www.nasa.gov/human-systems-integration-division/nasa-task-load-index-tlx/
5. **Cornell Musculoskeletal Discomfort Questionnaires** (Cornell Ergonomics). Longer-term musculoskeletal symptom screening; not appropriate as an instantaneous pose-rating scale. https://ergo.human.cornell.edu/ahmsquest.html
6. **Li, G., Weidner, F., Hu, J., & Gellersen, H. (2025).** Quantifying neck muscle activity during head fixation in VR. *Frontiers in Virtual Reality*, 6, 1682866. 15 participants, 67 head-pose targets; EMG and torso behavior, **not** direct subjective comfort or injury risk. https://doi.org/10.3389/frvir.2025.1682866
7. **Yan, Y., Yu, C., Yi, X., & Shi, Y. (2018).** HeadGesture: Hands-Free Input Approach Leveraging Head Movements for HMD Devices. *Proceedings of the ACM on Interactive, Mobile, Wearable and Ubiquitous Technologies*, 2(4), Article 198. Addresses intentional versus incidental head gestures. https://doi.org/10.1145/3287076
8. **Kinematics of the Cervical Spine Under Healthy and Degenerative Conditions: A Systematic Review** (2022/2023). Caution that vertebral-scale coupling does not by itself establish whole-head comfort. https://pmc.ncbi.nlm.nih.gov/articles/PMC9794546/
9. **The effect of initial head position on active cervical axial rotation range of motion in two age populations** (1996). 60 subjects; changing start posture changed rotation range, measured using forehead/sternum sensors. https://pubmed.ncbi.nlm.nih.gov/8923628/
10. **Coupled motions of the spine under standardized in vitro conditions: a systematic review and meta-analysis** (2025). Coupling between lateral bending and axial rotation; in vitro evidence and different levels must be interpreted carefully. https://pmc.ncbi.nlm.nih.gov/articles/PMC12647002/

---

**Protocol status:** Research design draft requiring faculty review, pilot-driven parameter refinement and Bucknell IRB determination/approval before involving research participants. This document is meant to guide the next technical specification, not certify neck safety or study approval.
