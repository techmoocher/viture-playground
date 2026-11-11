# Threats to validity (engineering observations for the research team)

These are recorded by the software side. They are not conclusions; investigating them is the research team's call.

| ID | Threat | Details and what Phase 1 does about it |
|---|---|---|
| TV1 | **Euler parameterisation dependence** | Euler sequences (and the rotation vector) differ from one another by bilinear second-order terms such as y·p, y·r and p·r, the same form as Model C's interaction terms. The parameterisation alone can shift effect from linear terms into apparent cross-axis interactions, especially when linear (asymmetric) coefficients are large. Euler interaction coefficients must **not** be read as anatomical coupling. Phase 1 preserves the full `q_WH` and `q_rel`, so alternative parameterisations (another Euler order, rotation-vector features) can be computed and compared before the model phase |
| TV2 | No torso reference | Head orientation relative to the tracking frame or neutral is not neck orientation relative to the torso. Torso motion cannot be distinguished (protocol §2.2) |
| TV3 | No magnetometer | No absolute heading on the Pro; yaw drift is expected but not yet measured under approved conditions |
| TV4 | Undocumented SDK fusion filter | Smoothing, latency and bias handling are unknown. The SDK Euler order is undocumented. The SDK keeps `w ≥ 0`, so its quaternion sign jumps (handled) |
| TV5 | Timestamp resolution | 1 ms device timestamps floor interval-jitter estimates; the sample instant they refer to is undocumented |
| TV6 | Relative latency only | Host-arrival latency is relative (no shared clock). With the native shim, arrival times exclude Python scheduling. Python-side processing latency after the drain, which matters for later command timing, is a separate quantity and is not yet measured |
| TV7 | Device irregularities | Occasional duplicate-timestamp reports, and one 297 ms device-side pause during handling. Flagged, never silently used; frequency and cause to be characterised |
| TV8 | Provisional parameters | All flag, gate and neutral thresholds are engineering defaults (see quality-and-metrics.md). `tau_stab_deg` is a placeholder (O6). Their values could affect which calibration attempts are accepted and should be frozen before comparative data collection |
