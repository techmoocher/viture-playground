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
| `headmusic check-placement` | ~15 s of streaming, nothing recorded: tilt from upright and how still the glasses are, checked before every bench recording |
| `headmusic record --duration 60 --mounting fixture --stationary --capture-neutral-at 2` | Headless recording plus report |
| `headmusic view [--record] [--script r6a\|r6b\|r6c]` | Live yaw/pitch/roll, tilt from upright (placement aid), neutral capture (`N`), segment marks, tracking-gate status; `--script` runs a guided bench script (Space for every action) |
| `headmusic replay <session> --reprocess` | Offline reprocessing; checks byte-identity with the live output |
| `headmusic replay <session> --view [--speed 1]` | Replay into the viewer, no glasses needed |
| `headmusic analyze <session> [--stationary]` | Timing, jitter and drift report, plus per-segment net rotation for the bench checks (`analysis/report.md`) |
| `headmusic export <session>` | Denormalised per-row export with protocol §10 fields |
| `headmusic synth <scenario>` | Deterministic synthetic session: stationary, faults, reconnect, sign_flip, yaw_wrap, dropped, sustained_loss, chords |
| `headmusic synth chords --instrument` | Phase 2: synthetic chord tour through the gesture FSM, with interaction logs |
| `headmusic replay <session> --reprocess --instrument` | Phase 2: re-run the gesture FSM and chord engine offline; checks both logs are byte-identical |
| `headmusic replay <session> --instrument --speed 1` | Phase 2: real-time replay through the instrument with sound (Windows MIDI) |
| `headmusic play` | Phase 2: live four-chord instrument with the play window (Esc = emergency stop); hardware runs need the operator's approval, worn use waits for O3 |
| `headmusic replay <session> --instrument --view --speed 1` | Phase 2: replay through the instrument with the play window and sound |
| `headmusic midi-devices` / `headmusic midi-test` | Phase 2: list MIDI outputs / play C, G, Am, F once (sound check, no glasses) |

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
| [instrument.md](docs/instrument.md) | Phase 2 gesture state machine: regions, states, resets, logs |
| [play.md](docs/play.md) | Phase 2 play window, keys, emergency stop, `headmusic play` |
| [music.md](docs/music.md) | Phase 2 chord engine: MIDI, interruptions, panic, accompaniment, logs |
| [phase2-proposal.md](docs/phase2-proposal.md) | Phase 2 design and milestones 2A–2D |
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
