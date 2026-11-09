"""The capture-compare command: pairing by film tick, page and palette counts, unpaired runs."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

lazy import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "python" / "scripts"
PAGE = 320 * 200


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("capture_compare", SCRIPTS / "capture_compare.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


capture_compare = _load()


def _capture(
    directory: Path,
    pages: dict[int, int],
    *,
    palette_shift: set[int] | None = None,
    archive: str = "a" * 64,
) -> Path:
    """A capture whose page at each tick has its first *pages[tick]* pixels set to 1."""
    frames_dir = directory / "frames"
    frames_dir.mkdir(parents=True)
    frames = []
    for ordinal, (tick, set_pixels) in enumerate(sorted(pages.items()), start=1):
        frame = f"frames/tick_{ordinal:04d}.idx"
        palette = f"frames/palettes_{ordinal:04d}.json"
        (directory / frame).write_bytes(b"\x01" * set_pixels + b"\x00" * (PAGE - set_pixels))
        shift = 1 if palette_shift and tick in palette_shift else 0
        colours = [[i % 64, shift, 0] for i in range(256)]
        (directory / palette).write_text(json.dumps(colours), encoding="utf-8")
        frames.append(
            {"ordinal": ordinal, "film_tick": tick, "frame_file": frame, "palette_file": palette}
        )
    meta = {
        "schema_version": 1,
        "film": "TOD.FLM",
        "all_sha256": archive,
        "frames": frames,
        "width": 320,
        "height": 200,
        "playone_build": "unpatched",
    }
    (directory / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return directory


def test_nearest_rank_takes_the_smallest_value_with_q_at_or_below() -> None:
    values = [5, 1, 4, 2, 3, 10, 9, 8, 7, 6]
    assert capture_compare.nearest_rank(values, 0.5) == 5
    assert capture_compare.nearest_rank(values, 0.9) == 9
    assert capture_compare.nearest_rank([7], 0.9) == 7


def test_pages_pair_only_on_an_exact_tick(tmp_path: Path) -> None:
    a = _capture(tmp_path / "a", dict.fromkeys(range(0, 300, 10), 0))
    b = _capture(tmp_path / "b", dict.fromkeys(range(3, 300, 10), 0) | {100: 0, 110: 0})
    result = capture_compare.compare(a, b)
    assert result.shared == 2
    assert not result.paired
    assert "unpaired: 2 shared film ticks" in capture_compare.report(result)


def test_counts_identical_pages_differing_pixels_and_palettes(tmp_path: Path) -> None:
    ticks = range(0, 250, 10)  # 25 ticks
    a = _capture(tmp_path / "a", dict.fromkeys(ticks, 0))
    b = _capture(
        tmp_path / "b",
        {tick: (tick // 10 if tick >= 200 else 0) for tick in ticks},
        palette_shift={0, 10},
        archive="b" * 64,
    )
    result = capture_compare.compare(a, b)
    assert result.paired
    assert (result.shared, result.identical, result.palettes_equal) == (25, 20, 23)
    assert result.differing[-5:] == (20, 21, 22, 23, 24)
    text = capture_compare.report(result)
    assert "identical pages: 20 of 25" in text
    assert "differing pixels: median 0, 90th percentile 22" in text
    assert "palettes equal: 23 of 25" in text
    assert "archive bbbbbbbbbbbb, PLAYONE unpatched" in text


def test_a_tick_captured_twice_keeps_its_first_page(tmp_path: Path) -> None:
    a = _capture(tmp_path / "a", dict.fromkeys(range(0, 200, 10), 0))
    meta_path = a / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    extra = dict(meta["frames"][0], ordinal=len(meta["frames"]) + 1, frame_file="frames/x.idx")
    (a / "frames" / "x.idx").write_bytes(b"\x02" * PAGE)
    meta["frames"].append(extra)
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    b = _capture(tmp_path / "b", dict.fromkeys(range(0, 200, 10), 0))
    assert capture_compare.compare(a, b).identical == 20


def test_main_exits_3_when_unpaired_and_1_on_a_missing_capture(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a = _capture(tmp_path / "a", {0: 0})
    b = _capture(tmp_path / "b", {0: 0})
    assert capture_compare.main([str(a), str(b)]) == 3
    assert capture_compare.main([str(a), str(tmp_path / "none")]) == 1
    assert "capture-compare:" in capsys.readouterr().err


def _shifted_pair(tmp_path: Path) -> tuple[Path, Path]:
    """25 ticks of distinct pages; B draws A's tick 50 at 51 and A's 100 at 99, and differs at 150."""
    pages_a = {tick: tick + 1 for tick in range(0, 250, 10)}
    pages_b = dict(pages_a)
    pages_b[51] = pages_b.pop(50)
    pages_b[99] = pages_a[100]
    pages_b[100] = 999
    pages_b[150] = 7777
    return _capture(tmp_path / "a", pages_a), _capture(tmp_path / "b", pages_b)


def test_shift_matches_a_page_drawn_at_a_neighbouring_tick(tmp_path: Path) -> None:
    a, b = _shifted_pair(tmp_path)
    shift = capture_compare.compare(a, b, shift=2).shift
    assert shift is not None
    assert (shift.differing, shift.differing_matched) == (2, 1)
    assert (shift.only_a, shift.only_a_matched) == ((50,), 1)
    assert shift.only_b == (51, 99)
    assert shift.offsets == {-1: 1, 1: 1}
    assert shift.unmatched == (capture_compare.Unmatched(150, 7626, (0, 319, 0, 24)),)


def test_shift_report_lines(tmp_path: Path) -> None:
    a, b = _shifted_pair(tmp_path)
    text = capture_compare.report(capture_compare.compare(a, b, shift=2))
    assert (
        "shift ±2: 2 of 3 A pages with no identical B page at their tick match a B page "
        "within 2 ticks (differing pages 1 of 2, ticks only in A 1 of 1)"
    ) in text
    assert "offsets (B tick minus A tick): -1: 1, +1: 1" in text
    assert "film ticks only in A: 50; only in B: 51, 99" in text
    assert "no match: tick 150 (7626 differing pixels, columns 0-319, rows 0-24)" in text


def test_shift_too_small_to_reach_leaves_pages_unmatched(tmp_path: Path) -> None:
    pages_a = {tick: tick + 1 for tick in range(0, 250, 10)}
    pages_b = dict(pages_a)
    pages_b[53] = pages_b.pop(50)
    a, b = _capture(tmp_path / "a", pages_a), _capture(tmp_path / "b", pages_b)
    shift = capture_compare.compare(a, b, shift=2).shift
    assert shift is not None
    assert shift.only_a_matched == 0
    assert shift.unmatched == (capture_compare.Unmatched(50, None, None),)
    assert "no match: tick 50 (no B page)" in capture_compare.report(
        capture_compare.compare(a, b, shift=2)
    )


def test_no_shift_prints_what_it_printed_before(tmp_path: Path) -> None:
    a, b = _shifted_pair(tmp_path)
    result = capture_compare.compare(a, b)
    assert result.shift is None
    assert "shift ±" not in capture_compare.report(result)
    with pytest.raises(SystemExit):
        capture_compare.main([str(a), str(b), "--shift", "-1"])
