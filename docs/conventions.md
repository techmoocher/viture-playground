# Conventions: frames, quaternions, Euler angles, units, clocks

The status column says what is verified and what still needs the G0 bench check ([bench-checklist.md](bench-checklist.md)).

## Frames and terminology

| Symbol | Meaning | Status |
|---|---|---|
| W | SDK tracking frame, North-West-Up: X "North", Y "West" (left), Z Up. The Pro has no magnetometer (raw magnetometer fields are zero), so "North" is an arbitrary filter heading, not geographic north. In the first probe, yaw read −130.8° at stream start, so the heading is not zeroed per session | NWU per SDK docs; heading behaviour unverified |
| H | Glasses (head-mounted device) body frame: X forward through the lenses, Y left, Z up when worn level | **Consistent with G0 run R6a (2026-11-11)**: yaw about ±Z, nose-down pitch about +Y, right-down roll about +X, each within about 7° (hand movements, not a precision fixture). Read under the `q_WH` reading below |
| `q_WH` | SDK pose quaternion, assumed to rotate H-frame vectors into W | **Supported, not yet confirmed (U1).** In R6a `yaw_right_90` (rotation about the vertical from a 6.2° tilt), `P_track` was 0.3° from vertical and `P_head` 6.0°, as this reading predicts; the inverse predicts the reverse. The margin is small; the decisive test is R6b (wedge) |
| `q0` | Accepted neutral reference: a `q_WH` value, per connection | — |
| `q_rel` | `conj(q0) ⊗ q_WH`: head orientation relative to the neutral reference, in the neutral head frame (protocol §2.2) | — |
| `q_TH` | Head relative to torso. **Not available**: it needs a torso sensor in the same frame. No field carries this meaning | Protocol §2.2 |

Use "head orientation relative to the tracking frame" (`q_WH`) and "relative to the neutral reference" (`q_rel`).
Do **not** use anatomical terms (flexion, extension, lateral bending, axial rotation, range of motion).

## Quaternions

| Topic | Convention |
|---|---|
| Algebra | Hamilton product; scalar first `(w, x, y, z)`; active rotations: `v_W = q ⊗ (0, v_H) ⊗ conj(q)` |
| SDK storage order | `[roll, pitch, yaw, qw, qx, qy, qz]`. Verified as w-first: \|q\| = 1 ± 2·10⁻⁷ with `w` first |
| SDK sign | **The SDK keeps `w ≥ 0`.** In a real session no sample had `w < 0`, and the sign jumped 3 times when `w` passed 0. Raw values are stored unchanged |
| Processed `quat` | Normalised, then sign-aligned to the previous finite sample (continuous). Each SDK sign jump is flagged `hemisphere_flip` once |
| `quat_rel` | Canonical `w ≥ 0` |
| Angular distance | `θ(a, b) = 2·atan2(‖vec(conj(a) ⊗ b)‖, |w|)`, sign-invariant and accurate for small angles |
| Mean (neutral `q0`) | Normalised arithmetic mean after aligning signs to the first sample. With the dispersion bounded by the stability check, this differs from the Markley eigenvector mean only at second order |
| Tilt from upright | `acos(clamp(1 − 2(x² + y²)))`: the angle between the glasses' up axis (H +Z rotated into W) and W's up axis. 0° = upright, 90° = up axis horizontal, 180° = upside down. It is identical for q, −q and conj(q), so it does **not** depend on the unverified quaternion direction (U1). It relies only on H +Z being the glasses' up axis (G0 check) and W +Z being up (SDK NWU). **Descriptive only:** shown live in the viewer and stored with each neutral capture; nothing is accepted or rejected on it. Real upside-down samples on 2026-11-10 gave about 170° |

## Display Euler angles (exact conversion)

From `q_rel = (w, x, y, z)`, intrinsic Z-Y′-X″ (yaw, then pitch, then roll), `q_rel = q_z(ψ) ⊗ q_y(θ) ⊗ q_x(φ)`:

```
yaw   ψ = atan2( 2(w·z + x·y), 1 − 2(y² + z²) )     ∈ (−180°, 180°]
pitch θ = asin ( clamp( 2(w·y − z·x), −1, 1 ) )      ∈ [−90°, 90°]
roll  φ = atan2( 2(w·x + y·z), 1 − 2(x² + y²) )     ∈ (−180°, 180°]
```

- **Signs (right-handed NWU, no flips in data):** +yaw = turn left, +pitch = nose down, +roll = right ear down. The viewer adds direction words. These are unit-tested mathematically; **physical signs confirmed in G0 run R6a (2026-11-11)**: 90° left turn +90.5°, right turn −89.8°, nose-down +39.8°, right side down +55.3°.
- **Singularity:** |θ| > 89° sets `euler_near_singular`, a numeric guard only.
- **Use:** display and diagnostics only. All computation uses quaternions.
- **Parameterisation:** Euler interaction products must not be read as anatomical coupling ([threats-to-validity.md](threats-to-validity.md), TV1).
- **Metrics:** stationary metrics use the sequence-free rotation vector instead.
- **SDK Euler angles** (`sdk_roll_deg`, `sdk_pitch_deg`, `sdk_yaw_deg`) are stored raw and never used. Their rotation order is undocumented, and one static pose could not identify it. SDK pitch read −168°, outside a standard ZYX range.

## Units

| Quantity | Unit |
|---|---|
| Angles in files | degrees |
| Quaternions | unitless |
| Times | integer nanoseconds |
| Raw IMU mode (gyro, accel, mag, temperature) | **Undocumented by the SDK**; recorded as such. At rest \|accel\| ≈ 0.99, which suggests g, but this is not verified |

## Clocks

| Field | Meaning |
|---|---|
| `device_ts_raw` | SDK timestamp, stored verbatim (`uint64`). Observed: about 10⁹ units per host second (ns) and every value a multiple of 10⁶ (1 ms resolution). Epoch consistent with time since power-on. The sample instant it refers to is undocumented |
| `host_rx_monotonic_ns` | QueryPerformanceCounter scaled to ns, taken by the native capture shim as the first statement of the SDK callback. Same timebase as Python `time.perf_counter_ns()` (verified) |
| Clock anchors | `session.json` stores (host monotonic, UTC) pairs at the start and end of each session |
| Rule | Device clock for sample flags and intervals; host clock for staleness, the gate and the UI. The relation between them is estimated (clock fit), never assumed. Latency figures are relative, not absolute |
