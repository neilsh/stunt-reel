#!/usr/bin/env python3
"""Fail a commit message whose subject is not a Conventional Commit, or that lacks a due review.

The subject is ``type(scope)!: summary`` with one of the usual types. Git's own subjects (a merge,
a revert, ``fixup!``, ``squash!``, ``amend!``) are left alone (AGENTS.md, Committing, rule 3).

The hook also requires a ``Fresh-review: <what it read>`` trailer, the record of a fresh
reviewer's pass (AGENTS.md, Committing, rule 5), on a commit that adds, changes or deletes a work
``spec.md`` or ``plan.md``, or a second one (``spec-<topic>.md``, ``plan-<topic>.md``). It sees only what is staged, so an ``--amend`` that only rewords is not
checked; a range is not checked for it. Git's own subjects need no trailer.

Usage: ``mise run commit-msg-check -- <message file>`` (the commit-msg hook), or
``mise run commit-msg-check -- --subject TEXT`` to check a pull request title (CI), which becomes
the squash-merge subject; that checks the subject only, with no git and no trailer check.
Exit status: ``0`` when the message passes, ``1`` when it does not, ``2`` when git cannot be run.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

TYPES = (
    "build",
    "chore",
    "ci",
    "docs",
    "feat",
    "fix",
    "perf",
    "refactor",
    "revert",
    "style",
    "test",
)
SUBJECT = re.compile(rf"^(?:{'|'.join(TYPES)})(?:\([^()\s][^()]*\))?!?: \S")
GIT_SUBJECT = re.compile(r"^(?:Merge |Revert \"|fixup! |squash! |amend! )")
SCISSORS = "# ------------------------ >8 ------------------------"
FRESH_REVIEW = re.compile(r"^Fresh-review:[ \t]*\S")
#: A work folder's ``spec.md``, ``plan.md``, ``spec-<topic>.md`` or ``plan-<topic>.md``.
REVIEWED_FILE = re.compile(r"^(?:spec|plan)(?:-[^/]+)?\.md$")
RULE_5 = "AGENTS.md, Committing, rule 5"


def reviewed_at_commit(path: str) -> bool:
    """Whether a change to repository-relative *path* needs its review before the commit."""
    parts = path.split("/")
    return len(parts) == 4 and parts[0] == "work" and bool(REVIEWED_FILE.match(parts[3]))


def is_reviewed(message: str) -> bool:
    """Whether any line git keeps of *message* is ``Fresh-review:`` with a value."""
    return any(FRESH_REVIEW.match(line) for line in _lines(message))


def review_problems(message: str, paths: list[str]) -> list[str]:
    """The review *message* lacks for a commit changing *paths* that must be reviewed first."""
    lines = _lines(message)
    if GIT_SUBJECT.match(next((line for line in lines if line), "")):
        return []
    due = sorted(path for path in paths if reviewed_at_commit(path))
    if not due or is_reviewed(message):
        return []
    problem = (
        f"changes {', '.join(due)} with no Fresh-review: trailer ({RULE_5}): have a fresh "
        "reviewer read the diff, then add 'Fresh-review: <what it read>' to the message"
    )
    return [problem]


def _lines(message: str) -> list[str]:
    """The message as git keeps it: up to the scissors line, without ``#`` comments."""
    kept: list[str] = []
    for line in message.splitlines():
        if line == SCISSORS:
            break
        if not line.startswith("#"):
            kept.append(line.rstrip())
    return kept


def problems(message: str) -> list[str]:
    """What is wrong with *message*; empty when it follows AGENTS.md, Committing."""
    lines = _lines(message)
    subject = next((line for line in lines if line), "")
    if GIT_SUBJECT.match(subject):
        return []
    found: list[str] = []
    if not SUBJECT.match(subject):
        found.append(
            f"subject {subject!r} is not a Conventional Commit, type(scope): summary, "
            f"with a type of {', '.join(TYPES)}"
        )
    return found


def _git(*args: str) -> str:
    """The output of ``git <args>``."""
    done = subprocess.run(  # noqa: S603 - fixed git arguments
        ["git", *args],  # noqa: S607 - git from PATH
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return done.stdout


def _staged_paths() -> list[str]:
    """The paths the commit being made changes, as the index holds them."""
    return _git(
        "-c", "core.quotepath=false", "diff", "--cached", "--name-only", "--no-renames"
    ).splitlines()


def main(argv: list[str] | None = None) -> int:
    """Check one message file or one pull request title; print each problem."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("message", nargs="?", type=Path, help="the commit message file")
    group.add_argument("--subject", help="a pull request title, checked as a commit subject")
    args = parser.parse_args(argv)
    if args.message is not None:
        message = args.message.read_text(encoding="utf-8")
        try:
            staged = _staged_paths()
        except (OSError, subprocess.CalledProcessError) as error:
            print(f"[commit-msg] cannot read the staged paths: {error}", file=sys.stderr)
            return 2
        name, listed = "this commit", problems(message) + review_problems(message, staged)
    else:
        name, listed = "pull request title", problems(args.subject)
    for problem in listed:
        print(f"[commit-msg] {name}: {problem}", file=sys.stderr)
    return 1 if listed else 0


if __name__ == "__main__":
    raise SystemExit(main())
