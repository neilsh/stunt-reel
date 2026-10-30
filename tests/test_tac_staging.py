"""Staging for both programs: the PLAYONE mount from an explicit archive and the MAKEONE mount."""

from __future__ import annotations

from pathlib import Path

import pytest

from stunt_reel import dataroot, parity_layout
from stunt_reel.tac import staging
from tac_mock import StagedRepo

REAL_CONF = Path(__file__).resolve().parent.parent / "tools" / "dosbox" / "dosbox-parity.conf"
BACKSLASH = chr(92)
FILM_LITERAL = f"VAULT{BACKSLASH}CTRY.FLM"
MOUNT_LINE = 'mount c "corpus/stisldem"\n'
CONF_WITH_PLAYONE = MOUNT_LINE + f"title {FILM_LITERAL}\n[autoexec]\nc:\nplayone.exe\n"
CONF_WITHOUT_PLAYONE = MOUNT_LINE + f"title {FILM_LITERAL}\n"


def _tree(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def _no_stage_left() -> bool:
    stage_root = dataroot.REPO_ROOT / parity_layout.stage_root()
    return not stage_root.exists() or not any(stage_root.iterdir())


def test_stage_play_takes_an_explicit_archive(
    staged_repo: StagedRepo,
    tmp_path: Path,
) -> None:
    archive = tmp_path / "elsewhere" / "weird.All"
    archive.parent.mkdir()
    archive.write_bytes(b"stored archive")

    mount, _conf = staging.stage_play(staged_repo.film, archive, staged_repo.conf)

    assert (mount / "VAULT" / "CTRY.ALL").read_bytes() == b"stored archive"
    assert (mount / "VAULT" / "CTRY.FLM").is_file()


def test_stage_starts_from_an_empty_mount_when_a_stale_one_has_the_label(
    staged_repo: StagedRepo,
    game_root: Path,
    makeone_conf: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(staging, "_stage_label", lambda: "reused")
    stale = dataroot.REPO_ROOT / parity_layout.stage_dir(staged_repo.film.stem, "reused")
    (stale / "VAULT").mkdir(parents=True)
    (stale / "VAULT" / "CTRY.ALL").write_bytes(b"left by a killed run")

    mount, _conf = staging.stage_makeone(staged_repo.film, game_root, makeone_conf)

    assert "VAULT/CTRY.ALL" not in _tree(mount)


def test_stage_makeone_holds_exactly_the_makeone_tree(
    staged_repo: StagedRepo,
    game_root: Path,
    makeone_conf: Path,
) -> None:
    mount, _conf = staging.stage_makeone(staged_repo.film, game_root, makeone_conf)

    assert _tree(mount) == {
        *staging.MAKEONE_FILES,
        "RES/a.bin",
        "RES/sub/b.bin",
        "VAULT/CTRY.FLM",
    }


def test_stage_makeone_rewrites_the_real_conf(
    staged_repo: StagedRepo,
    game_root: Path,
) -> None:
    mount, conf = staging.stage_makeone(staged_repo.film, game_root, REAL_CONF)

    text = conf.read_text(encoding="utf-8")
    assert "makeone.exe" in text
    assert "playone.exe" not in text
    assert f'mount c "{mount.relative_to(dataroot.REPO_ROOT).as_posix()}"' in text
    assert FILM_LITERAL in text


def test_stage_makeone_rewrites_the_playone_line(
    staged_repo: StagedRepo,
    game_root: Path,
    tmp_path: Path,
) -> None:
    conf = tmp_path / "ok.conf"
    conf.write_text(CONF_WITH_PLAYONE, encoding="utf-8")
    _mount, staged = staging.stage_makeone(staged_repo.film, game_root, conf)
    assert staged.read_text(encoding="utf-8").endswith("\nmakeone.exe\n")


def test_stage_makeone_rejects_a_conf_without_the_playone_line(
    staged_repo: StagedRepo,
    game_root: Path,
    tmp_path: Path,
) -> None:
    conf = tmp_path / "no-autoexec.conf"
    conf.write_text(CONF_WITHOUT_PLAYONE, encoding="utf-8")
    with pytest.raises(RuntimeError, match="does not contain"):
        staging.stage_makeone(staged_repo.film, game_root, conf)
    assert _no_stage_left()


def test_stage_makeone_without_res_leaves_nothing_behind(
    staged_repo: StagedRepo,
    game_root: Path,
    makeone_conf: Path,
) -> None:
    for leaf in sorted((game_root / "RES").rglob("*"), reverse=True):
        leaf.unlink() if leaf.is_file() else leaf.rmdir()
    (game_root / "RES").rmdir()
    with pytest.raises(FileNotFoundError, match="RES"):
        staging.stage_makeone(staged_repo.film, game_root, makeone_conf)
    assert _no_stage_left()


def test_stage_makeone_missing_film_leaves_nothing_behind(
    staged_repo: StagedRepo,
    game_root: Path,
    makeone_conf: Path,
) -> None:
    with pytest.raises(FileNotFoundError):
        staging.stage_makeone(staged_repo.film.with_name("NOPE.FLM"), game_root, makeone_conf)
    assert _no_stage_left()


def test_stage_play_finds_the_engine_files_when_the_film_is_outside_a_game_tree(
    staged_repo: StagedRepo,
    tmp_path: Path,
) -> None:
    """A film kept anywhere is staged with the demo's engine files, not its parent's neighbours."""
    film = tmp_path / "films" / "FOO.FLM"
    film.parent.mkdir()
    film.write_bytes(b"FILM")
    archive = tmp_path / "FOO.ALL"
    archive.write_bytes(b"ARCHIVE")

    mount, _conf = staging.stage_play(film, archive, staged_repo.conf)

    assert set(staging.ENGINE_FILES) <= _tree(mount)
    assert (mount / "VAULT" / "FOO.ALL").read_bytes() == b"ARCHIVE"
