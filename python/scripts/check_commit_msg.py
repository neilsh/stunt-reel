#!/usr/bin/env python3
"""Fail a commit message that breaks AGENTS.md SOP 3: a Conventional Commit subject, and a gate line.

The subject is ``type(scope)!: summary`` with one of the usual types. A message with a body
(anything past the subject but git's trailers, such as ``Co-Authored-By:``) must also say what
the gate did: ``mise run check``, or one of its parts such as ``mise run check-py``, followed
directly by its outcome, ``passes`` or ``not run``, as in ``mise run check passes.`` or
``mise run check-py passes; check-rust not run.`` Every gate name on the line must be followed by its outcome, so
``mise run check failed; CI passes.`` is refused. A message with no body needs none, as SOP 3
lets a rename or a formatting commit go without one. Git's own subjects (a merge, a revert, ``fixup!``,
``squash!``, ``amend!``) are left alone.

Usage: ``mise run commit-msg-check -- <message file>`` (the commit-msg hook), or
``mise run commit-msg-check -- --range <base>..<head> [--pr <number>]`` to check commits already
made (CI). In a range, a failing commit that already landed elsewhere is skipped, with a line
saying why: ``git cherry`` finds its patch in ``<base>``, or GitHub (through ``gh``) lists a
merged pull request other than ``--pr`` that holds it. That is a branch stacked on a pull request
that was then squash-merged: the parent's own commits stay on the branch with hashes ``<base>``
lacks, though they were reviewed in the parent. When ``gh`` cannot answer, the script says so and
counts every failing commit, as before.
Exit status: ``0`` when every message passes, ``1`` when one does not, ``2`` when git cannot be
run.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
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
#: A name of the gate or one of its parts: ``mise run check``, ``mise run check-py``, ``check-rust``.
GATE_NAME = re.compile(r"mise run check(?:-[a-z]+)?|\bcheck-[a-z]+")
#: The outcome that must follow each gate name directly.
OUTCOME = re.compile(r" (?:passes|not run)\b")


def _is_gate_line(line: str) -> bool:
    """Whether *line* names the gate and gives every gate name on it an outcome."""
    names = list(GATE_NAME.finditer(line))
    return GATE in line and all(OUTCOME.match(line, name.end()) for name in names)


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
    if any(not TRAILER.match(line) for line in body) and not any(map(_is_gate_line, body)):
        found.append(
            f"the body has no gate line: end it with '{GATE} passes.', or name the part of "
            f"the gate that did not run (AGENTS.md SOP 3)"
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


def _messages(revisions: str) -> list[tuple[str, str, str]]:
    """``(full hash, short hash, message)`` for each commit in *revisions*, oldest first."""
    fields = _git("log", "--reverse", "--format=%H%x00%h%x00%B%x00", revisions).split("\0")
    return [(fields[i].strip(), fields[i + 1], fields[i + 2]) for i in range(0, len(fields) - 2, 3)]


def _in_base(revisions: str) -> set[str]:
    """Full hashes of the commits in ``<base>..<head>`` whose patch ``<base>`` already holds."""
    base, dots, head = revisions.partition("..")
    if not dots or head.startswith("."):
        return set()
    lines = _git("cherry", base or "HEAD", head or "HEAD").splitlines()
    return {line[2:].strip() for line in lines if line.startswith("- ")}


class GitHubUnavailableError(Exception):
    """``gh`` is missing, or could not answer."""


def _merged_pulls(sha: str) -> list[int]:
    """The numbers of the merged pull requests that hold commit *sha*, as GitHub lists them."""
    gh = shutil.which("gh")
    if gh is None:
        raise GitHubUnavailableError("gh is not on PATH")
    try:
        done = subprocess.run(  # noqa: S603 - gh from PATH, fixed arguments
            [
                gh,
                "api",
                f"repos/{{owner}}/{{repo}}/commits/{sha}/pulls",
                "--jq",
                "[.[] | select(.merged_at != null) | .number]",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        numbers = json.loads(done.stdout)
    except subprocess.CalledProcessError as error:
        raise GitHubUnavailableError(error.stderr.strip() or str(error)) from error
    except (OSError, ValueError) as error:
        raise GitHubUnavailableError(str(error)) from error
    if not isinstance(numbers, list) or not all(isinstance(n, int) for n in numbers):
        raise GitHubUnavailableError(f"unexpected answer {done.stdout.strip()!r}")
    return numbers


def _landed_elsewhere(
    revisions: str, failing: list[tuple[str, str]], pr: int | None
) -> dict[str, str]:
    """Why each failing ``(full hash, short hash)`` commit already landed, keyed by full hash.

    git answers first; GitHub is asked, one call per commit, only about the rest. Once GitHub
    cannot answer, the remaining commits count as this pull request's own, and a line says so.
    """
    reasons = dict.fromkeys(_in_base(revisions), "its patch is already in the base")
    for full, short in failing:
        if full in reasons:
            continue
        try:
            merged = [number for number in _merged_pulls(full) if number != pr]
        except GitHubUnavailableError as error:
            print(
                f"[commit-msg] cannot ask GitHub which pull requests hold {short} ({error}); "
                "checking every remaining commit",
                file=sys.stderr,
            )
            break
        if merged:
            reasons[full] = "merged in " + ", ".join(f"#{number}" for number in merged)
    return reasons


def main(argv: list[str] | None = None) -> int:
    """Check one message file, or every commit in a range; print each problem."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("message", nargs="?", type=Path, help="the commit message file")
    group.add_argument("--range", help="the commits to check, as <base>..<head>")
    parser.add_argument(
        "--pr",
        type=int,
        help="with --range, the pull request being checked: never a reason to skip",
    )
    args = parser.parse_args(argv)
    if args.message is not None:
        found = [("this commit", problems(args.message.read_text(encoding="utf-8")))]
    else:
        try:
            commits = [
                (full, short, problems(message)) for full, short, message in _messages(args.range)
            ]
            failing = [(full, short) for full, short, listed in commits if listed]
            skipped = _landed_elsewhere(args.range, failing, args.pr) if failing else {}
        except (OSError, subprocess.CalledProcessError) as error:
            print(f"[commit-msg] cannot read {args.range}: {error}", file=sys.stderr)
            return 2
        found = []
        for full, short, listed in commits:
            if listed and full in skipped:
                print(f"[commit-msg] skip {short}: {skipped[full]}", file=sys.stderr)
            else:
                found.append((short, listed))
    failed = False
    for name, listed in found:
        for problem in listed:
            print(f"[commit-msg] {name}: {problem}", file=sys.stderr)
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
