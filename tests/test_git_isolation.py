"""A suite run under ``git rebase --exec`` or a hook leaves the caller's repository alone."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GIT = shutil.which("git")

#: A test whose fixture runs ``git init`` and ``git config user.name`` in its scratch directory.
_SCRATCH_REPO_TEST = "tests/test_check_commit_msg.py::test_the_script_checks_a_commit_range"


@pytest.mark.skipif(GIT is None, reason="git is not on PATH")
def test_a_test_run_with_git_dir_set_leaves_that_repository_unchanged(tmp_path: Path) -> None:
    assert GIT is not None
    caller = tmp_path / "caller"
    subprocess.run([GIT, "init", "-q", str(caller)], check=True)  # noqa: S603 - fixed git arguments
    before = (caller / ".git" / "config").read_text()
    # `git rebase --exec` exports GIT_DIR to the command it runs; the suite inherits it.
    env = {**os.environ, "GIT_DIR": str(caller / ".git"), "PYTEST_ADDOPTS": ""}
    inner = subprocess.run(  # noqa: S603 - this interpreter, fixed pytest arguments
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            str(tmp_path / "inner"),
            _SCRATCH_REPO_TEST,
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (caller / ".git" / "config").read_text() == before
    assert "1 passed" in inner.stdout, inner.stdout + inner.stderr
