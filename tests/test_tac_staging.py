"""Staging for both programs: the PLAYONE mount from an explicit archive and the MAKEONE mount."""

from __future__ import annotations

from pathlib import Path

import pytest

from stunt_reel import dataroot, parity_layout
from stunt_reel.tac import staging
from tac_mock import StagedRepo, staged_repo  # noqa: F401  (the fixture)

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


@pytest.fixture
def game_root(tmp_path: Path) -> Path:
    root = tmp_path / "game"
    root.mkdir()
    for name in staging.MAKEONE_FILES:
        (root / name).write_bytes(b"x" + name.encode())
    (root / "RES" / "sub").mkdir(parents=True)
    (root / "RES" / "a.bin").write_bytes(b"a")
    (root / "RES" / "sub" / "b.bin").write_bytes(b"b")
    (root / "VAULT").mkdir()
    (root / "VAULT" / "OTHER.FLM").write_bytes(b"o")
    (root / "VAULT" / "OTHER.TKE").write_bytes(b"t")
    (root / "SETS").mkdir()
    (root / "SETS" / "X.SET").write_bytes(b"s")
    return root


@pytest.fixture
def makeone_conf(tmp_path: Path) -> Path:
    conf = tmp_path / "makeone.conf"
    conf.write_text(CONF_WITH_PLAYONE, encoding="utf-8")
    return conf


def test_stage_play_takes_an_explicit_archive(
    staged_repo: StagedRepo,  # noqa: F811
    tmp_path: Path,
) -> None:
    archive = tmp_path / "elsewhere" / "weird.All"
    archive.parent.mkdir()
    archive.write_bytes(b"stored archive")

    mount, _conf = staging.stage_play(staged_repo.film, archive, staged_repo.conf)

    assert (mount / "VAULT" / "CTRY.ALL").read_bytes() == b"stored archive"
    assert (mount / "VAULT" / "CTRY.FLM").is_file()


def test_stage_makeone_holds_exactly_the_makeone_tree(
    staged_repo: StagedRepo,  # noqa: F811
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
    staged_repo: StagedRepo,  # noqa: F811
    game_root: Path,
) -> None:
    mount, conf = staging.stage_makeone(staged_repo.film, game_root, REAL_CONF)

    text = conf.read_text(encoding="utf-8")
    assert "makeone.exe" in text
    assert "playone.exe" not in text
    assert f'mount c "{mount.relative_to(dataroot.REPO_ROOT).as_posix()}"' in text
    assert FILM_LITERAL in text


def test_stage_makeone_rewrites_the_playone_line(
    staged_repo: StagedRepo,  # noqa: F811
    game_root: Path,
    tmp_path: Path,
) -> None:
    conf = tmp_path / "ok.conf"
    conf.write_text(CONF_WITH_PLAYONE, encoding="utf-8")
    _mount, staged = staging.stage_makeone(staged_repo.film, game_root, conf)
    assert staged.read_text(encoding="utf-8").endswith("\nmakeone.exe\n")


def test_stage_makeone_rejects_a_conf_without_the_playone_line(
    staged_repo: StagedRepo,  # noqa: F811
    game_root: Path,
    tmp_path: Path,
) -> None:
    conf = tmp_path / "no-autoexec.conf"
    conf.write_text(CONF_WITHOUT_PLAYONE, encoding="utf-8")
    with pytest.raises(RuntimeError, match="does not contain"):
        staging.stage_makeone(staged_repo.film, game_root, conf)
    assert _no_stage_left()


def test_stage_makeone_without_res_leaves_nothing_behind(
    staged_repo: StagedRepo,  # noqa: F811
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
    staged_repo: StagedRepo,  # noqa: F811
    game_root: Path,
    makeone_conf: Path,
) -> None:
    with pytest.raises(FileNotFoundError):
        staging.stage_makeone(staged_repo.film.with_name("NOPE.FLM"), game_root, makeone_conf)
    assert _no_stage_left()
