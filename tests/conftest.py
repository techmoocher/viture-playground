import dataclasses
import json
from pathlib import Path

import pytest

from headmusic.config import REPO_ROOT, load_config
from headmusic.orientation.processor import OrientationProcessor, ProcessorConfig

DATA = Path(__file__).parent / "data"
SDK_DIR = REPO_ROOT / "vendor" / "viture" / "windows_x86_64" / "bin"
INCLUDE_DIR = REPO_ROOT / "vendor" / "viture" / "windows_x86_64" / "include"
SHIM = REPO_ROOT / "native" / "build" / "capture_shim.dll"


def pytest_addoption(parser):
    parser.addoption("--hardware", action="store_true", help="run tests that need the connected VITURE glasses")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--hardware"):
        return
    skip = pytest.mark.skip(reason="needs glasses: run with --hardware")
    for item in items:
        if "hardware" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def cfg():
    return load_config()


@pytest.fixture
def make_processor(cfg):
    def make(measured_rate_hz=202.5, selected_hz=240, **overrides):
        pc = dataclasses.replace(ProcessorConfig.from_config(cfg), **overrides)
        p = OrientationProcessor(pc)
        p.configure_stream(selected_hz, measured_rate_hz)
        return p
    return make


def load_real_trace(name):
    doc = json.loads((DATA / f"real_trace_{name}.json").read_text())
    return [doc["device_ts_first"] + ms * 1_000_000 for ms in doc["device_ms_offsets"]]
