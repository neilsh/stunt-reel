"""The parity scripts' shared options: one definition of the flags both accept."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import cli  # noqa: E402
import parity_run  # noqa: E402
import parity_sweep  # noqa: E402
from cli import ParityOptions, UsageError, add_parity_options, parity_options  # noqa: E402

from archive_helpers import build_all  # noqa: E402
from render_helpers import reference_tree  # noqa: E402
from stunt_reel import dataroot, parity_layout, parity_pipeline, references  # noqa: E402
from stunt_reel.all_archive import ArchiveMeta, publish_archive  # noqa: E402
from stunt_reel.parity_artifacts import Report, write_report  # noqa: E402
from stunt_reel.parity_pipeline import REPO_ROOT  # noqa: E402

#: The films of the committed references.toml, which is what the parity loop covers.
FILMS = references.reference_films(REPO_ROOT)


def _options(module: Any, argv: list[str]) -> ParityOptions:
    return parity_options(module.parse_args(argv))


def test_both_entry_points_build_the_same_options() -> None:
    argv = ["--films", "ctry", "--no-build", "--reuse", "retimed", "--retime", "3"]
    assert _options(parity_run, argv) == _options(parity_sweep, argv)


def test_defaults_cover_every_film_and_the_data_root() -> None:
    options = _options(parity_run, [])
    assert options.films == FILMS
    assert options.data_root == dataroot.data_root()
    assert (options.no_build, options.reuse, options.retime) == (False, None, None)


def test_films_are_split_and_trimmed() -> None:
    assert _options(parity_sweep, ["--films", " ctry , intro "]).films == ("ctry", "intro")


def test_an_unknown_film_is_refused_with_one_message() -> None:
    messages: list[str] = []
    for module in (parity_run, parity_sweep):
        with pytest.raises(UsageError) as refusal:
            _options(module, ["--films", "ctry,nope"])
        messages.append(str(refusal.value))
    assert messages[0] == messages[1] == "--films must be from ctry, intro, got 'ctry,nope'"


def test_the_shared_flags_are_defined_once() -> None:
    parser = argparse.ArgumentParser(prog="parity")
    add_parity_options(parser)
    actions = {action.dest: action for action in parser._actions}
    assert set(actions) == {"help", "films", "data_root", "no_build", "reuse", "retime", "jobs"}
    assert actions["films"].default is None
    assert actions["reuse"].help == "score DIR/<film> without rendering"


def test_script_specific_flags_stay_local() -> None:
    assert parity_run.parse_args(["--no-render"]).no_render is True
    sweep = parity_sweep.parse_args(["--probe", "iou", "--var", "DBG_X=0", "--keep-best"])
    assert (sweep.probe, sweep.keep_best) == ("iou", True)


def test_the_films_come_from_the_selected_data_root(tmp_path: Path) -> None:
    """Another root's references.toml decides the default set and what --films accepts."""
    pointers = tmp_path / "research" / "parity" / "references.toml"
    pointers.parent.mkdir(parents=True)
    pointers.write_text(
        '[balloon]\nfilm = "vault-balloon"\nsha256 = "ab"\nmakeone = "patch3"\nplayone = "patch3"\n',
        encoding="utf-8",
    )
    options = _options(parity_run, ["--data-root", str(tmp_path)])
    assert options.films == ("balloon",)
    with pytest.raises(UsageError, match="must be from balloon"):
        _options(parity_run, ["--data-root", str(tmp_path), "--films", "ctry"])


def test_the_default_data_root_leaves_the_corpus_fallback_alone() -> None:
    """Only an explicit --data-root sets STUNT_DATA_ROOT; the default keeps the clone fallback."""
    before = os.environ.get(dataroot.DATA_ENV)
    options = _options(parity_run, [])
    assert os.environ.get(dataroot.DATA_ENV) == before
    assert options.data_root == dataroot.data_root()


def test_a_named_data_root_supplies_the_archive_too(tmp_path: Path) -> None:
    """--data-root DIR must move every read, the stored .ALL included, not only the films."""
    root = reference_tree(tmp_path / "data", [0], films=("ctry",))
    vault = root / "corpus" / "stisldem" / "VAULT"
    (vault / "CTRY.ALL").unlink()
    flm = (vault / "CTRY.FLM").read_bytes()
    data = build_all([b"stored"])
    meta = ArchiveMeta(
        film="CTRY.FLM",
        flm_bytes=len(flm),
        flm_sha256=hashlib.sha256(flm).hexdigest(),
        all_bytes=len(data),
        all_sha256=hashlib.sha256(data).hexdigest(),
    )
    publish_archive(root, data, meta, slug="vault-ctry", film="CTRY.FLM")
    options = _options(parity_run, ["--films", "ctry", "--data-root", str(root)])
    assert dataroot.data_root() == root.resolve()
    problems = parity_pipeline.preflight(
        options.data_root, ["ctry"], build_required=False, locked=lambda _path: False
    )
    assert problems == []


def test_the_bench_data_root_flag_moves_the_data_root(tmp_path: Path) -> None:
    import parity_bench  # noqa: PLC0415 - a script, imported only here

    args = parity_bench.parse_args(
        ["run", "--film", "ctry", "--recapture", "x", "--data-root", str(tmp_path)]
    )
    assert dataroot.data_root_flag(args.data_root) == tmp_path.resolve()
    assert dataroot.data_root() == tmp_path.resolve()


def test_jobs_defaults_to_eight_capped_by_cores_and_pairs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "cpu_count", lambda: 16)
    assert cli.resolve_jobs(None, 24) == 8
    assert cli.resolve_jobs(None, 2) == 2
    monkeypatch.setattr(os, "cpu_count", lambda: None)
    assert cli.resolve_jobs(None, 24) == 1


def test_jobs_above_pairs_is_clamped() -> None:
    assert cli.resolve_jobs(32, 3) == 3
    assert cli.resolve_jobs(1, 3) == 1


@pytest.mark.parametrize("value", ["0", "-1", "two"])
def test_jobs_must_be_a_positive_integer(value: str) -> None:
    for module in (parity_run, parity_sweep):
        with pytest.raises(SystemExit):
            module.parse_args(["--jobs", value])


def test_jobs_reaches_the_options() -> None:
    assert _options(parity_run, ["--jobs", "3"]).jobs == 3
    assert _options(parity_sweep, []).jobs is None


@pytest.mark.parametrize("jobs", ["1", "2"])
def test_parity_run_rotates_trees_the_same_at_any_jobs(
    jobs: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = reference_tree(tmp_path / "data", [7])
    repo = tmp_path / "repo"
    renders: list[str] = []

    def fake_render(job: parity_pipeline.FilmJob, out: Path, *_a: object, **_k: object) -> None:
        renders.append(job.name)
        out.mkdir(parents=True)
        (out / "marker").write_text(str(renders.count(job.name)), encoding="utf-8")

    def fake_score(
        job: parity_pipeline.FilmJob, render: Path, report: Path, **_k: object
    ) -> parity_pipeline.FilmScore:
        report.mkdir(parents=True, exist_ok=True)
        write_report(report / "report.json", Report(per_frame=()))  # no adapter recorded
        return parity_pipeline.FilmScore(job.name, render, report, parity_pipeline.Score(0.5, 0.5))

    monkeypatch.setattr(parity_run, "REPO_ROOT", repo)
    monkeypatch.setattr(parity_run, "render_film", fake_render)
    monkeypatch.setattr(parity_run, "check_film", lambda *_a: None)
    monkeypatch.setattr(parity_run, "score_film", fake_score)
    monkeypatch.setattr(parity_run, "format_summary", lambda name, _report: f"{name} scored")
    monkeypatch.setattr(parity_run, "preflight", lambda *_a, **_k: [])
    argv = ["--no-build", "--data-root", str(root), "--jobs", jobs]
    assert parity_run.main(argv) == 0
    assert parity_run.main(argv) == 0
    compare = "      no adapter in the report: re-render to compare"
    film_lines = ["ctry scored", compare, "intro scored", compare, parity_run.NOISE_NOTE]
    assert capsys.readouterr().out.splitlines() == film_lines * 2
    for film in ("ctry", "intro"):
        current = repo / parity_layout.render_dir(film) / "marker"
        previous = repo / parity_layout.previous_dir(film) / "marker"
        assert current.read_text(encoding="utf-8") == "2"
        assert previous.read_text(encoding="utf-8") == "1"


@pytest.mark.parametrize(
    ("argv", "flag"),
    [
        ([], None),
        (["--reuse", "elsewhere"], "--reuse"),
        (["--retime", "-2"], "--retime"),
        (["--reuse", "elsewhere", "--retime", "1"], "--retime"),
    ],
)
def test_a_run_that_scores_another_tree_names_its_flag(argv: list[str], flag: str | None) -> None:
    assert parity_run.rescored_with(_options(parity_run, argv)) == flag
