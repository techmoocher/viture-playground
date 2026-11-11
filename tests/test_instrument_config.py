"""Regions, the region coordinate and instrument configuration (2A-1, 2A-6, 2A-8)."""
import json

import pytest

from headmusic.cli import main
from headmusic.config import load_config
from headmusic.instrument.regions import ConfigError, InstrumentConfig, yaw_elevation_deg
from headmusic.orientation.euler import quat_from_zyx, zyx_from_quat


@pytest.mark.parametrize("yaw", [-170.0, -45.0, -13.0, 0.0, 7.5, 31.0, 120.0])
@pytest.mark.parametrize("pitch", [-60.0, -10.0, 0.0, 25.0])
@pytest.mark.parametrize("roll", [-30.0, 0.0, 15.0])
def test_region_coordinate_equals_display_yaw_and_ignores_tilt(yaw, pitch, roll):
    q = quat_from_zyx(yaw, pitch, roll)
    y, e = yaw_elevation_deg(q)
    assert y == pytest.approx(zyx_from_quat(q)[0], abs=1e-9)
    assert y == pytest.approx(yaw, abs=1e-9)
    assert e == pytest.approx(-pitch, abs=1e-9)  # + elevation = nose up; + pitch = nose down


def test_turn_left_is_positive_yaw():
    assert yaw_elevation_deg(quat_from_zyx(20.0, 0, 0))[0] > 0  # conventions.md: +yaw = turn left


def test_defaults_load_and_validate():
    ic = InstrumentConfig.from_config(load_config())
    assert [r.chord for r in ic.regions] == ["C", "G", "Am", "F"]
    meta = ic.to_meta()
    assert meta["dwell_ms"] == 500.0 and "provisional" in meta and len(meta["mapping_version"]) == 16


def _cfg(**ic_overrides):
    cfg = load_config()
    cfg["instrument"] = {**cfg["instrument"], **ic_overrides}
    return cfg


@pytest.mark.parametrize("regions, msg", [
    ([], "at least one"),
    ([{"chord": "C", "yaw_min_deg": 10, "yaw_max_deg": 20}, {"chord": "C", "yaw_min_deg": 30, "yaw_max_deg": 40}],
     "exactly one"),
    ([{"chord": "C", "yaw_min_deg": 3, "yaw_max_deg": 20}], "neutral zone"),
    ([{"chord": "C", "yaw_min_deg": 20, "yaw_max_deg": 10}], "yaw_min_deg < yaw_max_deg"),
    ([{"chord": "C", "yaw_min_deg": 10, "yaw_max_deg": 20}, {"chord": "G", "yaw_min_deg": 21, "yaw_max_deg": 30}],
     "apart"),
])
def test_invalid_regions_are_rejected(regions, msg):
    with pytest.raises(ConfigError, match=msg):
        InstrumentConfig.from_config(_cfg(yaw_regions=regions))


@pytest.mark.parametrize("key, value", [("dwell_ms", 0.0), ("hysteresis_deg", -1.0), ("max_elevation_deg", 95.0),
                                        ("cooldown_ms", float("nan"))])
def test_invalid_parameters_are_rejected(key, value):
    with pytest.raises(ConfigError):
        InstrumentConfig.from_config(_cfg(**{key: value}))


def test_missing_key_is_reported():
    cfg = load_config()
    del cfg["instrument"]["dwell_ms"]
    with pytest.raises(ConfigError, match="dwell_ms"):
        InstrumentConfig.from_config(cfg)


def test_synth_and_replay_cli_roundtrip(tmp_path, capsys):
    s = tmp_path / "s"
    assert main(["synth", "chords", "--instrument", "--out", str(s)]) == 0
    assert "instrument commits: ['C', 'G', 'Am', 'F']" in capsys.readouterr().out
    meta = json.loads((s / "session.json").read_text())
    assert meta["instrument"]["regions"][0]["chord"] == "C"
    assert main(["replay", str(s), "--reprocess", "--instrument", "--out", str(tmp_path / "r")]) == 0
    assert "interaction_events.jsonl identical to the original: True" in capsys.readouterr().out


def test_small_yaw_profile_is_valid_and_smaller():
    from headmusic.config import REPO_ROOT
    cfg = load_config(REPO_ROOT / "config" / "profiles" / "small_yaw.toml")
    ic = InstrumentConfig.from_config(cfg)
    assert [r.chord for r in ic.regions] == ["C", "G", "Am", "F"]
    assert max(max(abs(r.yaw_min_deg), abs(r.yaw_max_deg)) for r in ic.regions) == 24.0
    assert ic.dwell_ms == 500.0  # only the geometry changes
