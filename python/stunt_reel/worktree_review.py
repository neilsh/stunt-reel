"""Make a review's detached worktree under the primary checkout (issue #981).

A reviewer reads a PR or an unpushed commit in a scratch checkout of its own.
``review-worktree`` makes it at ``<primary>/.claude/worktrees/review-<PR or sha7>`` from any
checkout or linked worktree, so a coordinator's relative path can never nest it inside an Orca
workspace, where ``reap`` skips the workspace for the worktrees it holds.
"""

from __future__ import annotations

import re
import string
import sys
from pathlib import Path

from stunt_reel.dataroot import SharedDataError
from stunt_reel.worktree_git import _git
from stunt_reel.worktree_reap import REVIEW_PREFIX

#: Where a review worktree lives, inside the primary checkout (AGENTS.md, Worktrees).
REVIEW_POOL = ".claude/worktrees"

#: A target of at most this many digits is a PR number; anything else is a commit.
_PR_PATTERN = re.compile(r"\d{1,6}")

#: Characters of a commit's SHA in a worktree's name.
_SHA_LENGTH = 7


def _fail(message: str) -> int:
    print(f"review-worktree: {message}", file=sys.stderr)
    return 1


def _primary(cwd: Path) -> Path:
    """The primary checkout: the parent of the git common directory, from any worktree."""
    done = _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    common = done.stdout.strip()
    if done.returncode != 0 or not common:
        raise SharedDataError(f"{cwd} is not in a git checkout: {done.stderr.strip()}")
    return Path(common).parent


def _free_path(pool: Path, name: str) -> Path:
    """``pool/name``, or the first of ``name`` + ``b``, ``c`` … that does not exist yet."""
    for suffix in ("", *string.ascii_lowercase[1:]):
        candidate = pool / f"{name}{suffix}"
        if not candidate.exists():
            return candidate
    raise SharedDataError(f"{pool} holds {name} through {name}z already; reap the old ones")


def _resolve(primary: Path, target: str) -> tuple[str, str]:
    """The commit *target* names and the worktree name, from a PR number or a commit SHA.

    A PR's head is fetched from origin (``pull/<n>/head``, which also exists for a PR from a
    fork); a SHA is read from the shared object store, so an unpushed commit from any worktree
    resolves.
    """
    is_pr = _PR_PATTERN.fullmatch(target) is not None
    if is_pr:
        fetched = _git(primary, "fetch", "--quiet", "origin", f"pull/{target}/head")
        if fetched.returncode != 0:
            raise SharedDataError(f"cannot fetch PR {target}: {fetched.stderr.strip()}")
    done = _git(
        primary,
        "rev-parse",
        "--verify",
        "--quiet",
        "FETCH_HEAD" if is_pr else f"{target}^{{commit}}",
    )
    sha = done.stdout.strip()
    if done.returncode != 0 or not sha:
        raise SharedDataError(f"{target} names no commit in this repository")
    return sha, target if is_pr else sha[:_SHA_LENGTH]


def _add(primary: Path, path: Path, sha: str) -> None:
    """Check commit *sha* out detached at *path*."""
    added = _git(primary, "worktree", "add", "--detach", str(path), sha)
    if added.returncode != 0:
        raise SharedDataError(f"git worktree add failed: {added.stderr.strip()}")


def _review(target: str, cwd: Path | None = None) -> int:
    """Create the review worktree for *target* and print its absolute path as the last line."""
    try:
        primary = _primary(cwd or Path.cwd())
        sha, name = _resolve(primary, target)
        pool = primary / REVIEW_POOL
        pool.mkdir(parents=True, exist_ok=True)
        path = _free_path(pool, f"{REVIEW_PREFIX}{name}")
        _add(primary, path, sha)
    except SharedDataError as error:
        return _fail(str(error))
    print(f"review worktree for {target} at {sha[:_SHA_LENGTH]}", file=sys.stderr)
    print(path.resolve())
    return 0
