"""Offline tests for `python/scripts/parity_probe.py`'s report summary (synthetic data only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from render_helpers import tick_entry

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import parity_probe  # noqa: E402

from stunt_reel import (  # noqa: E402
    matched_frames,
    parity_artifacts,
    parity_layout,
    references,
)
from stunt_reel.dataroot import REPO_ROOT  # noqa: E402
from stunt_reel.parity_artifacts import FilmId, Geometry, StoredFrame  # noqa: E402

#: The bands the probe once hardcoded for every film, now `ctry`'s `background` row field.
CTRY_BANDS = ((192, 199), (228, 238), (161, 165))
CTRY_BANDS_TOML = "[[192, 199], [228, 238], [161, 165]]"


def _report(per_frame: tuple[parity_artifacts.FrameReport, ...]) -> parity_artifacts.Report:
    """A report whose totals agree with the frames given, so ``validate`` accepts it."""
    scored = [frame for frame in per_frame if frame.scored is True]
    return parity_artifacts.Report(
        per_frame=per_frame,
        reference_frames=len(per_frame),
        frames=len(per_frame),
        scored_frames=len(scored),
        excluded_frames=len(per_frame) - len(scored),
        mean_ssim_scored=sum(frame.ssim for frame in scored) / len(scored) if scored else None,
        mean_iou_scored=sum(frame.iou for frame in scored) / len(scored) if scored else None,
        mean_loss_by_class_scored={"props": 0.02, "terrain": 0.01},
    )


def test_summary_prints_the_headline_the_worst_frames_and_the_journal_scores(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    frames = (
        parity_artifacts.FrameReport(film_tick=10, ssim=0.50, iou=0.90, ordinal=1, scored=True),
        parity_artifacts.FrameReport(film_tick=11, ssim=0.90, iou=0.95, ordinal=2, scored=True),
        parity_artifacts.FrameReport(film_tick=12, ssim=0.00, iou=0.00, ordinal=3, scored=False),
    )
    path = tmp_path / "ctry" / "report.json"
    path.parent.mkdir()
    parity_artifacts.write_report(path, _report(frames))

    parity_probe.cmd_summary(argparse.Namespace(report=path, worst=1))

    out = capsys.readouterr().out
    assert "ssim 0.7000" in out
    assert "iou 0.9250" in out
    assert "loss by class: props 0.0200  terrain 0.0100" in out
    assert "worst scored frames: tick 10 0.500" in out
    assert "journal entry: ssim 0.7000  iou 0.9250  scored 2/3 at `<commit>`" in out
    assert "log row" not in out


def test_world_shift_finds_how_far_the_capture_scene_is_moved() -> None:
    width, rows = 16, 12
    ours = bytes((x * 7 + y * 13) % 251 for y in range(rows) for x in range(width))
    # The capture holds the same scene two columns right and four rows down.
    capture = bytes(((x - 2) * 7 + (y - 4) * 13) % 251 for y in range(rows) for x in range(width))
    dx, dy, agree = parity_probe.world_shift(ours, capture, [], width, rows, reach=6)
    assert (dx, dy, agree) == (2, 4, 1.0)


def test_world_shift_ignores_actor_pixels() -> None:
    width, rows = 8, 6
    ours = bytearray(range(width * rows))
    capture = bytes(ours)
    actor = [0, 1, 2]
    for pixel in actor:
        ours[pixel] = 255  # an actor the capture does not hold
    assert parity_probe.world_shift(bytes(ours), capture, actor, width, rows, reach=2) == (
        0,
        0,
        1.0,
    )


def test_shift_summary_reports_the_actor_relative_to_the_world() -> None:
    line = parity_probe.shift_summary([(2, -4, 0, 0), (4, -2, 2, 2), (2, -4, 0, 0)])
    assert line == (
        "frames 3: median actor dx 2 dy -4; world dx 0 dy 0; actor minus world dx 2 dy -4"
    )
    assert parity_probe.shift_summary([]) == "no frame had enough actor pixels"


def test_world_shift_keeps_zero_for_an_odd_reach_and_prefers_the_smaller_tie() -> None:
    width, rows = 8, 6
    flat = bytes([3] * (width * rows))  # every offset agrees fully
    assert parity_probe.world_shift(flat, flat, [], width, rows, reach=1) == (0, 0, 1.0)
    assert parity_probe.world_shift(flat, flat, [], width, rows, reach=4) == (0, 0, 1.0)


def test_world_shift_is_not_pulled_by_the_captures_actor() -> None:
    width, rows = 16, 12
    scene = bytes((x * 7 + y * 13) % 251 for y in range(rows) for x in range(width))
    capture = bytearray(scene)
    # The capture's aircraft sits four columns right of where ours is drawn.
    ours_actor = [y * width + x for y in range(3, 6) for x in range(2, 6)]
    capture_actor = [p + 4 for p in ours_actor]
    for p in capture_actor:
        capture[p] = 250
    result = parity_probe.world_shift(
        scene, bytes(capture), ours_actor, width, rows, reach=6, capture_actor=capture_actor
    )
    assert result == (0, 0, 1.0)


def test_shifted_pixels_moves_the_silhouette_and_drops_what_leaves_the_frame() -> None:
    width, rows = 4, 3
    # (0, 0), (3, 0) and (1, 2), moved one column right and one row down.
    assert parity_probe.shifted_pixels([0, 3, 9], 1, 1, width, rows) == [5]
    assert parity_probe.shifted_pixels([5], -1, -1, width, rows) == [0]


def test_world_shift_skips_offsets_as_large_as_the_frame() -> None:
    width, rows = 8, 6
    flat = bytes([3] * (width * rows))
    assert parity_probe.world_shift(flat, flat, [], width, rows, reach=8) == (0, 0, 1.0)


def test_a_wider_capture_aircraft_does_not_move_the_world() -> None:
    width, rows = 24, 12
    sky = 230  # a CTRY background index, so never an object
    ours = bytearray([sky] * (width * rows))
    capture = bytearray(ours)
    silhouette = [y * width + x for y in range(4, 7) for x in range(8, 12)]
    for p in silhouette:
        ours[p] = 40
    # The capture's aircraft is two columns wider on the right.
    for p in [y * width + x for y in range(4, 7) for x in range(8, 14)]:
        capture[p] = 40
    capture_actor = parity_probe.capture_actor_pixels(
        bytes(capture), silhouette, width, rows, CTRY_BANDS
    )
    assert set(capture_actor) == {y * width + x for y in range(4, 7) for x in range(8, 14)}
    result = parity_probe.world_shift(
        bytes(ours), bytes(capture), silhouette, width, rows, reach=4, capture_actor=capture_actor
    )
    assert result == (0, 0, 1.0)


def test_scenery_between_two_separated_actors_stays_in_the_world_match() -> None:
    width, rows = 60, 10
    sky = 230
    capture = bytearray([sky] * (width * rows))
    left = [y * width + x for y in range(4, 6) for x in range(2, 4)]
    right = [y * width + x for y in range(4, 6) for x in range(56, 58)]
    tree = [y * width + x for y in range(3, 7) for x in range(29, 31)]
    for p in left + right + tree:
        capture[p] = 40
    masked = set(
        parity_probe.capture_actor_pixels(bytes(capture), left + right, width, rows, CTRY_BANDS)
    )
    assert set(left + right) <= masked
    assert not masked & set(tree)


def test_cmd_shift_leaves_the_captures_displaced_aircraft_out_of_the_world_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    rows: Path,
) -> None:
    _write_rows(rows, _row("ctry", f"background = {CTRY_BANDS_TOML}"))
    width, height = 24, 12
    # Backdrop indices only, so nothing in the scene counts as an object; period 19 > reach.
    backdrop = [*range(192, 200), *range(228, 239)]
    scene = bytes(backdrop[(x * 7 + y * 13) % 19] for y in range(height) for x in range(width))
    ours = bytearray(scene)
    capture = bytearray(scene)
    actor = [y * width + x for y in range(4, 8) for x in range(4, 9)]
    for p in actor:
        ours[p] = 40
        capture[p + 6] = 40  # the capture's aircraft sits six columns right of ours
    (tmp_path / "f0.idx").write_bytes(bytes(capture))
    _capture_of(tmp_path, "CTRY.FLM")
    frame = SimpleNamespace(ordinal=0, film_tick=5, frame_file="f0.idx", palette_file="p0.json")
    geometry = SimpleNamespace(width=width, plane_rows=lambda: height)
    page = SimpleNamespace(indices=bytes(ours), actor_pixels=lambda: actor)
    report = SimpleNamespace(per_frame=[SimpleNamespace(scored=True, film_tick=5, ordinal=0)])
    monkeypatch.setattr(matched_frames, "read_capture", lambda _: SimpleNamespace(frames=[frame]))
    monkeypatch.setattr(
        parity_probe,
        "RenderStore",
        lambda _: SimpleNamespace(record=SimpleNamespace(geometry=geometry)),
    )
    monkeypatch.setattr(parity_probe, "read_report", lambda _: report)
    monkeypatch.setattr(matched_frames, "read_page", lambda _store, _tick: page)
    args = argparse.Namespace(
        reference=tmp_path, ours=tmp_path, report=tmp_path, min_pixels=1, reach=8, world_reach=6
    )

    parity_probe.cmd_shift(args)

    # Agreement 1.0 holds only if the capture's aircraft, found through the actor shift, is
    # masked: left in, it disagrees with our scenery at the zero offset.
    assert capsys.readouterr().out.splitlines()[1] == "5 20 6 0 1.0 0 0 1.0"


def test_report_defaults_to_the_one_parity_run_writes() -> None:
    """`shift`, `iou` and `summary` read the report `mise run parity` last wrote, not a hand-run one."""
    written = REPO_ROOT / parity_layout.report_dir("ctry") / "report.json"
    parser = parity_probe.build_parser()
    for argv in (["shift", "--ours", "x"], ["iou", "--ours", "x"], ["summary"]):
        assert parser.parse_args(argv).report == written


def _write_rows(pointer: Path, *tables: str) -> None:
    """Write `tables` (each a row's text) into the stand-in `references.toml` of the `rows` fixture."""
    pointer.write_text("\n".join(tables) + "\n", encoding="utf-8")


def _row(film: str, *fields: str) -> str:
    lines = [f"[{film}]", f'film = "vault-{film}"', 'sha256 = "0"', *fields]
    return "\n".join(lines)


def _capture_of(directory: Path, film_file: str) -> Path:
    """A capture directory whose `meta.json` names `film_file` (no frames needed)."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "meta.json").write_text(
        json.dumps({"film": film_file, "frames": []}), encoding="utf-8"
    )
    return directory


def test_background_comes_from_the_row_of_the_film_the_capture_names(
    tmp_path: Path, rows: Path
) -> None:
    _write_rows(
        rows,
        _row("ctry", "background = [[192, 199]]"),
        _row("land", "background = [[10, 20], [100, 100]]"),
    )
    land = _capture_of(tmp_path / "land", "LAND.FLM")
    assert parity_probe.background_for(land) == ((10, 20), (100, 100))


def test_a_film_with_no_row_is_refused_not_guessed(tmp_path: Path, rows: Path) -> None:
    _write_rows(rows, _row("ctry", "background = [[192, 199]]"))
    with pytest.raises(
        references.ReferenceCaptureError, match=r"LAND\.FLM.*\[land\] row.*names no reference"
    ):
        parity_probe.background_for(_capture_of(tmp_path / "land", "LAND.FLM"))


def test_a_row_without_background_is_refused_naming_the_field(tmp_path: Path, rows: Path) -> None:
    _write_rows(rows, _row("land"))
    with pytest.raises(references.ReferenceCaptureError, match=r"\[land\].*`background`"):
        parity_probe.background_for(_capture_of(tmp_path / "land", "LAND.FLM"))


def test_a_capture_that_names_no_film_is_refused(tmp_path: Path, rows: Path) -> None:
    _write_rows(rows, _row("ctry", "background = [[192, 199]]"))
    directory = tmp_path / "anon"
    directory.mkdir()
    (directory / "meta.json").write_text(json.dumps({"frames": []}), encoding="utf-8")
    with pytest.raises(references.ReferenceCaptureError, match="names no film"):
        parity_probe.background_for(directory)


def test_capture_actor_pixels_uses_the_bands_it_is_given() -> None:
    width, rows = 24, 12
    capture = bytearray([100] * (width * rows))  # this film's ground, not CTRY's
    silhouette = [y * width + x for y in range(4, 7) for x in range(8, 12)]
    for p in silhouette:
        capture[p] = 40
    land = parity_probe.capture_actor_pixels(bytes(capture), silhouette, width, rows, ((100, 100),))
    assert set(land) == set(silhouette)
    # Read as CTRY, index 100 is not backdrop, so the ground around the silhouette is "aircraft".
    ctry = parity_probe.capture_actor_pixels(bytes(capture), silhouette, width, rows, CTRY_BANDS)
    assert set(silhouette) < set(ctry)


def _iou_inputs(tmp_path: Path, film_file: str, ground: int) -> tuple[Path, Path]:
    """A render with a 10x10 actor and a capture holding the top half of it over `ground`."""
    geometry = Geometry(width=320, height=200, viewport_rows=185)
    width, rows = geometry.width, geometry.plane_rows()
    layer = bytearray(2 * width * geometry.height)
    capture = bytearray([ground]) * (width * rows)
    for y in range(50, 60):
        for x in range(100, 110):
            layer[2 * (y * width + x)] = parity_artifacts.LAYER_FIRST_ACTOR
            if y < 55:
                capture[y * width + x] = 10
    frame = StoredFrame(
        indices=bytes(width * geometry.height), layers=bytes(layer), palette=bytes(768)
    )
    parity_artifacts.write_render_store(
        tmp_path, FilmId(), geometry, [(tick_entry(7), frame)], adapter=None
    )
    (tmp_path / "tick_0001.idx").write_bytes(bytes(capture))
    (tmp_path / "meta.json").write_text(
        json.dumps({"film": film_file, "frames": [{"film_tick": 7}]}), encoding="utf-8"
    )
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {"per_frame": [{"film_tick": 7, "ordinal": 1, "ssim": 0.7, "iou": 0.9, "scored": True}]}
        ),
        encoding="utf-8",
    )
    return report, tmp_path


def test_actor_iou_reads_a_non_ctry_films_ground_as_backdrop(tmp_path: Path, rows: Path) -> None:
    _write_rows(rows, _row("land", "background = [[100, 100]]"))
    report, directory = _iou_inputs(tmp_path, "LAND.FLM", ground=100)
    value, count = parity_probe.actor_iou(report, directory, directory, every=1)
    assert count == 1
    assert value == pytest.approx(0.5)  # 50 of 100 actor pixels seen, none from the ground


def test_actor_iou_refuses_a_film_with_no_background_row(tmp_path: Path, rows: Path) -> None:
    _write_rows(rows, _row("ctry", "background = [[192, 199]]"))
    report, directory = _iou_inputs(tmp_path, "LAND.FLM", ground=100)
    with pytest.raises(references.ReferenceCaptureError, match=r"LAND\.FLM"):
        parity_probe.actor_iou(report, directory, directory, every=1)


def test_cmd_shift_refuses_a_film_with_no_background_row(tmp_path: Path, rows: Path) -> None:
    _write_rows(rows, _row("ctry", "background = [[192, 199]]"))
    directory = _capture_of(tmp_path / "land", "LAND.FLM")
    args = argparse.Namespace(
        reference=directory, ours=tmp_path, report=tmp_path, min_pixels=1, reach=8, world_reach=6
    )
    with pytest.raises(references.ReferenceCaptureError, match=r"LAND\.FLM"):
        parity_probe.cmd_shift(args)


def test_background_reads_a_ctry_capture_from_its_stand_in_row(tmp_path: Path, rows: Path) -> None:
    _write_rows(rows, _row("ctry", f"background = {CTRY_BANDS_TOML}"))
    ctry = _capture_of(tmp_path / "ctry", "CTRY.FLM")
    assert parity_probe.background_for(ctry) == CTRY_BANDS


def test_background_reads_the_row_under_the_root_it_is_given(tmp_path: Path, rows: Path) -> None:
    _write_rows(rows, _row("land", "background = [[1, 2]]"))
    root = tmp_path / "root"
    (root / parity_layout.REFERENCES_FILE).parent.mkdir(parents=True)
    (root / parity_layout.REFERENCES_FILE).write_text(
        _row("land", "background = [[7, 8]]") + "\n", encoding="utf-8"
    )
    land = _capture_of(tmp_path / "land", "LAND.FLM")
    assert parity_probe.background_for(land, root) == ((7, 8),)


def test_main_refuses_a_film_with_no_background_row_with_exit_1(
    tmp_path: Path,
    rows: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_rows(rows, _row("ctry", f"background = {CTRY_BANDS_TOML}"))
    land = _capture_of(tmp_path / "land", "LAND.FLM")
    argv = ["parity_probe", "iou", "--reference", str(land), "--ours", str(tmp_path)]
    monkeypatch.setattr(sys, "argv", argv)
    assert parity_probe.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("parity_probe: LAND.FLM: cannot read the [land] row")
