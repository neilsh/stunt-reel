#!/usr/bin/env python3
"""Fail a commit message that breaks AGENTS.md SOP 3: a Conventional Commit subject, and a gate line.

The subject is ``type(scope)!: summary`` with one of the usual types. A message with a body
(anything past the subject but git's trailers, such as ``Co-Authored-By:``) must also say what
the gate did: a line naming ``mise run check`` and an outcome, ``passes`` or ``not run``, as in
``mise run check passes.`` or ``mise run check-py passes; check-rust not run.`` A message with no body needs none, as SOP 3 lets a rename
or a formatting commit go without one. Git's own subjects (a merge, a revert, ``fixup!``,
``squash!``, ``amend!``) are left alone.

Usage: ``mise run commit-msg-check -- <message file>`` (the commit-msg hook), or
``mise run commit-msg-check -- --range <base>..<head>`` to check commits already made (CI).
Exit status: ``0`` when every message passes, ``1`` when one does not, ``2`` when git cannot be
run.
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
TRAILER = re.compile(r"^[A-Za-z][A-Za-z-]*: \S")
SCISSORS = "# ------------------------ >8 ------------------------"
GATE = "mise run check"
#: A gate line names the gate and its outcome: what passed, or what did not run.
GATE_LINE = re.compile(rf"{GATE}.*\b(?:passes|not run)\b")


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
    """What is wrong with *message*; empty when it follows SOP 3."""
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
    body = [line for line in lines[lines.index(subject) + 1 :] if line] if subject else []
    if any(not TRAILER.match(line) for line in body) and not any(map(GATE_LINE.search, body)):
        found.append(
            f"the body has no gate line: end it with '{GATE} passes.', or name the part of "
            f"the gate that did not run (AGENTS.md SOP 3)"
        )
    return found


def _messages(revisions: str) -> list[tuple[str, str]]:
    """``(short hash, message)`` for each commit in *revisions*, oldest first."""
    done = subprocess.run(  # noqa: S603 - fixed git arguments
        ["git", "log", "--reverse", "--format=%h%x00%B%x00", revisions],  # noqa: S607 - git from PATH
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    fields = done.stdout.split("\0")
    return [(fields[i].strip(), fields[i + 1]) for i in range(0, len(fields) - 1, 2)]


def main(argv: list[str] | None = None) -> int:
    """Check one message file, or every commit in a range; print each problem."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("message", nargs="?", type=Path, help="the commit message file")
    group.add_argument("--range", help="the commits to check, as <base>..<head>")
    args = parser.parse_args(argv)
    if args.message is not None:
        checked = [("this commit", args.message.read_text(encoding="utf-8"))]
    else:
        try:
            checked = _messages(args.range)
        except (OSError, subprocess.CalledProcessError) as error:
            print(f"[commit-msg] cannot read {args.range}: {error}", file=sys.stderr)
            return 2
    failed = False
    for name, message in checked:
        for problem in problems(message):
            print(f"[commit-msg] {name}: {problem}", file=sys.stderr)
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
