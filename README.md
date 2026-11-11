# headmusic — Phase 1 hardware foundation

Head-orientation acquisition for a research prototype of a head-controlled music instrument on
**VITURE Pro XR** glasses (Gen1, 3DoF). Phase 1 covers only the hardware data pipeline:
- connect through the official SDK;
- acquire timestamped quaternions;
- neutral capture and recentering;
- live view;
- record raw and processed data;
- timing, jitter and drift metrics;
- deterministic replay without glasses.

There is no musical interface, no experiment and no comfort model here.

> Head orientation here is the orientation of the glasses relative to the SDK tracking frame or to a
> neutral reference. It is **not** neck or cervical orientation relative to the torso.

Design and decisions: [docs/phase1-proposal.md](docs/phase1-proposal.md).
Research protocol: [docs/research/](docs/research/).

## Setup (Windows 11 x86_64)

1. **SDK** (proprietary, never committed). Put `VITURE_XR_Glasses_SDK_for_Windows_x86_64.zip` (v2.4.2) in `sdk/`, then:
   ```bash
   python scripts/setup_sdk.py
   ```
   This extracts `glasses.dll` and the headers into `vendor/viture/` and records SHA-256 hashes.
2. **Capture shim** (native C; MinGW-w64 in WSL). One-time, inside WSL:
   ```bash
   sudo apt install gcc-mingw-w64-x86-64
   ```
   Then build, from the repository root in Windows:
   ```bash
   wsl sh native/build_shim.sh
   ```
   The output is `native/build/capture_shim.dll` plus `BUILDINFO.txt` (compiler and hashes).
3. **Python ≥ 3.11:**
   ```bash
   python -m venv .venv
   ```
   ```bash
   .venv\Scripts\python -m pip install -e ".[dev]"
   ```
   The only runtime dependency is `numpy`. The viewer uses `tkinter` from the standard library.
4. Close VITURE's own apps: on Windows only one process can open the glasses.

## Commands

| Command | Purpose |
|---|---|
| `headmusic devices` | List glasses and SDK frequency support |
| `headmusic info` | Identity and firmware (no streaming) |
| `headmusic record --duration 60 --mounting fixture --stationary --capture-neutral-at 2` | Headless recording plus report |
| `headmusic view [--record]` | Live yaw/pitch/roll, tilt from upright (placement aid), neutral capture (`N`), segment marks, tracking-gate status |
| `headmusic replay <session> --reprocess` | Offline reprocessing; checks byte-identity with the live output |
| `headmusic replay <session> --view [--speed 1]` | Replay into the viewer, no glasses needed |
| `headmusic analyze <session> [--stationary]` | Timing, jitter and drift report (`analysis/report.md`) |
| `headmusic export <session>` | Denormalised per-row export with protocol §10 fields |
| `headmusic synth <scenario>` | Deterministic synthetic session: stationary, faults, reconnect, sign_flip, yaw_wrap, dropped, sustained_loss |

Sessions are written to `data/sessions/` (git-ignored). Run commands with `.venv\Scripts\python -m headmusic …`
or `.venv\Scripts\headmusic …`.

## Tests

```bash
.venv\Scripts\python -m pytest
```

Unit tests need no glasses. Hardware tests are opt-in; run them only with the glasses connected and the run agreed:
```bash
.venv\Scripts\python -m pytest --hardware tests/hardware
```

## Documentation

| Document | Content |
|---|---|
| [conventions.md](docs/conventions.md) | Frames, quaternions, Euler conversion, signs, units, clocks |
| [quality-and-metrics.md](docs/quality-and-metrics.md) | Sample flags, tracking gate, neutral capture, metric definitions, provisional parameters |
| [data-format.md](docs/data-format.md) | Session files, columns, mapping to protocol §10, export |
| [sdk-notes.md](docs/sdk-notes.md) | Verified SDK and device behaviour vs the documentation |
| [bench-checklist.md](docs/bench-checklist.md) | G0 bench procedure (run with the operator) |
| [bench-report.md](docs/bench-report.md) | Results so far (preliminary) |
| [threats-to-validity.md](docs/threats-to-validity.md) | Engineering observations for the research team |

## Layout

```
src/headmusic/   types · config · orientation/ · tracking/ · recording/ · metrics/ · acquisition/ · pipeline · viewer/ · cli
native/          capture_shim.c, build_shim.sh
scripts/         setup_sdk.py
tests/           unit tests (no hardware); tests/hardware (opt-in)
docs/            documentation; docs/research/ protocol
```

Only `headmusic.acquisition` touches ctypes, the SDK or hardware (enforced by `tests/test_architecture.py`).
