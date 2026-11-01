"""The batch stage runners: each builds one command, runs it through an injected runner, and records the outcome.

Every test injects a fake runner, so nothing here launches dosbox-automation, MAKEONE or the stuntreel binary,
and nothing reads the corpus.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from stunt_reel import batch_stages, dataroot, parity_layout
from stunt_reel.batch_films import BatchFilm

if TYPE_CHECKING:
    from collections.abc import Iterator

    from stunt_reel.batch_ledger import Record


class FakeRunner:
    """Records each command and answers with a fixed exit code and output tail."""

    def __init__(self, code: int = 0, tail: str = "") -> None:
        self.code = code
        self.tail = tail
        self.calls: list[tuple[list[str], float]] = []

    def __call__(self, command: list[str], timeout: float) -> tuple[int, str]:
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


def _write_capture(tmp_path: Path, slug: str, ticks: list[int], run: str = "001") -> None:
    """A fake capture run with a ``meta.json`` of frames at *ticks*, as the harness writes it."""
    directory = tmp_path / parity_layout.frames_root(slug) / run
    directory.mkdir(parents=True)
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


def test_the_capture_checked_is_the_latest_run(tmp_path: Path) -> None:
    film = _film(tmp_path)
    _write_capture(tmp_path, film.slug, [0, 0, 0], run="001")
    _write_capture(tmp_path, film.slug, [0, 100, 200], run="002")
    assert batch_stages.run_capture(film, tmp_path, FakeRunner(), 900.0).status == "ok"


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
    def broken(_command: list[str], _timeout: float) -> tuple[int, str]:
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
    assert batch_stages.KNOWN_CAPTURE_STALLS == ("flmonly-bigman", "vault-location")


def test_render_without_a_capture_is_an_error_naming_capture(tmp_path: Path) -> None:
    runner = FakeRunner()
    record = batch_stages.run_render(_film(tmp_path), tmp_path, runner, 600.0)
    assert record.status == "error"
    assert record.stage == "render"
    assert "capture" in record.message
    assert runner.calls == []


def test_score_record_carries_ssim_and_iou(tmp_path: Path) -> None:
    film = _film(tmp_path)
    capture = tmp_path / "build" / "parity" / "captures" / "vault-ctry" / "frames" / "001"
    capture.mkdir(parents=True)

    def score_writes_report(command: list[str], _timeout: float) -> tuple[int, str]:
        output = Path(command[command.index("--output") + 1])
        output.mkdir(parents=True, exist_ok=True)
        document = {"per_frame": [], "mean_ssim_scored": 0.7, "mean_iou_scored": 0.9}
        (output / "report.json").write_text(json.dumps(document), encoding="utf-8")
        return 0, ""

    record = batch_stages.run_score(film, tmp_path, score_writes_report, 600.0)
    assert record.status == "ok"
    assert record.stage == "score"
    assert record.ssim == 0.7
    assert record.iou == 0.9
