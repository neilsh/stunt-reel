"""Offline tests for ``stunt_reel.dataroot`` against synthetic checkouts in ``tmp_path``."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from stunt_reel import dataroot, parity_layout

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.windows


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Drop the caller's overrides and the cached root around every test."""
    monkeypatch.delenv(dataroot.DATA_ENV, raising=False)
    dataroot.data_root.cache_clear()
    yield
    dataroot.data_root.cache_clear()


def _checkout(monkeypatch: pytest.MonkeyPatch, root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(dataroot, "REPO_ROOT", root)
    return root


def _primary(tmp_path: Path, *, data: bool = False) -> Path:
    """A primary checkout, with an empty data root beside it when *data* is true."""
    primary = tmp_path / "stunt-reel"
    (primary / ".git").mkdir(parents=True)
    if data:
        (tmp_path / "stunt-reel.data").mkdir()
    return primary


def _worktree(monkeypatch: pytest.MonkeyPatch, primary: Path, slug: str = "slug") -> Path:
    """A linked worktree sitting inside the primary, with an empty data root beside it."""
    gitdir = primary / ".git" / "worktrees" / slug
    gitdir.mkdir(parents=True)
    worktree = _checkout(monkeypatch, primary / ".agents" / "worktrees" / slug)
    (worktree / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    return worktree


def test_primary_checkout_owns_the_git_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = _checkout(monkeypatch, _primary(tmp_path, data=True))
    assert dataroot.primary_checkout() == primary
    assert dataroot.data_root() == tmp_path / "stunt-reel.data"


def test_linked_worktree_resolves_to_the_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = _primary(tmp_path, data=True)
    gitdir = primary / ".git" / "worktrees" / "slug"
    gitdir.mkdir(parents=True)
    # Inside the primary, as the desktop app and .agents/worktrees place them.
    worktree = _checkout(monkeypatch, primary / ".agents" / "worktrees" / "slug")
    (worktree / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    assert dataroot.primary_checkout() == primary
    assert dataroot.data_root() == tmp_path / "stunt-reel.data"


def test_outside_git_the_checkout_is_its_own_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _checkout(monkeypatch, tmp_path / "export")
    assert dataroot.primary_checkout() is None
    assert dataroot.data_root() == root


def test_a_missing_data_root_falls_back_to_the_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A clone that keeps its corpus in the checkout has no <primary>.data beside it.
    primary = _primary(tmp_path)
    (primary / "corpus" / "stisldem").mkdir(parents=True)
    _worktree(monkeypatch, primary)
    film = Path("corpus/stisldem/VAULT/CTRY.FLM")
    assert dataroot.corpus_root() == primary / "corpus"
    assert dataroot.resolve_data_path(film) == primary / film
    # The captures and the stage are written, so they stay beside the primary.
    assert dataroot.data_root() == tmp_path / "stunt-reel.data"


def test_a_data_root_with_a_corpus_wins_over_the_primarys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = _primary(tmp_path)
    (tmp_path / "stunt-reel.data" / "corpus").mkdir(parents=True)
    _worktree(monkeypatch, primary)
    assert dataroot.corpus_root() == tmp_path / "stunt-reel.data" / "corpus"


def test_corpus_root_is_under_the_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(dataroot.DATA_ENV, str(tmp_path))
    assert dataroot.corpus_root() == tmp_path.resolve() / "corpus"


def test_a_relative_corpus_path_resolves_against_the_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(dataroot.DATA_ENV, str(tmp_path))
    film = Path("corpus/stisldem/VAULT/CTRY.FLM")
    assert dataroot.resolve_data_path(film) == tmp_path.resolve() / film
    assert dataroot.resolve_data_path(Path("captures/x")) == tmp_path.resolve() / "captures/x"
    assert dataroot.data_path_arg(film.as_posix()) == tmp_path.resolve() / film


def test_other_paths_resolve_to_themselves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(dataroot.DATA_ENV, str(tmp_path))
    for path in (Path("build/re/playone.img"), tmp_path / "corpus" / "x", Path("corpusx/a")):
        assert dataroot.resolve_data_path(path) == path


def test_the_override_moves_captures_too(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(dataroot.DATA_ENV, str(tmp_path))
    frames = parity_layout.frames_path("vault-ctry")
    assert dataroot.resolve_data_path(frames) == tmp_path.resolve() / "captures/vault-ctry/frames"


def test_environment_overrides_the_derived_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _checkout(monkeypatch, _primary(tmp_path))
    monkeypatch.setenv(dataroot.DATA_ENV, str(tmp_path / "elsewhere"))
    assert dataroot.data_root() == (tmp_path / "elsewhere").resolve()


def _legacy_env(worktree: Path) -> Path:
    """An environment an older init parked in the cache for *worktree*, with its marker."""
    target = dataroot.env_target(worktree)
    target.mkdir(parents=True)
    dataroot.env_marker(target).write_text(f"{worktree}\n", encoding="utf-8")
    return target


def test_env_target_is_stable_and_per_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = _primary(tmp_path)
    first = _worktree(monkeypatch, primary, slug="one")
    target = dataroot.env_target(first)
    assert dataroot.env_target(first) == target
    assert dataroot.env_target(_worktree(monkeypatch, primary, slug="two")) != target
    assert target.parent == dataroot.env_root()


def test_orphan_envs_are_the_ones_whose_checkout_is_gone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = _primary(tmp_path)
    worktree = _worktree(monkeypatch, primary)
    target = _legacy_env(worktree)
    assert dataroot.orphan_envs() == []
    shutil.rmtree(worktree)
    _checkout(monkeypatch, primary)
    assert dataroot.orphan_envs() == [target]
    assert dataroot.sweep_orphan_envs() == [target]
    assert not target.exists()
    assert not dataroot.env_marker(target).exists()


def test_env_marker_survives_uv_replacing_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # uv empties the environment directory when the interpreter no longer satisfies
    # requires-python; a marker inside it went too, and another worktree's init then
    # swept the live environment as an orphan.
    primary = _primary(tmp_path)
    worktree = _worktree(monkeypatch, primary)
    target = _legacy_env(worktree)
    shutil.rmtree(target)
    target.mkdir()
    _checkout(monkeypatch, primary)
    assert dataroot.orphan_envs() == []
    shutil.rmtree(worktree)
    assert dataroot.orphan_envs() == [target]


def test_an_environment_of_unknown_owner_is_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No marker proves nothing about the checkout; only a named checkout that is gone
    # makes an environment an orphan.
    _checkout(monkeypatch, _primary(tmp_path))
    unknown = dataroot.env_root() / "unknown-00000000"
    unknown.mkdir(parents=True)
    assert dataroot.orphan_envs() == []
    assert dataroot.sweep_orphan_envs() == []
    assert unknown.is_dir()


@pytest.mark.parametrize("content", [b"\xff\xfe\x80", b"  \n"], ids=["undecodable", "empty"])
def test_an_unreadable_marker_is_an_unknown_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: bytes
) -> None:
    # A marker that is not UTF-8 names no checkout, and an empty one would read as the
    # current directory; init must keep the environment and keep going, not raise.
    _checkout(monkeypatch, _primary(tmp_path))
    unknown = dataroot.env_root() / "garbled-00000000"
    unknown.mkdir(parents=True)
    dataroot.env_marker(unknown).write_bytes(content)
    assert dataroot.orphan_envs() == []
    assert unknown.is_dir()


def test_a_marker_inside_the_environment_still_names_its_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Environments made before the marker moved beside them keep it inside until their
    # checkout's next init.
    _checkout(monkeypatch, _primary(tmp_path))
    legacy = dataroot.env_root() / "gone-00000000"
    legacy.mkdir(parents=True)
    (legacy / dataroot.ENV_MARKER).write_text(str(tmp_path / "gone"), encoding="utf-8")
    assert dataroot.orphan_envs() == [legacy]
    assert dataroot.sweep_orphan_envs() == [legacy]
    assert not legacy.exists()


def test_a_marker_without_its_environment_is_swept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # An environment deleted by hand leaves its marker beside it; the sweep removes it,
    # and discard_env does too for a checkout whose environment is already gone.
    _checkout(monkeypatch, _primary(tmp_path))
    stray = dataroot.env_marker(dataroot.env_root() / "gone-00000000")
    stray.parent.mkdir(parents=True)
    stray.write_text(str(tmp_path / "gone"), encoding="utf-8")
    assert dataroot.sweep_orphan_envs() == []
    assert not stray.exists()
    gone = tmp_path / "other"
    marker = dataroot.env_marker(dataroot.env_target(gone))
    marker.write_text(str(gone), encoding="utf-8")
    assert dataroot.discard_env(gone) is False
    assert not marker.exists()


def _old_layout(root: Path) -> None:
    for name in ("stisldem", "si_archive", "oracle", "target_bin/StuntIsl", "target_bin/patch"):
        (root / name).mkdir(parents=True)
    (root / "stisldem" / "A.TXT").write_text("a", encoding="utf-8")
    (root / "target_bin" / "StuntIsl" / "PLAYONE.EXE").write_bytes(b"MZ")
    (root / "target_bin" / "PLAYONE.EXE").write_bytes(b"MZ")
    (root / "oracle" / "intro_trajectory.json").write_text("[]", encoding="utf-8")
    (root / "reference" / "ctry").mkdir(parents=True)
    (root / "reference" / "ctry" / "meta.json").write_text("{}", encoding="utf-8")


def test_convert_layout_moves_an_old_root_to_corpus_and_captures(tmp_path: Path) -> None:
    root = tmp_path / "stunt-reel.data"
    _old_layout(root)
    moved = dataroot.convert_layout(root)
    assert (root / "corpus" / "stisldem" / "A.TXT").is_file()
    assert (root / "corpus" / "siarchive").is_dir()
    assert (root / "corpus" / "stuntisl" / "PLAYONE.EXE").is_file()
    assert (root / "corpus" / "patches").is_dir()
    assert (root / "captures" / "vault-ctry" / "frames" / "meta.json").is_file()
    for old in ("stisldem", "si_archive", "oracle", "target_bin", "reference"):
        assert not (root / old).exists()
    assert any("oracle/intro_trajectory.json removed" in line for line in moved)
    assert dataroot.convert_layout(root) == []  # a converted root is left alone


def test_convert_layout_keeps_a_different_top_level_executable(tmp_path: Path) -> None:
    root = tmp_path / "stunt-reel.data"
    _old_layout(root)
    (root / "target_bin" / "PLAYONE.EXE").write_bytes(b"MZ-other")
    moved = dataroot.convert_layout(root)
    assert (root / "target_bin" / "PLAYONE.EXE").read_bytes() == b"MZ-other"
    assert any("target_bin still holds" in line for line in moved)


def test_convert_layout_refuses_a_root_holding_both_names(tmp_path: Path) -> None:
    root = tmp_path / "stunt-reel.data"
    _old_layout(root)
    (root / "corpus").mkdir()
    (root / "corpus" / "README.md").write_text("new", encoding="utf-8")
    with pytest.raises(dataroot.SharedDataError, match="both old names"):
        dataroot.convert_layout(root)
    assert (root / "stisldem" / "A.TXT").is_file()  # nothing moved


def test_convert_layout_accepts_the_empty_directories_a_read_created(tmp_path: Path) -> None:
    # An older layout's links created corpus/<name> and captures empty before a --migrate.
    root = tmp_path / "stunt-reel.data"
    _old_layout(root)
    (root / "corpus" / "stuntisl").mkdir(parents=True)
    (root / "captures").mkdir()
    dataroot.convert_layout(root)
    assert (root / "corpus" / "stuntisl" / "PLAYONE.EXE").is_file()
    assert not (root / "corpus" / "stuntisl" / "stuntisl").exists()
    assert (root / "captures" / "vault-ctry" / "frames" / "meta.json").is_file()


def test_convert_layout_keeps_foreign_files_in_the_old_oracle(tmp_path: Path) -> None:
    root = tmp_path / "stunt-reel.data"
    _old_layout(root)
    (root / "oracle" / "mine.json").write_text("[]", encoding="utf-8")
    moved = dataroot.convert_layout(root)
    assert not (root / "oracle" / "intro_trajectory.json").exists()
    assert (root / "oracle" / "mine.json").is_file()
    assert any("oracle still holds" in line for line in moved)


def test_a_primary_corpus_holding_only_its_readmes_is_no_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``corpus/README.md`` is tracked, so the folder exists in every checkout, game files or not."""
    primary = _primary(tmp_path)
    (primary / "corpus").mkdir()
    (primary / "corpus" / "README.md").write_text("readme", encoding="utf-8")
    _worktree(monkeypatch, primary)
    assert dataroot.corpus_root() == tmp_path / "stunt-reel.data" / "corpus"


def test_require_corpus_names_the_missing_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(dataroot.DATA_ENV, str(tmp_path / "data"))
    with pytest.raises(dataroot.SharedDataError, match="no game files") as caught:
        dataroot.require_corpus()
    assert str((tmp_path / "data").resolve() / "corpus") in str(caught.value)
    _game_file(tmp_path / "data" / "corpus")
    assert dataroot.require_corpus() == (tmp_path / "data").resolve() / "corpus"


def test_require_corpus_of_a_named_root(tmp_path: Path) -> None:
    with pytest.raises(dataroot.SharedDataError, match="no game files"):
        dataroot.require_corpus(tmp_path)
    _game_file(tmp_path / "corpus")
    assert dataroot.require_corpus(tmp_path) == tmp_path / "corpus"


def _game_file(corpus: Path) -> None:
    (corpus / "stisldem").mkdir(parents=True)
    (corpus / "stisldem" / "PLAYONE.EXE").write_bytes(b"MZ")


def test_require_corpus_refuses_the_empty_folders_an_old_layout_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The old links created ``corpus/<name>`` empty; folders with no file in them are no corpus."""
    monkeypatch.setenv(dataroot.DATA_ENV, str(tmp_path))
    for name in ("stisldem", "siarchive", "stuntisl", "patches"):
        (tmp_path / "corpus" / name).mkdir(parents=True)
    with pytest.raises(dataroot.SharedDataError, match="holds no game files"):
        dataroot.require_corpus()


def test_an_unreadable_primary_corpus_is_raised_not_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Falling back past it would send the user to look for the game files in the wrong place."""
    primary = _primary(tmp_path)
    (primary / "corpus").mkdir()
    _worktree(monkeypatch, primary)

    def refused(_self: Path) -> None:
        raise PermissionError("access denied")

    monkeypatch.setattr(Path, "iterdir", refused)
    with pytest.raises(PermissionError):
        dataroot.corpus_root()


def test_a_capitalised_corpus_path_resolves_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows paths are case-insensitive, so ``Corpus\\...`` names the same folder."""
    monkeypatch.setenv(dataroot.DATA_ENV, str(tmp_path))
    resolved = dataroot.resolve_data_path(Path("Corpus/stisldem/X.FLM"))
    assert resolved == tmp_path.resolve() / "corpus" / "stisldem" / "X.FLM"


def test_require_corpus_refuses_a_corpus_holding_only_its_readmes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A checkout that is its own data root has a tracked ``corpus/README.md`` and no game files."""
    monkeypatch.setenv(dataroot.DATA_ENV, str(tmp_path))
    (tmp_path / "corpus").mkdir()
    (tmp_path / "corpus" / "README.md").write_text("readme", encoding="utf-8")
    with pytest.raises(dataroot.SharedDataError, match="holds no game files"):
        dataroot.require_corpus()
