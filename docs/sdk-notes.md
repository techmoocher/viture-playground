# VITURE SDK notes (v2.4.2, Windows x86_64, VITURE Pro)

What the SDK documentation says, and what we observed on this PC. Runtime values win over the docs.
Observations come from runs on 2026-11-10. Several were started without announcing them to the operator, so
**the device's physical conditions during them are unconfirmed** ([bench-report.md](bench-report.md)).

## Integration

- **Official C API (`glasses.dll`, 69 exports), loaded with `ctypes`** for lifecycle and queries:
  `create → initialize → start → register callbacks → open_imu → close_imu → stop → shutdown → destroy`.
- **The IMU callbacks are native.** We register function pointers exported by `native/capture_shim.c`, not Python
  callbacks. Reason: a Python callback must take the GIL on the SDK's IMU thread. Under Python load, the toolchain test
  lost 58% of samples upstream and delayed the rest by about 0.3 s (proposal §3.5). The shim had no loss under the same load.
- **Enumeration:** `glasses.dll` exports no enumeration function. We use Windows SetupAPI filtered on VID `0x35CA`, then
  `xr_device_provider_is_product_id_valid`, which is the SDK demo's fallback approach.
- **MinGW-w64 (GCC 13, in WSL)** links against `glasses.dll` both through VITURE's MSVC `glasses.lib` and directly against the DLL. It is not VITURE's
  documented toolchain; re-verify after SDK updates.
- **Not used:** the stat reporter (`xr_stat_reporter_*`, network), the camera provider, and the Carina and native-DOF APIs.

## Verified on this device

| Item | Observation |
|---|---|
| Identity | PID `0x101D`, market name "Pro", device type `GEN1` (0), firmware `07.0.03.013_20250422`, no native DOF |
| Frequency support (SDK table) | Pose: 60, 90, 120, 240 Hz. Raw: 60–500 Hz. 1000 Hz: no |
| Achieved pose rates (preliminary) | 60 → 59.4 Hz; 90 → 84.7 Hz; 120 → 112.3 Hz; 240 → 202.5–202.6 Hz. **Never assume the requested rate** |
| Device timestamp | `uint64`, nanosecond units, **1 ms resolution** (all values multiples of 10⁶). Epoch consistent with time since power-on |
| Duplicate-timestamp reports | Occasionally the device sends an extra pose report with the **same device timestamp** as the previous one, slightly different values, about 1 ms later in host time. Seen 0–2 times per 15 s at each rate. Flagged `ts_duplicate`, kept, and excluded by the gate |
| Device-side pause | One 297 ms gap in device timestamps when the glasses were picked up from the table (operator-confirmed; viewer run). A 13° orientation step followed. The SDK logged no error. Cause unknown (cable or connector movement? on-device filter?); to be reproduced deliberately in the bench run |
| Quaternion sign | SDK quaternions always have `w ≥ 0`, so the sign jumps when `w` passes 0 (3 times in a 30 s handled session) |
| Quaternion order | `[qw, qx, qy, qz]` after the 3 Euler values; norm 1 ± 2·10⁻⁷ |
| SDK Euler | Degrees (2.4.0 release notes). Rotation order undocumented and not identifiable from one static pose. SDK pitch read −168° (non-standard range). Not used for computation |
| Quaternion direction (head→world?) | Weak evidence only: gravity prediction 3.6° vs 9.2° off for the two readings. **Unverified: G0 bench test** |
| Raw mode | Gyro/accel/temperature; magnetometer fields zero on the Pro; units undocumented. About 342 Hz at 500 Hz requested (2 s probe). A few raw callbacks arrived after `start()` before pose mode was opened; in pose mode we count them via a count-only callback and never mix them in |
| Teardown | close → destroy takes about 1.0–1.9 s; runs on the acquisition thread |
| Single process | Windows allows one process per device (SDK 2.4.1). Close VITURE apps first |
| Logging | Log level 2 prints about 130 lines per session to stderr even with a hook. We use level 1 (errors) via the hook into `sdk_log.txt` |
| Callback thread | Pose callbacks arrive on one SDK thread, separate from the caller |

## Documentation inconsistencies found

- The demo README lists the Pro as Gen2. The Concepts and Head-Tracking pages and the runtime say **Gen1**.
- Quick Start says `VITURE_IMU_FREQUENCY_HIGH` gives "~500 Hz". Pose mode on the Pro does not support 500 Hz, and 240 Hz delivers about 202 Hz.
- The web page names the DLL `libglasses.dll`; the Windows bundle ships `glasses.dll`.
- **No recentering exists for Gen1 in the SDK.** The demo subtracts SDK yaw only; we implement the protocol's full `conj(q0) ⊗ q`.
- **The Web SDK delivers only the latest pose per animation frame and has no timestamp field.** It is unsuitable for logging.
