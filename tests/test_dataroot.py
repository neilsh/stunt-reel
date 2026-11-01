"""Offline tests for ``stunt_reel.dataroot`` against synthetic checkouts in ``tmp_path``."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

import pytest

from stunt_reel import dataroot

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


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


def _primary(tmp_path: Path) -> Path:
    primary = tmp_path / "stunt-reel"
    (primary / ".git").mkdir(parents=True)
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
    primary = _checkout(monkeypatch, _primary(tmp_path))
    assert dataroot.primary_checkout() == primary
    assert dataroot.data_root() == tmp_path / "stunt-reel.data"


def test_linked_worktree_resolves_to_the_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = _primary(tmp_path)
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


def test_environment_overrides_the_derived_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _checkout(monkeypatch, _primary(tmp_path))
    monkeypatch.setenv(dataroot.DATA_ENV, str(tmp_path / "elsewhere"))
    assert dataroot.data_root() == (tmp_path / "elsewhere").resolve()


def test_ensure_links_repairs_a_worktree_that_never_ran_init(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The failure this exists for: a checkout made by an agent's own worktree tooling
    # reads corpus/stisldem as an empty placeholder instead of failing at creation.
    root = tmp_path / "stunt-reel.data"
    (root / "corpus" / "stisldem").mkdir(parents=True)
    worktree = _worktree(monkeypatch, _primary(tmp_path))
    outcomes = dataroot.ensure_links()
    assert [(outcome.relative, outcome.status) for outcome in outcomes] == [
        ("corpus/stisldem", "repaired"),
        ("corpus/siarchive", "created-empty"),
        ("corpus/stuntisl", "created-empty"),
        ("corpus/patches", "created-empty"),
        ("build/parity/captures", "created-empty"),
    ]
    for outcome in outcomes:
        assert dataroot.link_points_at(worktree / outcome.relative, outcome.target)
    assert (root / "captures").is_dir()  # a shared directory that was still empty
    assert {outcome.status for outcome in dataroot.ensure_links()} == {"ok"}


def test_ensure_links_replaces_a_gitkeep_placeholder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "stunt-reel.data"
    (root / "corpus" / "stisldem").mkdir(parents=True)
    worktree = _worktree(monkeypatch, _primary(tmp_path))
    placeholder = worktree / "corpus" / "stisldem"
    placeholder.mkdir(parents=True)
    (placeholder / ".gitkeep").write_text("", encoding="utf-8")
    repaired = [outcome for outcome in dataroot.ensure_links() if outcome.status == "repaired"]
    assert [outcome.relative for outcome in repaired] == ["corpus/stisldem"]
    assert dataroot.link_points_at(worktree / "corpus" / "stisldem", root / "corpus" / "stisldem")


def test_ensure_links_refuses_a_checkout_holding_real_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Moving a populated corpus is --migrate's decision, and it must not be half-applied.
    root = tmp_path / "stunt-reel.data"
    (root / "corpus" / "siarchive").mkdir(parents=True)
    worktree = _worktree(monkeypatch, _primary(tmp_path))
    populated = worktree / "corpus" / "siarchive"
    populated.mkdir(parents=True)
    (populated / "SITools.zip").write_bytes(b"PK\x03\x04")
    outcomes = dataroot.ensure_links()
    assert [(outcome.relative, outcome.status) for outcome in outcomes] == [
        ("corpus/siarchive", "refused")
    ]
    assert "migrate" in (outcomes[0].reason or "")
    # The refusal is all-or-nothing: the other links were not touched either.
    assert not (worktree / "corpus" / "stuntisl").exists()
    assert not (root / "corpus" / "stisldem").exists()


def test_ensure_links_replaces_a_link_that_points_elsewhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "stunt-reel.data"
    (root / "corpus" / "stisldem").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    worktree = _worktree(monkeypatch, _primary(tmp_path))
    dataroot.create_link(worktree / "corpus" / "stisldem", elsewhere)
    outcome = next(item for item in dataroot.ensure_links() if item.relative == "corpus/stisldem")
    assert (outcome.status, outcome.target) == ("repaired", root / "corpus" / "stisldem")
    assert dataroot.link_points_at(worktree / "corpus" / "stisldem", root / "corpus" / "stisldem")


def test_ensure_links_names_init_when_the_root_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _worktree(monkeypatch, _primary(tmp_path))
    with pytest.raises(dataroot.SharedDataError, match="mise run init"):
        dataroot.ensure_links()


def test_ensure_links_is_a_no_op_without_a_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _checkout(monkeypatch, tmp_path / "export")
    assert dataroot.ensure_links() == []


def test_shared_target_derives_both_names_from_the_link_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _checkout(monkeypatch, _primary(tmp_path))
    for shared, relative in dataroot.LINK_TARGETS:
        assert dataroot.shared_target(relative) == dataroot.data_root() / shared
    with pytest.raises(KeyError):
        dataroot.shared_target("corpus/elsewhere")


def test_ensure_links_or_report_renders_the_outcomes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "stunt-reel.data"
    (root / "corpus" / "stisldem").mkdir(parents=True)
    _worktree(monkeypatch, _primary(tmp_path))
    assert dataroot.ensure_links_or_report("reader")
    assert capsys.readouterr().err == "".join(
        f"reader: linked {relative}\n" for _shared, relative in dataroot.LINK_TARGETS
    )
    assert dataroot.ensure_links_or_report("reader")
    assert capsys.readouterr().err == ""


def test_ensure_links_or_report_names_a_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "stunt-reel.data"
    (root / "corpus" / "siarchive").mkdir(parents=True)
    worktree = _worktree(monkeypatch, _primary(tmp_path))
    populated = worktree / "corpus" / "siarchive"
    populated.mkdir(parents=True)
    (populated / "SITools.zip").write_bytes(b"PK\x03\x04")
    assert not dataroot.ensure_links_or_report("reader")
    err = capsys.readouterr().err
    assert err.startswith("reader: corpus/siarchive holds data of its own")
    assert "migrate" in err


def test_cache_link_points_a_worktree_at_the_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = _primary(tmp_path)
    worktree = _worktree(monkeypatch, primary)
    outcome = dataroot.ensure_cache_link()
    assert (outcome.relative, outcome.status, outcome.target) == (
        ".cache",
        "repaired",
        primary / ".cache",
    )
    assert dataroot.cache_root() == primary / ".cache"
    assert dataroot.link_points_at(worktree / ".cache", primary / ".cache")
    assert dataroot.ensure_cache_link().status == "ok"


def test_cache_link_is_a_real_directory_in_the_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = _checkout(monkeypatch, _primary(tmp_path))
    outcome = dataroot.ensure_cache_link()
    assert (outcome.relative, outcome.status) == (".cache", "ok")
    assert (primary / ".cache").is_dir()
    assert not dataroot.is_link(primary / ".cache")


def test_env_link_parks_a_worktrees_environment_in_the_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A checkout's volume usually differs from the primary's, so uv can only hardlink
    # the packages out of the cache when the environment itself sits in the cache.
    primary = _primary(tmp_path)
    worktree = _worktree(monkeypatch, primary)
    target = dataroot.env_target(worktree)
    assert dataroot.ensure_venv_link() == f"+ .venv -> {target}"
    assert target.parent == primary / ".cache" / dataroot.ENV_DIRNAME
    assert dataroot.link_points_at(worktree / ".venv", target)
    marker = dataroot.env_marker(target)
    assert marker.parent == target.parent
    assert marker.read_text(encoding="utf-8").strip() == str(worktree)
    assert dataroot.ensure_venv_link() == "= .venv"


def test_env_link_discards_a_per_checkout_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A worktree that synced before running init holds a copy on its own volume; its
    # absolute paths cannot move, so init throws the copy away instead of adopting it.
    primary = _primary(tmp_path)
    worktree = _worktree(monkeypatch, primary)
    copy = worktree / ".venv"
    (copy / "Lib" / "site-packages").mkdir(parents=True)
    (copy / "pyvenv.cfg").write_text("home = C:/Python311\n", encoding="utf-8")
    line = dataroot.ensure_venv_link()
    assert line is not None
    assert line.endswith("(per-checkout copy discarded)")
    assert dataroot.link_points_at(copy, dataroot.env_target(worktree))
    assert not (dataroot.env_target(worktree) / "pyvenv.cfg").exists()


def test_env_link_leaves_the_primary_checkout_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The primary's .venv already sits beside the cache and needs no junction.
    primary = _checkout(monkeypatch, _primary(tmp_path))
    (primary / ".venv").mkdir()
    assert dataroot.ensure_venv_link() is None
    assert not dataroot.is_link(primary / ".venv")


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
    dataroot.ensure_venv_link()
    target = dataroot.env_target(worktree)
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
    dataroot.ensure_venv_link()
    target = dataroot.env_target(worktree)
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


def test_env_link_rewrites_an_undecodable_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # init links .venv before it sweeps, so a garbled marker of its own must not stop it.
    primary = _primary(tmp_path)
    worktree = _worktree(monkeypatch, primary)
    marker = dataroot.env_marker(dataroot.env_target(worktree))
    marker.parent.mkdir(parents=True)
    marker.write_bytes(b"\xff\xfe\x80")
    assert dataroot.ensure_venv_link() is not None
    assert marker.read_text(encoding="utf-8").strip() == str(worktree)


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


def test_cache_link_adopts_a_cache_made_before_the_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The first uv sync of a worktree runs before mise run init links the cache.
    primary = _primary(tmp_path)
    worktree = _worktree(monkeypatch, primary)
    partial = worktree / ".cache" / "uv"
    partial.mkdir(parents=True)
    (partial / "artifact").write_bytes(b"cache")
    outcome = dataroot.ensure_cache_link()
    assert (outcome.status, outcome.target) == ("repaired", primary / ".cache")
    assert (primary / ".cache" / "uv" / "artifact").read_bytes() == b"cache"
    assert dataroot.link_points_at(worktree / ".cache", primary / ".cache")


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
    assert (root / "captures" / "vault-ctry" / "frames" / "001" / "meta.json").is_file()
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
    # ensure_links creates corpus/<name> and captures empty when a read precedes --migrate.
    root = tmp_path / "stunt-reel.data"
    _old_layout(root)
    (root / "corpus" / "stuntisl").mkdir(parents=True)
    (root / "captures").mkdir()
    dataroot.convert_layout(root)
    assert (root / "corpus" / "stuntisl" / "PLAYONE.EXE").is_file()
    assert not (root / "corpus" / "stuntisl" / "stuntisl").exists()
    assert (root / "captures" / "vault-ctry" / "frames" / "001" / "meta.json").is_file()


def test_convert_layout_keeps_foreign_files_in_the_old_oracle(tmp_path: Path) -> None:
    root = tmp_path / "stunt-reel.data"
    _old_layout(root)
    (root / "oracle" / "mine.json").write_text("[]", encoding="utf-8")
    moved = dataroot.convert_layout(root)
    assert not (root / "oracle" / "intro_trajectory.json").exists()
    assert (root / "oracle" / "mine.json").is_file()
    assert any("oracle still holds" in line for line in moved)
