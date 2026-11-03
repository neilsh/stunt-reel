"""The batch stage runners: each builds one command, runs it through an injected runner, and records the outcome.

Every test injects a fake runner, so nothing here launches dosbox-automation, MAKEONE or the stuntreel binary,
and nothing reads the corpus.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from render_helpers import write_store
from stunt_reel import batch_stages, dataroot, parity_layout, parity_pipeline
from stunt_reel.batch_films import BatchFilm

if TYPE_CHECKING:
    from collections.abc import Iterator

    from stunt_reel.batch_ledger import Record


class FakeRunner:
    """The subprocess adapter: records each command and answers with a fixed exit code and tail."""

    def __init__(self, code: int = 0, tail: str = "") -> None:
        self.code = code
        self.tail = tail
        self.calls: list[tuple[list[str], float | None]] = []

    def __call__(
        self, command: list[str], _env: dict[str, str] | None, timeout: float | None
    ) -> tuple[int, str]:
        self.calls.append((list(command), timeout))
        return self.code, self.tail


def _film(tmp_path: Path, *, name: str | None = None, sibling: bool = False) -> BatchFilm:
    return BatchFilm(
        slug="vault-ctry" if name is None else name,
        name=name,
        flm=tmp_path / "VAULT" / "CTRY.FLM",
        sha256="0" * 64,
        has_sibling_all=sibling,
    )


def _write_capture(tmp_path: Path, slug: str, ticks: list[int]) -> None:
    """A fake capture with a ``meta.json`` of frames at *ticks*, as the harness writes it."""
    directory = tmp_path / parity_layout.frames_path(slug)
    directory.mkdir(parents=True, exist_ok=True)
    frames = [{"ordinal": i + 1, "film_tick": tick} for i, tick in enumerate(ticks)]
    meta = {"film": "CTRY.FLM", "frames": frames, "width": 320, "height": 200}
    (directory / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


def _capture_record(tmp_path: Path, ticks: list[int] | None) -> Record:
    film = _film(tmp_path)
    if ticks is not None:
        _write_capture(tmp_path, film.slug, ticks)
    return batch_stages.run_capture(film, tmp_path, FakeRunner(), 900.0)


def test_a_capture_whose_clock_advanced_is_ok(tmp_path: Path) -> None:
    assert _capture_record(tmp_path, [0, 50, 100, 150, 200, 250]).status == "ok"


def test_a_short_film_with_two_advancing_frames_is_ok(tmp_path: Path) -> None:
    assert _capture_record(tmp_path, [0, 12]).status == "ok"


def test_a_capture_stuck_at_zero_is_invalid(tmp_path: Path) -> None:
    record = _capture_record(tmp_path, [0, 0, 0])
    assert record.status == "error"
    assert record.message.startswith("capture invalid: ")
    assert "clock" in record.message


def test_a_capture_whose_first_and_last_ticks_match_is_invalid(tmp_path: Path) -> None:
    record = _capture_record(tmp_path, [40, 41, 40])
    assert record.status == "error"
    assert record.message.startswith("capture invalid: ")


def test_a_capture_with_one_frame_is_invalid(tmp_path: Path) -> None:
    record = _capture_record(tmp_path, [7])
    assert record.status == "error"
    assert record.message.startswith("capture invalid: ")
    assert "1 frame" in record.message


def test_a_successful_capture_run_without_a_capture_is_invalid(tmp_path: Path) -> None:
    record = _capture_record(tmp_path, None)
    assert record.status == "error"
    assert record.message.startswith("capture invalid: ")


def test_a_capture_without_meta_json_is_not_checked(tmp_path: Path) -> None:
    """A capture still being written is incomplete, so the stage reports none (ADR 0028)."""
    film = _film(tmp_path)
    (tmp_path / parity_layout.frames_path(film.slug)).mkdir(parents=True)
    record = batch_stages.run_capture(film, tmp_path, FakeRunner(), 900.0)
    assert record.status == "error"
    assert "no complete capture" in record.message


def test_a_failed_capture_command_keeps_its_exit_error(tmp_path: Path) -> None:
    record = batch_stages.run_capture(_film(tmp_path), tmp_path, FakeRunner(code=1), 900.0)
    assert record.message == "exit 1"


def test_archive_is_skipped_when_a_sibling_all_exists(tmp_path: Path) -> None:
    runner = FakeRunner()
    record = batch_stages.run_archive(_film(tmp_path, sibling=True), tmp_path, runner, 900.0)
    assert record.status == "skipped"
    assert record.stage == "archive"
    assert runner.calls == []


def test_archive_command_carries_name_only_when_set(tmp_path: Path) -> None:
    plain = FakeRunner()
    batch_stages.run_archive(_film(tmp_path), tmp_path, plain, 900.0)
    command, timeout = plain.calls[0]
    assert Path(command[1]).name == "make_all.py"
    assert command[command.index("--film") + 1] == str(tmp_path / "VAULT" / "CTRY.FLM")
    assert "--name" not in command
    assert timeout == 900.0
    # make_all's own timeout fires 90 s before the runner's kill so it can tear the emulator down.
    assert command[command.index("--timeout") + 1] == "810.0"

    assert "--conf" not in command

    short = FakeRunner()
    batch_stages.run_archive(_film(tmp_path), tmp_path, short, 30.0)
    assert short.calls[0][0][short.calls[0][0].index("--timeout") + 1] == "1"

    named = FakeRunner()
    batch_stages.run_archive(_film(tmp_path, name="vault-ctry-0a1b2c3d"), tmp_path, named, 900.0)
    command, _ = named.calls[0]
    assert command[command.index("--name") + 1] == "vault-ctry-0a1b2c3d"


def test_nonzero_exit_becomes_an_error_record_with_the_output_tail(tmp_path: Path) -> None:
    runner = FakeRunner(code=1, tail="MAKEONE started\nno such shape in RES")
    record = batch_stages.run_archive(_film(tmp_path), tmp_path, runner, 900.0)
    assert record.status == "error"
    assert "exit 1" in record.message
    assert "no such shape in RES" in record.message
    assert "\n" not in record.message


def test_a_runner_exception_becomes_an_error_record(tmp_path: Path) -> None:
    def broken(
        _command: list[str], _env: dict[str, str] | None, _timeout: float | None
    ) -> tuple[int, str]:
        raise RuntimeError("dosbox not found")

    record = batch_stages.run_capture(_film(tmp_path), tmp_path, broken, 900.0)
    assert record.status == "error"
    assert record.stage == "capture"
    assert "dosbox not found" in record.message


def test_capture_command_uses_the_film_path(tmp_path: Path) -> None:
    runner = FakeRunner()
    _write_capture(tmp_path, "x-y", [0, 10])
    record = batch_stages.run_capture(_film(tmp_path, name="x-y"), tmp_path, runner, 900.0)
    assert record.status == "ok"
    command, _ = runner.calls[0]
    assert Path(command[1]).name == "capture_playone_reference.py"
    assert command[command.index("--film") + 1] == str(tmp_path / "VAULT" / "CTRY.FLM")
    assert command[command.index("--name") + 1] == "x-y"


def test_capture_runs_the_films_own_build_by_default(tmp_path: Path) -> None:
    runner = FakeRunner()
    _write_capture(tmp_path, "vault-ctry", [0, 10])
    batch_stages.run_capture(_film(tmp_path), tmp_path, runner, 900.0)
    command, _ = runner.calls[0]
    assert "--game-root" not in command


@pytest.fixture
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A data root of the test's own, so nothing reads the machine's (``data_root`` is cached)."""
    root = tmp_path / "data"
    monkeypatch.setenv(dataroot.DATA_ENV, str(root))
    dataroot.data_root.cache_clear()
    yield root.resolve()
    dataroot.data_root.cache_clear()


def _newplay_film(tmp_path: Path, slug: str) -> BatchFilm:
    name = {"vault-intro": "INTRO.FLM", "vault-tod": "TOD.FLM"}[slug]
    return BatchFilm(
        slug=slug,
        name=slug,
        flm=tmp_path / "corpus" / "siarchive" / "Films" / "NewPLAY" / "Vault" / name,
        sha256="0" * 64,
        has_sibling_all=True,
    )


def _unpatched_build(data_root: Path) -> Path:
    tree = data_root / "builds" / "unpatched"
    tree.mkdir(parents=True)
    (tree / "PLAYONE.EXE").write_bytes(b"MZ")
    return tree


@pytest.mark.parametrize("slug", ["vault-intro", "vault-tod"])
def test_a_film_that_stalls_on_the_patched_build_captures_on_the_unpatched_one(
    tmp_path: Path, data_root: Path, slug: str
) -> None:
    tree = _unpatched_build(data_root)
    runner = FakeRunner()
    _write_capture(tmp_path, slug, [0, 10])
    batch_stages.run_capture(_newplay_film(tmp_path, slug), tmp_path, runner, 900.0)
    command, _ = runner.calls[0]
    assert Path(command[command.index("--game-root") + 1]) == tree


@pytest.mark.usefixtures("data_root")
def test_the_demo_copy_of_a_film_keeps_its_own_engine(tmp_path: Path) -> None:
    # In a demo-only corpus vault-intro is stisldem's INTRO.FLM, which plays on the demo engine;
    # only the NewPLAY copy ships the patched PLAYONE.EXE that stalls.
    runner = FakeRunner()
    _write_capture(tmp_path, "vault-intro", [0, 10])
    demo = BatchFilm(
        slug="vault-intro",
        name="vault-intro",
        flm=tmp_path / "corpus" / "stisldem" / "VAULT" / "INTRO.FLM",
        sha256="0" * 64,
        has_sibling_all=True,
    )
    record = batch_stages.run_capture(demo, tmp_path, runner, 900.0)
    assert record.status == "ok"
    command, _ = runner.calls[0]
    assert "--game-root" not in command


def test_a_missing_unpatched_build_is_an_error_naming_game_builds(
    tmp_path: Path, data_root: Path
) -> None:
    runner = FakeRunner()
    record = batch_stages.run_capture(_newplay_film(tmp_path, "vault-tod"), tmp_path, runner, 900.0)
    assert runner.calls == []
    assert (record.stage, record.status) == ("capture", "error")
    assert "mise run game-builds" in record.message
    assert str(data_root / "builds" / "unpatched") in record.message


def test_a_known_stall_is_a_skipped_capture_record(tmp_path: Path) -> None:
    record = batch_stages.skip_stalled_capture(_film(tmp_path))
    assert (record.stage, record.status) == ("capture", "skipped")
    assert record.message == "known capture stall"
    assert batch_stages.KNOWN_CAPTURE_STALLS == ("flmonly-bigman",)


def _render_film(tmp_path: Path, ticks: list[int] | None = None) -> BatchFilm:
    """The CTRY film with a sibling archive and, when *ticks* is given, a capture of them."""
    film = _film(tmp_path)
    film.flm.parent.mkdir(parents=True, exist_ok=True)
    (film.flm.parent / "CTRY.ALL").write_bytes(b"")
    if ticks is not None:
        _write_capture(tmp_path, film.slug, ticks)
    return film


def test_render_without_a_capture_is_an_error_naming_capture(tmp_path: Path) -> None:
    runner = FakeRunner()
    record = batch_stages.run_render(_film(tmp_path), tmp_path, runner, 600.0)
    assert record.status == "error"
    assert record.stage == "render"
    assert "capture" in record.message
    assert runner.calls == []


def test_render_asks_the_binary_for_the_captured_ticks_into_the_batch_directory(
    tmp_path: Path,
) -> None:
    film = _render_film(tmp_path, [7, 9])
    runner = FakeRunner()
    record = batch_stages.run_render(film, tmp_path, runner, 600.0)
    assert (record.stage, record.status) == ("render", "ok")
    ((command, timeout),) = runner.calls
    assert timeout == 600.0
    assert command[0] == str(parity_pipeline.binary_path())
    assert command[command.index("--all") + 1] == str(film.flm.parent / "CTRY.ALL")
    assert command[command.index("--tick-range") + 1] == "7..=9"
    assert command[command.index("--sidata") + 1] == str(tmp_path / parity_pipeline.SIDATA)
    out = tmp_path / parity_layout.batch_film_dir(film.slug) / "render"
    assert command[command.index("--out-dir") + 1] == str(out)
    assert command[-6:] == list(parity_pipeline.RENDER_FLAGS)


def test_score_without_a_complete_capture_does_not_run_the_command(tmp_path: Path) -> None:
    film = _film(tmp_path)
    (tmp_path / parity_layout.frames_path(film.slug)).mkdir(parents=True)
    runner = FakeRunner()
    record = batch_stages.run_score(film, tmp_path, runner, 600.0)
    assert record.status == "error"
    assert record.stage == "score"
    assert "capture" in record.message
    assert runner.calls == []


def test_a_failed_render_keeps_its_exit_and_tail(tmp_path: Path) -> None:
    film = _render_film(tmp_path, [7, 9])
    record = batch_stages.run_render(film, tmp_path, FakeRunner(code=2, tail="no GPU\n"), 600.0)
    assert (record.stage, record.status) == ("render", "error")
    assert record.message == "exit 2: no GPU"


def test_render_without_an_archive_is_an_error_and_starts_nothing(tmp_path: Path) -> None:
    film = _film(tmp_path)
    film.flm.parent.mkdir(parents=True)
    _write_capture(tmp_path, film.slug, [7, 9])
    runner = FakeRunner()
    record = batch_stages.run_render(film, tmp_path, runner, 600.0)
    assert (record.stage, record.status) == ("render", "error")
    assert "no .ALL" in record.message
    assert runner.calls == []


def _write_render(tmp_path: Path, film: BatchFilm, ticks: list[int]) -> None:
    write_store(tmp_path / parity_layout.batch_film_dir(film.slug) / "render", ticks)


class ReportWriter(FakeRunner):
    """A score adapter that writes the ``report.json`` the binary would."""

    def __call__(
        self, command: list[str], env: dict[str, str] | None, timeout: float | None
    ) -> tuple[int, str]:
        output = Path(command[command.index("--output") + 1])
        output.mkdir(parents=True, exist_ok=True)
        document = {"per_frame": [], "mean_ssim_scored": 0.7, "mean_iou_scored": 0.9}
        (output / "report.json").write_text(json.dumps(document), encoding="utf-8")
        return super().__call__(command, env, timeout)


def test_score_record_carries_ssim_and_iou(tmp_path: Path) -> None:
    film = _render_film(tmp_path, [7, 9])
    _write_render(tmp_path, film, [7, 9])
    runner = ReportWriter()
    record = batch_stages.run_score(film, tmp_path, runner, 600.0)
    assert record.status == "ok"
    assert record.stage == "score"
    assert record.ssim == 0.7
    assert record.iou == 0.9
    ((command, _timeout),) = runner.calls
    capture = tmp_path / parity_layout.frames_path(film.slug)
    assert command[command.index("--reference") + 1] == str(capture)
    film_dir = tmp_path / parity_layout.batch_film_dir(film.slug)
    assert command[command.index("--test") + 1] == str(film_dir / "render")
    assert command[command.index("--output") + 1] == str(film_dir / "report")


def test_score_refuses_a_render_that_misses_a_captured_tick(tmp_path: Path) -> None:
    film = _render_film(tmp_path, [7, 9])
    _write_render(tmp_path, film, [7])
    runner = ReportWriter()
    record = batch_stages.run_score(film, tmp_path, runner, 600.0)
    assert (record.stage, record.status) == ("score", "error")
    assert "no render planes for 1 captured tick(s), first 9" in record.message
    assert runner.calls == []


def test_score_without_a_capture_is_an_error_naming_capture(tmp_path: Path) -> None:
    runner = FakeRunner()
    record = batch_stages.run_score(_film(tmp_path), tmp_path, runner, 600.0)
    assert (record.stage, record.status) == ("score", "error")
    assert "capture" in record.message
    assert runner.calls == []
