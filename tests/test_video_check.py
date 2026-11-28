"""Offline tests for the video capture checks: reference check, replay and pairing (synthetic)."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from stunt_reel import video_check
from stunt_reel.parity_artifacts import (
    VIDEO_FILE,
    CapturedFrame,
    CaptureSet,
    Geometry,
    VideoCapture,
    derive_columns,
    load_video_capture,
    write_capture,
)

FIXTURES = Path(__file__).parent / "fixtures" / "parity" / "video"
SYNTHETIC_AVI = FIXTURES / "synthetic.avi"
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg decodes the AVI")


def frame(seed: int) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 256, (6, 4, 3), dtype=np.uint8)


def test_the_best_offset_is_the_frame_that_matches() -> None:
    decoded = {index: frame(index) for index in range(10)}
    assert video_check.best_offset(decoded, 5, decoded[4], (0, 6), 3) == (-1, 0)
    assert video_check.best_offset(decoded, 5, decoded[7], (0, 6), 3) == (2, 0)


def test_a_tie_goes_to_the_offset_nearest_zero() -> None:
    same = frame(1)
    decoded = dict.fromkeys(range(10), same)
    assert video_check.best_offset(decoded, 5, same, (0, 6), 3) == (0, 0)
    decoded[5] = frame(2)
    assert video_check.best_offset(decoded, 5, same, (0, 6), 3) == (-1, 0)


def test_the_differing_pixels_are_counted_over_the_rows_asked_for() -> None:
    shown = frame(1)
    other = shown.copy()
    other[5, 0] ^= 0xFF
    decoded = dict.fromkeys(range(3), other)
    assert video_check.best_offset(decoded, 1, shown[:5], (0, 5), 1)[1] == 0
    assert video_check.best_offset(decoded, 1, shown, (0, 6), 1)[1] == 1


def matches() -> list[video_check.PageMatch]:
    return [
        video_check.PageMatch(1, 10, 0, 1.0, 0, "exact"),
        video_check.PageMatch(2, 20, -1, 0.9, 40, "band"),
        video_check.PageMatch(3, 30, -1, 0.99, 4, "split"),
    ]


def test_the_summary_counts_offsets_pages_and_exact_pages() -> None:
    check = video_check.summarise(matches(), 2, digest="ab" * 32)
    assert check.pages == 5
    assert check.skipped == 2
    assert check.offsets == {"-1": 2, "0": 1}
    assert check.pixel_equal.min == pytest.approx(0.9)
    assert check.pixel_equal.median == pytest.approx(0.99)
    assert (check.exact_pages, check.split_pages, check.band_pages) == (1, 1, 1)


def test_a_summary_of_no_pages_is_empty() -> None:
    check = video_check.summarise([], 0, digest="ab" * 32)
    assert (check.pages, check.exact_pages, check.offsets) == (0, 0, {})


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


def test_two_identical_recordings_replay_identically(recordings: tuple[Path, Path]) -> None:
    replay = video_check.replay_report(*recordings)
    assert replay.identical
    assert replay.differing == {}


def test_a_differing_avi_or_log_is_reported(recordings: tuple[Path, Path]) -> None:
    first, second = recordings
    (second / VIDEO_FILE).write_bytes(b"another recording")
    meta = (second / "meta.json").read_text(encoding="utf-8")
    (second / "meta.json").write_text(
        meta.replace("5,\n   5,\n   6,\n   7", "5,\n   5,\n   6,\n   8"), "utf-8"
    )
    replay = video_check.replay_report(first, second)
    assert not replay.video_identical
    assert not replay.meta_identical
    assert replay.differing == {"log.slot_clock": 3}


def test_a_page_is_exact_split_or_band() -> None:
    top, bottom = frame(1), frame(2)
    both = np.concatenate([top[:3], bottom[3:]])
    decoded = {index: top if index < 5 else bottom for index in range(-4, 12)}
    window = (0, 6)
    assert video_check.classify_page(decoded, 4, top, window, 0) == "exact"
    assert video_check.classify_page(decoded, 4, both, window, 12) == "split"
    stray = both.copy()
    stray[4] ^= 0xFF
    assert video_check.classify_page(decoded, 4, stray, window, 12) == "band"


def test_a_page_pairs_with_the_log_row_of_its_frame() -> None:
    capture = load_video_capture(FIXTURES / "with-slots")
    assert video_check._paired_index(capture, 103) == 2
    assert video_check._paired_index(capture, 100) is None


def test_run_ends_mark_the_frame_before_a_clock_change() -> None:
    capture = load_video_capture(FIXTURES / "with-slots")
    assert video_check.run_ends(capture) == (False, True, True, False)


def test_key_groups_find_a_key_that_names_two_pictures() -> None:
    groups = video_check._groups([1, 1, 2, 3, 3], [b"a", b"a", b"b", b"c", b"d"])
    assert (groups.shared, groups.conflicting, groups.conflicting_frames) == (2, 1, 2)


@needs_ffmpeg
def test_the_synthetic_avi_decodes_to_its_documented_frames() -> None:
    frames = list(video_check.iter_video_frames(SYNTHETIC_AVI, 64, 48))
    assert len(frames) == 12
    for n in (0, 5, 11):
        x, y = 10, 20
        # The fixture's formula is in B, G, R order.
        expected = [((x + y + n * 7) * 2) & 255, (y * 5) & 255, (x * 4 + n * 3) & 255]
        assert frames[n][y, x].tolist() == expected
        assert frames[n][4 + 2 * n, 4 + 3 * n].tolist() == [255, 255, 255]


@needs_ffmpeg
def test_decode_frames_keeps_only_the_frames_asked_for() -> None:
    held = video_check.decode_frames(SYNTHETIC_AVI, 64, 48, {2, 7, 40})
    assert sorted(held) == [2, 7]


@needs_ffmpeg
def test_pairing_without_a_render_groups_run_ends_by_key(tmp_path: Path) -> None:
    shutil.copy(SYNTHETIC_AVI, tmp_path / VIDEO_FILE)
    capture = load_video_capture(FIXTURES / "with-slots")
    capture = replace(
        capture,
        geometry=replace(capture.geometry, width=64, height=48),
        log=replace(
            capture.log,
            frame=tuple(range(101, 113)),
            film_tick=tuple(range(12)),
            global_tick=tuple(range(12)),
            slot_clock=tuple(i // 2 for i in range(12)),
            slot_ticks=(0,) * 12,
        ),
        palettes=replace(capture.palettes, changes=()),
    )
    ticks = tuple(range(12))
    clean = video_check.pairing_check(tmp_path, capture, ticks, rows=(0, 47))
    assert clean.compared == 5
    assert clean.by_render_tick.shared == 0
    merged = video_check.pairing_check(tmp_path, capture, (0,) * 12, rows=(0, 47))
    assert merged.by_render_tick.shared == 1
    assert merged.by_render_tick.conflicting == 1
    assert merged.by_render_tick.conflicting_frames == 5


def test_page_matches_pairs_classifies_and_rejects_a_narrow_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = load_video_capture(FIXTURES / "with-slots")
    capture = replace(capture, capture_start_frame=100, video_frames=60)
    palette = np.random.default_rng(7).integers(0, 256, (256, 3), dtype=np.uint8)
    pages = [np.array([[1, 2, 3, 4], [5, 6, 7, 8]], dtype=np.uint8) + 10 * i for i in range(3)]
    rgb = [palette[page] for page in pages]
    emu = (120, 130, 140)
    base = [e - 101 for e in emu]
    decoded: dict[int, np.ndarray] = {
        k: np.random.default_rng(k).integers(0, 256, (2, 4, 3), dtype=np.uint8) for k in range(60)
    }
    decoded[base[0] + 1] = rgb[0]
    decoded[base[1]] = np.concatenate([rgb[1][:1], decoded[base[1]][1:]])
    decoded[base[1] + 2] = np.concatenate([decoded[base[1] + 2][:1], rgb[1][1:]])
    monkeypatch.setattr(video_check, "decode_frames", lambda *_args: decoded)
    reference = tmp_path / "reference"
    reference.mkdir()
    frames = tuple(
        CapturedFrame(ordinal=i + 1, film_tick=i, frame_file=f"{i}.idx", palette_file="p.json")
        for i in range(3)
    )
    write_capture(
        reference,
        CaptureSet(1, capture.film, Geometry(width=4, height=2), frames),
        frame_diagnostics=[{"emu_frame": e} for e in emu],
    )
    (reference / "p.json").write_text(json.dumps(palette.tolist()), encoding="utf-8")
    for i, page in enumerate(pages):
        page.tofile(reference / f"{i}.idx")
    matches, skipped = video_check.page_matches(tmp_path, capture, reference, rows=(0, 1), search=4)
    assert skipped == 0
    assert [m.kind for m in matches] == ["exact", "split", "band"]
    assert [m.offset for m in matches[:2]] == [1, 0]
    with pytest.raises(ValueError, match="search"):
        video_check.page_matches(tmp_path, capture, reference, search=3)


def _twelve_row_capture(rows: int = 12) -> VideoCapture:
    """The ``with-slots`` capture re-logged to *rows* rows of the 64x48 synthetic AVI."""
    capture = load_video_capture(FIXTURES / "with-slots")
    return replace(
        capture,
        geometry=replace(capture.geometry, width=64, height=48),
        log=replace(
            capture.log,
            frame=tuple(range(101, 101 + rows)),
            film_tick=tuple(range(10, 10 + rows)),
            global_tick=tuple(range(rows)),
            slot_clock=tuple(i // 2 for i in range(rows)),
            slot_ticks=(0,) * rows,
        ),
        palettes=replace(capture.palettes, changes=()),
    )


@needs_ffmpeg
def test_every_frame_comes_with_its_clocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shutil.copy(SYNTHETIC_AVI, tmp_path / VIDEO_FILE)
    capture = _twelve_row_capture()
    monkeypatch.setattr(video_check, "load_video_capture", lambda _directory: capture)
    frames = list(video_check.iter_capture_frames(tmp_path))
    assert [f.index for f in frames] == list(range(12))
    assert [f.emu_frame for f in frames] == list(range(101, 113))
    assert [f.film_tick for f in frames] == list(range(10, 22))
    assert frames[3].rgb.shape == (48, 64, 3)
    expected = derive_columns(capture)[1].render_tick
    assert tuple(f.render_tick for f in frames) == expected


@needs_ffmpeg
def test_a_log_and_an_avi_of_different_lengths_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shutil.copy(SYNTHETIC_AVI, tmp_path / VIDEO_FILE)
    for rows in (11, 13):
        capture = _twelve_row_capture(rows)
        monkeypatch.setattr(video_check, "load_video_capture", lambda _d, c=capture: c)
        with pytest.raises(video_check.VideoCheckError):
            list(video_check.iter_capture_frames(tmp_path))
