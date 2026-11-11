"""File round trips: bit-exact raw values, schema, crash tolerance."""
import math
import random
import struct

from headmusic.acquisition import synthetic as SY
from headmusic.recording import schema as S
from headmusic.recording.reader import iter_processed, iter_raw_imu, iter_raw_pose, load_meta, read_jsonl
from headmusic.recording.writer import SessionWriter, processed_row
from headmusic.types import Command, Event, RawImuSample


def bits(x):
    return struct.pack("<f", x)


def test_float32_text_round_trip_is_bit_exact():
    rng = random.Random(7)
    for _ in range(20000):
        x = struct.unpack("<f", struct.pack("<I", rng.getrandbits(32)))[0]
        if math.isnan(x):
            continue
        assert bits(S.to_f32(S.fmt_f32(x))) == bits(x)
    for x in (0.0, -0.0, math.inf, -math.inf, 1e-45, 3.4028234663852886e38):
        assert bits(S.to_f32(S.fmt_f32(x))) == bits(x)
    assert math.isnan(S.to_f32(S.fmt_f32(math.nan)))


def test_session_round_trip(tmp_path, make_processor):
    tr = SY.scenario_faults()
    w = SessionWriter(tmp_path / "s", {"schema_version": S.SCHEMA_VERSION}, write_raw_imu=True)
    proc = make_processor()
    processed = []
    for s in tr.samples:
        w.write_raw_pose(s)
        p, _ = proc.process(s)
        w.write_processed(p)
        processed.append(p)
    imu = RawImuSample(0, 1, 5, 6, 7, tuple(SY.f32(v) for v in (0.1, -0.2, 0.3, 0.14, 0.0, -0.98, 0, 0, 0, 25.0)))
    w.write_raw_imu(imu)
    w.write_command(Command("segment_start", 1, {"label": "x"}, after_seq=3))
    w.write_event(Event("device_connected", 2, {"connection_id": 1}), last_seq=-1)
    w.write_event(Event("sdk_log", 3, {"level": 1, "tag": "libglasses", "message": "hello"}), last_seq=-1)
    w.close(extra={"done": True})
    back = list(iter_raw_pose(tmp_path / "s" / "raw_pose.csv"))
    assert len(back) == len(tr.samples)
    for a, b in zip(tr.samples, back):
        assert a.seq == b.seq and a.device_ts_raw == b.device_ts_raw and a.host_rx_monotonic_ns == b.host_rx_monotonic_ns
        assert [bits(x) for x in a.values] == [bits(x) for x in b.values] or any(math.isnan(x) for x in a.values)
    assert list(iter_processed(tmp_path / "s" / "processed_pose.csv")) == processed
    assert list(iter_raw_imu(tmp_path / "s" / "raw_imu.csv")) == [imu]
    meta = load_meta(tmp_path / "s")
    assert meta["extra"] == {"done": True} and meta["files"]["row_counts"]["raw_pose"] == len(tr.samples)
    assert read_jsonl(tmp_path / "s" / "commands.jsonl")[0]["after_seq"] == 3
    assert "hello" in (tmp_path / "s" / "sdk_log.txt").read_text()
    assert [e["kind"] for e in read_jsonl(tmp_path / "s" / "events.jsonl")] == ["device_connected"]


def test_truncated_files_are_readable(tmp_path):
    s = SY.generate(1.0)
    w = SessionWriter(tmp_path / "s", {})
    for x in s:
        w.write_raw_pose(x)
    w.write_event(Event("device_connected", 1, {}), -1)
    w.close()
    raw = tmp_path / "s" / "raw_pose.csv"
    text = raw.read_text()
    raw.write_text(text[: len(text) - 25])  # simulate a crash mid-row
    back = list(iter_raw_pose(raw))
    assert len(back) == len(s) - 1
    ev = tmp_path / "s" / "events.jsonl"
    ev.write_text(ev.read_text() + '{"kind": "trunc')
    assert len(read_jsonl(ev)) == 1


def test_processed_columns_match_schema(make_processor):
    p, _ = make_processor().process(SY.generate(0.01)[0])
    assert len(processed_row(p)) == len(S.PROCESSED_COLUMNS)
