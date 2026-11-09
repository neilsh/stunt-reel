"""The environment for a git command that must act on the repository it names, not the caller's.

A hook, ``git rebase --exec`` or a shell can leave ``GIT_DIR`` and its kin set; a git command
inheriting them acts on that repository instead of the one its ``-C`` or ``cwd`` names.
"""

from __future__ import annotations

import functools
import os
import shutil
import subprocess

__all__ = ["git_location_vars", "isolated_env"]

#: Listed by every git ``--local-env-vars`` reports; kept so a failing git still strips them.
_CORE = frozenset({"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"})


@functools.cache
def git_location_vars() -> frozenset[str]:
    """The variables that point git at a repository: ``git rev-parse --local-env-vars``'s list.

    Always holds ``GIT_DIR``, ``GIT_WORK_TREE``, ``GIT_INDEX_FILE`` and ``GIT_COMMON_DIR``, also
    when git is missing or fails.
    """
    git = shutil.which("git")
    if git is None:
        return _CORE
    listed = subprocess.run(  # noqa: S603 - fixed git arguments, git resolved from PATH
        [git, "rev-parse", "--local-env-vars"], capture_output=True, text=True, check=False
    )
    return _CORE | frozenset(listed.stdout.split()) if listed.returncode == 0 else _CORE


def isolated_env(*, keep_index: bool) -> dict[str, str]:
    """``os.environ`` without :func:`git_location_vars`.

    With *keep_index*, ``GIT_INDEX_FILE`` stays: a pre-commit check that reads the index must
    see the one ``git commit -- <paths>`` builds, not the repository's own.
    """
    drop = git_location_vars() - {"GIT_INDEX_FILE"} if keep_index else git_location_vars()
    return {key: value for key, value in os.environ.items() if key not in drop}
