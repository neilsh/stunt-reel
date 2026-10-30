"""The make-all command: ids, refusals, validation and what gets published."""

from __future__ import annotations

import functools
import hashlib
import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

from archive_helpers import build_all
from stunt_reel import dataroot, parity_layout
from stunt_reel.all_archive import ArchiveMeta
from tac_mock import StagedRepo, makeone_guest

SCRIPTS = Path(__file__).resolve().parent.parent / "python" / "scripts"
ARCHIVE = build_all([b"one", b"two"])


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("make_all", SCRIPTS / "make_all.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script(monkeypatch: pytest.MonkeyPatch) -> Any:
    module = _load()
    monkeypatch.setattr(module, "ensure_links_or_report", lambda _program: True)
    # The real poll interval is 2 s per wait; the mock guest answers at once.
    monkeypatch.setattr(
        module.makeone, "make_all", functools.partial(module.makeone.make_all, poll=0.0)
    )
    return module


def _args(
    script: Any,
    monkeypatch: pytest.MonkeyPatch,
    film: Path,
    game_root: Path,
    conf: Path,
    *extra: str,
) -> Any:
    argv = [
        "make_all.py",
        "--film",
        str(film),
        "--game-root",
        str(game_root),
        "--conf",
        str(conf),
        *extra,
    ]
    monkeypatch.setattr(sys, "argv", argv)
    return script.parse_args()


def _archives(film: str = "ctry") -> list[Path]:
    root = dataroot.REPO_ROOT / parity_layout.all_root() / film
    return sorted(root.iterdir()) if root.exists() else []


def test_a_run_publishes_the_archive_with_meta(
    script: Any,
    monkeypatch: pytest.MonkeyPatch,
    staged_repo: StagedRepo,
    game_root: Path,
    makeone_conf: Path,
) -> None:
    emulator, _keys = makeone_guest(text_after=1, archive=ARCHIVE)
    args = _args(script, monkeypatch, staged_repo.film, game_root, makeone_conf, "--timeout", "30")

    assert script.run(args, emulator) == 0

    (directory,) = _archives()
    assert (directory / "CTRY.ALL").read_bytes() == ARCHIVE
    meta = ArchiveMeta.from_json((directory / "meta.json").read_text(encoding="utf-8"))
    assert meta.flm_sha256 == hashlib.sha256(staged_repo.film.read_bytes()).hexdigest()
    assert meta.all_sha256 == hashlib.sha256(ARCHIVE).hexdigest()
    assert dict(meta.game_files)["MAKEONE.EXE"] == (game_root / "MAKEONE.EXE").stat().st_size


def test_the_all_stem_is_refused_before_launch(
    script: Any,
    monkeypatch: pytest.MonkeyPatch,
    staged_repo: StagedRepo,
    game_root: Path,
    makeone_conf: Path,
) -> None:
    film = staged_repo.film.with_name("ALL.FLM")
    film.write_bytes(b"FILM")
    emulator, _keys = makeone_guest(text_after=1, archive=ARCHIVE)

    assert script.run(_args(script, monkeypatch, film, game_root, makeone_conf), emulator) == 2

    assert not emulator.started
    assert _archives("all") == []


def test_an_existing_id_is_refused_before_launch(
    script: Any,
    monkeypatch: pytest.MonkeyPatch,
    staged_repo: StagedRepo,
    game_root: Path,
    makeone_conf: Path,
) -> None:
    first, _keys = makeone_guest(text_after=1, archive=ARCHIVE)
    args = _args(script, monkeypatch, staged_repo.film, game_root, makeone_conf)
    assert script.run(args, first) == 0
    (directory,) = _archives()
    before = {p.name: p.read_bytes() for p in directory.iterdir()}

    second, _keys = makeone_guest(text_after=1, archive=build_all([b"other"]))
    assert script.run(args, second) == 2

    assert not second.started
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == before


def test_a_non_archive_is_rejected_and_publishes_nothing(
    script: Any,
    monkeypatch: pytest.MonkeyPatch,
    staged_repo: StagedRepo,
    game_root: Path,
    makeone_conf: Path,
) -> None:
    emulator, _keys = makeone_guest(text_after=1, archive=b"junk")
    args = _args(script, monkeypatch, staged_repo.film, game_root, makeone_conf)

    assert script.run(args, emulator) == 1
    assert _archives() == []


def test_a_publish_failure_is_a_make_all_line_and_exit_1(
    script: Any,
    monkeypatch: pytest.MonkeyPatch,
    staged_repo: StagedRepo,
    game_root: Path,
    makeone_conf: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def full_disk(*_args: object) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr(script, "publish_archive", full_disk)
    emulator, _keys = makeone_guest(text_after=1, archive=ARCHIVE)
    args = _args(script, monkeypatch, staged_repo.film, game_root, makeone_conf)

    assert script.run(args, emulator) == 1
    assert "[make-all] could not store the archive: disk full" in capsys.readouterr().err


def test_a_missing_game_file_is_a_make_all_line_and_exit_1(
    script: Any,
    monkeypatch: pytest.MonkeyPatch,
    staged_repo: StagedRepo,
    game_root: Path,
    makeone_conf: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    emulator, _keys = makeone_guest(text_after=1, archive=ARCHIVE)
    args = _args(script, monkeypatch, staged_repo.film, game_root, makeone_conf)
    original = script.makeone.make_all

    def vanish(*a: Any, **k: Any) -> bytes:
        data: bytes = original(*a, **k)
        (game_root / "MAKEONE.EXE").unlink()
        return data

    monkeypatch.setattr(script.makeone, "make_all", vanish)

    assert script.run(args, emulator) == 1
    assert "[make-all]" in capsys.readouterr().err
    assert _archives() == []


def test_a_timeout_exits_1_and_leaves_no_mount(
    script: Any,
    monkeypatch: pytest.MonkeyPatch,
    staged_repo: StagedRepo,
    game_root: Path,
    makeone_conf: Path,
) -> None:
    emulator, _keys = makeone_guest(text_after=None, archive=None)
    args = _args(
        script, monkeypatch, staged_repo.film, game_root, makeone_conf, "--timeout", "0.01"
    )

    assert script.run(args, emulator) == 1
    assert _archives() == []
    stage_root = dataroot.REPO_ROOT / parity_layout.stage_root()
    assert not stage_root.exists() or not any(stage_root.iterdir())
