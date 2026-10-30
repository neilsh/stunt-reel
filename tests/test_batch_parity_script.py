"""Offline tests for `python/scripts/batch_parity.py`: the four stage functions are replaced by fakes.

Nothing here launches DOSBox-X, MAKEONE or the stuntreel binary, and nothing reads the corpus: the
corpus is built in `tmp_path`, and the process runner fails the test if anything calls it.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import batch_parity  # noqa: E402

from stunt_reel import batch_ledger, batch_stages, parity_layout  # noqa: E402
from stunt_reel.batch_films import BatchFilm  # noqa: E402
from stunt_reel.batch_ledger import STAGES, Record  # noqa: E402
from stunt_reel.batch_stages import Runner  # noqa: E402

if TYPE_CHECKING:
    import pytest

TIMEOUTS = {"archive": 900.0, "capture": 900.0, "render": 600.0, "score": 600.0}
StageFunction = Callable[[BatchFilm, Path, Runner, float], Record]


class FakeStages:
    """Stands in for the four stage functions; a (slug, stage) pair in ``failing`` answers with an error."""

    def __init__(self) -> None:
        self.failing: set[tuple[str, str]] = set()
        self.calls: list[tuple[str, str]] = []
        self.options: list[dict[str, int]] = []

    def factory(self, stage: str) -> StageFunction:
        def run_stage(
            film: BatchFilm, _root: Path, _run: Runner, _timeout: float, **options: int
        ) -> Record:
            self.calls.append((film.slug, stage))
            self.options.append(options)
            failed = (film.slug, stage) in self.failing
            return Record(
                slug=film.slug,
                stage=stage,
                status="error" if failed else "ok",
                message="boom" if failed else "",
                seconds=0.0,
                at="2026-10-30T00:00:00+00:00",
            )

        return run_stage


def _install(monkeypatch: pytest.MonkeyPatch) -> FakeStages:
    fake = FakeStages()
    for stage in STAGES:
        monkeypatch.setattr(batch_stages, f"run_{stage}", fake.factory(stage))
    return fake


def _no_process(command: list[str], _timeout: float) -> tuple[int, str]:
    raise AssertionError(f"a stage started a process: {command}")


def _film(slug: str) -> BatchFilm:
    return BatchFilm(
        slug=slug,
        name=None,
        flm=Path(slug.upper() + ".FLM"),
        sha256="0" * 64,
        has_sibling_all=False,
    )


def _process(
    films: list[BatchFilm],
    root: Path,
    *,
    stages: tuple[str, ...] = STAGES,
    retry_errors: bool = False,
    limit: int | None = None,
    skip: frozenset[str] = frozenset(),
    capture_frames: int = 0,
) -> int:
    return batch_parity.process(
        films,
        root,
        root / "ledger.jsonl",
        _no_process,
        stages=stages,
        retry_errors=retry_errors,
        limit=limit,
        timeouts=TIMEOUTS,
        skip=skip,
        capture_frames=capture_frames,
    )


def test_a_second_run_repeats_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch)
    films = [_film("a-film")]
    assert _process(films, tmp_path) == 0
    assert len(fake.calls) == 4
    assert _process(films, tmp_path) == 0
    assert len(fake.calls) == 4
    assert len(batch_ledger.read(tmp_path / "ledger.jsonl")) == 4


def test_an_error_stops_that_film_but_not_the_next(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _install(monkeypatch)
    fake.failing.add(("a-film", "render"))
    errors = _process([_film("a-film"), _film("b-film")], tmp_path)
    assert errors == 1
    assert fake.calls == [
        ("a-film", "archive"),
        ("a-film", "capture"),
        ("a-film", "render"),
        ("b-film", "archive"),
        ("b-film", "capture"),
        ("b-film", "render"),
        ("b-film", "score"),
    ]
    latest = batch_ledger.latest(batch_ledger.read(tmp_path / "ledger.jsonl"), "a-film", "render")
    assert latest is not None
    assert latest.status == "error"
    assert latest.message == "boom"


def test_retry_errors_reruns_only_failed_stages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _install(monkeypatch)
    films = [_film("a-film")]
    fake.failing.add(("a-film", "render"))
    assert _process(films, tmp_path) == 1
    first_run = len(fake.calls)

    fake.failing.clear()
    assert _process(films, tmp_path) == 0
    assert len(fake.calls) == first_run, "an error is not retried without --retry-errors"

    assert _process(films, tmp_path, retry_errors=True) == 0
    assert fake.calls[first_run:] == [("a-film", "render"), ("a-film", "score")]


def test_limit_takes_the_first_films(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch)
    _process([_film("a-film"), _film("b-film")], tmp_path, limit=1)
    assert {slug for slug, _ in fake.calls} == {"a-film"}
    assert len(fake.calls) == 4


def test_stages_flag_runs_just_those_stages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _install(monkeypatch)
    _process([_film("a-film")], tmp_path, stages=("capture", "render"))
    assert fake.calls == [("a-film", "capture"), ("a-film", "render")]


def test_only_selects_slugs_and_unknown_slug_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = _install(monkeypatch)
    (tmp_path / "corpus" / "VAULT").mkdir(parents=True)
    (tmp_path / "corpus" / "VAULT" / "CTRY.FLM").write_bytes(b"ctry")
    (tmp_path / "corpus" / "MORGAN").mkdir(parents=True)
    (tmp_path / "corpus" / "MORGAN" / "INTRO.FLM").write_bytes(b"intro")
    monkeypatch.setattr(batch_parity, "_run_command", _no_process)

    assert batch_parity.main(["--only", "vault-ctry", "--data-root", str(tmp_path)]) == 0
    assert {slug for slug, _ in fake.calls} == {"vault-ctry"}

    assert batch_parity.main(["--only", "nope", "--data-root", str(tmp_path)]) == 2
    assert "nope" in capsys.readouterr().err


def test_summary_prints_and_runs_no_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = _install(monkeypatch)
    ledger = tmp_path / parity_layout.batch_root() / "ledger.jsonl"
    batch_ledger.append(
        ledger,
        Record(
            slug="vault-ctry",
            stage="render",
            status="error",
            message="exit 1: no archive",
            seconds=1.0,
            at="2026-10-30T00:00:00+00:00",
        ),
    )
    assert batch_parity.main(["--summary", "--data-root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "vault-ctry" in out
    assert "render" in out
    assert fake.calls == []


def test_contact_sheets_are_copied_after_a_successful_score(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch)

    def score_writes_sheets(film: BatchFilm, root: Path, _run: Runner, _timeout: float) -> Record:
        report = root / parity_layout.batch_film_dir(film.slug) / "report"
        report.mkdir(parents=True, exist_ok=True)
        (report / "contact_0001.png").write_bytes(b"png")
        (report / "report.json").write_text("{}", encoding="utf-8")
        return Record(slug=film.slug, stage="score", status="ok", message="", seconds=0.0, at="now")

    monkeypatch.setattr(batch_stages, "run_score", score_writes_sheets)
    _process([_film("a-film")], tmp_path)
    frames = tmp_path / parity_layout.batch_film_dir("a-film") / "frames"
    assert sorted(path.name for path in frames.iterdir()) == ["contact_0001.png"]


def test_rendered_frames_are_deleted_after_a_successful_score(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch)
    render = tmp_path / parity_layout.batch_film_dir("a-film") / "render"
    render.mkdir(parents=True)
    (render / "tick_00001.idx").write_bytes(b"x")
    _process([_film("a-film")], tmp_path)
    assert not render.exists()


def test_capture_frames_reach_only_the_capture_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _install(monkeypatch)
    _process([_film("a-film")], tmp_path, capture_frames=40)
    assert fake.options == [{}, {"frames": 40}, {}, {}]


def test_a_known_stall_is_recorded_skipped_and_stops_that_film(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _install(monkeypatch)
    films = [_film("amcrisis-ac"), _film("a-film")]
    assert _process(films, tmp_path, skip=frozenset({"amcrisis-ac"})) == 0
    assert fake.calls == [
        ("amcrisis-ac", "archive"),
        ("a-film", "archive"),
        ("a-film", "capture"),
        ("a-film", "render"),
        ("a-film", "score"),
    ]
    ledger = tmp_path / "ledger.jsonl"
    stalled = batch_ledger.latest(batch_ledger.read(ledger), "amcrisis-ac", "capture")
    assert stalled is not None
    assert (stalled.status, stalled.message) == ("skipped", "known capture stall")

    # A second run neither repeats the record nor runs the later stages.
    _process(films, tmp_path, skip=frozenset({"amcrisis-ac"}))
    assert len(fake.calls) == 5
    assert [r.stage for r in batch_ledger.read(ledger) if r.slug == "amcrisis-ac"] == [
        "archive",
        "capture",
    ]


def test_a_film_that_leaves_the_skip_list_captures_despite_its_skipped_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _install(monkeypatch)
    films = [_film("amcrisis-ac")]
    _process(films, tmp_path, stages=("capture",), skip=frozenset({"amcrisis-ac"}))
    assert fake.calls == []
    _process(films, tmp_path, stages=("capture", "render"))
    assert fake.calls == [("amcrisis-ac", "capture"), ("amcrisis-ac", "render")]


def _corpus(root: Path) -> None:
    for folder, stem in (("AMCRISIS", "AC"), ("VAULT", "CTRY")):
        (root / "corpus" / folder).mkdir(parents=True)
        (root / "corpus" / folder / f"{stem}.FLM").write_bytes(stem.encode())


def test_main_skips_known_stalls_unless_only_or_retry_errors_name_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _install(monkeypatch)
    _corpus(tmp_path)
    monkeypatch.setattr(batch_parity, "_run_command", _no_process)
    root = ["--data-root", str(tmp_path), "--stages", "capture"]

    assert batch_parity.main(root) == 0
    assert fake.calls == [("vault-ctry", "capture")]
    assert fake.options == [{"frames": 40}]

    assert batch_parity.main([*root, "--only", "amcrisis-ac", "--capture-frames", "0"]) == 0
    assert fake.calls[-1] == ("amcrisis-ac", "capture")
    assert fake.options[-1] == {}

    (tmp_path / parity_layout.batch_root() / "ledger.jsonl").unlink()
    fake.calls.clear()
    assert batch_parity.main([*root, "--retry-errors"]) == 0
    assert {slug for slug, _ in fake.calls} == {"amcrisis-ac", "vault-ctry"}


def test_skip_flag_adds_slugs_to_the_default_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _install(monkeypatch)
    _corpus(tmp_path)
    monkeypatch.setattr(batch_parity, "_run_command", _no_process)
    args = ["--data-root", str(tmp_path), "--stages", "capture", "--skip", "vault-ctry"]
    assert batch_parity.main(args) == 0
    assert fake.calls == []
