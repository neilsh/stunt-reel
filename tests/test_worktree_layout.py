"""Repo shape: a worktree inside the checkout must stay out of every walker's way.

``.agents/worktrees/`` and ``.claude/worktrees/`` hold live worktrees, each with its
own ``target/``.  A directory there that is neither git-ignored nor ruff-excluded is
read by every recursive tool in the repo: ``tests/test_doc_invariants.py`` lost 61
seconds to exactly that before it learned to prune.  The rule lives in SOP 6; this
is what enforces it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Never walked: build output, caches, and the git directory itself.
_PRUNED = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "node_modules",
        "target",
    }
)
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def _is_link(path: Path) -> bool:
    """True for a symlink or a Windows junction, which ``walk`` would descend."""
    if path.is_symlink():
        return True
    try:
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)
    except OSError:
        return False


def _nested_worktrees(root: Path) -> list[Path]:
    """Every linked worktree inside *root*, without descending into one it finds."""
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        if here != root and ".git" in filenames:
            found.append(here)
            dirnames[:] = []
            continue
        dirnames[:] = [name for name in dirnames if name not in _PRUNED]
        dirnames[:] = [name for name in dirnames if not _is_link(here / name)]
    return found


def _ruff_excludes() -> list[str]:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        config = tomllib.load(handle)
    return [str(entry) for entry in config["tool"]["ruff"]["exclude"]]


def _excluded(relative: str, excludes: list[str]) -> bool:
    parts = relative.split("/")
    for entry in excludes:
        cleaned = entry.rstrip("/")
        if cleaned and (relative == cleaned or relative.startswith(cleaned + "/")):
            return True
        if Path(relative).match(cleaned):
            return True
        if parts[0] == cleaned:
            return True
    return False


def _ignored(relative: str, git: str) -> bool:
    result = subprocess.run(  # noqa: S603
        [git, "check-ignore", "-q", "--", relative],
        cwd=REPO_ROOT,
        check=False,
    )
    return result.returncode == 0


def test_the_detector_finds_a_linked_worktree(tmp_path: Path) -> None:
    # A worktree is a directory whose .git is a file naming its git directory.
    (tmp_path / ".git").mkdir()
    worktree = tmp_path / ".agents" / "worktrees" / "slug"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    assert _nested_worktrees(tmp_path) == [worktree]


def test_a_worktree_inside_the_checkout_is_ignored_and_excluded() -> None:
    git = shutil.which("git")
    assert git, "git must be on PATH: check-ignore is the only authority on .gitignore"
    excludes = _ruff_excludes()
    for worktree in _nested_worktrees(REPO_ROOT):
        relative = worktree.relative_to(REPO_ROOT).as_posix()
        assert _ignored(relative, git), (
            f"{relative} is a worktree inside the checkout; .gitignore must cover it"
        )
        assert _excluded(relative, excludes), (
            f"{relative} is a worktree inside the checkout; ruff's exclude must cover it"
        )
