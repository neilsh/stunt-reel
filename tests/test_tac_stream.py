"""Offline tests for the stream log encoder: refusals, the round trip and the sidecar (synthetic)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest

from stunt_reel.tac import stream
from stunt_reel.tac.stream import StreamError

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg encodes the stream"
)

HEADER = "[F:00014 T:00:00:00.016] debugmsg: h0e4fc435db2585f1:patch3:1"
TRAILER = "[F:00016 T:00:00:00.200] debugmsg: exhold"
NOISE = "[F:00015 T:00:00:00.150] dosbox.mem_read(0x0e66, 0x20ee, 768)"
AFTER = [
    "[F:00016 T:00:00:00.201] dosbox.capture_stop()",
    "[F:00016 T:00:00:00.202] script completed: ok",
]
FIRST = 14


def pictures(seed: int = 7, count: int = 3) -> np.ndarray:
    """Random palette indices, ``(count, 192, 320)``, from a seeded generator."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, (count, stream.HEIGHT, stream.WIDTH), dtype=np.uint8)


def p_line(frame: int, flags: int, indices: np.ndarray, hexpart: str | None = None) -> str:
    payload = indices.tobytes().hex() if hexpart is None else hexpart
    return f"[F:{frame:05d} T:00:00:00.000] debugmsg: p{frame}:{flags}:{payload}"


def good_lines(data: np.ndarray, flags: tuple[int, ...] = (0, 2, 3)) -> list[str]:
    lines = ["# lua debug log: unnamed", HEADER]
    for index, indices in enumerate(data):
        lines.append(NOISE)
        lines.append(p_line(FIRST + index, flags[index], indices))
    lines.append(TRAILER)
    lines += AFTER
    return lines


def write_log(directory: Path, lines: list[str]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "stream.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def refused(path: Path) -> str:
    """The StreamError message of reading *path* to its end."""
    with pytest.raises(StreamError) as error:
        list(stream.read_stream(path))
    return str(error.value)


def test_a_good_log_reads_back_its_pictures(tmp_path: Path) -> None:
    data = pictures()
    path = write_log(tmp_path, good_lines(data))
    frames = list(stream.read_stream(path))
    assert [f.frame for f in frames] == [FIRST, FIRST + 1, FIRST + 2]
    assert [f.flags for f in frames] == [0, 2, 3]
    assert [f.indices for f in frames] == [d.tobytes() for d in data]


def test_a_log_without_a_header_is_refused(tmp_path: Path) -> None:
    lines = [line for line in good_lines(pictures()) if line != HEADER]
    assert "before the header" in refused(write_log(tmp_path, lines))


def test_a_log_with_only_a_header_and_trailer_is_refused(tmp_path: Path) -> None:
    path = write_log(tmp_path, [HEADER, TRAILER, *AFTER])
    assert "no frame lines" in refused(path)


def test_a_gap_in_the_frame_numbers_is_refused(tmp_path: Path) -> None:
    data = pictures()
    lines = good_lines(data)
    lines[lines.index(p_line(FIRST + 1, 2, data[1]))] = p_line(FIRST + 2, 2, data[1])
    assert "follows frame" in refused(write_log(tmp_path, lines))


def test_a_short_hex_payload_is_refused(tmp_path: Path) -> None:
    data = pictures()
    lines = good_lines(data)
    short = data[1].tobytes().hex()[:-2]
    lines[lines.index(p_line(FIRST + 1, 2, data[1]))] = p_line(FIRST + 1, 2, data[1], short)
    assert "hex characters" in refused(write_log(tmp_path, lines))


def test_a_hex_payload_with_a_non_hex_character_is_refused(tmp_path: Path) -> None:
    data = pictures()
    lines = good_lines(data)
    bad = "g" + data[0].tobytes().hex()[1:]
    lines[lines.index(p_line(FIRST, 0, data[0]))] = p_line(FIRST, 0, data[0], bad)
    assert "outside [0-9a-f]" in refused(write_log(tmp_path, lines))


def test_flags_outside_zero_to_three_are_refused(tmp_path: Path) -> None:
    data = pictures()
    lines = good_lines(data)
    lines[lines.index(p_line(FIRST, 0, data[0]))] = p_line(FIRST, 4, data[0])
    assert "outside 0..3" in refused(write_log(tmp_path, lines))


def test_a_log_without_a_trailer_is_refused(tmp_path: Path) -> None:
    lines = [line for line in good_lines(pictures()) if line != TRAILER]
    assert "no e<hold|capped> trailer" in refused(write_log(tmp_path, lines))


def test_a_trailer_before_a_later_frame_is_refused(tmp_path: Path) -> None:
    data = pictures()
    lines = good_lines(data)
    lines.insert(lines.index(NOISE) + 2, TRAILER)  # after frame 0, before frames 1 and 2
    assert "after the trailer" in refused(write_log(tmp_path, lines))


def test_an_empty_log_has_no_header_and_is_refused(tmp_path: Path) -> None:
    assert "no header line" in refused(write_log(tmp_path, []))


def test_a_missing_ffmpeg_is_refused_before_anything_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    path = write_log(tmp_path / "run", good_lines(pictures()))
    with pytest.raises(StreamError, match="ffmpeg is not on PATH"):
        stream.encode_stream(path, tmp_path / "run")
    assert path.exists()
    assert not (tmp_path / "run" / stream.MKV_NAME).exists()


@needs_ffmpeg
def test_the_round_trip_is_lossless_and_the_sidecar_records_it(tmp_path: Path) -> None:
    data = pictures()
    run = tmp_path / "run"
    log = write_log(run, good_lines(data))
    info = stream.encode_stream(log, run)

    decoded = list(stream.decode_stream(run / stream.MKV_NAME))
    assert len(decoded) == len(data)
    for got, want in zip(decoded, data, strict=True):
        assert got.shape == (stream.HEIGHT, stream.WIDTH)
        assert np.array_equal(got, want)

    raw = b"".join(d.tobytes() for d in data)
    document = json.loads((run / stream.JSON_NAME).read_text(encoding="utf-8"))
    assert document == {
        "schema_version": 1,
        "kind": "stream",
        "file": "stream.mkv",
        "sha256_raw": hashlib.sha256(raw).hexdigest(),
        "sha256_file": hashlib.sha256((run / stream.MKV_NAME).read_bytes()).hexdigest(),
        "frames": 3,
        "first_frame": FIRST,
        "width": 320,
        "height": 192,
        "flags": {"0": 1, "1": 0, "2": 1, "3": 1},
        "held": [FIRST],
        "layout": "patch3",
        "end": "hold",
    }
    assert info.frames == 3
    assert info.sha256_raw == document["sha256_raw"]
    assert info.sha256_file == document["sha256_file"]
    assert info.flags == {0: 1, 1: 0, 2: 1, 3: 1}
    assert log.exists()


@needs_ffmpeg
def test_delete_log_removes_the_log_only_after_a_passing_round_trip(tmp_path: Path) -> None:
    run = tmp_path / "run"
    log = write_log(run, good_lines(pictures()))
    stream.encode_stream(log, run, delete_log=True)
    assert not log.exists()
    assert (run / stream.JSON_NAME).exists()


@needs_ffmpeg
def test_a_refused_log_is_kept_by_delete_log_and_leaves_no_mkv(tmp_path: Path) -> None:
    run = tmp_path / "run"
    lines = [line for line in good_lines(pictures()) if line != TRAILER]
    log = write_log(run, lines)
    with pytest.raises(StreamError, match=r"no e<hold\|capped> trailer"):
        stream.encode_stream(log, run, delete_log=True)
    assert log.exists()
    assert not (run / stream.MKV_NAME).exists()
    assert not (run / stream.JSON_NAME).exists()


@needs_ffmpeg
def test_capped_end_is_accepted_and_recorded(tmp_path: Path) -> None:
    run = tmp_path / "run"
    lines = [line.replace("exhold", "excapped") for line in good_lines(pictures())]
    info = stream.encode_stream(write_log(run, lines), run)
    assert info.end == "capped"


def test_decode_refuses_when_ffmpeg_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    with pytest.raises(StreamError):
        next(stream.decode_stream(tmp_path / stream.MKV_NAME))


@needs_ffmpeg
def test_a_refused_rerun_leaves_an_earlier_encode_intact(tmp_path: Path) -> None:
    run = tmp_path / "run"
    log = write_log(run, good_lines(pictures()))
    stream.encode_stream(log, run)
    before = {name: (run / name).read_bytes() for name in (stream.MKV_NAME, stream.JSON_NAME)}
    write_log(run, [line for line in good_lines(pictures()) if line != TRAILER])
    with pytest.raises(StreamError):
        stream.encode_stream(log, run)
    assert before == {name: (run / name).read_bytes() for name in before}
    assert not list(run.glob("*.part"))


def test_a_second_header_is_refused(tmp_path: Path) -> None:
    lines = good_lines(pictures())
    lines.insert(-3, HEADER)
    assert refused(write_log(tmp_path, lines))


def test_a_second_trailer_is_refused(tmp_path: Path) -> None:
    lines = good_lines(pictures())
    lines.insert(-2, TRAILER)
    assert refused(write_log(tmp_path, lines))


def test_a_malformed_trailer_is_refused(tmp_path: Path) -> None:
    lines = [line.replace("exhold", "exfoo") for line in good_lines(pictures())]
    assert refused(write_log(tmp_path, lines))


@needs_ffmpeg
def test_a_round_trip_mismatch_is_refused_and_leaves_no_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = tmp_path / "run"
    log = write_log(run, good_lines(pictures()))
    monkeypatch.setattr(
        stream, "decode_stream", lambda _path: iter([np.zeros((192, 320), dtype=np.uint8)])
    )
    with pytest.raises(StreamError):
        stream.encode_stream(log, run)
    assert log.exists()
    assert not (run / stream.MKV_NAME).exists()
    assert not (run / stream.JSON_NAME).exists()
    assert not list(run.glob("*.part"))


def test_the_cli_exits_two_on_a_refused_log_and_on_a_missing_one(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location(
        "stream_encode", Path(__file__).parents[1] / "python" / "scripts" / "stream_encode.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["stream_encode"] = module
    spec.loader.exec_module(module)
    assert module.main([str(tmp_path)]) == 2
    write_log(tmp_path, ["junk"])
    assert module.main([str(tmp_path)]) == 2
