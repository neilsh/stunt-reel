"""Offline tests for ``stunt_reel.dataroot`` against synthetic checkouts in ``tmp_path``."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from stunt_reel import dataroot


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Drop the caller's overrides and the cached root around every test."""
    monkeypatch.delenv(dataroot.DATA_ENV, raising=False)
    monkeypatch.delenv(dataroot.WRITE_ENV, raising=False)
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
    assert not dataroot.is_shared(root / "corpus")


def test_environment_overrides_the_derived_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _checkout(monkeypatch, _primary(tmp_path))
    monkeypatch.setenv(dataroot.DATA_ENV, str(tmp_path / "elsewhere"))
    assert dataroot.data_root() == (tmp_path / "elsewhere").resolve()


def test_is_shared_separates_the_root_from_the_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = _checkout(monkeypatch, _primary(tmp_path))
    assert dataroot.is_shared(tmp_path / "stunt-reel.data" / "reference" / "ctry")
    assert not dataroot.is_shared(primary / "build" / "parity" / "ours")


def test_is_shared_follows_the_linked_reference_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # capture-ref's default --out reaches the shared captures only through this link,
    # so is_shared must see through it or the write opt-in is silently skipped.
    primary = _checkout(monkeypatch, _primary(tmp_path))
    target = tmp_path / "stunt-reel.data" / "reference"
    target.mkdir(parents=True)
    link = primary / "build" / "parity" / "reference"
    dataroot.create_link(link, target)
    assert dataroot.is_shared(link / "ctry")


def test_shared_write_needs_the_opt_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _checkout(monkeypatch, _primary(tmp_path))
    with pytest.raises(dataroot.SharedWriteError, match=dataroot.WRITE_ENV):
        dataroot.require_shared_write("capture")
    monkeypatch.setenv(dataroot.WRITE_ENV, "1")
    dataroot.require_shared_write("capture")


def test_ensure_links_repairs_a_worktree_that_never_ran_init(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The failure this exists for: a checkout made by an agent's own worktree tooling
    # reads corpus/stisldem as an empty placeholder instead of failing at creation.
    root = tmp_path / "stunt-reel.data"
    (root / "stisldem").mkdir(parents=True)
    worktree = _worktree(monkeypatch, _primary(tmp_path))
    assert dataroot.ensure_links() == [relative for _, relative in dataroot.LINK_TARGETS]
    for shared, relative in dataroot.LINK_TARGETS:
        assert dataroot.link_points_at(worktree / relative, root / shared)
    assert (root / "reference").is_dir()  # a shared directory that was still empty
    assert dataroot.ensure_links() == []


def test_ensure_links_replaces_a_gitkeep_placeholder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "stunt-reel.data"
    (root / "stisldem").mkdir(parents=True)
    worktree = _worktree(monkeypatch, _primary(tmp_path))
    placeholder = worktree / "corpus" / "stisldem"
    placeholder.mkdir(parents=True)
    (placeholder / ".gitkeep").write_text("", encoding="utf-8")
    assert "corpus/stisldem" in dataroot.ensure_links()
    assert dataroot.link_points_at(worktree / "corpus" / "stisldem", root / "stisldem")


def test_ensure_links_refuses_a_checkout_holding_real_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Moving a populated corpus is --migrate's decision, and it must not be half-applied.
    root = tmp_path / "stunt-reel.data"
    (root / "si_archive").mkdir(parents=True)
    worktree = _worktree(monkeypatch, _primary(tmp_path))
    populated = worktree / "corpus" / "siarchive"
    populated.mkdir(parents=True)
    (populated / "SITools.zip").write_bytes(b"PK\x03\x04")
    with pytest.raises(dataroot.SharedDataError, match="migrate"):
        dataroot.ensure_links()
    assert not (worktree / "target_bin").exists()


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


def test_cache_link_points_a_worktree_at_the_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = _primary(tmp_path)
    worktree = _worktree(monkeypatch, primary)
    assert dataroot.ensure_cache_link() == f"+ .cache -> {primary / '.cache'}"
    assert dataroot.cache_root() == primary / ".cache"
    assert dataroot.link_points_at(worktree / ".cache", primary / ".cache")
    assert dataroot.ensure_cache_link() == "= .cache"


def test_cache_link_is_a_real_directory_in_the_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = _checkout(monkeypatch, _primary(tmp_path))
    assert dataroot.ensure_cache_link() == "= .cache"
    assert (primary / ".cache").is_dir()
    assert not dataroot.is_link(primary / ".cache")


def test_cache_link_adopts_a_cache_made_before_the_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The first uv sync of a worktree runs before mise run init links the cache.
    primary = _primary(tmp_path)
    worktree = _worktree(monkeypatch, primary)
    partial = worktree / ".cache" / "uv"
    partial.mkdir(parents=True)
    (partial / "artifact").write_bytes(b"cache")
    assert dataroot.ensure_cache_link().startswith("+ .cache ->")
    assert (primary / ".cache" / "uv" / "artifact").read_bytes() == b"cache"
    assert dataroot.link_points_at(worktree / ".cache", primary / ".cache")
