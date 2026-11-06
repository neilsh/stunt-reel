"""Offline tests for the film parity operation (synthetic data only).

The pipeline owns render, check and score for one film and for a list, the preflight and the
release build, and it hands every command to one adapter, ``(argv, env, timeout) -> (code,
tail)``. These tests drive it with a fake adapter and pin the commands it builds, the per-film
failure a list run returns instead of raising, the retime copy, and the checks that refuse an
unscorable render.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import threading
import time
import zlib
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from render_helpers import pin_reference, reference_tree, write_store
from stunt_reel import link, parity_artifacts, parity_layout, parity_pipeline
from stunt_reel.batch_films import BatchFilm
from stunt_reel.parity_artifacts import (
    FilmId,
    Geometry,
    RenderStore,
    read_render,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


def _geometry() -> Geometry:
    return Geometry(width=320, height=200, viewport_rows=185)


class FakeRun:
    """The subprocess adapter: records each command and writes the artifacts a real run would."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.envs: list[dict[str, str] | None] = []
        self.timeouts: list[float | None] = []
        self.fail_on: str | None = None

    def __call__(
        self, cmd: list[str], env: dict[str, str] | None, timeout: float | None
    ) -> tuple[int, str]:
        self.calls.append(cmd)
        self.envs.append(env)
        self.timeouts.append(timeout)
        if self.fail_on is not None and any(str(part).endswith(self.fail_on) for part in cmd):
            return 1, f"{self.fail_on} exploded"
        out_dir = _after(cmd, "--out-dir")
        if out_dir is not None:
            _write_render(Path(out_dir), _ticks_for(cmd))
        output = _after(cmd, "--output")
        if output is not None:
            _write_report(Path(output))
        return 0, ""


def _after(cmd: list[str], flag: str) -> str | None:
    try:
        return cmd[cmd.index(flag) + 1]
    except ValueError:
        return None


def _ticks_for(cmd: list[str]) -> list[int]:
    """The film ticks a --tick-range renders: 0-based and inclusive."""
    value = _after(cmd, "--tick-range")
    if value is None:
        return []
    first, _, last = value.partition("..=")
    return list(range(int(first), int(last) + 1))


def _write_render(render: Path, ticks: list[int] | None = None) -> None:
    write_store(render, ticks or [], geometry=_geometry())


def _write_report(report: Path, *, ssim: float = 0.8, iou: float = 0.9) -> None:
    report.mkdir(parents=True, exist_ok=True)
    (report / "report.json").write_text(
        json.dumps({"per_frame": [], "mean_ssim_scored": ssim, "mean_iou_scored": iou}),
        encoding="utf-8",
    )


def test_build_release_runs_cargo_through_the_adapter() -> None:
    fake = FakeRun()
    parity_pipeline.build_release(run=fake)
    assert fake.calls == [["cargo", "build", "--release", "-p", "stunt-cli"]]


def test_a_failing_command_raises_with_its_exit_and_the_tail() -> None:
    def failing(
        _cmd: list[str], _env: dict[str, str] | None, _timeout: float | None
    ) -> tuple[int, str]:
        return 3, "one\ntwo"

    with pytest.raises(parity_pipeline.CommandError, match=r"cargo exited 3: one\ntwo") as raised:
        parity_pipeline.build_release(run=failing)
    assert (raised.value.code, raised.value.tail) == (3, "one\ntwo")


def test_render_film_asks_for_the_captured_tick_range(tmp_path: Path) -> None:
    root = reference_tree(tmp_path, [7, 9])
    vault = root / "corpus" / "stisldem" / "VAULT"
    out = tmp_path / "work" / "ctry"
    fake = FakeRun()
    with parity_pipeline.reference_job(root, "ctry") as job:
        parity_pipeline.render_film(job, out, run=fake)
    assert fake.calls == [
        [
            str(link.binary_path()),
            "--headless",
            str(vault / "CTRY.FLM"),
            "--all",
            str(vault / "CTRY.ALL"),
            "--tick-range",
            "7..=9",
            "--sidata",
            str(root / "corpus" / parity_pipeline.SIDATA),
            "--out-dir",
            str(out),
            *parity_pipeline.RENDER_FLAGS,
        ]
    ]
    assert fake.envs == [None]


def test_render_film_passes_the_environment_and_timeout_to_the_adapter(tmp_path: Path) -> None:
    root = reference_tree(tmp_path, [7, 9])
    fake = FakeRun()
    with parity_pipeline.reference_job(root, "ctry") as job:
        parity_pipeline.render_film(job, tmp_path / "out", {"DBG_X": "1"}, timeout=60.0, run=fake)
    assert (fake.envs, fake.timeouts) == ([{"DBG_X": "1"}], [60.0])


def test_a_film_scored_against_its_current_capture_uses_that_capture(tmp_path: Path) -> None:
    film = BatchFilm(
        slug="vault-ctry",
        name=None,
        flm=tmp_path / "VAULT" / "CTRY.FLM",
        sha256="0" * 64,
        has_sibling_all=True,
    )
    assert parity_pipeline.current_job(film, tmp_path) is None
    capture = pin_reference(tmp_path, "ctry", [{"film_tick": 3}])
    job = parity_pipeline.current_job(film, tmp_path)
    assert job is not None
    assert (job.name, job.capture, job.flm, job.root) == ("vault-ctry", capture, film.flm, tmp_path)


def test_score_film_runs_parity_and_reads_the_report(tmp_path: Path) -> None:
    root = reference_tree(tmp_path, [])
    render, report = tmp_path / "ours", tmp_path / "report"
    _write_render(render)
    fake = FakeRun()
    with parity_pipeline.reference_job(root, "ctry") as job:
        result = parity_pipeline.score_film(job, render, report, run=fake)
    # The score reads the job's snapshot of the capture, never the store's path (ADR 0031).
    assert job.capture.parent == (root / parity_layout.frames_path("vault-ctry")).parent
    assert job.capture.name.startswith("frames.read-")
    assert not job.capture.exists()
    assert fake.calls == [
        [
            str(link.binary_path()),
            "parity",
            "--reference",
            str(job.capture),
            "--test",
            str(render),
            "--output",
            str(report),
        ]
    ]
    assert result.score == parity_pipeline.Score(0.8, 0.9)
    assert (result.render, result.report) == (render, report)


def test_score_film_refuses_a_missing_render_directory(tmp_path: Path) -> None:
    root = reference_tree(tmp_path, [])
    with (
        parity_pipeline.reference_job(root, "ctry") as job,
        pytest.raises(ValueError, match="not a render directory"),
    ):
        parity_pipeline.score_film(job, tmp_path / "missing", tmp_path / "report")


def test_score_film_refuses_a_render_that_misses_a_captured_tick(tmp_path: Path) -> None:
    root = reference_tree(tmp_path, [7, 9])
    render = tmp_path / "ours"
    _write_render(render, [7])
    fake = FakeRun()
    with (
        parity_pipeline.reference_job(root, "ctry") as job,
        pytest.raises(ValueError, match="no render planes"),
    ):
        parity_pipeline.score_film(job, render, tmp_path / "report", run=fake)
    assert fake.calls == []


def test_run_films_returns_a_failure_instead_of_raising(tmp_path: Path) -> None:
    root = reference_tree(tmp_path, [7, 9])
    fake = FakeRun()
    fake.fail_on = "INTRO.ALL"
    attempts = parity_pipeline.run_films(["ctry", "intro"], root, tmp_path / "work", run=fake)
    assert isinstance(attempts[0], parity_pipeline.FilmScore)
    failure = attempts[1]
    assert isinstance(failure, parity_pipeline.FilmFailure)
    assert failure.film == "intro"
    assert "exploded" in str(failure.error)


def test_run_films_scores_existing_trees_without_rendering(tmp_path: Path) -> None:
    root = reference_tree(tmp_path, [])
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


def _render(directory: Path, ticks: list[int]) -> Path:
    """A render store of CTRY.FLM (100 bytes) holding *ticks*."""
    write_store(directory, ticks, geometry=_geometry(), film=FilmId(name="CTRY.FLM", flm_bytes=100))
    return directory


def test_plan_retime_maps_each_distinct_tick_in_both_directions() -> None:
    assert parity_pipeline.plan_retime([12, 10, 12], 1) == [(10, 11), (12, 13)]
    assert parity_pipeline.plan_retime([10, 12], -1) == [(10, 9), (12, 11)]
    assert parity_pipeline.plan_retime([7], 0) == [(7, 7)]


def test_retime_copies_planes_and_records_under_target_ticks(tmp_path: Path) -> None:
    reference = _capture(tmp_path / "ref", [10, 11, 12])
    render = _render(tmp_path / "ours", [10, 11, 12])
    out = tmp_path / "retimed"
    result = parity_pipeline.retime_render(render, reference, out, 0)
    assert result.copied == 3
    assert result.missing == []
    source, retimed = RenderStore(render), RenderStore(out)
    for tick in (10, 11, 12):
        assert retimed.frame(tick) == source.frame(tick)
    record = read_render(out / parity_artifacts.RENDER_DOCUMENT)
    assert [tick.tick for tick in record.ticks] == [10, 11, 12]
    assert record.film == FilmId(name="CTRY.FLM", flm_bytes=100)
    assert record.ticks[0].palette == source.record.ticks[0].palette
    assert record.ticks[0].camera == source.record.ticks[0].camera


def test_retime_positive_offset_takes_the_next_ticks_frames(tmp_path: Path) -> None:
    reference = _capture(tmp_path / "ref", [10, 11])
    render = _render(tmp_path / "ours", [11, 12])
    out = tmp_path / "retimed"
    result = parity_pipeline.retime_render(render, reference, out, 1)
    assert result.copied == 2
    assert result.missing == []
    source, retimed = RenderStore(render), RenderStore(out)
    assert retimed.frame(10) == source.frame(11)
    assert retimed.frame(11) == source.frame(12)
    assert retimed.ticks() == [10, 11]
    assert retimed.record.ticks[0].camera == source.record.ticks[0].camera


def test_retime_recuts_the_chunks_by_target_second(tmp_path: Path) -> None:
    reference = _capture(tmp_path / "ref", [49, 50])
    render = _render(tmp_path / "ours", [50, 51])
    out = tmp_path / "retimed"
    parity_pipeline.retime_render(render, reference, out, 1)
    seconds = [(chunk.second, chunk.ticks) for chunk in RenderStore(out).record.chunks]
    assert seconds == [(0, 1), (1, 1)]


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
    assert RenderStore(tmp_path / "out").ticks() == [11]


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


def test_run_films_writes_the_retimed_copy_beside_the_render(tmp_path: Path) -> None:
    root = reference_tree(tmp_path / "root", [10, 11], films=("ctry",))
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
    """A capture of CTRY.FLM (100 bytes) at ticks 7 and 9, and a render store holding ticks."""
    reference, render = tmp_path / "ref", tmp_path / "ours"
    reference.mkdir()
    frames = [{"film_tick": 7}, {"film_tick": 9}]
    meta = {"film": "CTRY.FLM", "flm_bytes": 100, "frames": frames}
    (reference / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    write_store(render, ticks, geometry=_geometry(), film=FilmId(name=film, flm_bytes=flm_bytes))
    return reference, render


def test_check_render_accepts_a_matching_render_with_planes(tmp_path: Path) -> None:
    reference, render = _render_tree(tmp_path, "ctry.flm", 100, [7, 9])
    parity_pipeline.check_render(reference, render, [7, 9])


def test_check_render_refuses_a_render_from_before_the_store(tmp_path: Path) -> None:
    reference, render = _render_tree(tmp_path, "CTRY.FLM", 100, [7, 9])
    document = json.loads((render / "render.json").read_text(encoding="utf-8"))
    document["schema_version"] = 1
    (render / "render.json").write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="re-render"):
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
    with pytest.raises(ValueError, match=r"no render planes for 1 captured tick.*first 9"):
        parity_pipeline.check_render(reference, render, [7, 9])


def _report(tmp_path: Path, **fields: float | None) -> Path:
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
    root = reference_tree(tmp_path, [])
    (root / parity_layout.frames_path("vault-intro") / "meta.json").unlink()
    problems = parity_pipeline.preflight(
        root, ["ctry", "intro"], build_required=False, locked=lambda _path: False
    )
    assert len(problems) == 1
    assert "intro is absent" in problems[0]
    assert "capture-ref" in problems[0]


def test_preflight_names_a_locked_release_binary(tmp_path: Path) -> None:
    root = reference_tree(tmp_path, [])
    problems = parity_pipeline.preflight(
        root, ["ctry"], build_required=True, locked=lambda _path: True
    )
    assert problems == ["release binary is in use; rerun with --no-build or wait"]
    assert (
        parity_pipeline.preflight(root, ["ctry"], build_required=False, locked=lambda _path: True)
        == []
    )


def test_preflight_names_a_missing_flm_archive_and_sidata(tmp_path: Path) -> None:
    root = reference_tree(tmp_path, [])
    vault = root / "corpus" / "stisldem" / "VAULT"
    (vault / "CTRY.FLM").unlink()
    (vault / "INTRO.ALL").unlink()
    (root / "corpus" / parity_pipeline.SIDATA).rmdir()
    problems = parity_pipeline.preflight(
        root, ["ctry", "intro"], build_required=False, locked=lambda _path: False
    )
    assert len(problems) == 3
    assert f"missing input {root / 'corpus' / parity_pipeline.SIDATA}" in problems[0]
    assert "no .FLM of vault-ctry" in problems[1]
    assert "no .ALL for" in problems[2]


def _intro_from_a_manifest(root: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replaces INTRO's sibling .ALL with a matching manifest; returns the link calls made.

    The manifests are the checkout's, so *root* stands in for this checkout too.
    """
    monkeypatch.setattr(parity_pipeline, "REPO_ROOT", root)
    vault = root / "corpus" / "stisldem" / "VAULT"
    (vault / "INTRO.ALL").unlink()
    flm_sha256 = hashlib.sha256((vault / "INTRO.FLM").read_bytes()).hexdigest()
    manifest = root / parity_layout.manifest_path("vault-intro")
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        f'flm_sha256 = "{flm_sha256}"\ngame_root = "game"\nall_sha256 = "{"a" * 64}"\n',
        encoding="utf-8",
    )
    (root / "game").mkdir()
    calls: list[str] = []

    def ensure_binary() -> Path:
        calls.append("cargo")
        return link.binary_path()

    def build_archive(_manifest: Path, _game: Path, out: Path, *, cwd: Path) -> None:  # noqa: ARG001 - link.build_archive passes cwd by keyword
        calls.append("link")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"LINKED")

    monkeypatch.setattr(link, "ensure_binary", ensure_binary)
    monkeypatch.setattr(link, "build_archive", build_archive)
    return calls


def test_preflight_checks_a_manifest_without_building_or_linking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = reference_tree(tmp_path, [])
    calls = _intro_from_a_manifest(root, monkeypatch)
    problems = parity_pipeline.preflight(
        root, ["intro"], build_required=False, locked=lambda _path: False
    )
    assert problems == []
    assert calls == []


def test_render_film_links_a_manifest_without_running_cargo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = reference_tree(tmp_path, [7, 9])
    calls = _intro_from_a_manifest(root, monkeypatch)
    fake = FakeRun()
    with parity_pipeline.reference_job(root, "intro") as job:
        parity_pipeline.render_film(job, tmp_path / "work" / "intro", run=fake)
    assert calls == ["link"]
    linked = root / parity_layout.linked_path("vault-intro", "INTRO.FLM")
    assert _after(fake.calls[0], "--all") == str(linked)


def test_preflight_names_the_missing_game_files(tmp_path: Path) -> None:
    problems = parity_pipeline.preflight(
        tmp_path / "nothing", ["ctry"], build_required=False, locked=lambda _path: False
    )
    assert len(problems) == 1
    assert problems[0].startswith("no game files")


def _matrix_work(
    sleep: bool = False,
) -> Callable[[parity_pipeline.FilmJob, str], parity_pipeline.FilmScore]:
    """A ``run_matrix`` work fake: a score whose render path names the variant and the film."""

    def work(job: parity_pipeline.FilmJob, variant: str) -> parity_pipeline.FilmScore:
        if sleep:
            # Uneven but repeatable delays, so pairs finish out of submission order.
            time.sleep(zlib.crc32(f"{variant}{job.name}".encode()) % 20 / 1000)
        where = Path(variant) / job.name
        return parity_pipeline.FilmScore(job.name, where, where, parity_pipeline.Score(0.5, 0.5))

    return work


def test_run_matrix_returns_results_in_input_order(tmp_path: Path) -> None:
    root = reference_tree(tmp_path, [7])
    out = parity_pipeline.run_matrix(
        ["ctry", "intro"], root, ["v0", "v1", "v2"], _matrix_work(sleep=True), jobs=4
    )
    assert [[cell.film for cell in row] for row in out] == [["ctry", "intro"]] * 3
    for index, row in enumerate(out):
        for cell in row:
            assert isinstance(cell, parity_pipeline.FilmScore)
            assert cell.render == Path(f"v{index}") / cell.film


def test_run_matrix_jobs_one_and_four_agree(tmp_path: Path) -> None:
    root = reference_tree(tmp_path, [7])
    args = (["ctry", "intro"], root, ["v0", "v1", "v2"], _matrix_work())
    assert parity_pipeline.run_matrix(*args, jobs=1) == parity_pipeline.run_matrix(*args, jobs=4)


def test_run_matrix_isolates_a_failing_pair(tmp_path: Path) -> None:
    root = reference_tree(tmp_path, [7])
    fine = _matrix_work()

    def work(job: parity_pipeline.FilmJob, variant: str) -> parity_pipeline.FilmScore:
        if (job.name, variant) == ("intro", "v1"):
            raise RuntimeError("intro v1 exploded")
        result: parity_pipeline.FilmScore = fine(job, variant)
        return result

    out = parity_pipeline.run_matrix(["ctry", "intro"], root, ["v0", "v1", "v2"], work, jobs=4)
    failures = [
        (i, j)
        for i, row in enumerate(out)
        for j, cell in enumerate(row)
        if isinstance(cell, parity_pipeline.FilmFailure)
    ]
    assert failures == [(1, 1)]
    failure = out[1][1]
    assert isinstance(failure, parity_pipeline.FilmFailure)
    assert "exploded" in str(failure.error)


def test_run_matrix_fails_a_film_without_a_reference_in_every_variant(tmp_path: Path) -> None:
    root = reference_tree(tmp_path, [7])
    called: list[str] = []
    fine = _matrix_work()

    def work(job: parity_pipeline.FilmJob, variant: str) -> parity_pipeline.FilmScore:
        called.append(job.name)
        result: parity_pipeline.FilmScore = fine(job, variant)
        return result

    out = parity_pipeline.run_matrix(["ctry", "nope"], root, ["v0", "v1"], work, jobs=2)
    assert all(isinstance(row[0], parity_pipeline.FilmScore) for row in out)
    assert all(isinstance(row[1], parity_pipeline.FilmFailure) for row in out)
    assert all(row[1].film == "nope" for row in out)
    assert "nope" not in called


def test_run_matrix_opens_each_reference_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = reference_tree(tmp_path, [7])
    opened: list[str] = []
    real = parity_pipeline.reference_job

    @contextlib.contextmanager
    def counting(root_: Path, name: str) -> Iterator[parity_pipeline.FilmJob]:
        opened.append(name)
        with real(root_, name) as job:
            yield job

    monkeypatch.setattr(parity_pipeline, "reference_job", counting)
    parity_pipeline.run_matrix(
        ["ctry", "intro"], root, ["v0", "v1", "v2", "v3"], _matrix_work(), jobs=3
    )
    assert sorted(opened) == ["ctry", "intro"]


def test_run_matrix_calls_on_variant_on_the_calling_thread(tmp_path: Path) -> None:
    root = reference_tree(tmp_path, [7])
    seen: list[tuple[int, int, int]] = []

    def on_variant(
        index: int, row: list[parity_pipeline.FilmScore | parity_pipeline.FilmFailure]
    ) -> None:
        seen.append((index, len(row), threading.get_ident()))

    parity_pipeline.run_matrix(
        ["ctry", "intro"],
        root,
        ["v0", "v1", "v2"],
        _matrix_work(sleep=True),
        jobs=4,
        on_variant=on_variant,
    )
    assert sorted(index for index, _, _ in seen) == [0, 1, 2]
    assert all(size == 2 for _, size, _ in seen)
    assert {ident for _, _, ident in seen} == {threading.get_ident()}


def test_run_matrix_cancels_pending_pairs_on_interrupt(tmp_path: Path) -> None:
    root = reference_tree(tmp_path, [7])
    ran: list[str] = []
    slow = _matrix_work()

    def work(job: parity_pipeline.FilmJob, variant: str) -> parity_pipeline.FilmScore:
        ran.append(variant)
        time.sleep(0.05)
        result: parity_pipeline.FilmScore = slow(job, variant)
        return result

    def interrupt(_index: int, _row: object) -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        parity_pipeline.run_matrix(
            ["ctry", "intro"],
            root,
            [f"v{i}" for i in range(6)],
            work,
            jobs=2,
            on_variant=interrupt,
        )
    assert len(ran) < 12
