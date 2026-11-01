"""The error readout: categories, sheets, grades, readouts, comparisons and calibration."""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pytest

from stunt_reel.bench.errors import (
    FilmWindow,
    add_example,
    build_sheet,
    idx_digest,
    load_categories,
    pick_ticks,
    plan_sheets,
    render_brief,
    sheet_id,
)
from stunt_reel.bench.planes import BenchError, RenderTree, load_capture
from stunt_reel.parity_artifacts import FrameReport, I6Gate, Report

REPO = Path(__file__).resolve().parents[1]
CATEGORIES = REPO / "research" / "parity" / "error-categories.toml"

TWO_CATEGORIES = """\
# a comment
[[category]]
id = "a"
definition = "first"
examples = []

[[category]]
id = "b"
definition = "second"
examples = ["x"]

[faults]
"actors_removed" = ["a"]

[films.ctry]
start = 0
end = 990

[readout]
min_change = 2
"""


def _write(tmp_path: Path, text: str) -> Path:
    examples = tmp_path / "error-examples"
    examples.mkdir(exist_ok=True)
    (examples / "x.png").write_bytes(b"")
    (examples / "y.png").write_bytes(b"")
    path = tmp_path / "categories.toml"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def test_committed_categories_load() -> None:
    taxonomy = load_categories(CATEGORIES)
    assert len(taxonomy.categories) == 15
    assert taxonomy.ids[0] == "aircraft-parts-missing"
    assert taxonomy.ids[-1] == "explosion-missing"
    assert taxonomy.films["intro"] == FilmWindow(1000, None)
    assert taxonomy.films["ctry"] == FilmWindow(0, 990)
    assert taxonomy.min_change == 2
    assert len(taxonomy.digest) == 64


def test_film_window_end_is_exclusive() -> None:
    window = FilmWindow(10, 20)
    assert window.holds(10)
    assert not window.holds(20)
    assert FilmWindow(10, None).holds(10**9)


def test_digest_ignores_examples(tmp_path: Path) -> None:
    path = _write(tmp_path, TWO_CATEGORIES)
    before = load_categories(path).digest
    add_example(path, "a", "y")
    assert load_categories(path).digest == before
    path.write_text(
        path.read_text(encoding="utf-8").replace('"first"', '"first, changed"'),
        encoding="utf-8",
        newline="\n",
    )
    assert load_categories(path).digest != before


@pytest.mark.parametrize(
    ("old", "new", "named"),
    [
        ('id = "b"', 'id = "a"', '"a"'),
        ('"actors_removed" = ["a"]', '"wobble:3" = ["a"]', "wobble:3"),
        ('"actors_removed" = ["a"]', '"actors_removed" = ["no-such-category"]', "no-such-category"),
        ('examples = ["x"]', 'examples = ["ctry-0001"]', "ctry-0001"),
    ],
)
def test_rejects_bad_files(tmp_path: Path, old: str, new: str, named: str) -> None:
    path = _write(tmp_path, TWO_CATEGORIES.replace(old, new))
    with pytest.raises(BenchError, match=named.strip('"')):
        load_categories(path)


def test_add_example_edits_one_block(tmp_path: Path) -> None:
    path = _write(tmp_path, TWO_CATEGORIES)
    add_example(path, "b", "y")
    text = path.read_text(encoding="utf-8")
    assert text == TWO_CATEGORIES.replace('examples = ["x"]', 'examples = ["x", "y"]')
    add_example(path, "b", "y")
    assert path.read_text(encoding="utf-8") == text
    with pytest.raises(BenchError, match="zzz"):
        add_example(path, "zzz", "y")


def test_committed_file_copy_takes_an_example(tmp_path: Path) -> None:
    path = tmp_path / "error-categories.toml"
    shutil.copy(CATEGORIES, path)
    shutil.copytree(CATEGORIES.parent / "error-examples", tmp_path / "error-examples")
    add_example(path, "aircraft-too-small", "ctry-0004")
    assert load_categories(path).categories[2].examples == ("ctry-0004",)


def _report(frames: list[FrameReport]) -> Report:
    return Report(
        per_frame=tuple(frames),
        reference_frames=len(frames),
        frames=len(frames),
        mean_ssim_scored=0.9,
        mean_iou_scored=0.0,
        i6_gate=I6Gate(),
        scored_frames=len(frames),
    )


def test_pick_ticks_spreads_and_filters() -> None:
    frames = [
        FrameReport(
            film_tick=t,
            ssim=0.9,
            iou=0.0,
            fade_level=0.5 if 40 <= t < 50 else None,
            scored=t != 50,
        )
        for t in range(100)
    ]
    report = _report(frames)
    held = set(range(100))
    ticks = pick_ticks(report, held, FilmWindow(10, 90))
    assert len(ticks) == 12
    assert ticks == sorted(ticks)
    assert ticks[0] == 10
    assert all(10 <= t < 90 and not 40 <= t <= 50 for t in ticks)
    assert ticks == pick_ticks(report, held, FilmWindow(10, 90))
    assert pick_ticks(report, {20, 30}, FilmWindow(10, 90)) == [20, 30]
    assert pick_ticks(report, held, FilmWindow(200, None)) == []


def test_sheet_id_is_stable_and_distinct() -> None:
    base = sheet_id(1, "planted", "shift_y:4", 10)
    assert base == sheet_id(1, "planted", "shift_y:4", 10)
    assert len(base) == 12
    assert int(base, 16) >= 0
    others = {
        sheet_id(2, "planted", "shift_y:4", 10),
        sheet_id(1, "real", None, 10),
        sheet_id(1, "planted", "advance:5", 10),
        sheet_id(1, "planted", "shift_y:4", 20),
    }
    assert base not in others
    assert len(others) == 4


def test_plan_sheets_counts(bench_fixture: Path) -> None:
    tree = RenderTree(bench_fixture / "render")
    taxonomy = load_categories(CATEGORIES)
    ticks = [10, 20]
    real = plan_sheets(ticks, tree, taxonomy, seed=1, calibrate=False)
    assert [(s.kind, s.tick) for s in real] == [("real", 10), ("real", 20)]
    sheets = plan_sheets(ticks, tree, taxonomy, seed=1, calibrate=True)
    kinds = [s.kind for s in sheets]
    assert kinds.count("real") == 2
    assert kinds.count("control") == 2
    with_actors = sum(1 for t in ticks if (tree.load(t).layer >= 16).any())
    for key in taxonomy.faults:
        planted = [s for s in sheets if s.kind == "planted" and s.fault == key]
        expected = with_actors if key == "actors_removed" else len(ticks)
        assert len(planted) == min(6, expected)
    assert len({s.id for s in sheets}) == len(sheets)


def test_build_sheet_layout(bench_fixture: Path) -> None:
    capture = load_capture(bench_fixture / "capture")[10]
    render = RenderTree(bench_fixture / "render").load(10)
    sheet = build_sheet(capture.palette[capture.idx], render.rgb, render.layer)
    assert sheet.size == (1288, 1020)
    pixels = np.asarray(sheet)
    bar = pixels[26 + 2 * 222 : 26 + 480]
    assert (bar[:, :640] == 128).all()
    assert (bar[:, 648:1288] == 128).all()


def test_render_brief_lists_categories(tmp_path: Path) -> None:
    taxonomy = load_categories(CATEGORIES)
    brief = render_brief(taxonomy, tmp_path, 42)
    rows = [brief.index(f"| `{i}` |") for i in taxonomy.ids]
    assert rows == sorted(rows)
    example = " ".join(f"{i}=0" for i in taxonomy.ids)
    assert f"`<id> {example} | other: none`" in brief
    assert f"{(tmp_path / 'grades.txt').as_posix()}" in brief
    assert "lists 42 image ids" in brief


def test_idx_digest_changes_with_render(tmp_path: Path, bench_fixture: Path) -> None:
    render = bench_fixture / "render"
    assert idx_digest(render, [10, 20]) == idx_digest(render, [10, 20])
    copy = tmp_path / "render"
    shutil.copytree(render, copy)
    plane = copy / "tick_00010.idx"
    data = bytearray(plane.read_bytes())
    data[0] ^= 1
    plane.write_bytes(bytes(data))
    assert idx_digest(copy, [10, 20]) != idx_digest(render, [10, 20])
