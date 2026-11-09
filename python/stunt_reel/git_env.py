"""The environment a script hands git so that git acts on the repository it is pointed at.

A hook or ``git rebase --exec`` exports ``GIT_DIR``, ``GIT_INDEX_FILE``, ``GIT_CONFIG*`` and
their kin to the command it runs; git run from that command would act on the caller's repository.
"""

from __future__ import annotations

import functools
import os
import shutil
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = ["clean_environ", "local_env_vars"]

#: What ``git rev-parse --local-env-vars`` lists in git 2.x, used only when git cannot be asked.
_KNOWN = frozenset(
    {
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_CONFIG",
        "GIT_CONFIG_PARAMETERS",
        "GIT_CONFIG_COUNT",
        "GIT_OBJECT_DIRECTORY",
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_IMPLICIT_WORK_TREE",
        "GIT_GRAFT_FILE",
        "GIT_INDEX_FILE",
        "GIT_NO_REPLACE_OBJECTS",
        "GIT_REPLACE_REF_BASE",
        "GIT_PREFIX",
        "GIT_SHALLOW_FILE",
        "GIT_COMMON_DIR",
    }
)


@functools.cache
def local_env_vars() -> frozenset[str]:
    """The variables that point git at a repository, as ``git rev-parse --local-env-vars`` lists.

    When git is missing or the call fails, the names git 2.x lists: never an empty set, which
    would strip nothing and let the caller's repository through.
    """
    git = shutil.which("git")
    if git is None:
        return _KNOWN
    try:
        proc = subprocess.run(  # noqa: S603 - fixed git arguments, git resolved from PATH
            [git, "rev-parse", "--local-env-vars"],
            capture_output=True,
            text=True,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except OSError:
        return _KNOWN
    listed = frozenset(proc.stdout.split())
    return listed | _KNOWN if proc.returncode == 0 and listed else _KNOWN


def clean_environ(
    environ: Mapping[str, str] | None = None, *, keep: Iterable[str] = ()
) -> dict[str, str]:
    """*environ* (default ``os.environ``) without git's local variables, except those in *keep*."""
    source = os.environ if environ is None else environ
    strip = local_env_vars() - frozenset(keep)
    return {key: value for key, value in source.items() if key not in strip}
