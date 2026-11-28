"""The composite-video command: its views, the capture's timing and the panel layout."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import numpy as np
import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "python" / "scripts"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("composite_video", SCRIPTS / "composite_video.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


composite_video = _load()


def test_views_default_to_the_four_panels_in_reading_order() -> None:
    args = composite_video.parse_args(["--out", "x.mp4"])
    assert args.views == ["capture", "diagnostic", "mode13h", "modern"]


def test_an_unknown_view_is_refused() -> None:
    with pytest.raises(SystemExit):
        composite_video.parse_args(["--out", "x.mp4", "--views", "capture,sepia"])


def test_each_capture_frame_holds_until_the_next_and_the_first_starts_at_zero() -> None:
    assert composite_video.hold_seconds([14, 24, 35]) == [0.48, 0.22, 1.0]


def test_the_concat_listing_repeats_the_last_image() -> None:
    listing = composite_video.concat_listing(["a.png", "b.png"], [0.5, 1.0])
    assert listing.splitlines() == [
        "file 'a.png'",
        "duration 0.5000",
        "file 'b.png'",
        "duration 1.0000",
        "file 'b.png'",
    ]


def test_four_panels_lay_out_two_by_two() -> None:
    graph = composite_video.filter_graph(["A", "B", "C", "D"], 2, 2, 25, "font=Sans")
    assert "xstack=inputs=4:layout=0_0|640_0|0_400|640_400" in graph
    assert graph.endswith("[out]")


def test_a_label_colon_is_escaped_for_drawtext() -> None:
    graph = composite_video.filter_graph(["a:b"], 1, 1, 25, "font=Sans")
    assert r"text='a\:b'" in graph
    assert "xstack" not in graph
    assert graph.endswith("[out]")


def test_a_grid_is_scaled_whole_and_each_label_sits_in_its_panel() -> None:
    graph = composite_video.grid_filter(["A", "B", "C"], 2, 2, "font=Sans")
    assert graph.startswith("scale=1280:-1:flags=neighbor,setsar=1,")
    assert "text='B':x=648:y=8" in graph
    assert "text='C':x=8:y=408" in graph


def test_panels_lay_out_in_rows_and_the_last_row_is_padded() -> None:
    panels = [np.full((2, 3, 3), n, dtype=np.uint8) for n in (1, 2, 3)]
    grid = composite_video.lay_out(panels, 2)
    assert grid.shape == (4, 6, 3)
    assert [grid[0, 0, 0], grid[0, 3, 0], grid[2, 0, 0], grid[2, 3, 0]] == [1, 2, 3, 0]


def test_video_dir_needs_as_seen() -> None:
    with pytest.raises(SystemExit):
        composite_video.parse_args(["--out", "x.mp4", "--video-dir", "d"])
    args = composite_video.parse_args(["--out", "x.mp4", "--as-seen", "--video-dir", "d"])
    assert args.as_seen
