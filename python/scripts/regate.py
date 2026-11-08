#!/usr/bin/env python3
"""Gate every commit of ``<base>..HEAD`` and give each the gate line its run printed.

After a rebase every commit holds a new tree, so the commit-msg hook no longer matches its gate
line to a passing run (docs/development.md, "The gate line is checked"). This checks out each
commit detached, oldest first, and runs ``mise run check`` on it with the variables
``git rev-parse --local-env-vars`` lists removed, since a gate whose tests run git would act on
the outer repository with them set. Each run picks its own scope, as ``mise run check`` does;
arguments after a second ``--`` reach every run.

All or nothing: when a run fails, the original checkout comes back, the branch is untouched, and
the failing commit is named. When every run passes, the chain is rebuilt with ``git commit-tree``
(no hook runs) on the same trees, authors, committers and dates, each message's gate line
replaced, or added before its trailers. The old tip is kept as ``refs/backup/regate/<branch>``
and the branch moves once. Nothing is pushed.

Usage: ``mise run regate -- <base> [-- <gate args>]``. Exit status: ``0`` when the branch was
regated, ``1`` when it was not.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
lazy from collections.abc import Sequence

import check_commit_msg

GATE = ("mise", "run", "check")
GATE_LINE = "[gate] gate line: "


class RegateError(Exception):
    """Why the branch cannot be, or was not, regated."""


def parse(argv: Sequence[str]) -> tuple[str, list[str]]:
    """``(base, gate args)`` from ``<base> [-- <gate args>]``."""
    head, gate_args = list(argv), []
    if "--" in head:
        split = head.index("--")
        head, gate_args = head[:split], head[split + 1 :]
    parser = argparse.ArgumentParser(prog="mise run regate --", description=__doc__.splitlines()[0])
    parser.add_argument("base", help="the commit the branch's commits sit on, as in <base>..HEAD")
    return str(parser.parse_args(head).base), gate_args


def gate_command(gate_args: Sequence[str]) -> list[str]:
    """The gate run on each commit, with *gate_args* passed through."""
    return [*GATE, "--", *gate_args] if gate_args else list(GATE)


def clean_env() -> dict[str, str]:
    """This process's environment without the variables that point git at a repository."""
    listed = subprocess.run(
        ["git", "rev-parse", "--local-env-vars"],  # noqa: S607 - git from PATH
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.split()
    return {name: value for name, value in os.environ.items() if name not in listed}


class Repo:
    """git in one checkout, with a fixed environment."""

    def __init__(self, path: Path, env: dict[str, str]) -> None:
        self.path = path
        self.env = env

    def git(self, *args: str, stdin: str | None = None, env: dict[str, str] | None = None) -> str:
        """The stripped output of ``git <args>``; raise ``RegateError`` when it fails."""
        # Bytes, not text: a text pipe on Windows would write each message with CRLF.
        done = subprocess.run(  # noqa: S603 - fixed git arguments
            ["git", *args],  # noqa: S607 - git from PATH
            cwd=self.path,
            input=None if stdin is None else stdin.encode("utf-8"),
            capture_output=True,
            check=False,
            env={**self.env, **(env or {})},
        )
        if done.returncode != 0:
            problem = done.stderr.decode("utf-8", "replace").strip() or done.returncode
            raise RegateError(f"git {' '.join(args)}: {problem}")
        return done.stdout.decode("utf-8").strip()


def with_gate_line(message: str, line: str) -> str:
    """*message* with its gate line replaced by *line*, or *line* added before its trailers.

    A gate line's prose before ``mise run check`` is kept. Without one, *line* becomes its own
    paragraph, before the last paragraph when that holds only trailers.
    """
    lines = message.rstrip("\n").split("\n")
    found = False
    for index, text in enumerate(lines[1:], start=1):
        if check_commit_msg.is_gate_line(text):
            lines[index] = text[: text.index(check_commit_msg.GATE)] + line
            found = True
    if not found:
        start = len(lines)
        while start > 0 and lines[start - 1] and check_commit_msg.TRAILER.match(lines[start - 1]):
            start -= 1
        has_trailers = start < len(lines) and start > 1 and not lines[start - 1]
        at = start if has_trailers else len(lines)
        lines[at:at] = [line, ""] if has_trailers else ["", line]
    return "\n".join(lines) + "\n"


def _run_gate(command: Sequence[str], repo: Repo) -> str | None:
    """Run the gate in *repo*, echoing its output; the gate line it printed, or ``None``."""
    found: str | None = None
    # Resolved first: on Windows mise may be a shim CreateProcess would not find by name.
    program = [shutil.which(command[0]) or command[0], *command[1:]]
    try:
        with subprocess.Popen(  # noqa: S603 - the gate command
            program,
            cwd=repo.path,
            env=repo.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        ) as process:
            for text in process.stdout or ():
                print(text, end="", flush=True)
                if text.startswith(GATE_LINE):
                    found = text.removeprefix(GATE_LINE).strip()
    except OSError as error:
        raise RegateError(f"cannot run {command[0]}: {error}") from error
    return found if process.returncode == 0 and found else None


def _gate_each(command: Sequence[str], repo: Repo, commits: list[str], branch: str) -> list[str]:
    """Each commit's gate line, gating them in order in a detached checkout.

    The checkout of *branch* is restored whatever happens.
    """
    lines: list[str] = []
    try:
        for number, sha in enumerate(commits, start=1):
            subject = repo.git("log", "-1", "--format=%h %s", sha)
            print(f"[regate] {number}/{len(commits)} {subject}", flush=True)
            repo.git("checkout", "-q", "--detach", sha)
            line = _run_gate(command, repo)
            if line is None:
                raise RegateError(f"the gate failed at {subject}")
            if repo.git("status", "--porcelain"):
                raise RegateError(f"the gate left the working tree changed at {subject}")
            lines.append(line)
    finally:
        try:
            repo.git("checkout", "-q", branch)
        except RegateError as error:
            print(f"[regate] cannot check {branch} out again: {error}", file=sys.stderr)
    return lines


def _rebuild(repo: Repo, commits: list[str], lines: list[str]) -> str:
    """The new tip: each commit again on the same tree, people and dates, with its gate line."""
    parent = repo.git("rev-parse", f"{commits[0]}^")
    for sha, line in zip(commits, lines, strict=True):
        fields = repo.git(
            "log", "-1", "--date=raw", "--format=%T%x00%an%x00%ae%x00%ad%x00%cn%x00%ce%x00%cd", sha
        ).split("\0")
        tree, people = (
            fields[0],
            dict(
                zip(
                    (
                        "GIT_AUTHOR_NAME",
                        "GIT_AUTHOR_EMAIL",
                        "GIT_AUTHOR_DATE",
                        "GIT_COMMITTER_NAME",
                        "GIT_COMMITTER_EMAIL",
                        "GIT_COMMITTER_DATE",
                    ),
                    fields[1:],
                    strict=True,
                )
            ),
        )
        message = with_gate_line(repo.git("log", "-1", "--format=%B", sha), line)
        parent = repo.git("commit-tree", tree, "-p", parent, "-F", "-", stdin=message, env=people)
    return parent


def _commits_to_gate(repo: Repo, base: str) -> list[str]:
    """The commits of ``<base>..HEAD``, oldest first, once the checkout can be regated."""
    if repo.git("status", "--porcelain"):
        raise RegateError(
            "the working tree is not clean (the gate tests untracked files too): "
            "commit or remove the changes first"
        )
    if repo.git("rev-list", "--merges", f"{base}..HEAD"):
        raise RegateError(f"{base}..HEAD holds a merge commit; regate rebuilds a line only")
    commits = repo.git("rev-list", "--reverse", f"{base}..HEAD").split()
    if not commits:
        raise RegateError(f"{base}..HEAD holds no commits")
    return commits


def regate(base: str, command: Sequence[str], path: Path) -> int:
    """Gate ``<base>..HEAD`` in *path* with *command*; rewrite the branch only if all pass."""
    repo = Repo(path, clean_env())
    try:
        branch = repo.git("symbolic-ref", "--quiet", "--short", "HEAD")
    except RegateError:
        print("[regate] HEAD is detached: check out the branch to regate", file=sys.stderr)
        return 1
    try:
        commits = _commits_to_gate(repo, base)
        old_tip = repo.git("rev-parse", "HEAD")
        lines = _gate_each(command, repo, commits, branch)
        new_tip = _rebuild(repo, commits, lines)
        backup = f"refs/backup/regate/{branch}"
        repo.git("update-ref", "-m", "regate: the tip before", backup, old_tip)
        repo.git("update-ref", "-m", "regate", f"refs/heads/{branch}", new_tip, old_tip)
    except RegateError as error:
        print(f"[regate] {error}; {branch} is unchanged", file=sys.stderr)
        return 1
    print(f"[regate] {branch}: {len(commits)} commits regated, {old_tip[:12]} -> {new_tip[:12]}")
    print(f"[regate] the old tip is {backup}; undo with: git reset --keep {backup}")
    print(
        f"[regate] next: gh stack push in a stack, else git push --force-with-lease origin {branch}"
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Regate the checked-out branch from the command line."""
    base, gate_args = parse(sys.argv[1:] if argv is None else argv)
    return regate(base, gate_command(gate_args), Path.cwd())


if __name__ == "__main__":
    raise SystemExit(main())
