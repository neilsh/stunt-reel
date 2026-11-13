#!/usr/bin/env python3
"""Fail a commit message whose subject is not a Conventional Commit, or that lacks its review.

The subject is ``type(scope)!: summary`` with one of the usual types. Git's own subjects (a merge,
a revert, ``fixup!``, ``squash!``, ``amend!``) are left alone (AGENTS.md, Committing, rule 3).

A fresh reviewer's pass (AGENTS.md, Committing, rule 5) is recorded as a ``Fresh-review: <what it
read>`` trailer. A commit that changes a work ``spec.md`` or ``plan.md`` carries one itself; in a
range, a commit that changes ``research/``, ``NOTICE.md``, ``docs/howto/`` or ``docs/*.md`` needs
one on it or on a later commit of the range, since that review is due before the push. A path
counts when the commit adds, changes or deletes it. The hook sees only what is staged, so an
``--amend`` that only rewords is not checked there; the range check covers it. Git's own subjects
need no trailer.

Usage: ``mise run commit-msg-check -- <message file>`` (the commit-msg hook), or
``mise run commit-msg-check -- --range <base>..<head> [--pr <number>]`` to check commits already
made (CI). In a range, a failing commit that already landed elsewhere is skipped, with a line
saying why: ``git cherry`` finds its non-empty patch in ``<base>``, or GitHub (through ``gh``)
lists a pull request into this repository, other than ``--pr``, that holds it and was merged.
That is a branch stacked on a pull request
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
SCISSORS = "# ------------------------ >8 ------------------------"
FRESH_REVIEW = re.compile(r"^Fresh-review:[ \t]*\S")
RULE_5 = "AGENTS.md, Committing, rule 5"


def reviewed_at_commit(path: str) -> bool:
    """Whether a change to repository-relative *path* needs its review before the commit."""
    parts = path.split("/")
    return len(parts) == 4 and parts[0] == "work" and parts[3] in ("spec.md", "plan.md")


def reviewed_before_push(path: str) -> bool:
    """Whether a change to repository-relative *path* needs its review before the push."""
    parts = path.split("/")
    return (
        parts[0] == "research"
        or path == "NOTICE.md"
        or path.startswith("docs/howto/")
        or (len(parts) == 2 and parts[0] == "docs" and path.endswith(".md"))
    )


def is_reviewed(message: str) -> bool:
    """Whether *message* carries a ``Fresh-review:`` trailer with a value."""
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


def _changed_paths(sha: str) -> list[str]:
    """The paths commit *sha* changes against its first parent (none for a merge)."""
    listed = _git(
        "-c",
        "core.quotepath=false",
        "diff-tree",
        "--no-commit-id",
        "--name-only",
        "--no-renames",
        "-r",
        "--root",
        sha,
    )
    return listed.splitlines()


def _range_review_problems(commits: list[tuple[str, str, str]]) -> dict[str, list[str]]:
    """Each oldest-first ``(full, short, message)`` commit's missing reviews, keyed by full hash."""
    found: dict[str, list[str]] = {}
    later_reviewed = False
    for full, _short, message in reversed(commits):
        paths = _changed_paths(full)
        listed = review_problems(message, paths)
        reviewed = is_reviewed(message)
        later_reviewed = later_reviewed or reviewed
        pushed = sorted(path for path in paths if reviewed_before_push(path))
        if pushed and not later_reviewed:
            listed.append(
                f"changes {', '.join(pushed)}, and neither it nor a later commit of the range "
                f"carries a Fresh-review: trailer ({RULE_5}): have a fresh reviewer read the "
                "diff, then add 'Fresh-review: <what it read>' to the newest commit's message"
            )
        if listed:
            found[full] = listed
    return found


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
    marked = [line[2:].strip() for line in lines if line.startswith("- ")]
    # An empty commit's patch matches any empty commit in the base, so it proves nothing.
    return {sha for sha in marked if _git("diff-tree", "--no-commit-id", "--name-only", "-r", sha)}


#: Seconds one ``gh api`` call may take before GitHub counts as unavailable.
GH_TIMEOUT = 30


class GitHubUnavailableError(Exception):
    """``gh`` is missing, or could not answer."""


_MERGED_PULLS_QUERY = """
query($owner: String!, $name: String!, $oid: GitObjectID!) {
  repository(owner: $owner, name: $name) {
    nameWithOwner
    object(oid: $oid) {
      ... on Commit {
        associatedPullRequests(first: 100) {
          nodes { number merged baseRepository { nameWithOwner } }
        }
      }
    }
  }
}
"""
#: The merged pull requests whose base is the queried repository, as a JSON list of numbers.
_MERGED_PULLS_JQ = (
    ".data.repository as $r | [($r.object.associatedPullRequests.nodes // [])[]"
    " | select(.merged and .baseRepository.nameWithOwner == $r.nameWithOwner) | .number]"
)


def _merged_pulls(sha: str) -> list[int]:
    """The numbers of the merged pull requests into this repository that hold commit *sha*.

    Only a pull request whose base is this repository counts: GitHub associates a commit with
    pull requests across the fork network, and one merged inside a contributor's fork was never
    checked here. A commit GitHub does not know has none.
    """
    gh = shutil.which("gh")
    if gh is None:
        raise GitHubUnavailableError("gh is not on PATH")
    try:
        done = subprocess.run(  # noqa: S603 - gh from PATH, fixed arguments
            [
                gh,
                "api",
                "graphql",
                "-F",
                "owner={owner}",
                "-F",
                "name={repo}",
                "-f",
                f"oid={sha}",
                "-f",
                f"query={_MERGED_PULLS_QUERY}",
                "--jq",
                _MERGED_PULLS_JQ,
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
            timeout=GH_TIMEOUT,
        )
        numbers = json.loads(done.stdout)
    except subprocess.CalledProcessError as error:
        raise GitHubUnavailableError(error.stderr.strip() or str(error)) from error
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
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
        message = args.message.read_text(encoding="utf-8")
        try:
            staged = _staged_paths()
        except (OSError, subprocess.CalledProcessError) as error:
            print(f"[commit-msg] cannot read the staged paths: {error}", file=sys.stderr)
            return 2
        found = [("this commit", problems(message) + review_problems(message, staged))]
    else:
        try:
            messages = _messages(args.range)
            reviews = _range_review_problems(messages)
            commits = [
                (full, short, problems(message) + reviews.get(full, []))
                for full, short, message in messages
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
