#!/usr/bin/env python3
"""Reject a work journal line the branch adds that names a branch-only commit as main's.

A journal entry names the commit it measured on. ``main`` at ``<sha>`` says main holds that
commit, but a worker who measured on the PR branch writes the branch's own commit that way;
#920 had three, each caught a review round later. This reads the lines the branch adds to a
``work/<YYYY-MM>/<folder>/journal.md`` and refuses each ``main`` at ``<sha>`` whose commit is not
an ancestor of ``origin/main`` (``main`` when there is no ``origin/main``), suggesting ``the
branch at <sha>`` instead. Only the lines the branch adds are read, so an older journal's shas
never fail it.

It checks the branch since the gate's base, the working tree and untracked files included;
``--base`` counts from another ref. ``tests/test_work_journal_main.py`` runs it in the gate's
documentation tests, so ``mise run check`` and CI run it too.

Exit status: 0 when every added claim is main's, 1 when one is not, 2 when git cannot be run.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import gate
from added_lines import AddedLine, added_lines

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

__all__ = ["Claim", "branch_violations", "claims", "holds", "is_journal", "main"]

#: A work folder's journal, where its entries are written (work/README.md, Journal entries).
_JOURNAL = re.compile(r"^work/[0-9]{4}-[0-9]{2}/[^/]+/journal\.md$")
#: The claim this check refuses: a backticked `main` at a backticked commit.
_MAIN_AT = re.compile(r"`main` at `([0-9a-fA-F]{7,40})`")


@dataclass(frozen=True)
class Claim:
    """One added journal line naming a commit as main's: repo-relative *path*, line *number*, *sha*."""

    path: str
    number: int
    sha: str
    text: str


def is_journal(path: str) -> bool:
    """Whether repo-relative POSIX *path* is a work folder's journal.md."""
    return _JOURNAL.fullmatch(path) is not None


def claims(lines: Iterable[AddedLine]) -> list[Claim]:
    """Each `main` at `<sha>` in *lines*, one Claim per match, in path and line order."""
    return [
        Claim(line.path, line.number, match.group(1), line.text)
        for line in lines
        for match in _MAIN_AT.finditer(line.text)
    ]


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run git args in *repo* without raising, capturing UTF-8 output."""
    return subprocess.run(  # noqa: S603 - fixed git arguments
        ["git", *args],  # noqa: S607 - git from PATH, as every task
        cwd=repo,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _git(repo: Path, *args: str) -> str:
    """``git *args``' stdout in *repo*; raises CalledProcessError or OSError."""
    done = subprocess.run(  # noqa: S603 - fixed git arguments
        ["git", *args],  # noqa: S607 - git from PATH, as every task
        cwd=repo,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return done.stdout


def holds(repo: Path, sha: str, base: str) -> bool:
    """Whether *sha* is a commit *base* holds: an ancestor of it, or *base* itself.

    A sha git cannot resolve is not *base*'s. Raises OSError when git cannot start, and
    CalledProcessError when git cannot compare the two.
    """
    resolved = _run(repo, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}")
    if resolved.returncode != 0:
        return False
    ancestor = _run(repo, "merge-base", "--is-ancestor", sha, base)
    if ancestor.returncode not in (0, 1):
        raise subprocess.CalledProcessError(
            ancestor.returncode, ancestor.args, ancestor.stdout, ancestor.stderr
        )
    return ancestor.returncode == 0


def branch_violations(repo: Path, base: str | None = None) -> list[Claim]:
    """The added journal claims that name a commit *repo*'s *base* does not hold.

    *base* defaults to ``gate.default_base``: ``origin/main`` when it resolves, else ``main``.
    Reads only the lines the working tree adds over its merge base with *base*, untracked files
    included. Raises ``gate.ChangedPathsError`` when git cannot name the changed paths, and
    ``OSError`` or ``subprocess.CalledProcessError`` when git fails.
    """
    base = base or gate.default_base(repo)
    added = added_lines(repo, base, covered=is_journal)
    return [claim for claim in claims(added) if not holds(repo, claim.sha, base)]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", help="the ref counted from (default: origin/main, else main)")
    args = parser.parse_args(argv)
    try:
        repo = Path(_git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
        base = args.base or gate.default_base(repo)
        violations = branch_violations(repo, base)
    except (OSError, subprocess.CalledProcessError, gate.ChangedPathsError) as error:
        print(f"check-work-journal-main: git failed: {error}", file=sys.stderr)
        return 2
    if not violations:
        return 0
    print(
        "check-work-journal-main: these added journal lines name a commit as main's "
        f"that {base} does not hold:",
        file=sys.stderr,
    )
    for violation in violations:
        print(
            f"  {violation.path}:{violation.number}: `main` at `{violation.sha}`; "
            f'write "the branch at `{violation.sha}`"',
            file=sys.stderr,
        )
    print(
        "A commit named as main's is one origin/main holds; one measured on the branch is "
        "the branch's.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
