"""Which tree each passing gate run tested, so a commit's gate line can be held to it.

``gate.py`` captures the working copy's tree when a run starts and, if the run passes, records it
under ``target/gate/<name>.tree``, one file per gate name it proves
(``check``, ``check-rust``, ``check-py``, ``check-docs``). The commit-msg hook (``check_commit_msg.py``) then refuses a gate line claiming
``<name> passes`` unless the staged tree is the one a passing run of that name, or of the full
``check``, tested. See docs/development.md, "The gate line is checked".

The working copy's tree is what ``git add -A`` would stage: every tracked file and every untracked
one that is not ignored. It is written through a copy of the index, so the real index, and so
what a commit holds, is never touched.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

#: The names a passing run records under (``gate.recorded_names``) and the hook holds to a record;
#: any other gate name on a gate line is not checked.
RECORDED = frozenset({"check", "check-rust", "check-py", "check-docs"})


def _git(*args: str, env: dict[str, str] | None = None) -> str:
    """The stripped output of ``git <args>``."""
    done = subprocess.run(  # noqa: S603 - fixed git arguments
        ["git", *args],  # noqa: S607 - git from PATH
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        env=env,
    )
    return done.stdout.strip()


def _record_dir() -> Path:
    """``target/gate`` in the checkout the current directory is in."""
    return Path(_git("rev-parse", "--show-toplevel")) / "target" / "gate"


def working_tree() -> str:
    """The tree of the working copy, written through a scratch copy of the index."""
    index = Path(_git("rev-parse", "--git-path", "index"))
    with tempfile.TemporaryDirectory() as scratch:
        copy = Path(scratch) / "index"
        if index.is_file():
            # Starting from the real index lets git skip rehashing every unchanged file.
            shutil.copyfile(index, copy)
        env = {**os.environ, "GIT_INDEX_FILE": str(copy)}
        _git("add", "-A", env=env)
        return _git("write-tree", env=env)


def staged_tree() -> str:
    """The tree the next commit would hold."""
    return _git("write-tree")


def record(name: str, tree: str) -> None:
    """Record that a run of the gate *name* passed on *tree*."""
    directory = _record_dir()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.tree").write_text(f"{tree}\n", encoding="utf-8")


def recorded(name: str) -> str | None:
    """The tree the last passing run of the gate *name* tested, or ``None``."""
    try:
        return (_record_dir() / f"{name}.tree").read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def differing(first: str, second: str) -> list[str]:
    """The paths whose content differs between two trees."""
    return _git("diff-tree", "-r", "--name-only", first, second).splitlines()
