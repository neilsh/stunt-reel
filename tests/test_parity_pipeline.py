"""Offline tests for the parity pipeline seam (synthetic data only).

The pipeline owns the film catalogue, render/check/score for one film and for a list,
the preflight and the release build. These tests pin the commands it hands the adapter,
the per-film failure a list run returns instead of raising, the retime copy, and the
checks that refuse an unscorable render.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from stunt_reel import parity_artifacts, parity_layout, parity_pipeline, references
from stunt_reel.parity_artifacts import (
    SCHEMA_VERSION,
    CameraPose,
    FilmId,
    Geometry,
    RenderPalette,
    RenderRecord,
    RenderTick,
    read_render,
)


def _geometry() -> Geometry:
    return Geometry(width=320, height=200, viewport_rows=185)


def test_the_catalogue_names_each_films_inputs_and_its_capture() -> None:
    assert list(parity_pipeline.FILMS) == ["ctry", "intro"]
    for name, film in parity_pipeline.FILMS.items():
        assert film.flm.endswith(f"{name.upper()}.FLM")
        assert film.all.endswith(f"{name.upper()}.ALL")


class FakeRun:
    """The run adapter: records each command and writes the artifacts a real run would."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.envs: list[dict[str, str] | None] = []
        self.fail_on: str | None = None

    def __call__(self, cmd: list[str], env: dict[str, str] | None = None) -> None:
        self.calls.append(cmd)
        self.envs.append(env)
        if self.fail_on is not None and any(str(part).endswith(self.fail_on) for part in cmd):
            raise RuntimeError(f"{self.fail_on} exploded")
        out_dir = _after(cmd, "--out-dir")
        if out_dir is not None:
            _write_render(Path(out_dir), _frames_for(cmd))
        output = _after(cmd, "--output")
        if output is not None:
            _write_report(Path(output))


def _after(cmd: list[str], flag: str) -> str | None:
    try:
        return cmd[cmd.index(flag) + 1]
    except ValueError:
        return None


def _frames_for(cmd: list[str]) -> list[int]:
    """The film ticks a --frames range renders: frame n draws tick n - 1."""
    value = _after(cmd, "--frames")
    if value is None:
        return []
    first, _, last = value.partition("..")
    return [frame - 1 for frame in range(int(first), int(last) + 1)]


def _write_render(render: Path, ticks: list[int] | None = None) -> None:
    render.mkdir(parents=True, exist_ok=True)
    parity_artifacts.write_render(
        render / parity_artifacts.RENDER_DOCUMENT,
        RenderRecord(schema_version=SCHEMA_VERSION, film=FilmId(), geometry=_geometry(), ticks=()),
    )
    for tick in ticks or []:
        for ext in ("idx", "layer"):
            (render / f"tick_{tick:05d}.{ext}").write_bytes(b"")


def _write_report(report: Path, *, ssim: float = 0.8, iou: float = 0.9) -> None:
    report.mkdir(parents=True, exist_ok=True)
    (report / "report.json").write_text(
        json.dumps({"per_frame": [], "mean_ssim_scored": ssim, "mean_iou_scored": iou}),
        encoding="utf-8",
    )


def _input_tree(root: Path, ticks: list[int]) -> Path:
    """A data root holding every corpus input and reference capture of both films."""
    for film in parity_pipeline.FILMS.values():
        for path in (film.flm, film.all):
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"")
        (root / film.sidata).mkdir(parents=True, exist_ok=True)
    for name in parity_pipeline.FILMS:
        _pin(root, name, [{"film_tick": tick} for tick in ticks])
    return root


def _pin(root: Path, film: str, frames: list[dict[str, int]]) -> Path:
    """Write a capture of *film* under *root* and name it in the root's references.toml."""
    reference = root / parity_layout.capture_path(film, "test-0001")
    reference.mkdir(parents=True, exist_ok=True)
    (reference / "meta.json").write_text(json.dumps({"frames": frames}), encoding="utf-8")
    pointers = root / parity_layout.REFERENCES_FILE
    pointers.parent.mkdir(parents=True, exist_ok=True)
    digest = references.capture_digest(reference)
    with pointers.open("a", encoding="utf-8") as handle:
        handle.write(f'[{film}]\ncapture = "test-0001"\nsha256 = "{digest}"\n')
    return reference


def test_build_release_runs_cargo_through_the_adapter() -> None:
    fake = FakeRun()
    parity_pipeline.build_release(run=fake)
    assert fake.calls == [["cargo", "build", "--release", "-p", "stunt-cli"]]


def test_render_film_asks_for_the_captured_tick_range(tmp_path: Path) -> None:
    root = _input_tree(tmp_path, [7, 9])
    film = parity_pipeline.FILMS["ctry"]
    out = tmp_path / "work" / "ctry"
    fake = FakeRun()
    parity_pipeline.render_film("ctry", root, out, run=fake)
    assert fake.calls == [
        [
            str(parity_pipeline.binary_path()),
            "--headless",
            str(root / film.flm),
            "--all",
            str(root / film.all),
            "--frames",
            "8..11",
            "--sidata",
            str(root / film.sidata),
            "--out-dir",
            str(out),
            *parity_pipeline.RENDER_FLAGS,
        ]
    ]


def test_score_film_runs_parity_and_reads_the_report(tmp_path: Path) -> None:
    root = _input_tree(tmp_path, [])
    render, report = tmp_path / "ours", tmp_path / "report"
    _write_render(render)
    fake = FakeRun()
    result = parity_pipeline.score_film("ctry", root, render, report, run=fake)
    assert fake.calls == [
        [
            str(parity_pipeline.binary_path()),
            "parity",
            "--reference",
            str(root / parity_layout.capture_path("ctry", "test-0001")),
            "--test",
            str(render),
            "--output",
            str(report),
        ]
    ]
    assert result.score == parity_pipeline.Score(0.8, 0.9)
    assert (result.render, result.report) == (render, report)


def test_score_film_refuses_a_missing_render_directory(tmp_path: Path) -> None:
    root = _input_tree(tmp_path, [])
    with pytest.raises(ValueError, match="not a render directory"):
        parity_pipeline.score_film("ctry", root, tmp_path / "missing", tmp_path / "report")


def test_run_films_returns_a_failure_instead_of_raising(tmp_path: Path) -> None:
    root = _input_tree(tmp_path, [7, 9])
    fake = FakeRun()
    fake.fail_on = "INTRO.ALL"
    attempts = parity_pipeline.run_films(["ctry", "intro"], root, tmp_path / "work", run=fake)
    assert isinstance(attempts[0], parity_pipeline.FilmScore)
    failure = attempts[1]
    assert isinstance(failure, parity_pipeline.FilmFailure)
    assert failure.film == "intro"
    assert "exploded" in str(failure.error)


def test_run_films_scores_existing_trees_without_rendering(tmp_path: Path) -> None:
    root = _input_tree(tmp_path, [])
    work = tmp_path / "reuse"
    for film in ("ctry", "intro"):
        _write_render(work / film)
    fake = FakeRun()
    attempts = parity_pipeline.run_films(["ctry", "intro"], root, work, render=False, run=fake)
    scores: list[parity_pipeline.FilmScore] = []
    for attempt in attempts:
        assert isinstance(attempt, parity_pipeline.FilmScore)
        scores.append(attempt)
    assert all("--headless" not in call for call in fake.calls)
    assert [score.report for score in scores] == [
        work / "ctry_report",
        work / "intro_report",
    ]


# The retime half: the probe's retime subcommand consumes these helpers, so they are
# tested here at their owner.
def _capture(reference: Path, ticks: list[int]) -> Path:
    """A capture directory whose meta.json tags ticks as the film clock."""
    reference.mkdir(parents=True)
    frames = [{"ordinal": index + 1, "film_tick": tick} for index, tick in enumerate(ticks)]
    (reference / "meta.json").write_text(json.dumps({"frames": frames}), encoding="utf-8")
    return reference


def _record(ticks: list[int]) -> RenderRecord:
    return RenderRecord(
        schema_version=SCHEMA_VERSION,
        film=FilmId(name="CTRY.FLM", flm_bytes=100),
        geometry=_geometry(),
        ticks=tuple(
            RenderTick(
                tick=tick,
                palette=RenderPalette(sky=45, brightness=32768, saturation=32768),
                camera=CameraPose(
                    eye=(0.0, 0.0, 0.0),
                    target=(0.0, 0.0, 0.0),
                    fov_degrees=45.0,
                    roll_radians=0.0,
                ),
            )
            for tick in ticks
        ),
    )


def _sidecar(ticks: list[int]) -> dict[str, Any]:
    return {
        "film": "CTRY.FLM",
        "flm_bytes": 100,
        "ticks": [
            {
                "tick": tick,
                "camera": {"eye": [tick, 0, 0]},
                "brightness": 32768,
                "saturation": 32768,
                "sky": 45,
            }
            for tick in ticks
        ],
    }


def _render(
    directory: Path, ticks: list[int], *, sidecar: bool = True, record: bool = True
) -> Path:
    """A render directory with the three per-tick files and, optionally, its documents."""
    directory.mkdir(parents=True)
    for tick in ticks:
        for ext in parity_artifacts.RENDER_SUFFIXES:
            (directory / f"tick_{tick:05d}{ext}").write_bytes(f"{tick}{ext}".encode())
    if record:
        parity_artifacts.write_render(directory / parity_artifacts.RENDER_DOCUMENT, _record(ticks))
    if sidecar:
        (directory / parity_artifacts.LEGACY_SIDECAR).write_text(
            json.dumps(_sidecar(ticks)), encoding="utf-8"
        )
    return directory


def test_plan_retime_maps_each_distinct_tick_in_both_directions() -> None:
    assert parity_pipeline.plan_retime([12, 10, 12], 1) == [(10, 11), (12, 13)]
    assert parity_pipeline.plan_retime([10, 12], -1) == [(10, 9), (12, 11)]
    assert parity_pipeline.plan_retime([7], 0) == [(7, 7)]


def test_retime_copies_planes_under_target_names_and_rewrites_both_documents(
    tmp_path: Path,
) -> None:
    reference = _capture(tmp_path / "ref", [10, 11, 12])
    render = _render(tmp_path / "ours", [10, 11, 12])
    out = tmp_path / "retimed"
    result = parity_pipeline.retime_render(render, reference, out, 0)
    assert result.copied == 3
    assert result.missing == []
    assert result.palette_written is True
    assert result.record_written is True
    for tick in (10, 11, 12):
        for ext in parity_artifacts.RENDER_SUFFIXES:
            assert (out / f"tick_{tick:05d}{ext}").read_bytes() == f"{tick}{ext}".encode()
    palette = json.loads((out / parity_artifacts.LEGACY_SIDECAR).read_text(encoding="utf-8"))
    assert [entry["tick"] for entry in palette["ticks"]] == [10, 11, 12]
    assert palette["film"] == "CTRY.FLM"
    record = read_render(out / parity_artifacts.RENDER_DOCUMENT)
    assert [tick.tick for tick in record.ticks] == [10, 11, 12]
    assert record.ticks[0].palette == _record([10]).ticks[0].palette


def test_retime_positive_offset_takes_the_next_ticks_frames(tmp_path: Path) -> None:
    reference = _capture(tmp_path / "ref", [10, 11])
    render = _render(tmp_path / "ours", [11, 12], sidecar=False)
    out = tmp_path / "retimed"
    result = parity_pipeline.retime_render(render, reference, out, 1)
    assert result.copied == 2
    assert result.missing == []
    assert result.palette_written is False
    assert result.record_written is True
    assert (out / "tick_00010.png").read_bytes() == b"11.png"
    assert (out / "tick_00011.png").read_bytes() == b"12.png"
    assert not (out / parity_artifacts.LEGACY_SIDECAR).exists()
    record = read_render(out / parity_artifacts.RENDER_DOCUMENT)
    assert [tick.tick for tick in record.ticks] == [10, 11]


def test_retime_negative_offset_names_the_first_missing_tick(tmp_path: Path) -> None:
    reference = _capture(tmp_path / "ref", [10, 11])
    render = _render(tmp_path / "ours", [10])
    with pytest.raises(parity_pipeline.RetimeError, match="first 10"):
        parity_pipeline.retime_render(render, reference, tmp_path / "out", -1)
    result = parity_pipeline.retime_render(
        render, reference, tmp_path / "out", -1, allow_missing=True
    )
    assert result.copied == 1
    assert result.missing == [10]
    assert (tmp_path / "out" / "tick_00011.png").is_file()
    assert not (tmp_path / "out" / "tick_00010.png").exists()


def test_retime_refuses_a_non_empty_output_unless_forced(tmp_path: Path) -> None:
    reference = _capture(tmp_path / "ref", [10])
    render = _render(tmp_path / "ours", [10])
    out = tmp_path / "out"
    out.mkdir()
    (out / "stale.txt").write_text("x", encoding="utf-8")
    with pytest.raises(parity_pipeline.RetimeError, match="not empty"):
        parity_pipeline.retime_render(render, reference, out, 0)
    result = parity_pipeline.retime_render(render, reference, out, 0, force=True)
    assert result.copied == 1


def test_retime_without_documents_copies_frames_only(tmp_path: Path) -> None:
    reference = _capture(tmp_path / "ref", [10])
    render = _render(tmp_path / "ours", [10], sidecar=False, record=False)
    out = tmp_path / "out"
    result = parity_pipeline.retime_render(render, reference, out, 0)
    assert result.palette_written is False
    assert result.record_written is False
    assert not (out / parity_artifacts.LEGACY_SIDECAR).exists()
    assert not (out / parity_artifacts.RENDER_DOCUMENT).exists()


def test_retime_keeps_the_legacy_sidecar_in_sync_while_it_exists(tmp_path: Path) -> None:
    reference = _capture(tmp_path / "ref", [10])
    render = _render(tmp_path / "ours", [10], record=False)
    out = tmp_path / "out"
    result = parity_pipeline.retime_render(render, reference, out, 0)
    assert result.palette_written is True
    assert result.record_written is False
    assert (out / parity_artifacts.LEGACY_SIDECAR).is_file()
    assert not (out / parity_artifacts.RENDER_DOCUMENT).exists()


def test_retime_preserves_unknown_document_keys(tmp_path: Path) -> None:
    reference = _capture(tmp_path / "ref", [10])
    render = _render(tmp_path / "ours", [10])
    record_path = render / parity_artifacts.RENDER_DOCUMENT
    record_document: dict[str, Any] = json.loads(record_path.read_text(encoding="utf-8"))
    record_document["future_top"] = {"kept": True}
    record_document["ticks"][0]["future_entry"] = [1, 2]
    record_path.write_text(json.dumps(record_document), encoding="utf-8")
    sidecar_path = render / parity_artifacts.LEGACY_SIDECAR
    sidecar_document: dict[str, Any] = json.loads(sidecar_path.read_text(encoding="utf-8"))
    sidecar_document["future_top"] = True
    sidecar_path.write_text(json.dumps(sidecar_document), encoding="utf-8")

    out = tmp_path / "out"
    parity_pipeline.retime_render(render, reference, out, 0)

    shifted: dict[str, Any] = json.loads(
        (out / parity_artifacts.RENDER_DOCUMENT).read_text(encoding="utf-8")
    )
    assert shifted["future_top"] == {"kept": True}
    assert shifted["ticks"][0]["future_entry"] == [1, 2]
    shifted_sidecar: dict[str, Any] = json.loads(
        (out / parity_artifacts.LEGACY_SIDECAR).read_text(encoding="utf-8")
    )
    assert shifted_sidecar["future_top"] is True


def test_run_films_writes_the_retimed_copy_beside_the_render(tmp_path: Path) -> None:
    root = tmp_path / "root"
    _pin(root, "ctry", [{"ordinal": 1, "film_tick": 10}, {"ordinal": 2, "film_tick": 11}])
    work = tmp_path / "reuse"
    _render(work / "ctry", [10, 11])
    fake = FakeRun()
    attempts = parity_pipeline.run_films(["ctry"], root, work, render=False, retime=1, run=fake)
    attempt = attempts[0]
    assert isinstance(attempt, parity_pipeline.FilmScore)
    assert attempt.render == work / "ctry_retime"
    assert attempt.retime is not None
    assert attempt.retime.copied == 1
    assert attempt.retime.missing == [11]


def _render_tree(tmp_path: Path, film: str, flm_bytes: int, ticks: list[int]) -> tuple[Path, Path]:
    """A capture of CTRY.FLM (100 bytes) at ticks 7 and 9, and a render with planes at ticks."""
    reference, render = tmp_path / "ref", tmp_path / "ours"
    reference.mkdir()
    render.mkdir()
    frames = [{"film_tick": 7}, {"film_tick": 9}]
    meta = {"film": "CTRY.FLM", "flm_bytes": 100, "frames": frames}
    (reference / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    parity_artifacts.write_render(
        render / "render.json",
        RenderRecord(
            schema_version=SCHEMA_VERSION,
            film=FilmId(name=film, flm_bytes=flm_bytes),
            geometry=_geometry(),
            ticks=(),
        ),
    )
    for tick in ticks:
        (render / f"tick_{tick:05d}.idx").write_bytes(b"")
        (render / f"tick_{tick:05d}.layer").write_bytes(b"")
    return reference, render


def test_check_render_accepts_a_matching_render_with_planes(tmp_path: Path) -> None:
    reference, render = _render_tree(tmp_path, "ctry.flm", 100, [7, 9])
    parity_pipeline.check_render(reference, render, [7, 9])


def test_check_render_accepts_a_legacy_sidecar_render(tmp_path: Path) -> None:
    reference, render = _render_tree(tmp_path, "CTRY.FLM", 100, [7, 9])
    (render / "render.json").unlink()
    (render / "palette_controls.json").write_text(
        json.dumps({"film": "CTRY.FLM", "flm_bytes": 100, "ticks": []}), encoding="utf-8"
    )
    parity_pipeline.check_render(reference, render, [7, 9])


@pytest.mark.parametrize(
    ("film", "flm_bytes", "message"),
    [("INTRO.FLM", 100, "render is of INTRO.FLM"), ("CTRY.FLM", 101, "render's is 101$")],
)
def test_check_render_refuses_another_film(
    tmp_path: Path, film: str, flm_bytes: int, message: str
) -> None:
    reference, render = _render_tree(tmp_path, film, flm_bytes, [7, 9])
    with pytest.raises(ValueError, match=message):
        parity_pipeline.check_render(reference, render, [7, 9])


def test_check_render_refuses_a_render_without_planes(tmp_path: Path) -> None:
    reference, render = _render_tree(tmp_path, "CTRY.FLM", 100, [7])
    (render / "tick_00007.layer").unlink()
    with pytest.raises(ValueError, match="no render planes for 2 captured tick"):
        parity_pipeline.check_render(reference, render, [7, 9])


def _report(tmp_path: Path, **fields: float | int | None) -> Path:
    report = tmp_path / "report"
    report.mkdir()
    document: dict[str, object] = {"per_frame": []}
    document.update(fields)
    (report / "report.json").write_text(json.dumps(document), encoding="utf-8")
    return report


def test_format_summary_names_the_scored_means(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        mean_ssim_scored=0.77322346,
        mean_iou_scored=0.97829825,
        mean_index_agreement_scored=0.5046078,
        scored_frames=114,
        frames=140,
    )
    assert (
        parity_pipeline.format_summary("ctry", report)
        == "ctry  ssim 0.7732  iou 0.9783  idx 0.505  scored 114/140"
    )


def test_format_summary_marks_a_missing_index_agreement(tmp_path: Path) -> None:
    report = _report(tmp_path, mean_ssim=0.7, mean_iou=0.9, mean_index_agreement_scored=None)
    assert parity_pipeline.format_summary("intro", report).startswith("intro ssim 0.7000")
    assert " idx - " in parity_pipeline.format_summary("intro", report)


def test_preflight_names_a_missing_capture(tmp_path: Path) -> None:
    root = _input_tree(tmp_path, [])
    (root / parity_layout.capture_path("intro", "test-0001") / "meta.json").unlink()
    problems = parity_pipeline.preflight(
        root, ["ctry", "intro"], build_required=False, locked=lambda _path: False
    )
    assert len(problems) == 1
    assert "test-0001" in problems[0]
    assert "capture-ref" in problems[0]


def test_preflight_names_a_locked_release_binary(tmp_path: Path) -> None:
    root = _input_tree(tmp_path, [])
    problems = parity_pipeline.preflight(
        root, ["ctry"], build_required=True, locked=lambda _path: True
    )
    assert problems == ["release binary is in use; rerun with --no-build or wait"]
    assert (
        parity_pipeline.preflight(root, ["ctry"], build_required=False, locked=lambda _path: True)
        == []
    )
