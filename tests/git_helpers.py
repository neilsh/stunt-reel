"""Git commands that a test runs in its own fixture repository, never the caller's.

A suite run under a git hook or ``git rebase --exec`` inherits ``GIT_DIR`` and its kin, which send
a git command to the caller's repository; and a fixture repository whose ``.git`` has gone lets
git discover the enclosing checkout instead.  Either one lets a fixture's ``git worktree add``
register with a repository outside the test (issues #520 and #868), so every fixture command
strips those variables, stops discovery at the fixture's parent and names the fixture's own git
directory.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from stunt_reel.git_env import isolated_env

GIT = shutil.which("git")

#: Identity per command, so no ``git config`` writes one; no signing key is needed; and
#: ``core.longpaths`` because a fixture under the per-run basetemp can pass ``MAX_PATH``.
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_COUNT": "2",
    "GIT_CONFIG_KEY_0": "commit.gpgSign",
    "GIT_CONFIG_VALUE_0": "false",
    "GIT_CONFIG_KEY_1": "core.longpaths",
    "GIT_CONFIG_VALUE_1": "true",
}


def git_dir(cwd: Path) -> Path | None:
    """The git directory of the repository checked out at *cwd*, if it has one.

    A linked worktree's ``.git`` is a file naming its directory under the main repository's.
    """
    marker = cwd / ".git"
    if marker.is_dir():
        return marker
    try:
        text = marker.read_text(encoding="utf-8")
    except OSError:
        return None
    prefix = "gitdir:"
    if not text.startswith(prefix):
        return None
    named = Path(text[len(prefix) :].strip())
    return named if named.is_absolute() else (cwd / named).resolve()


def run_git(cwd: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    """Run git in *cwd*, pinned to the repository checked out there.

    ``GIT_CEILING_DIRECTORIES`` stops discovery at *cwd*'s parent, so a fixture that has lost its
    ``.git`` fails rather than acting on the checkout that holds the tests.
    """
    assert GIT is not None, "git is not on PATH"
    pinned = git_dir(cwd)
    return subprocess.run(  # noqa: S603 - fixed git arguments, git resolved from PATH
        [GIT, *([f"--git-dir={pinned.as_posix()}"] if pinned else []), *args],
        cwd=cwd,
        env={
            **isolated_env(keep_index=False),
            "GIT_CEILING_DIRECTORIES": str(cwd.parent),
            **GIT_ENV,
        },
        capture_output=True,
        text=True,
        check=check,
    )
