"""Offline tests for `python/scripts/parity_frame.py` (synthetic data only)."""

from __future__ import annotations

import json
import struct
import sys
import zlib
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import parity_frame  # noqa: E402
import parity_probe  # noqa: E402

from render_helpers import TINY, write_store  # noqa: E402
from stunt_reel import parity_pipeline  # noqa: E402
from stunt_reel.parity_artifacts import (  # noqa: E402
    CapturedFrame,
    CaptureSet,
    FilmId,
    read_capture,
)


def _png_rows(path: Path) -> tuple[int, list[bytes]]:
    """Width and the unfiltered RGB rows of a PNG written with filter 0."""
    data = path.read_bytes()
    width = struct.unpack(">I", data[16:20])[0]
    height = struct.unpack(">I", data[20:24])[0]
    start = data.index(b"IDAT") + 4
    length = struct.unpack(">I", data[start - 8 : start - 4])[0]
    raw = zlib.decompress(data[start : start + length])
    stride = 1 + width * 3
    return width, [raw[y * stride + 1 : (y + 1) * stride] for y in range(height)]


def _capture_set(ticks: list[int]) -> CaptureSet:
    frames = tuple(
        CapturedFrame(ordinal=i + 1, film_tick=t, frame_file=f"f{i}.idx", palette_file=f"p{i}.json")
        for i, t in enumerate(ticks)
    )
    return CaptureSet(
        schema_version=1,
        film=FilmId(),
        geometry=TINY,
        frames=frames,
    )


def test_parse_ticks_sorts_dedups_and_accepts_one_tick() -> None:
    assert parity_frame.parse_ticks("92, 48,92,1009") == [48, 92, 1009]
    assert parity_frame.parse_ticks("1009") == [1009]


@pytest.mark.parametrize("text", ["", "4x", "-3", "1,,2"])
def test_parse_ticks_refuses_junk(text: str) -> None:
    with pytest.raises(ValueError, match="tick"):
        parity_frame.parse_ticks(text)


def test_parse_box_reads_four_edges() -> None:
    assert parity_frame.parse_box("10,20,110,120") == (10, 20, 110, 120)
    with pytest.raises(ValueError, match="x0,y0,x1,y1"):
        parity_frame.parse_box("1,2,3")


def test_locate_maps_ticks_to_ordinals_and_names_neighbours_of_the_rest() -> None:
    capture = _capture_set([10, 12, 20])
    found, missing = parity_frame.locate(capture, [12, 15, 3, 99])
    assert found == {12: 2}
    assert missing == {15: (12, 20), 3: (None, 10), 99: (20, None)}


def test_render_film_with_ticks_asks_the_binary_once_for_the_exact_list(tmp_path: Path) -> None:
    root = tmp_path
    film = parity_pipeline.FILMS["ctry"]
    calls: list[list[str]] = []
    parity_pipeline.render_film(
        "ctry", root, tmp_path / "out", ticks=[48, 92], run=lambda cmd, _env: calls.append(cmd)
    )
    (cmd,) = calls
    assert cmd[cmd.index("--at-ticks") + 1] == "48,92"
    assert "--frames" not in cmd
    assert cmd[cmd.index("--sidata") + 1] == str(root / film.sidata)


def test_side_by_side_puts_the_capture_left_of_ours(tmp_path: Path) -> None:
    reference = tmp_path / "ref"
    reference.mkdir()
    pixels = TINY.width * TINY.height
    (reference / "f.idx").write_bytes(bytes([1] * pixels))
    (reference / "p.json").write_text(json.dumps([[i, i, 0] for i in range(256)]), encoding="utf-8")
    (reference / "meta.json").write_text(
        json.dumps(
            {
                "frames": [
                    {"ordinal": 1, "film_tick": 5, "frame_file": "f.idx", "palette_file": "p.json"}
                ]
            }
        ),
        encoding="utf-8",
    )
    ours = tmp_path / "ours"
    write_store(ours, [5], geometry=TINY)
    out = tmp_path / "side.png"
    parity_probe.make_side_by_side(
        reference, ours, read_capture(reference).frames[0].ordinal, 5, (0, 0, 4, 2), 1, out
    )
    width, rows = _png_rows(out)
    assert (width, len(rows)) == (4 + 2 + 4, 2)
    assert rows[0][:3] == bytes([1, 1, 0])  # the capture's index 1 is on the left
    assert rows[0][4 * 3 : 6 * 3] == bytes([255, 0, 255] * 2)  # the magenta divider
    # Our tick 5 holds indices 5, 6, 7, 8 on row 0 (render_helpers.frame_for).
    assert rows[0][6 * 3 :] == bytes([5, 5, 0, 6, 6, 0, 7, 7, 0, 8, 8, 0])


def test_missing_tick_says_whether_it_was_rendered() -> None:
    assert parity_frame.describe_missing(1010, (1009, 1020), rendered=True) == (
        "tick 1010: not in the capture (nearest captured: 1009, 1020)"
    )
    assert parity_frame.describe_missing(99999, (3822, None), rendered=False) == (
        "tick 99999: past the film's end, not rendered (last captured: 3822)"
    )
    assert parity_frame.describe_missing(7, (None, None), rendered=False) == (
        "tick 7: past the film's end, not rendered"
    )


@pytest.mark.parametrize(
    ("box", "scale", "message"),
    [
        ((-1, 0, 4, 2), 1, "outside"),
        ((0, 0, 4, 3), 1, "outside"),
        ((2, 0, 2, 2), 1, "outside"),
        ((0, 0, 4, 2), 0, "--scale"),
    ],
)
def test_crop_outside_the_raster_or_bad_scale_is_refused(
    box: tuple[int, int, int, int], scale: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        parity_frame.check_crop(box, scale, width=4, height=2)


def test_crop_inside_the_raster_is_accepted() -> None:
    parity_frame.check_crop((0, 1, 4, 2), 2, width=4, height=2)


def test_clear_previous_removes_only_this_films_pictures(tmp_path: Path) -> None:
    for name in ("intro_48.png", "intro_1009.png", "ctry_48.png", "notes.txt"):
        (tmp_path / name).write_bytes(b"x")
    parity_frame.clear_previous(tmp_path, "intro")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["ctry_48.png", "notes.txt"]
