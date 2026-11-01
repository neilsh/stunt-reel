"""The numpy SSIM reproduces the Rust scorer on the synthetic bench fixture."""

from __future__ import annotations

import json
import shutil
from typing import TYPE_CHECKING

import numpy as np
import pytest

from stunt_reel.bench.planes import BenchError, RenderTree, load_capture
from stunt_reel.bench.ssim import frame_ssim, stretch
from stunt_reel.parity_artifacts import RENDER_INDEX_FILE, RENDER_LAYER_FILE

if TYPE_CHECKING:
    from pathlib import Path


def test_numpy_ssim_matches_the_rust_golden(bench_fixture: Path) -> None:
    golden = json.loads((bench_fixture / "golden.json").read_text(encoding="utf-8"))["ssim"]
    capture = load_capture(bench_fixture / "capture")
    tree = RenderTree(bench_fixture / "render")
    for tick in (10, 20):
        assert abs(frame_ssim(capture[tick], tree.load(tick).rgb) - golden[str(tick)]) < 1e-4


def test_identical_frames_score_one(bench_fixture: Path) -> None:
    capture = load_capture(bench_fixture / "capture")[10]
    rgb = capture.palette[capture.idx]
    assert abs(frame_ssim(capture, rgb) - 1.0) < 1e-9


def test_a_render_from_before_the_store_names_a_rerender(
    tmp_path: Path, bench_fixture: Path
) -> None:
    shutil.copytree(bench_fixture / "render", tmp_path / "r")
    record = tmp_path / "r" / "render.json"
    document = json.loads(record.read_text(encoding="utf-8"))
    document["schema_version"] = 1
    record.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(BenchError, match="re-render"):
        RenderTree(tmp_path / "r").load(10)


def test_stretch_repeats_every_fifth_row() -> None:
    plane = np.arange(200, dtype=np.float64)[:, None].repeat(320, axis=1)
    out = stretch(plane)
    assert out.shape == (240, 320)
    assert out[:7, 0].tolist() == [0, 0, 1, 2, 3, 4, 5]


@pytest.mark.parametrize("name", [RENDER_INDEX_FILE, RENDER_LAYER_FILE])
def test_a_render_with_a_truncated_plane_file_is_refused(
    tmp_path: Path, bench_fixture: Path, name: str
) -> None:
    render = tmp_path / "render"
    shutil.copytree(bench_fixture / "render", render)
    (render / name).write_bytes(b"\x00\x00")
    with pytest.raises(BenchError, match="chunks end at"):
        RenderTree(render).load(10)


def test_a_truncated_capture_plane_is_refused(tmp_path: Path, bench_fixture: Path) -> None:
    capture = tmp_path / "capture"
    shutil.copytree(bench_fixture / "capture", capture)
    (capture / "tick_0001.idx").write_bytes(b"\x00")
    with pytest.raises(BenchError, match="holds 1 bytes"):
        load_capture(capture)


def test_a_render_trees_picture_is_its_palette_over_its_index_plane(bench_fixture: Path) -> None:
    tree = RenderTree(bench_fixture / "render")
    assert tree.ticks() == [10, 20]
    planes = tree.load(10)
    palette = np.frombuffer(tree.stored(10).palette, dtype=np.uint8).reshape(256, 3)
    assert planes.idx is not None
    assert np.array_equal(planes.rgb, palette[planes.idx])
