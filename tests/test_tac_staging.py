"""Staging for both programs: the PLAYONE mount from an explicit archive and the MAKEONE mount."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from stunt_reel import dataroot, parity_layout
from stunt_reel.tac import staging

if TYPE_CHECKING:
    from pathlib import Path

    from tac_mock import StagedRepo


def _tree(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def _no_stage_left() -> bool:
    stage_root = dataroot.data_root() / parity_layout.stage_root()
    return not stage_root.exists() or not any(stage_root.iterdir())


def test_stage_play_takes_an_explicit_archive(staged_repo: StagedRepo, tmp_path: Path) -> None:
    archive = tmp_path / "elsewhere" / "weird.All"
    archive.parent.mkdir()
    archive.write_bytes(b"stored archive")

    staged = staging.stage_play(staged_repo.film, archive)

    assert (staged.mount / "VAULT" / "CTRY.ALL").read_bytes() == b"stored archive"
    assert (staged.mount / "VAULT" / "CTRY.FLM").is_file()


def test_stage_starts_from_an_empty_mount_when_a_stale_one_has_the_label(
    staged_repo: StagedRepo,
    game_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(staging, "_stage_label", lambda: "reused")
    stale = dataroot.data_root() / parity_layout.stage_mount(staged_repo.film.stem, "reused")
    (stale / "VAULT").mkdir(parents=True)
    (stale / "VAULT" / "CTRY.ALL").write_bytes(b"left by a killed run")

    staged = staging.stage_makeone(staged_repo.film, game_root)

    assert "VAULT/CTRY.ALL" not in _tree(staged.mount)


def test_stage_makeone_holds_exactly_the_makeone_tree(
    staged_repo: StagedRepo, game_root: Path
) -> None:
    staged = staging.stage_makeone(staged_repo.film, game_root)

    assert _tree(staged.mount) == {
        *staging.MAKEONE_FILES,
        "RES/a.bin",
        "RES/sub/b.bin",
        "VAULT/CTRY.FLM",
    }


def test_stage_makeone_without_res_leaves_nothing_behind(
    staged_repo: StagedRepo, game_root: Path
) -> None:
    for leaf in sorted((game_root / "RES").rglob("*"), reverse=True):
        leaf.unlink() if leaf.is_file() else leaf.rmdir()
    (game_root / "RES").rmdir()
    with pytest.raises(FileNotFoundError, match="RES"):
        staging.stage_makeone(staged_repo.film, game_root)
    assert _no_stage_left()


def test_stage_makeone_missing_film_leaves_nothing_behind(
    staged_repo: StagedRepo, game_root: Path
) -> None:
    with pytest.raises(FileNotFoundError):
        staging.stage_makeone(staged_repo.film.with_name("NOPE.FLM"), game_root)
    assert _no_stage_left()


def test_a_failed_populate_removes_the_whole_stage(
    staged_repo: StagedRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    archive = tmp_path / "a.ALL"
    archive.write_bytes(b"x")
    monkeypatch.setattr("shutil.copy2", boom)

    with pytest.raises(OSError, match="disk full"):
        staging.stage_play(staged_repo.film, archive)
    assert _no_stage_left()


def test_stage_play_requires_the_archive(staged_repo: StagedRepo, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match=r"NOPE\.ALL"):
        staging.stage_play(staged_repo.film, tmp_path / "NOPE.ALL")
    assert _no_stage_left()


def test_stage_film_uses_the_sibling_archive(staged_repo: StagedRepo) -> None:
    staged = staging.stage_film(staged_repo.film)

    assert (staged.mount / "VAULT" / "CTRY.ALL").read_bytes() == b"ALL"


def test_two_stages_of_one_film_are_distinct(staged_repo: StagedRepo) -> None:
    first = staging.stage_film(staged_repo.film)
    second = staging.stage_film(staged_repo.film)

    assert first.root != second.root
    assert first.mount.is_dir()
    assert second.mount.is_dir()


@pytest.mark.usefixtures("staged_repo")
def test_stage_play_finds_the_engine_files_when_the_film_is_outside_a_game_tree(
    tmp_path: Path,
) -> None:
    """A film kept anywhere is staged with the demo's engine files, not its parent's neighbours."""
    film = tmp_path / "films" / "FOO.FLM"
    film.parent.mkdir()
    film.write_bytes(b"FILM")
    archive = tmp_path / "FOO.ALL"
    archive.write_bytes(b"ARCHIVE")

    staged = staging.stage_play(film, archive)

    assert set(staging.ENGINE_FILES) <= _tree(staged.mount)
    assert (staged.mount / "VAULT" / "FOO.ALL").read_bytes() == b"ARCHIVE"


def test_stage_lives_under_the_data_root_with_conf_and_mount_together(
    staged_repo: StagedRepo,
) -> None:
    """dosbox-automation refuses a mount under the checkout, so conf and mount share a stage."""
    staged = staging.stage_film(staged_repo.film)

    assert staged.mount.name == "mount"
    assert staged.root == dataroot.data_root() / parity_layout.stage_dir(
        "CTRY", staged.root.name[5:]
    )
    assert staged.conf.parent == staged.root
    assert staged.root.parent == dataroot.data_root() / parity_layout.stage_root()


def test_write_conf_names_the_port_and_the_program(staged_repo: StagedRepo) -> None:
    staged = staging.stage_film(staged_repo.film)

    conf = staged.write_conf(41234, program="makeone.exe")

    text = conf.read_text(encoding="utf-8")
    assert conf == staged.conf
    assert "webserver_port = 41234" in text
    assert f'mount c "{staged.mount}"' in text
    assert text.splitlines()[-1] == "makeone.exe"


def test_unstage_deletes_the_whole_stage(staged_repo: StagedRepo) -> None:
    staged = staging.stage_film(staged_repo.film)

    staging.unstage(staged)

    assert not staged.root.exists()
    staging.unstage(staged)  # idempotent


def test_render_conf_carries_the_automation_dials(tmp_path: Path) -> None:
    mount = tmp_path / "mount"
    text = staging.render_conf(
        mount, port=41234, program="playone.exe", capture_dir=tmp_path / "cap"
    )

    for line in (
        "webserver_enabled = true",
        "webserver_port = 41234",
        "core = normal",
        "cpu_cycles = 7000",
        "machine = svga_s3",
        "sbtype = sb16",
        "[autoexec]",
        f'mount c "{mount}"',
        "c:",
        "playone.exe",
        f"capture_dir = {tmp_path / 'cap'}",
    ):
        assert line in text.splitlines()
    assert text.index("[autoexec]") < text.index("playone.exe")


def test_render_conf_runs_the_program_it_is_given(tmp_path: Path) -> None:
    text = staging.render_conf(tmp_path, port=1, program="makeone.exe")

    assert text.splitlines()[-1] == "makeone.exe"
    assert "playone.exe" not in text
