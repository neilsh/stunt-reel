"""Offline tests for `python/scripts/shape_diff.py` (synthetic manifests and images only)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from PIL import Image

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import shape_diff  # noqa: E402

from stunt_reel import parity_pipeline  # noqa: E402


def _shape(shape_id: str, hash_: str | None = None, error: str | None = None) -> dict[str, object]:
    shape: dict[str, object] = {"id": shape_id, "vertices": 3, "triangles": 1}
    if hash_ is not None:
        shape["geometry_hash"] = hash_
    if error is not None:
        shape["error"] = error
    return shape


def _write_views(out: Path, shapes: list[dict[str, object]], colour: tuple[int, int, int]) -> None:
    """A `shape-views` output: the manifest, and a 4x3 image of every shape with a hash."""
    out.mkdir(parents=True)
    manifest = {"archive": "X.ALL", "views": ["top"], "tile_px": 4, "shapes": shapes}
    (out / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for shape in shapes:
        if "geometry_hash" in shape:
            Image.new("RGB", (4, 3), colour).save(out / f"{shape['id']}.png")


def test_variants_take_two_or_more_distinct_values(tmp_path: Path) -> None:
    runs = shape_diff.variants(tmp_path, "DBG_FLIP=0,a/b")
    assert [run.label for run in runs] == ["DBG_FLIP=0", "DBG_FLIP=a/b"]
    assert [run.env for run in runs] == [{"DBG_FLIP": "0"}, {"DBG_FLIP": "a/b"}]
    assert [run.out.name for run in runs] == ["views_0_0", "views_1_a_b"]
    for spec, message in (
        ("DBG_FLIP=1", "two or more"),
        ("DBG_FLIP=1,1", "repeats"),
        ("FLIP=0,1", "DBG_NAME"),
    ):
        with pytest.raises(ValueError, match=message):
            shape_diff.variants(tmp_path, spec)


def test_a_shape_changes_when_its_hash_failure_or_presence_differs() -> None:
    first = {
        "0001": _shape("0001", "a"),
        "0002": _shape("0002", "b"),
        "0003": _shape("0003", "c"),
        "000A": _shape("000A", error="bad opcode"),
    }
    later = {
        "0001": _shape("0001", "a"),
        "0002": _shape("0002", "B"),
        "000A": _shape("000A", error="bad opcode"),
        "0010": _shape("0010", "d"),
    }
    assert shape_diff.changed_shapes([first, later]) == ["0002", "0003", "0010"]
    assert shape_diff.changed_shapes([first, first, later]) == ["0002", "0003", "0010"]
    assert shape_diff.changed_shapes([first, first]) == []


def test_the_sheet_has_a_row_per_changed_shape_and_a_panel_per_value(tmp_path: Path) -> None:
    before, after = tmp_path / "before", tmp_path / "after"
    _write_views(before, [_shape("0001", "a"), _shape("0002", "b")], (255, 0, 0))
    _write_views(after, [_shape("0001", "a"), _shape("0002", error="stopped")], (0, 0, 255))
    sheet = tmp_path / "sheet.png"
    shape_diff.draw_sheet([before, after], ["0001", "0002"], sheet)
    image = shape_diff._load_rgb(sheet)
    assert image.size == (4 * 2 + shape_diff.GAP, 3 * 2 + shape_diff.GAP)
    assert image.getpixel((0, 0)) == (255, 0, 0)
    assert image.getpixel((4, 0)) == shape_diff.DIVIDER
    assert image.getpixel((4 + shape_diff.GAP, 0)) == (0, 0, 255)
    assert image.getpixel((0, 3)) == shape_diff.DIVIDER
    assert image.getpixel((4 + shape_diff.GAP, 3 + shape_diff.GAP)) == (0, 0, 0), "no image"


def test_main_runs_shape_views_per_value_and_draws_only_the_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "X.ALL"
    archive.write_bytes(b"")
    monkeypatch.setattr(shape_diff, "REPO_ROOT", tmp_path)
    calls: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(argv: list[str], env: dict[str, str] | None = None) -> tuple[int, str]:
        assert env is not None
        calls.append((argv, env))
        flipped = env["DBG_FLIP"] == "1"
        shapes = [_shape("7F02", "x" if flipped else "a"), _shape("7F03", "b")]
        _write_views(Path(argv[argv.index("--out") + 1]), shapes, (9, 9, 9))
        return 0, ""

    monkeypatch.setattr(parity_pipeline, "run_command", fake_run)
    code = shape_diff.main(
        [
            "--var",
            "DBG_FLIP=0,1",
            "--archive",
            str(archive),
            "--shapes",
            "7F02..=7F03",
            "--no-build",
        ]
    )
    assert code == 0
    assert [argv[1] for argv, _ in calls] == ["shape-views", "shape-views"]
    assert all(argv[argv.index("--shapes") + 1] == "7F02..=7F03" for argv, _ in calls)
    assert "--views" not in calls[0][0]
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "1 of 2 shapes changed: 7F02"
    sheet = tmp_path / shape_diff.DIFF_DIR / "sheet.png"
    assert lines[1] == str(sheet)
    assert shape_diff._load_rgb(sheet).size == (4 * 2 + shape_diff.GAP, 3)
    assert lines[2] == "panels: DBG_FLIP=0 | DBG_FLIP=1"


def test_main_without_a_change_draws_no_sheet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "X.ALL"
    archive.write_bytes(b"")
    monkeypatch.setattr(shape_diff, "REPO_ROOT", tmp_path)

    def same_run(argv: list[str], _env: dict[str, str] | None = None) -> tuple[int, str]:
        _write_views(Path(argv[argv.index("--out") + 1]), [_shape("7F02", "a")], (9, 9, 9))
        return 0, ""

    monkeypatch.setattr(parity_pipeline, "run_command", same_run)
    code = shape_diff.main(["--var", "DBG_FLIP=0,1", "--archive", str(archive), "--no-build"])
    assert code == 0
    assert capsys.readouterr().out.splitlines()[0] == "0 of 1 shapes changed"
    assert not (tmp_path / shape_diff.DIFF_DIR / "sheet.png").exists()


def test_main_reports_a_failed_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "X.ALL"
    archive.write_bytes(b"")
    monkeypatch.setattr(shape_diff, "REPO_ROOT", tmp_path)

    def failing_run(_argv: list[str], _env: dict[str, str] | None = None) -> tuple[int, str]:
        return 1, "has no shape 7F99"

    monkeypatch.setattr(parity_pipeline, "run_command", failing_run)
    code = shape_diff.main(["--var", "DBG_FLIP=0,1", "--archive", str(archive), "--no-build"])
    assert code == 1
    assert "has no shape 7F99" in capsys.readouterr().err


def test_main_needs_the_archive(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    missing = tmp_path / "NONE.ALL"
    code = shape_diff.main(["--var", "DBG_FLIP=0,1", "--archive", str(missing), "--no-build"])
    assert code == 2
    assert "superset-all" in capsys.readouterr().err
