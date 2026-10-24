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


def test_shared_write_needs_the_opt_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _checkout(monkeypatch, _primary(tmp_path))
    with pytest.raises(dataroot.SharedWriteError, match=dataroot.WRITE_ENV):
        dataroot.require_shared_write("capture")
    monkeypatch.setenv(dataroot.WRITE_ENV, "1")
    dataroot.require_shared_write("capture")
