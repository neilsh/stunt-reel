"""Offline tests for the stream checks of the video capture: pages, replay, pairing and the CLI.

The streams are synthetic: each test encodes a log of seeded palette indices with
``stunt_reel.tac.stream.encode_stream``, so ffmpeg is needed wherever a test encodes or decodes one.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from dataclasses import replace
from pathlib import Path
lazy from types import ModuleType

import numpy as np
import pytest

from stunt_reel import video_check
from stunt_reel.parity_artifacts import (
    VIDEO_FILE,
    CapturedFrame,
    CaptureSet,
    Geometry,
    PaletteChange,
    PaletteLog,
    VideoCapture,
    load_video_capture,
    write_capture,
)
from stunt_reel.tac import stream
from stunt_reel.video_check import StreamPageMatch, StreamRun, VideoCheckError

FIXTURES = Path(__file__).parent / "fixtures" / "parity" / "video"
needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg decodes the stream"
)

FIRST = 100
HEADER = "[F:00099 T:00:00:00.016] debugmsg: h0e4fc435db2585f1:patch3:1"
TRAILER = "[F:00112 T:00:00:00.200] debugmsg: exhold"
INITIAL = np.random.default_rng(11).integers(0, 256, (256, 3), dtype=np.uint8)


def pictures(count: int, seed: int = 3) -> list[np.ndarray]:
    """Seeded random palette-index pictures, ``(192, 320)`` each."""
    rng = np.random.default_rng(seed)
    return [
        rng.integers(0, 256, (stream.HEIGHT, stream.WIDTH), dtype=np.uint8) for _ in range(count)
    ]


def write_recording(directory: Path, data: list[np.ndarray], flags: list[int]) -> Path:
    """Encode a log of *data* (frame ``FIRST + n``, flags ``flags[n]``) into *directory*."""
    directory.mkdir(parents=True, exist_ok=True)
    lines = ["# lua debug log: unnamed", HEADER]
    for n, (picture, flag) in enumerate(zip(data, flags, strict=True)):
        payload = picture.tobytes().hex()
        lines.append(f"[F:{FIRST + n:05d} T:00:00:00.000] debugmsg: p{FIRST + n}:{flag}:{payload}")
    lines.append(TRAILER)
    log = directory / "stream.log"
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    stream.encode_stream(log, directory)
    return directory


def write_reference(directory: Path, pages: list[tuple[int, np.ndarray, np.ndarray]]) -> Path:
    """A pinned reference of ``(emu_frame, indices, palette)`` pages, as ``read_capture`` reads it."""
    reference = directory / "reference"
    reference.mkdir(parents=True)
    frames = tuple(
        CapturedFrame(ordinal=i + 1, film_tick=i, frame_file=f"{i}.idx", palette_file=f"{i}.json")
        for i in range(len(pages))
    )
    film = load_video_capture(FIXTURES / "with-slots").film
    capture = CaptureSet(1, film, Geometry(width=stream.WIDTH, height=stream.HEIGHT), frames)
    write_capture(reference, capture, frame_diagnostics=[{"emu_frame": emu} for emu, _, _ in pages])
    for i, (_, indices, palette) in enumerate(pages):
        indices.tofile(reference / f"{i}.idx")
        (reference / f"{i}.json").write_text(json.dumps(palette.tolist()), encoding="utf-8")
    return reference


def capture_with(palettes: PaletteLog) -> VideoCapture:
    """The with-slots fixture, with its palette history replaced."""
    return replace(load_video_capture(FIXTURES / "with-slots"), palettes=palettes)


def initial_palette(changes: tuple[PaletteChange, ...] = ()) -> PaletteLog:
    return PaletteLog(initial=tuple(map(tuple, INITIAL.tolist())), changes=changes)


@needs_ffmpeg
def test_a_page_matches_the_stream_at_offset_zero_and_at_plus_one(tmp_path: Path) -> None:
    data = pictures(12)
    recording = write_recording(tmp_path / "rec", data, [2] * 12)
    reference = write_reference(
        tmp_path,
        [(104, data[4], INITIAL), (106, data[7], INITIAL)],
    )
    matches, skipped = video_check.stream_page_matches(
        recording, capture_with(initial_palette()), reference, search=2
    )
    assert skipped == 0
    assert [(m.emu_frame, m.offset, m.differing_pixels) for m in matches] == [
        (104, 0, 0),
        (106, 1, 0),
    ]
    assert all(m.palette_equal and not m.on_held for m in matches)


@needs_ffmpeg
def test_a_page_on_a_held_frame_is_flagged(tmp_path: Path) -> None:
    data = pictures(12)
    flags = [2] * 12
    flags[105 - FIRST] = 0
    recording = write_recording(tmp_path / "rec", data, flags)
    reference = write_reference(
        tmp_path,
        [(104, data[4], INITIAL), (105, data[5], INITIAL)],
    )
    matches, _ = video_check.stream_page_matches(
        recording, capture_with(initial_palette()), reference, search=2
    )
    assert [(m.emu_frame, m.offset, m.on_held) for m in matches] == [
        (104, 0, False),
        (105, 0, True),
    ]


@needs_ffmpeg
def test_palette_equal_follows_the_working_palette_at_the_matched_frame(tmp_path: Path) -> None:
    data = pictures(12)
    recording = write_recording(tmp_path / "rec", data, [2] * 12)
    changed = INITIAL.copy()
    changed[5] = (1, 2, 3)
    change = PaletteChange(frame=106, first=5, rgb=((1, 2, 3),))
    reference = write_reference(
        tmp_path,
        [(104, data[4], INITIAL), (108, data[8], changed), (108, data[8], INITIAL)],
    )
    matches, _ = video_check.stream_page_matches(
        recording, capture_with(initial_palette((change,))), reference, search=2
    )
    assert [m.palette_equal for m in matches] == [True, True, False]


@needs_ffmpeg
def test_a_page_whose_window_leaves_the_stream_is_skipped(tmp_path: Path) -> None:
    data = pictures(12)
    recording = write_recording(tmp_path / "rec", data, [2] * 12)
    reference = write_reference(
        tmp_path,
        [(100, data[0], INITIAL), (104, data[4], INITIAL)],
    )
    matches, skipped = video_check.stream_page_matches(
        recording, capture_with(initial_palette()), reference, search=2
    )
    assert skipped == 1
    assert [m.emu_frame for m in matches] == [104]
    check = video_check.summarise_stream(matches, skipped)
    assert (check.pages, check.skipped, check.offsets) == (2, 1, {"0": 1})
    assert (check.exact_pages, check.on_held_pages, check.palette_equal_pages) == (1, 0, 1)


def test_the_stream_summary_counts_offsets_exact_held_and_palette_pages() -> None:
    matches = [
        StreamPageMatch(1, 10, 0, 0, False, True),
        StreamPageMatch(2, 20, -1, 7, True, False),
        StreamPageMatch(3, 30, -1, 0, False, True),
    ]
    check = video_check.summarise_stream(matches, 2)
    assert check.pages == 5
    assert check.offsets == {"-1": 2, "0": 1}
    assert (check.exact_pages, check.on_held_pages, check.palette_equal_pages) == (2, 1, 2)


def test_the_working_palette_applies_each_write_at_or_before_the_frame() -> None:
    palettes = initial_palette(
        (
            PaletteChange(frame=5, first=0, rgb=((9, 9, 9), (8, 8, 8))),
            PaletteChange(9, 1, ((7, 7, 7),)),
        )
    )
    assert video_check.working_palette(palettes, 4).tolist() == INITIAL.tolist()
    at_five = video_check.working_palette(palettes, 5)
    assert at_five[0].tolist() == [9, 9, 9]
    assert at_five[1].tolist() == [8, 8, 8]
    assert video_check.working_palette(palettes, 9)[1].tolist() == [7, 7, 7]


@needs_ffmpeg
def test_load_stream_decodes_the_pictures_and_refuses_a_missing_or_short_stream(
    tmp_path: Path,
) -> None:
    data = pictures(3)
    recording = write_recording(tmp_path / "rec", data, [2, 0, 2])
    loaded = video_check.load_stream(recording)
    assert loaded.first_frame == FIRST
    assert loaded.held == frozenset({FIRST + 1})
    assert loaded.picture(FIRST + 2).tobytes() == data[2].tobytes()
    with pytest.raises(VideoCheckError, match="holds no picture"):
        loaded.picture(FIRST + 3)
    with pytest.raises(VideoCheckError, match=r"no stream\.json"):
        video_check.load_stream(tmp_path / "empty")
    document = json.loads((recording / stream.JSON_NAME).read_text(encoding="utf-8"))
    document["frames"] = 4
    (recording / stream.JSON_NAME).write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(VideoCheckError, match="decodes to 3 pictures"):
        video_check.load_stream(recording)


@pytest.fixture
def recordings(tmp_path: Path) -> tuple[Path, Path]:
    made = []
    for name in ("first", "second"):
        directory = tmp_path / name
        shutil.copytree(
            FIXTURES / "with-slots", directory, ignore=shutil.ignore_patterns("derived*")
        )
        (directory / VIDEO_FILE).write_bytes(b"one recording")
        made.append(directory)
    return made[0], made[1]


def write_stream_json(directory: Path, sha: str, frames: int) -> None:
    (directory / stream.JSON_NAME).write_text(
        json.dumps({"sha256_raw": sha, "frames": frames}), encoding="utf-8"
    )


def test_replay_compares_the_streams_when_both_recordings_hold_one(
    recordings: tuple[Path, Path],
) -> None:
    first, second = recordings
    write_stream_json(first, "aa", 5)
    write_stream_json(second, "aa", 5)
    replay = video_check.replay_report(first, second)
    assert replay.stream_identical is True
    assert replay.identical


def test_a_differing_stream_makes_the_recordings_differ(recordings: tuple[Path, Path]) -> None:
    first, second = recordings
    write_stream_json(first, "aa", 5)
    write_stream_json(second, "bb", 5)
    replay = video_check.replay_report(first, second)
    assert replay.stream_identical is False
    assert replay.video_identical
    assert replay.meta_identical
    assert not replay.identical


def test_a_stream_missing_from_one_recording_leaves_the_replay_unchanged(
    recordings: tuple[Path, Path],
) -> None:
    first, second = recordings
    write_stream_json(first, "aa", 5)
    replay = video_check.replay_report(first, second)
    assert replay.stream_identical is None
    assert replay.identical


@needs_ffmpeg
def test_pairing_with_a_stream_drops_held_rows_and_keys_by_index_bytes(tmp_path: Path) -> None:
    # Rows 1, 3, 5, 7 and 9 end a run. The palette write at frame 102 (row 2) puts row 3 in its lag
    # window and changes entry 7, which every picture holds: rows 5 and 9 show other colours for
    # the same indices as row 1, so only index bytes agree across it. Row 7 (frame 107) is held and
    # its picture differs, so it is compared only if it is not dropped.
    shared = np.zeros((stream.HEIGHT, stream.WIDTH), dtype=np.uint8)
    shared[0, 0] = 7
    data = [shared] * 12
    data[7] = pictures(1, seed=5)[0]
    run = StreamRun(
        first_frame=FIRST,
        held=frozenset({FIRST + 7}),
        pictures={FIRST + n: picture for n, picture in enumerate(data)},
    )
    capture = load_video_capture(FIXTURES / "with-slots")
    palettes = initial_palette((PaletteChange(frame=102, first=7, rgb=((1, 2, 3),)),))
    capture = replace(
        capture,
        geometry=replace(capture.geometry, width=stream.WIDTH, height=stream.HEIGHT),
        log=replace(
            capture.log,
            frame=tuple(FIRST + n for n in range(12)),
            film_tick=tuple(range(12)),
            global_tick=tuple(range(12)),
            slot_clock=tuple(i // 2 for i in range(12)),
            slot_ticks=(0,) * 12,
        ),
        palettes=palettes,
    )
    # No AVI in the directory: with a stream the video is not read.
    check = video_check.pairing_check(tmp_path, capture, (0,) * 12, stream=run)
    assert check.held_dropped == 1
    assert check.compared == 3
    assert check.by_render_tick.shared == 1
    assert check.by_render_tick.conflicting == 0


def load_video_derive() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "video_derive", Path(__file__).parents[1] / "python" / "scripts" / "video_derive.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["video_derive"] = module
    spec.loader.exec_module(module)
    return module


def test_the_cli_takes_the_stream_flag_on_reference_check_and_pairing(tmp_path: Path) -> None:
    script = load_video_derive()
    assert script.parse_args(["reference-check", "ctry", "--stream"]).stream is True
    assert script.parse_args(["reference-check", "ctry"]).stream is False
    args = script.parse_args(["pairing", "--dir", str(tmp_path), "--stream"])
    assert args.stream is True
    assert script.parse_args(["pairing", "--dir", str(tmp_path)]).stream is False


def test_replay_prints_the_stream_line_only_when_both_recordings_have_one(
    recordings: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    script = load_video_derive()
    first, second = recordings
    assert script.run_replay(first, second) == 0
    assert "stream: not compared" in capsys.readouterr().out
    write_stream_json(first, "aa", 5)
    write_stream_json(second, "bb", 5)
    assert script.run_replay(first, second) == 1
    assert "stream hashes identical: False" in capsys.readouterr().out
