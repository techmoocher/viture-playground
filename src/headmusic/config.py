"""Configuration: provisional engineering defaults (defaults.toml) plus optional user overrides."""
from __future__ import annotations

import copy
import hashlib
import json
import tomllib
from pathlib import Path
from typing import Any, Optional

DEFAULTS_PATH = Path(__file__).with_name("defaults.toml")
REPO_ROOT = Path(__file__).resolve().parents[2]


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(override_path: Optional[Path] = None, overrides: Optional[dict] = None) -> dict[str, Any]:
    with DEFAULTS_PATH.open("rb") as f:
        cfg = tomllib.load(f)
    if override_path is not None:
        with Path(override_path).open("rb") as f:
            cfg = _merge(cfg, tomllib.load(f))
    if overrides:
        cfg = _merge(cfg, overrides)
    return cfg


def config_sha256(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def reference_rate_hz(cfg: dict, mode: str, selected_hz: int) -> Optional[float]:
    """Fixture-measured achieved rate for (mode, selected frequency), if characterised."""
    table = cfg.get("flags", {}).get("r_ref_hz", {}).get(mode, {})
    value = table.get(str(int(selected_hz)))
    return float(value) if value is not None else None
