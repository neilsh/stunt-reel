"""Reject a file added to a frozen work folder, or a change to its README's ``outcome`` line.

A work folder is frozen once the PR that finishes its work writes the README ``outcome``; after
that it changes only for link fixes (``work/README.md``, Lifecycle). A link fix cannot be told
from another edit, so edits to existing files pass and review covers them; this check refuses
what can be told apart. ``stunt_reel.work_items.frozen_violations`` holds the rule.

With no arguments (the pre-commit hook, ``mise run check-work-frozen``) it compares the index
with ``HEAD``. With ``--branch`` it compares the working tree with the merge base of ``HEAD``
and the gate's base (``origin/main`` when it resolves, else ``main``; ``--base`` names another),
the paths ``gate.py`` counts; ``tests/test_work_frozen.py`` runs that in the gate's docs half,
so CI checks it too.

Exit status: ``0`` when nothing breaks a frozen folder, ``1`` when something does, ``2`` when git
cannot be run.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import gate

from stunt_reel.work_items import FrozenViolation, frozen_violations

if TYPE_CHECKING:
    from collections.abc import Sequence


def _git(repo: Path, *args: str) -> str:
    """``git *args``' stdout in *repo*; raises CalledProcessError or OSError."""
    return subprocess.run(  # noqa: S603 - fixed git arguments
        ["git", *args],  # noqa: S607 - git from PATH, as every task
        cwd=repo,
        capture_output=True,
        check=True,
        encoding="utf-8",
    ).stdout


def staged_violations(repo: Path) -> list[FrozenViolation]:
    """What the index, against ``HEAD``, breaks; none before the first commit."""
    try:
        _git(repo, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
    except subprocess.CalledProcessError:
        return []
    output = _git(repo, "diff", "--cached", "--name-only", "--no-renames", "-z", "HEAD")
    paths = [path for path in output.split("\0") if path]
    return frozen_violations("HEAD", paths, staged=True, repo=repo)


def branch_violations(repo: Path, base: str | None = None) -> list[FrozenViolation]:
    """What the working tree breaks against the merge base of ``HEAD`` and *base*.

    *base* defaults to ``gate.default_base``. Raises ``gate.ChangedPathsError`` when git cannot
    give the merge base or the paths.
    """
    base = base or gate.default_base(repo)
    paths = gate.changed_paths(repo, base)
    merge_base = _git(repo, "merge-base", "HEAD", base).strip()
    return frozen_violations(merge_base, paths, repo=repo)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--branch",
        action="store_true",
        help="check the branch since the gate's base, not the index",
    )
    parser.add_argument("--base", help="with --branch, the ref to count from (default: the gate's)")
    args = parser.parse_args(argv)
    try:
        repo = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
        violations = branch_violations(repo, args.base) if args.branch else staged_violations(repo)
    except (OSError, subprocess.CalledProcessError, gate.ChangedPathsError) as error:
        print(f"check-work-frozen: git failed: {error}", file=sys.stderr)
        return 2
    if not violations:
        return 0
    print("check-work-frozen: these changes break a frozen work folder:", file=sys.stderr)
    for violation in violations:
        print(f"  {violation.path}: {violation.rule}", file=sys.stderr)
    print(
        "Once its README has an outcome, a work folder changes only for link fixes\n"
        "(work/README.md, Lifecycle). Record new work in a new work item: mise run work -- new.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
