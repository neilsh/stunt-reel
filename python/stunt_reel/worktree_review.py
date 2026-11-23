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
from typing import TYPE_CHECKING

from stunt_reel.dataroot import SharedDataError
from stunt_reel.worktree_git import _git, _worktrees
from stunt_reel.worktree_reap import REVIEW_PREFIX

if TYPE_CHECKING:
    from collections.abc import Iterator

#: Where a review worktree lives, inside the primary checkout (AGENTS.md, Worktrees).
REVIEW_POOL = ".claude/worktrees"

#: A target of at most this many digits is a PR number; anything else is a commit.
_PR_PATTERN = re.compile(r"\d{1,6}")

#: A full SHA, which origin can be asked for by name.
_FULL_SHA = re.compile(r"[0-9a-f]{40}")

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


def _candidates(pool: Path, name: str) -> Iterator[Path]:
    """``pool/name``, then ``name`` + ``b``, ``c`` … ``z``, skipping a name already taken.

    A name is taken when its folder exists or git still registers a worktree there, even with
    the folder gone, where ``git worktree add`` would refuse it.
    """
    registered = {worktree.path for worktree in _worktrees(pool)}
    for suffix in ("", *string.ascii_lowercase[1:]):
        candidate = pool / f"{name}{suffix}"
        if candidate not in registered and not candidate.exists():
            yield candidate


def _fetch_pr_head(primary: Path, number: str) -> str:
    """The SHA of PR *number*'s head, with its objects fetched from origin.

    The SHA is read with ``ls-remote`` and fetched by name rather than read back from
    ``FETCH_HEAD``, which any concurrent fetch in the primary checkout overwrites.
    """
    listed = _git(primary, "ls-remote", "origin", f"refs/pull/{number}/head")
    sha = listed.stdout.split(maxsplit=1)[0] if listed.stdout.strip() else ""
    if listed.returncode != 0 or not sha:
        raise SharedDataError(f"cannot find PR {number} on origin: {listed.stderr.strip()}")
    _fetch_commit(primary, sha)
    return sha


def _fetch_commit(primary: Path, sha: str) -> None:
    """Fetch commit *sha* from origin unless it is already in the object store."""
    if _git(primary, "cat-file", "-e", f"{sha}^{{commit}}").returncode == 0:
        return
    fetched = _git(primary, "fetch", "--quiet", "origin", sha)
    if fetched.returncode != 0:
        raise SharedDataError(f"cannot fetch {sha} from origin: {fetched.stderr.strip()}")


def _resolve(primary: Path, target: str) -> tuple[str, str]:
    """The commit *target* names and the worktree name, from a PR number or a commit SHA.

    A PR's head is fetched from origin (``pull/<n>/head``, which also exists for a PR from a
    fork).
    A SHA already in the object store, an unpushed commit from any worktree included, resolves
    at once; otherwise a full 40-character SHA is fetched from origin, which GitHub serves for
    a pushed commit, and an abbreviated one that is not local fails.
    """
    if _PR_PATTERN.fullmatch(target):
        return _fetch_pr_head(primary, target), target
    rev = f"{target}^{{commit}}"
    done = _git(primary, "rev-parse", "--verify", "--quiet", rev)
    if done.returncode != 0 and _FULL_SHA.fullmatch(target):
        _fetch_commit(primary, target)
        done = _git(primary, "rev-parse", "--verify", "--quiet", rev)
    sha = done.stdout.strip()
    if done.returncode != 0 or not sha:
        raise SharedDataError(
            f"{target} names no commit in this repository; pass a full 40-character SHA to fetch"
            " a pushed one from origin"
        )
    return sha, sha[:_SHA_LENGTH]


def _add(primary: Path, pool: Path, name: str, sha: str) -> Path:
    """Check commit *sha* out detached at the first free ``pool/name`` path and return it.

    A path another run took between the check and the add is skipped like any taken name.
    """
    last = ""
    for path in _candidates(pool, name):
        added = _git(primary, "worktree", "add", "--detach", str(path), sha)
        if added.returncode == 0:
            return path
        last = added.stderr.strip()
        if not path.exists():
            break
    raise SharedDataError(f"git worktree add failed: {last or f'no free {name} name in {pool}'}")


def _review(target: str, cwd: Path | None = None) -> int:
    """Create the review worktree for *target* and print its absolute path as the last line."""
    try:
        primary = _primary(cwd or Path.cwd())
        sha, name = _resolve(primary, target)
        pool = primary / REVIEW_POOL
        pool.mkdir(parents=True, exist_ok=True)
        path = _add(primary, pool, f"{REVIEW_PREFIX}{name}", sha)
    except SharedDataError as error:
        return _fail(str(error))
    print(f"review worktree for {target} at {sha[:_SHA_LENGTH]}", file=sys.stderr)
    print(path.resolve())
    return 0
