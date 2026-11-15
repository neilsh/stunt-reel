"""The clean path measures and removes a worktree's build outputs, never a link's target.

The read-only retry, the refusal of a link, the parity render-tree rotation and the one
legacy capture link that sits inside ``build/`` are held here beside the module that runs
them (ADR 0018).
"""

from __future__ import annotations

import os
import stat
lazy from pathlib import Path

import pytest

from stunt_reel import dataroot, worktree_clean

pytestmark = pytest.mark.windows


def test_clean_parity_keeps_the_baselines_and_removes_a_scratch_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rotation asks the layout which names are baselines before deleting a tree."""
    monkeypatch.setattr(worktree_clean, "REPO_ROOT", tmp_path)
    ours = tmp_path / "build" / "parity" / "ours"
    sweep = tmp_path / "build" / "scratch" / "sweep"
    for tree in (ours / "ctry_current", ours / "ctry_base", ours / "ctry_old", sweep / "v001"):
        tree.mkdir(parents=True)
        (tree / "tick_00000.idx").write_bytes(b"frame")

    assert worktree_clean._prune_render_trees(confirmed=True, keep=0) == 0

    assert (ours / "ctry_current").is_dir()
    assert (ours / "ctry_base").is_dir()
    assert not (ours / "ctry_old").exists()
    assert not (sweep / "v001").exists()


def test_clean_removes_read_only_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A test's scratch repository under ``.pytest_cache`` holds git objects, which git
    marks read-only, and Windows refuses to unlink a read-only file."""
    monkeypatch.setattr(worktree_clean, "REPO_ROOT", tmp_path)
    objects = tmp_path / ".pytest_cache" / "basetemp" / "repo" / ".git" / "objects" / "05"
    objects.mkdir(parents=True)
    blob = objects / "43213c3e614823f0f6500583215b8c4a87066e"
    blob.write_bytes(b"blob")
    blob.chmod(0o444)

    assert worktree_clean._clean(confirmed=True) == 0

    assert not (tmp_path / ".pytest_cache").exists()


def test_remove_tree_refuses_a_link_and_leaves_its_target_alone(tmp_path: Path) -> None:
    """``chmod`` follows a link, so the read-only retry must not run on one."""
    target = tmp_path / "target"
    target.mkdir()
    (target / "frame.idx").write_bytes(b"frame")
    link = tmp_path / "link"
    dataroot.create_link(link, target)
    mode = target.stat().st_mode

    # rmtree words the refusal differently per platform (no message on POSIX).
    with pytest.raises(OSError):  # noqa: PT011
        worktree_clean._remove_tree(link)

    assert target.stat().st_mode == mode
    assert (target / "frame.idx").read_bytes() == b"frame"
    dataroot.remove_link(link)


def test_clean_parity_skips_a_linked_render_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A render child that links elsewhere is not this checkout's to prune."""
    monkeypatch.setattr(worktree_clean, "REPO_ROOT", tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "tick_00000.idx").write_bytes(b"frame")
    linked = tmp_path / "build" / "scratch" / "sweep" / "v001"
    dataroot.create_link(linked, elsewhere)

    assert worktree_clean._prune_render_trees(confirmed=True, keep=0) == 0

    assert dataroot.is_link(linked)
    assert (elsewhere / "tick_00000.idx").is_file()
    dataroot.remove_link(linked)


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory permissions")
def test_remove_tree_keeps_a_file_mode_when_its_directory_refuses(tmp_path: Path) -> None:
    """On POSIX a refused unlink is the parent directory's mode, so the file keeps its own."""
    locked = tmp_path / "tree" / "locked"
    locked.mkdir(parents=True)
    blob = locked / "blob"
    blob.write_bytes(b"blob")
    blob.chmod(0o444)
    locked.chmod(0o555)
    try:
        if os.access(locked, os.W_OK):
            pytest.skip("this process can write a 0555 directory (root or CAP_DAC_OVERRIDE)")
        with pytest.raises(PermissionError):
            worktree_clean._remove_tree(tmp_path / "tree")
        assert stat.S_IMODE(blob.stat().st_mode) == 0o444
    finally:
        locked.chmod(0o755)


def test_clean_unlinks_the_legacy_capture_link_and_keeps_the_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """build/ of an old worktree holds a junction into the data root's captures (ADR 0018)."""
    checkout = tmp_path / "checkout"
    meta = tmp_path / "data" / "captures" / "vault-ctry" / "frames" / "meta.json"
    meta.parent.mkdir(parents=True)
    meta.write_text("{}", encoding="utf-8")
    legacy = checkout / "build" / "parity" / "captures"
    dataroot.create_link(legacy, tmp_path / "data" / "captures")
    (checkout / "build" / "scratch").mkdir(parents=True)
    (checkout / "build" / "scratch" / "x.png").write_bytes(b"png")
    monkeypatch.setattr(worktree_clean, "REPO_ROOT", checkout)

    assert worktree_clean._clean(confirmed=True) == 0

    assert meta.is_file()
    assert not dataroot.is_link(legacy)
    assert not (checkout / "build").exists()
