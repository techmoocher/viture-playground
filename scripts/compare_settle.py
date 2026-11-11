"""Synthetic comparison of settle settings (dwell_ms, dwell_stability_deg) with the direct FSM (Driver, 200 Hz).

For each setting:
- crossed keys that sound on an F -> C traverse (crosses Am, neutral, G) at several constant speeds;
- onset: time from the cursor stopping on C to C sounding (arriving at 60 deg/s);
- onset with per-sample yaw noise (sigma 0.3 / 0.6 deg, white, seed-fixed) while holding still: a crude stand-in
  for sway, which is unmeasured (O3).
Synthetic outcome only, not a measurement with people (docs/mvp-iteration-2.md §8).
Run from the repo root: .venv/Scripts/python scripts/compare_settle.py
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from instrument_helpers import DT_NS, YAW, Driver  # noqa: E402

SPEEDS = [10, 15, 20, 25, 30, 45, 60, 120, 240]
SETTINGS = [(0, 0), (60, 2.0), (80, 1.5), (80, 2.0), (80, 3.0), (100, 2.0), (120, 2.0), (150, 3.0), (500, 3.0)]


def drv(dwell, stab):
    return Driver(transitions="direct", dwell_ms=float(dwell), dwell_stability_deg=float(stab),
                  neutral_rest_release_ms=0.0, cooldown_ms=0.0)


def crossed(dwell, stab, speed):
    d = drv(dwell, stab)
    d.arm()
    d.move(0.0, YAW["F"], 150)
    d.hold(YAW["F"], 700)
    n0 = len(d.commits())
    d.move(YAW["F"], YAW["C"], 1000 * (YAW["C"] - YAW["F"]) / speed)
    d.hold(YAW["C"], 600)
    got = d.commits()[n0:]
    return len([c for c in got if c != "C"]), "C" in got


def onset(dwell, stab, sigma=0.0, seed=0):
    d = drv(dwell, stab)
    d.arm()
    d.move(0.0, YAW["F"], 150)
    d.hold(YAW["F"], 700)
    d.move(YAW["F"], YAW["C"], 1000 * (YAW["C"] - YAW["F"]) / 60.0)
    rng = random.Random(seed)
    for k in range(400):  # up to 2 s
        if "C" in d.commits():
            return k * DT_NS / 1e6
        d.sample(YAW["C"] + rng.gauss(0.0, sigma))
    return float("inf")


def med(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2]


print("| dwell / stability | crossed keys sounding at " + " / ".join(str(s) for s in SPEEDS) +
      " °/s | onset after stop | onset, noise σ 0.3° (median of 20) | σ 0.6° (median of 20) |")
print("|---|---|---|---|---|")
for dwell, stab in SETTINGS:
    cr = [crossed(dwell, stab, s)[0] for s in SPEEDS]
    o = onset(dwell, stab)
    o3 = med([onset(dwell, stab, 0.3, k) for k in range(20)])
    o6 = med([onset(dwell, stab, 0.6, k) for k in range(20)])
    label = "immediate" if dwell == 0 else f"{dwell} ms / {stab:g}°"
    fmt = lambda v: f"{v:.0f} ms" if v != float("inf") else "never (2 s)"  # noqa: E731
    print(f"| {label} | {' / '.join(map(str, cr))} | {fmt(o) if dwell else 'on entry'} | "
          f"{fmt(o3) if dwell else 'on entry'} | {fmt(o6) if dwell else 'on entry'} |")
