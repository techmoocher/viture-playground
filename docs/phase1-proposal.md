# Phase 1 — Hardware Foundation: Engineering Proposal

**Revision:** 2 (2026-11-10). This revision incorporates your review decisions (§0). Revision 1 is in this file's history once git is initialised.
**Status:** **implemented** (Python + native C capture shim, chosen 2026-11-10). **G0 fixture characterisation was done on 2026-11-11, except steps 12–13, which were not run** (summary in [bench-report.md](bench-report.md)). Worn characterisation waits for O3. The current definitions live in [conventions.md](conventions.md), [quality-and-metrics.md](quality-and-metrics.md) and [data-format.md](data-format.md); where they differ from this proposal, those documents are authoritative.

Refinements made during implementation, each found by a test on real or synthetic data:
- **Gap and timestamp checks** compare to the last sample whose timestamp was in order (`d_ref`), not the last *valid* sample. Otherwise invalid values created false gaps.
- **`angular_jump`** needs the sample to be far from both the last valid and the previous finite sample. Otherwise a one-sample glitch flagged two samples.
- **`hemisphere_flip`** marks SDK sign changes once. The SDK keeps `w ≥ 0`; the earlier definition flagged every sample after the first change.
- **Duplicate-timestamp reports** from the device are real (see sdk-notes.md). They are flagged `ts_duplicate` and kept.
- **Defaults** live in `src/headmusic/defaults.toml` (packaged), not `config/defaults.toml`.
- **Gate staleness** is measured by data age, from the estimated production time, not by arrival time. G0 R9 found a sample arriving 29.9 s late after a PC sleep.
- **G0 tooling:**
  - the segment net-rotation report, which provides the U1 test;
  - `check-placement`;
  - guided bench scripts (`view --script`);
  - the longest gap-free stretch, giving `r_ref` measured per frequency.
**Scope:** Phase 1 only (hardware data pipeline). No musical interface, gestures, dwell, MIDI, HUD, calibration ratings, comfort or coupled models, ML, or experiments.

| Input | Status |
|---|---|
| `Head_Controlled_Music_Experiment_and_Calibration_Protocol_v1.md` (protocol v1.0) | Read in full; moves to `docs/research/` in Step 0 |
| Research report (biomechanics, gestures, ergonomics, interaction design) | **Still not in the folder.** Not reviewed (open item O1) |
| VITURE XR Glasses SDK v2.4.2 (`sdk/`) and the online SDK page | Read: headers, bundled docs, release notes 2.1.0–2.4.2, Windows demo source, Web SDK API |
| Connected glasses (`VID_35CA&PID_101D`) | Read-only probe, §1.2 |

This document is intended as the Phase 1 section of the Software Requirements Specification that protocol §13 asks for.

---

## 0. Decision log (your review, 2026-11-10)

| # | Decision | Where it lands in this plan |
|---|---|---|
| D1 Metadata | Normalised session metadata alongside high-rate pose, event and calibration logs. A reproducible denormalised export meets the protocol's per-row requirement. Identifiers, calibration references, software versions, clock conventions and provenance are preserved | §6.1, §6.3 |
| D2 Sample quality | Multiple flags per sample. Recenter and disconnect go in a separate event log. Sample validity is distinct from consumer-side staleness. Invalid or stale tracking must never trigger musical commands | §5.3, §5.4 |
| D3 Raw data | `VITURE_IMU_MODE_POSE` is primary. SDK quaternion, Euler and timestamps are preserved unmodified; derived neutral-relative data is stored separately. `VITURE_IMU_MODE_RAW` is an optional, separate characterisation mode. The two modes are never assumed concurrent | §4, §6.1 |
| D4 Euler | Original and neutral-relative quaternions preserved in full; exact conventions documented; Euler interaction coefficients are never interpreted as anatomical coupling. Parameterisation dependence is recorded as a threat to validity | §5.1, §5.2, §7.1 |
| D5 Jitter and drift | Stationary fixture for intrinsic characterisation. Worn measurements kept separate. Angular jitter, apparent drift and sampling-interval jitter defined independently | §5.5 |
| D6 Defaults | 3 s neutral capture as an initial engineering value, **with a stability check and retries**. 240 Hz only if supported in the selected mode; requested, selected and observed rates recorded. All thresholds configurable, documented, labelled **provisional**, with precise definitions, and never presented as validated hardware or ergonomic limits | §5.3–§5.6 |
| D7 Repository | Initialise git, create `docs/research/` holding the protocol. Data, PII and local secrets stay out of version control. Private remote optional | §8, §10 Step 0 |
| Also | Deterministic replay; tests for sign changes, timestamp faults, recentering, disconnects and invalid data; modular acquisition, processing, visualisation and recording; minimal dependencies; keep head-in-tracking-frame distinct from neck-relative-to-torso | §4, §5.1, §11 |

---

## 1. Verified facts

### 1.1 SDK (headers and docs)

- **Lifecycle:** `create(pid) → initialize → start → register callback → open_imu(mode, freq) → close_imu → stop → shutdown → destroy`. The Windows DLL is `glasses.dll` and exports 69 C functions.
- **Pose callback:** signature `void(float* data, uint64_t ts)`. Data is `[roll, pitch, yaw, qw, qx, qy, qz]` in North-West-Up (X North/forward, Y West/left, Z Up). Euler angles are in degrees (2.4.0 notes).
- **Raw callback:** signature `void(float*, uint64_t ts, uint64_t vsync)`. Data is `[gyro xyz, accel xyz, mag xyz (zero on Pro), temperature]`.
- **Modes:** RAW and POSE are mutually exclusive. Frequency support is queried per mode.
- **No SDK recenter on Gen1.** Windows allows one process per device.
- **Not documented:** Euler order; quaternion direction; device timestamp units, epoch and sample instant; raw-mode units; filter behaviour across `open_imu`, sleep or replug.

### 1.2 Read-only hardware probe (this PC, 2026-11-10; glasses stationary, not worn)

| Item | Result | Confidence |
|---|---|---|
| Identity | SDK 2.4.2; PID `0x101D`; "Pro"; device type `GEN1`; firmware `07.0.03.013_20250422`; no native DOF | Verified |
| Pose support | 60/90/120/240 Hz yes; 500/1000 Hz no | Verified (SDK table) |
| Raw support | 60–500 Hz yes; 1000 Hz no | Verified (SDK table) |
| Achieved pose rate at 240 Hz requested | **202.5 Hz**; device intervals 4 ms ×82, 5 ms ×912, 6 ms ×19 | Verified, 5 s |
| Achieved raw rate at 500 Hz requested | ≈342 Hz; intervals 2–4 ms | Verified, 2 s |
| Device timestamp | `uint64`, about 10⁹ units per host second (so ns), every value a multiple of 10⁶ (so 1 ms resolution) | Units inferred |
| Host arrival (Python callback, headless) | Median Δt 4.999 ms, SD 0.315 ms, max 6.05 ms; host−device offset range 1.13 ms over 5 s | Verified, 5 s |
| Mode transition | 5 raw-mode callbacks after `start()`, before pose mode opened | Verified |
| Euler vs quaternion; quaternion direction | Not identifiable from one static pose | Needs G0 bench test |

---

## 2. Open items (need your input; nothing proceeds on assumption)

| # | Item | Status |
|---|---|---|
| O1 | Research report missing from the folder | Still missing on 2026-11-11. Please add it; I'll re-check this plan and the Phase 2 proposal against it |
| O2 | Toolchain. The hardware test (§3.5) shows a pure-Python callback loses data under load | **Decided (2026-11-10): Python + native C capture shim**, built with MinGW in WSL |
| O3 | Worn recordings by developers: confirm with faculty or the IRB that engineering self-testing is outside the human-subjects gate | Not answered. Fixture-only work does not depend on it |
| O4 | **Methodology flag:** the protocol states no host-timing precision requirement. Whether a timing path is "adequate" for later raw-commit and rhythmic-error measures (protocol §8) is a research requirement | Phase 1 reports measured timing noise; the research team sets the target before Phase 2 |
| O5 | **Methodology flag:** after a disconnect, Phase 1 invalidates the neutral reference and requires a new capture, because the filter heading may change across reconnects (unverified, U5). G0 found that the device clock restarts and the glasses power-cycle on replug, and that moving the cable can disconnect them (R7, R8). How a later *scored block* handles a mid-block disconnect (abort, pause, or re-capture) is an experiment-procedure decision | Phase 1 only enforces "no usable tracking until a new neutral is accepted" |
| O6 | Value for the neutral stability threshold `τ_stab` (§5.6). The 2.0° default is a placeholder, not a statement about human stillness | Fixture data now exists: accepted untouched captures had a maximum dispersion of 0.003–0.010°, and captures right after handling 0.1–0.6°. Worn data waits for O3. The value is the research team's choice |

---

## 3. Technology stack and the WSL question

### 3.1 Baseline (approved direction)

**Python ≥ 3.11 calling the official C SDK (`glasses.dll` 2.4.2) through `ctypes`, on Windows x86_64.** The probe ran the full lifecycle this way.

Dependencies:
- Build-time (if Option 2, recommended): MinGW-w64 GCC in WSL for the ~60-line C capture shim. Already installed
- Runtime: `numpy`
- Viewer: `tkinter` (stdlib)
- Config: `tomllib` (stdlib)
- Development: `pytest`
- Optional: `matplotlib` for report plots

Rejected:
- Web SDK: it delivers only the latest pose per animation frame and carries no timestamp.
- C++/MSVC on Windows: needs a multi-GB, admin-level Build Tools install.

### 3.2 WSL findings on this PC

| Item | Found |
|---|---|
| WSL2, Ubuntu 26.04.1 LTS | Installed |
| `g++` 15.2.0, `make` | Installed |
| CMake 4.2.3 | Installed by you, 2026-11-10 |
| MinGW-w64 GCC 13 (`win32` and `posix` thread variants) | Installed by you, 2026-11-10. Default C runtime is `msvcrt.dll` |
| USB devices inside WSL | None visible: no `/dev/hidraw*`, and usbipd-win not installed |
| `sudo` inside WSL | Requires your password, so I cannot install packages there |

### 3.3 Two ways to use the WSL compiler

**A. Build Linux programs in WSL against the Linux SDK (`libglasses.so`). Not recommended.**
- WSL2 is a VM with no direct USB access. The glasses would have to be forwarded with **usbipd-win**: an admin install, then `bind` once and `attach` every session.
- Attaching moves the whole composite device (both HID interfaces and the serial port) from Windows into the VM.
- Every IMU packet would then travel through usbipd and the Hyper-V virtual network before reaching the SDK. That adds the virtualisation layer's latency and jitter to the very host-arrival timing Phase 1 is meant to characterise (protocol §2.3 item 5). We would be measuring the VM, not the target platform.
- Later phases need MIDI and audio output on Windows. WSL has no direct access to Windows MIDI devices, and its audio goes through WSLg.

**B. Use WSL as a cross-compiler (MinGW-w64) producing native Windows `.exe`/`.dll`. Feasible.**
- The SDK API is plain C, and x64 Windows has a single calling convention. So MinGW-built code can call `glasses.dll` and receive its callbacks.
- The output runs as an ordinary Windows process, with the same USB path and timing as the final system. It can even be launched from the WSL shell.
- Setup is a one-time install you would run, because it needs your password:
  ```bash
  sudo apt install gcc-mingw-w64-x86-64 g++-mingw-w64-x86-64 cmake
  ```
- Caveats:
  - MinGW is **not VITURE's documented toolchain**: they ship an MSVC import library, and their demo uses MSVC pragmas. Compatibility for the calls we use was **proven on hardware** on 2026-11-10 (§3.5). Re-check after any SDK update.
  - Two C runtimes share the process. That is safe for this API (caller-allocated buffers, no `FILE*` or `malloc`/`free` crossing the boundary), but it is a rule the code must keep.
  - libgcc/libstdc++/winpthread must be linked statically or shipped. C++ threads need the `posix` variant.
  - Debugging is weaker than with Visual Studio.
  - Builds on `/mnt/d` are slower than on the Linux filesystem.

### 3.4 What C++ could replace

| Option | Description | Assessment |
|---|---|---|
| 1. Python + ctypes (baseline) | No compiler. Host timestamps are taken inside the Python callback, after it acquires the GIL | Simplest. The GIL effect is measured in Step 7 (headless vs with viewer) |
| 2. Python + a small **native capture shim** in C, built with MinGW from WSL (~150 lines) | The SDK callback is handled in native code: QueryPerformanceCounter timestamp on the SDK thread, a single-producer/single-consumer ring buffer, no GIL on the SDK thread. Python drains batches. Processing, recording, viewer and analysis stay Python. The shim is a second acquisition backend with the identical `RawPoseSample` contract; the ctypes path remains as fallback and cross-check | **Recommended if you want C/C++ now.** It confines the second language to the one module designed to be swappable, and plain C avoids C++ runtime issues |
| 3. Full C++ application | Acquisition, processing, recording, viewer and tests in C++ | Not recommended for Phase 1. It needs a GUI library (e.g. raylib, as in VITURE's demo), a test framework and JSON handling. Later research analysis (models B/C, held-out error) will be Python anyway, giving two parallel codebases |

**Recommendation (revised after the §3.5 hardware test): Option 2.**
- The test showed that Option 1 loses 58% of samples and delivers the rest about 0.3 s late whenever other Python code holds the GIL. That breaks D3 (preserve the data) and the requirement that stale data never drive output. So Option 1 is **not acceptable as the acquisition path**.
- Option 2 matched a fully native C++ program in timing and loss, so Option 3 offers no measured timing advantage for its much larger cost.
- With Option 2, the pure-Python callback backend is dropped rather than kept as a fallback, which keeps one acquisition path.
- Rejected alternative: isolating a pure-Python callback in its own acquisition process would also avoid GIL contention, but it adds inter-process plumbing and is still exposed to garbage-collection and I/O pauses in that process.

### 3.5 Toolchain test on hardware (2026-11-10, throwaway probes in the scratchpad, not project code)

**Build (MinGW-w64 GCC 13 in WSL, `-Wall -Wextra`, no warnings)**
- A C++17 probe exe built three ways: `posix` threads linked via VITURE's MSVC import library `glasses.lib`; `posix` threads linked directly against `glasses.dll`; and the default `win32` thread model. All three built and ran.
- A C11 capture-shim DLL (~60 lines).
- With `-static`, the binaries import only `KERNEL32`, `msvcrt`, `SETUPAPI` and `glasses.dll`, so no MinGW runtime DLLs need shipping.
- The VITURE headers compile unmodified as C++. The shim needs no SDK headers.

**Run.** C++ probe: SetupAPI enumeration found PID 0x101D ("Pro", Gen1, firmware unchanged). Every lifecycle call returned 0. Teardown took 1.9 s.

**Clock identity.** The shim's QueryPerformanceCounter-to-ns conversion equals Python's `perf_counter_ns` timebase: bracketed readings stay ordered, with 0–100 ns differences.

**Timing comparison.** Pose mode at 240 Hz requested, 20 s per run, glasses stationary on the desk. "Load" means a CPU-bound pure-Python thread competing for the GIL, a deliberately synthetic worst case.

| Path | Samples | Device rate | Lost | Host Δt p99 / max | Arrival residual SD | Max lateness |
|---|---|---|---|---|---|---|
| Native C++ exe | 4052 | 202.50 Hz | 0 | 6.03 / 6.55 ms | 0.51 ms | 2.35 ms |
| Python ctypes callback, idle | 4048 | 202.35 Hz | 0 | 6.05 / 6.62 ms | 0.49 ms | 2.78 ms |
| **Python ctypes callback, load** | **1697** | **84.8 Hz** | **≈2353 (58%)** | 19.7 / 32.9 ms | **44.0 ms** | **346.7 ms** |
| Python + C shim, idle | 4049 | 202.44 Hz | 0 | 5.99 / 6.06 ms | 0.20 ms | 2.00 ms |
| **Python + C shim, load** | **4062** | **202.63 Hz** | **0** (ring overflow 0) | 5.99 / 6.13 ms | 0.38 ms | 1.34 ms |

"Lateness" is the arrival residual relative to the earliest arrival in the run; it is relative, not absolute, latency.

**Findings**
1. **The pure-Python callback is not just noisier under load; it loses data.** The SDK's IMU thread blocks inside our callback while waiting for the GIL. Samples are then dropped upstream: device intervals became 10/15/20 ms, i.e. 1–3 consecutive samples missing at a time. The ones that do arrive are up to about 0.3 s behind the device.
2. **Native timestamping in the shim removes this.** There was no loss under the same load, and timing matched the native C++ program. Across idle paths, arrival jitter is dominated by the 1 ms device-timestamp resolution.
3. **The proposed gap rule failed** on the lossy trace. Its running median shifted to 15 ms, so only 5 of about 2353 missing samples were flagged. This is fixed in §5.3. The real lossy trace becomes a regression test.
4. Limits of this test: 20 s runs, one stationary orientation, a synthetic load, and a single PC. Step 7 repeats it over 10 minutes and with the real viewer.

---

## 4. Architecture (revised)

```
┌──────────────────────── acquisition/ (only package that touches hardware or the DLL) ────────────────────────┐
│ VitureSdkSource ── viture_sdk.py (ctypes: lifecycle + device queries only)                                   │
│   enumerate (SetupAPI, VID 0x35CA) → create → initialize → start → open_imu(mode, selected freq)             │
│   callback = native capture shim (C): host_rx = QPC ns on the SDK thread; values copied verbatim into an     │
│   SPSC ring buffer (no GIL on the SDK thread). Drain thread reads batches → queue.put(RawPoseSample | ...)   │
│   shim counters (total, ring overflow) are logged; seq is assigned in native code                            │
│   counts callbacks of the non-selected mode (diagnostic only; never mixed into data)                         │
│   connection watcher: USB re-enumeration 1/s + SDK return codes → DeviceDisconnected / DeviceConnected        │
│ ReplaySource     reads raw_pose.csv + events.jsonl (+ commands) → identical item sequence                    │
│ SyntheticSource  deterministic fault traces (§11)                                                            │
└──────────────────────────────────────────┬───────────────────────────────────────────────────────────────────┘
               one ordered queue: samples · source events · operator commands (capture_neutral, segment marks)
                                           │  pipeline thread
          ┌────────────────────────────────┼──────────────────────────────────────────┐
          ▼                                ▼                                          ▼
 recording/ RawWriter               orientation/ OrientationProcessor            metrics/ online counters
 (raw row written first)            pure, deterministic, no wall clock:          (rates, intervals, gaps,
                                    validate → flags → normalise →                queue depth, seq loss)
                                    continuity → NeutralCapture (stability,
                                    retries) → q_rel → display Euler
                                           │ ProcessedSample (flags, validity)
          ┌────────────────────────────────┼──────────────────────────────────────────┐
          ▼                                ▼                                          ▼
 recording/ ProcessedWriter,        tracking/ TrackingGate (consumer side,       viewer/ (tkinter, 30 Hz,
 EventWriter, CalibrationWriter     host clock): fresh · valid · connected ·      reads snapshot; never
                                    neutral accepted → usable_for_control(now)    called from the callback)
                                    — the ONLY sanctioned input for any future
                                    command-producing module (Phase 2+)
```

**Module rules**
1. **Dependency direction:**
   - `types` ← `acquisition`, `orientation`, `recording`, `metrics`, `tracking`
   - ← `pipeline` ← `viewer`, `cli`

   `orientation`, `recording`, `metrics` and `tracking` never import `acquisition`, ctypes or the DLL. An import-graph test enforces this.
2. **Raw first:** the raw row is written before processing. Processed files are always regenerable from raw by replay.
3. **Determinism:**
   - Operator commands (neutral capture, segment marks) travel in the same ordered queue as samples. They are logged with the `seq` they apply at and replayed at the same position.
   - The processor never reads a clock; it uses only sample timestamps.
   - Live and replayed processed output are byte-identical on the same platform and versions. Across platforms they are identical to within floating-point last-digit (ulp) differences of `libm`; provenance records platform and versions.
4. **Clocks are never mixed:**
   - The device clock drives sample flags and intervals.
   - The host clock drives staleness, the gate and the UI.
   - The relation between the two clocks is estimated, never assumed.
5. **Validity ≠ staleness (D2):** validity is a property of a received sample. Staleness is a property of the stream at query time, so it is never stored on samples. Only the `TrackingGate` combines them.
6. **One process owns the device** (Windows single-process limit). The viewer and recorders live in that process.
7. **Extension point:** `SampleSink.on_sample(ProcessedSample)` / `on_event(Event)` plus `TrackingGate`. No placeholder modules are created for later phases.

---

## 5. Conventions and definitions (become `docs/conventions.md` and `docs/quality-and-metrics.md`)

### 5.1 Frames, quaternions, terminology

| Symbol | Meaning | Status |
|---|---|---|
| W | SDK tracking frame, NWU: X "North", Y "West", Z Up. The Pro has no magnetometer, so "North" is an arbitrary filter heading (yaw read −130.8° at stream start in the probe) | Per SDK; heading behaviour to verify |
| H | Glasses (head-mounted device) frame: X forward through the lenses, Y left, Z up | Inferred; **G0 check** |
| `q_WH` | SDK quaternion, assumed to rotate H-frame vectors into W | **Unverified; G0 check U1** |
| `q0` | Accepted neutral reference (a `q_WH` value), per connection | — |
| `q_rel` | `conj(q0) ⊗ q_WH`: head orientation relative to the neutral reference, expressed in the neutral head frame (protocol §2.2) | — |
| `q_TH` | Head relative to torso. **Not available**: it needs a torso sensor in the same frame. No Phase 1 field carries this name or meaning | Protocol §2.2 |

- **Algebra:** Hamilton product, scalar-first storage `[w, x, y, z]`, active rotations. The inverse of a unit quaternion is its conjugate.
- **Angular distance:** `θ(a, b) = 2·acos(min(1, |⟨a, b⟩|))`, sign-invariant.
- **Sign handling:**
  - SDK values are stored as delivered.
  - Processed `quat` is normalised and made continuous: if `⟨qᵢ, qᵢ₋₁⟩ < 0`, use −qᵢ and set flag `hemisphere_flip`.
  - `q_rel` uses the canonical `w ≥ 0`.
- **Terminology:** "head orientation relative to the tracking frame" (`q_WH`) and "relative to the neutral reference" (`q_rel`). **Never** anatomical neck or cervical terms (flexion, lateral bending, axial rotation, range of motion). Glasses orientation is not neck orientation relative to the torso.

### 5.2 Display Euler (exact conversion)

From `q_rel = (w, x, y, z)`, using the intrinsic Z-Y′-X″ sequence, `q_rel = q_z(ψ) ⊗ q_y(θ) ⊗ q_x(φ)` (equivalently R = R_z(ψ)·R_y(θ)·R_x(φ)):

```
yaw   ψ = atan2( 2(w·z + x·y), 1 − 2(y² + z²) )     ∈ (−180°, 180°]
pitch θ = asin ( clamp( 2(w·y − z·x), −1, 1 ) )      ∈ [−90°, 90°]
roll  φ = atan2( 2(w·x + y·z), 1 − 2(x² + y²) )     ∈ (−180°, 180°]
```

- **Signs (right-handed NWU, no flips in data):** +yaw = turn left, +pitch = nose down, +roll = right ear down. The UI adds direction words. Signs are a **G0 check**.
- **Gimbal lock:** the clamp avoids domain errors. Flag `euler_near_singular` when |θ| > 89° (a numeric guard).
- **Use:** these values are for display and diagnostics only. All computation uses quaternions.
- **SDK Euler angles** are stored raw and never used.
- **Threat to validity:** recorded in §7.1 (TV1).

### 5.3 Sample flags (deterministic, device-clock based; all thresholds provisional)

Notation:
- sample *i* has device time `dᵢ` (ns), as-delivered quaternion `q̃ᵢ`, and normalised `qᵢ`;
- `prev` is the last sample that passed validity;
- `m` is the reference interval:
  - **Primary (`gap_reference = measured`):** `m = 10⁹ / r_ref`, where `r_ref` is the fixture-measured rate for this device model and selected frequency from the bench report. It is stored in config together with its source session ID.
  - **Fallback (`gap_reference = adaptive`, used when no characterised value exists):** the 25th percentile of the last `N_ref` valid device intervals, or `10⁹/f_selected` while fewer than `N_min` intervals exist.
  - The mode used is recorded in `session.json`.
  - Checked on the §3.5 traces: the measured reference detected 2352 of ≈2354 missing samples, the adaptive quantile 2002, and the original running median only 338. There were no false flags on any clean run. A median fails because sustained loss lengthens many intervals; it never shortens the true period, so low quantiles and a fixed reference stay put;
- `δ_res` is the device timestamp resolution, measured at 1 ms. It keeps quantisation-only variation, such as 6 ms intervals around a 4.94 ms period, from being flagged.

| Flag | Definition | Class |
|---|---|---|
| `nonfinite` | Any of the 7 values is NaN or ±Inf | **Invalidating** |
| `zero_norm` | `‖q̃ᵢ‖ < ε_zero` | **Invalidating** |
| `ts_duplicate` | `dᵢ = d_prev` | **Invalidating** (row kept) |
| `ts_backward` | `dᵢ < d_prev` | **Invalidating** |
| `angular_jump` | `θ(q_prev, qᵢ) > τ_jump` | **Invalidating** (sensor-glitch detector; see note) |
| `norm_deviation` | \|‖q̃ᵢ‖ − 1\| > τ_norm (still normalised and used) | Informational |
| `gap_before` | `dᵢ − d_prev > k_gap · m + δ_res`; also logs `est_missing = round((dᵢ − d_prev)/m) − 1` | Informational |
| `hemisphere_flip` | Processed sign flipped for continuity | Informational |
| `euler_near_singular` | \|θ_display\| > 89° | Informational |
| `no_neutral` | No accepted neutral for the current connection, so `q_rel` and Euler are empty | Informational (blocks the gate) |

- `valid := no invalidating flag`. Invalid rows are always kept and never silently dropped.
- **Note on `angular_jump`:** the threshold is meant to catch sensor glitches only. It is not a statement about how fast heads move. Its effect is to mark one sample invalid.
- **Recentering, disconnects and reconnects are events (§5.4), not sample flags.** Samples carry `connection_id` and `neutral_calibration_id`, so they can be joined to events.

### 5.4 Events, staleness and the tracking gate (consumer side, host clock)

- **`events.jsonl`:**
  - session start/stop; device connected/disconnected (with detection method); IMU open/close;
  - frequency requested/selected; non-selected-mode callback counts;
  - neutral capture requested, accepted or rejected; segment start/end (bench step labels);
  - stale begin/end; gate usable/unusable (with reason); SDK error; queue-depth warning.
- **Staleness:** `stale(now) := now − h_last_valid > T_stale`, computed on query and never stored on samples. The pipeline watchdog logs stale begin/end events for diagnostics.
- **Gate:** `usable_for_control(now) := connected ∧ last sample valid ∧ ¬stale(now) ∧ neutral accepted for this connection`.
  - Any future command-producing module must use this gate. A test asserts it is false for every invalid, stale, disconnected or no-neutral case.
  - Phase 1 has no command producers; it displays and logs the gate state.
- **Disconnect:** the connection's neutral is invalidated, and the next connection gets a new `connection_id` and needs a new accepted capture (O5).

### 5.5 Metric definitions (independent of each other, D5)

All metrics are computed per recording and per 1-minute segment. Fixture (`mounting=fixture`) and worn (`mounting=worn`) recordings are **never pooled**. Worn reports are labelled "includes natural head movement".

| Metric | Definition |
|---|---|
| **Achieved rate** | (N−1) / (t_last − t_first), on the device clock and on the host clock. Reported with `frequency_requested_hz` and `frequency_selected_hz` |
| **Sampling-interval jitter, device** | Distribution of Δd = dᵢ − dᵢ₋₁ over valid consecutive samples: min, p1, p5, p50, p95, p99, max, mean, SD. SD and (p99 − p1) are the jitter summaries. The 1 ms timestamp resolution is reported alongside, since it floors this measure |
| **Sampling-interval jitter, host** | Same statistics on Δh = hᵢ − hᵢ₋₁ |
| **Arrival-time jitter (relative latency)** | Least-squares fit h = a + b·d. Reported: (b − 1)·10⁶ in ppm (clock skew); SD and (p99 − p1) of residuals rᵢ; and relative lateness rᵢ − min(r). Absolute latency is **not** measurable this way (no shared clock) |
| **Loss** | Gaps (count, longest, estimated missing samples Σ est_missing); **loss fraction** = 1 − N_received / (span × r_ref), where r_ref is the fixture-measured rate for the selected frequency from the bench report; pipeline loss = gaps in shim `seq` plus ring overflow count (both expected 0); maximum ring and queue depth |
| **Angular jitter** | Fixture or worn stationary recordings. `ref` = normalised sign-aligned mean of the first `W_ref` seconds. `v(t)` = rotation vector of `conj(ref) ⊗ q(t)` in degrees (sequence-free; components along the reference X, Y, Z axes). Jitter = per-component SD of `v(t)` minus its centred moving average of width `W_j`; also the geodesic RMS. Cross-check: RMS of consecutive-sample geodesic steps / √2 (underestimates if the SDK filter smooths) |
| **Apparent drift** | Least-squares slope of each `v(t)` component and of `θ(ref, q(t))` against device time over the whole recording, in °/min; plus the net change between the first and last `W_ref` means. "Apparent" because sensor bias, SDK filter behaviour and fixture creep cannot be separated |

### 5.6 Neutral capture (D6)

1. The operator requests a capture at `seq = s_r`. Samples arriving after `s_r` are collected until `W_neutral` of device time has elapsed.
2. If accepted, `q0` = the normalised, sign-aligned mean of the window. The neutral takes effect from the first sample after the window.
3. **Stability check.** The capture is accepted only if all of the following hold:
   - (a) every window sample is valid;
   - (b) no `gap_before` occurred in the window;
   - (c) no disconnect or stale event occurred;
   - (d) dispersion `d_max = maxᵢ θ(qᵢ, q0) ≤ τ_stab`.
   The RMS dispersion is logged too.
4. **Retries:** the operator may retry at any time, with no limit and no forced repetition. Every attempt (accepted or rejected, with reason, `d_max`, RMS, n, window) is written to `calibration_neutral.jsonl`.
5. Each acceptance increments `neutral_calibration_id`; the record holds `q0`, window `seq` range and `applies_from_seq`.

### 5.7 Provisional parameters (single file `config/defaults.toml`; snapshot copied into every `session.json`)

| Parameter | Default | Meaning / effect | Basis |
|---|---|---|---|
| `imu.mode` | `pose` | Primary mode (D3); `raw` = separate characterisation session | Protocol §2.1 |
| `imu.frequency_requested_hz` | 240 | Used if supported in the selected mode; otherwise the highest supported rate below it, logged as a fallback (`frequency_selection_reason`) | D6 |
| `neutral.window_s` (`W_neutral`) | 3.0 | Capture window | D6, provisional |
| `neutral.tau_stab_deg` (`τ_stab`) | 2.0 | Maximum dispersion for acceptance. **Placeholder; set from data (O6)** | Provisional |
| `flags.k_gap` | 1.5 | Gap factor relative to the reference interval `m` | Provisional |
| `flags.gap_reference`, `flags.r_ref_hz` | `measured`, table per frequency (240 → 202.5, from §3.5; replaced by Step 7 values) | Fixed reference interval from fixture-measured rates | Measured, provisional until Step 7 |
| `flags.ref_quantile`, `flags.n_ref`, `flags.n_min` | 0.25, 200, 20 | Adaptive fallback: quantile, window and warm-up | Provisional |
| `flags.ts_resolution_ns` (`δ_res`) | 1 000 000 | Device timestamp resolution added to the gap threshold. Measured value; re-measured in Step 7 | Measured (§1.2) |
| `flags.tau_jump_deg` | 20.0 | Sensor-glitch detector (≈4000°/s at 200 Hz), **not** a head-motion limit | Provisional |
| `flags.tau_norm`, `flags.eps_zero` | 1e-3, 1e-6 | Numeric sanity checks | Provisional |
| `gate.t_stale_ms` (`T_stale`) | 100 | Staleness on the host clock | Provisional |
| `metrics.w_ref_s`, `metrics.w_jitter_s` | 5.0, 1.0 | Drift reference window; jitter detrend window | Provisional |
| `io.flush_interval_s` | 1.0 | Maximum data lost on a crash | Engineering |

Every value is labelled *provisional engineering default, not a validated hardware or ergonomic limit* in the docs, the config file comments and `session.json`.

---

## 6. Data and files

### 6.1 Session directory `data/sessions/<UTC>_<condition>_<mounting>_<id>/`

| File | Content |
|---|---|
| `session.json` | Normalised metadata (§6.2) |
| `raw_pose.csv` | `seq, connection_id, host_rx_monotonic_ns, device_ts_raw, sdk_roll_deg, sdk_pitch_deg, sdk_yaw_deg, sdk_qw, sdk_qx, sdk_qy, sdk_qz`: callback values **as delivered** (float32 written with 9 significant digits, bit-exact round-trip) |
| `raw_imu.csv` | Raw-mode sessions only: `seq, connection_id, host_rx_monotonic_ns, device_ts_raw, vsync_raw, gyro_x..z, accel_x..z, mag_x..z, temperature` (units undocumented, recorded as such) |
| `processed_pose.csv` | `seq, connection_id, host_rx_monotonic_ns, device_ts_raw, dt_device_ns, dt_host_ns, quat_w..z, quat_rel_w..z, euler_display_yaw_deg, euler_display_pitch_deg, euler_display_roll_deg, valid, flags, neutral_calibration_id` (doubles via `repr`; regenerable from raw) |
| `events.jsonl` | §5.4; each event has `host_monotonic_ns`, `last_seq`, `connection_id` |
| `calibration_neutral.jsonl` | Every neutral-capture attempt (§5.6) |
| `commands.jsonl` | Operator commands with `seq` positions, used by replay |
| `sdk_log.txt` | SDK log hook output (level 1 by default) |
| `analysis/` | `report.json`, `report.md`, optional plots |

Raw-mode sessions produce only timing metrics and descriptive channel statistics. No orientation processing is applied to raw IMU data in Phase 1.

### 6.2 `session.json` (normalised)

| Group | Fields |
|---|---|
| Identity | `schema_version`, `session_id`, `condition` (`bench`), `mounting` (`fixture` \| `worn`), `participant_id` (`null` in Phase 1: no participants), operator notes (with a reminder: no PII) |
| Provenance | Package version, git commit plus dirty flag, Python and numpy versions, OS build, command line, config snapshot and its SHA-256, SDK version string, `glasses.dll` SHA-256, backend (`ctypes` or `shim`) |
| Device | Market name, PID, device type, firmware, SN hash (equipment identifier; can be disabled), USB port or hub note |
| IMU | Mode, frequency support table, requested, selected, selection reason; observed rate filled in at close |
| Clocks | Host clock (`perf_counter_ns`, QPC, frequency); anchor pairs (perf_counter_ns, UTC `time_ns`) at start and end; device timestamp described as "SDK device timebase; observed ns, 1 ms resolution; unverified" |
| Segments | Bench step labels (become `trial_id` in the export) |

### 6.3 Denormalised export (D1)

`headmusic export <session> --denormalized` writes `export/pose_samples_denormalized.csv`.
- Every row carries the protocol §10 fields:
  - `schema_version`, `participant_id`, `session_id`, `trial_id` (segment label), `condition`;
  - `software_build`, `sdk_version`, firmware, clock fields;
  - `neutral_calibration_id` plus the referenced `q0`;
  - the §10.1 fields (`device_ts_raw`, `host_rx_monotonic_ns`, `quat_wxyz_*`, `quat_neutral_relative_wxyz_*`, `euler_display_deg_*`, `sample_quality`).
- `sample_quality` is the flag set, or `valid`.
- `export_manifest.json` records the SHA-256 of every input file, the exporter version and the parameters.
- The CSV contains no export timestamp, so the same inputs and exporter version give a byte-identical file.

---

## 7. Documentation to be written

`README.md` (setup and commands), plus these files in `docs/`:
- `conventions.md` (§5.1–5.2, with a verified/unverified column)
- `quality-and-metrics.md` (§5.3–5.7)
- `data-format.md` (§6, with mapping to protocol §10)
- `sdk-notes.md` (§1 and the discrepancy list)
- `bench-checklist.md`
- `bench-report.md`
- `threats-to-validity.md`
- `docs/research/` (protocol, then the research report)

### 7.1 `threats-to-validity.md` (initial entries for the research team; engineering observations, no conclusions)

| ID | Threat | Details |
|---|---|---|
| TV1 | Euler parameterisation | Euler sequences and the rotation vector differ by bilinear second-order terms (y·p, y·r, p·r), the same form as Model C's interaction terms. The parameterisation alone can shift effect from linear terms into apparent interactions. Interaction coefficients must not be read as anatomical coupling. Full `q_WH` and `q_rel` are preserved so alternatives can be evaluated later |
| TV2 | No torso reference | Head-in-tracking-frame is not neck-relative-to-torso; torso motion is indistinguishable (protocol §2.2) |
| TV3 | No magnetometer | No absolute heading on the Pro; yaw drift is expected but not yet measured |
| TV4 | Undocumented SDK fusion filter | Smoothing, latency and bias handling are unknown |
| TV5 | Timestamp resolution | 1 ms device timestamps floor interval-jitter estimates |
| TV6 | Relative latency only | Host-arrival latency is relative (no shared clock). With the shim, arrival times exclude Python scheduling. Python-side processing latency after the drain, which matters for later command timing, is a separate quantity and is not yet measured |

---

## 8. Repository layout

```
viture-playground/
├─ README.md   pyproject.toml   .gitignore   config/defaults.toml
├─ docs/  (§7)   docs/research/  (protocol; research report when provided)
├─ sdk/                 vendor zips — git-ignored (proprietary licence)
├─ vendor/viture/       DLLs + headers extracted by scripts/setup_sdk.py (SHA-256 verified) — git-ignored
├─ scripts/setup_sdk.py
├─ native/              capture_shim.c (C11), build_shim.sh (MinGW in WSL), build notes; output in native/build/ (git-ignored);
│                       compiler version + shim SHA-256 recorded in session provenance
├─ src/headmusic/
│  ├─ types.py
│  ├─ acquisition/   base.py · viture_sdk.py · usb_enum.py · viture_source.py · replay_source.py · synthetic.py
│  ├─ orientation/   quaternion.py · euler.py · neutral.py · flags.py · processor.py
│  ├─ tracking/      gate.py
│  ├─ recording/     schema.py · writer.py · reader.py · export.py
│  ├─ metrics/       timing.py · angular.py · report.py
│  ├─ pipeline.py    config.py    cli.py
│  └─ viewer/app.py
├─ tests/   (unit, no hardware)   tests/hardware/  (opt-in: pytest --hardware)
└─ data/    session output — git-ignored
```

`.gitignore` from the first commit: `sdk/`, `vendor/`, `data/`, `exports/`, `.venv/`, `*.egg-info`, `.claude/settings.local.json`, `native/build/`.

**CLI**

| Command | Purpose |
|---|---|
| `devices` | List glasses |
| `info` | Device identity and capability table |
| `record --mode pose\|raw --freq 240 --duration S --mounting fixture\|worn [--segment LABEL]` | Headless recorder |
| `view [--record]` | Live view with neutral capture and retry, segment marks, gate status |
| `replay <session> [--speed 1\|max] [--view] [--reprocess]` | Replay without glasses |
| `analyze <session>` | Timing and angular metrics report |
| `export <session> --denormalized` | Protocol per-row export |
| `synth <scenario>` | Write a synthetic session |

---

## 9. Compatibility issues and unknowns

| # | Issue | Resolution path |
|---|---|---|
| U1 | Quaternion direction | G0: capture neutral at a pitched or rolled pose, then rotate about the glasses' own up axis. Under the correct convention `q_rel` is pure yaw. Repeat at several combined orientations |
| U2 | Head-frame axes and signs | G0: off-head rotations against a square desk edge (90° references) and slow single-axis movements |
| U3 | Timestamp units, epoch | 10-min clock fit (b ≈ 1 confirms ns); power-cycle test for the epoch; the sample instant stays undocumented |
| U4 | Requested ≠ achieved rate | Measure 60/90/120/240 Hz in pose mode (and raw-mode rates if used) |
| U5 | Filter state across `open_imu`, sleep/wake, replug | Bench tests. The gate already requires a new neutral after reconnect |
| U6 | Yaw drift without magnetometer | Fixture recordings of 60 s and 10 min |
| U7 | Python GIL in host timing | **Measured (§3.5):** the pure-Python callback loses data under load; the native shim does not. Step 7 repeats this over 10 min with the real viewer |
| U8 | Windows single-process lock | Clear error message; `info` checks for it |
| U9 | Mode-transition callbacks | Only the selected mode's data is recorded; others are counted |
| U10 | Unplug detection (no Gen1 callback) | Watchdog plus 1 Hz USB re-enumeration plus SDK return codes. Teardown takes about 1.8 s and runs off the UI thread |
| U11 | SDK logs to stderr even with a hook | Level 1, captured via the hook |
| U12 | Raw-mode units undocumented | Recorded as undocumented |
| U13 | SDK doc inconsistencies | `sdk-notes.md`; runtime values win |
| U14 | MinGW compatibility | **Verified (§3.5)** for enumeration, lifecycle, device queries and the pose callback. Raw callback to be verified in Step 2. Re-verify on SDK updates |

---

## 10. Implementation plan (begins only after your go-ahead)

| Step | Deliverable | Verified by |
|---|---|---|
| 0 Bootstrap | `git init` (branch `phase1/hardware-foundation`); `.gitignore`; move protocol to `docs/research/`; `pyproject.toml`; `config/defaults.toml`; `scripts/setup_sdk.py`; README setup. Optional private remote | Clean setup from README on a fresh clone |
| 1 Core math | `types`, `quaternion`, `euler`, `flags`, neutral-capture logic | Unit tests §11 |
| 2 Acquisition | Native capture shim (pose and raw records, SPSC ring, QPC timestamps, counters) with `native/build_shim.sh`; ctypes binding for lifecycle and queries; SetupAPI enumeration; `VitureSdkSource` (pose primary, raw optional, frequency selection, drain thread, connection watcher, log capture); `devices` and `info` | Hardware smoke test reproduces §1.2 and §3.5; no-device and locked-device starts fail cleanly; record layout and clock-identity checks pass |
| 3 Recording | Raw, processed, event, calibration and command writers; `session.json`; reader; denormalised export | Round-trip, crash-safety and export-reproducibility tests |
| 4 Processing, gate, replay | `OrientationProcessor`, `TrackingGate`, `ReplaySource`, `SyntheticSource`, `replay --reprocess` | Fault-trace tests; live vs replay byte-identical |
| 5 Metrics | `timing`, `angular`, `analyze` report | Recovery of injected properties on synthetic traces |
| 6 Viewer | Strip charts (10 s) of neutral-relative yaw/pitch/roll; readouts with direction words; status (connection, observed rate, gate, stale, gaps, neutral id and dispersion, recording); capture and retry; segment marks | Manual check, live and from replay |
| 7 Bench characterisation (with you; fixture first) | Identity; per-frequency achieved rates; 60 s and 10 min fixture stationary; axis, sign and convention checks (U1, U2); neutral capture and retry; unplug/replug; sleep/wake; second-process lock; headless vs viewer timing. Worn recordings only after O3 | `bench-report.md`; G0 evidence; conventions "verified" column filled |
| 8 Review | Docs, test report, threats-to-validity, open-issues list | Acceptance review with you |

---

## 11. Acceptance criteria and tests

| # | Criterion |
|---|---|
| AC1 Connect | `info` reports identity, firmware, SDK version and the support table. No-device and locked-device starts fail cleanly with readable SDK error mapping |
| AC2 Acquire | Every callback is stored verbatim with `seq`, `host_rx_monotonic_ns` and `device_ts_raw`; float32 values are bit-exact. A 10-min headless run has 0 pipeline loss |
| AC3 Frequency | Requested, selected (with reason) and observed rates are in `session.json` and the report. Unsupported requests fall back as logged, never silently |
| AC4 Neutral | The stability check enforces §5.6; rejected attempts are logged with a reason; retries work; `q_rel` at the first applied sample equals `conj(q0)⊗q`; replay reproduces every attempt and outcome |
| AC5 Quality and gate | Every flag in §5.3 fires on its synthetic fault and on nothing else. The gate is false for invalid, stale, disconnected and no-neutral states, and true only when all conditions hold |
| AC6 Record and export | All files are written; the raw float32 round-trip is bit-exact; files are readable after a forced kill (≤ 1 s lost); the denormalised export is byte-reproducible and carries every protocol §10 field |
| AC7 Metrics | On synthetic traces with known properties: rate within 0.1%, gap count exact, clock skew within 1 ppm, drift slope within 2%, jitter SD within 5% |
| AC8 Replay | Runs with no glasses or DLL present; reprocessed output is byte-identical to live (same platform and versions) |
| AC9 Modularity | The import-graph test passes; `orientation`, `recording`, `metrics`, `tracking` and `viewer` tests run with `glasses.dll` absent |
| AC10 Visualise | Display refresh ≥ 30 Hz; stale indication within `T_stale` + 1 frame; disconnect shown within about 1.5 s |
| G0 | Device identified as Pro Gen1; frame, axis signs and neutral behaviour checked and documented |

**Unit tests (no hardware), grouped by your additional requirements**

- **Quaternion sign changes:**
  - q vs −q geodesic invariance;
  - continuity flip on a sign-alternating trace;
  - canonical `w ≥ 0` for `q_rel`;
  - mean of mixed-sign samples;
  - Hamilton product against known values; `q ⊗ conj(q) = 1`.
- **Euler:**
  - 90° about each axis gives the documented signs;
  - round-trip on a grid;
  - ±90° pitch clamp and flag;
  - yaw crossing ±180° produces no jump in `q_rel` or metrics.
- **Timestamp problems:**
  - duplicate, backward, gap with `est_missing`;
  - **sustained loss**, a regression test built from the real §3.5 lossy trace: with the measured reference, ≥ 99% of the ≈2354 missing samples must be estimated; with the adaptive fallback, ≥ 80%, and the session loss fraction must still report the full deficit;
  - bursty arrival;
  - low rate (60 Hz);
  - running-median warm-up;
  - 1 ms quantisation.
- **Recentering:**
  - accepted capture;
  - rejection for each criterion (a)–(d), each with its logged reason;
  - retry;
  - `applies_from_seq` exactness;
  - raw data untouched;
  - replay equivalence.
- **Disconnects:**
  - disconnect event, then stale, then gate false, then neutral invalidated;
  - reconnect gives a new `connection_id` and requires a new capture;
  - no valid `q_rel` before acceptance.
- **Invalid measurements:**
  - NaN and Inf in each field;
  - zero quaternion;
  - norm deviation;
  - angular jump;
  - invalid rows kept and excluded by the gate.
- **Recording:** float32 bit-exact; schema and column order; partial-file readability; export byte-reproducibility and manifest hashes.
- **Metrics:** synthetic recovery (AC7); fixture and worn never pooled.
- **Architecture and binding:** import graph; ctypes prototypes checked against 2.4.2 headers (including the 4-int thread-ID buffer).
- **Capture shim** (runs without glasses by calling the shim's callback directly from a test thread):
  - record layout size identical in C and ctypes;
  - QPC-ns clock identity with `perf_counter_ns`;
  - ring wrap-around;
  - overflow counted, never silent;
  - `seq` continuity;
  - float values bit-exact through the ring.

**Hardware tests (opt-in, `pytest --hardware`, plus manual checklist):**
- 10 s stream at each supported pose rate;
- clean teardown;
- unplug mid-stream, then replug;
- sleep/wake;
- second-process lock.

---

## 12. Out of scope (Phase 1)

Musical interface, MIDI or audio, gestures, dwell or state machine, chord mapping, in-glasses HUD, calibration ratings UI, models A/B/C, optimiser, comfort estimation, ML, torso tracking, participant data collection (IRB gate).
