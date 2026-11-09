#!/usr/bin/env python3
"""Gate every commit of ``<base>..HEAD`` and give each the gate line its run printed.

Rewrites the branch only when every run passes, keeping the old tip as
``refs/backup/regate/<branch>``; never pushes. How and why: docs/howto/re-gate-after-a-rebase.md.

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
import gate

GATE = ("mise", "run", "check")
#: Each ``git log`` format code, and the variable that gives ``git commit-tree`` the same value.
PEOPLE = {
    "%an": "GIT_AUTHOR_NAME",
    "%ae": "GIT_AUTHOR_EMAIL",
    "%ad": "GIT_AUTHOR_DATE",
    "%cn": "GIT_COMMITTER_NAME",
    "%ce": "GIT_COMMITTER_EMAIL",
    "%cd": "GIT_COMMITTER_DATE",
}


class RegateError(Exception):
    """Why the branch cannot be, or was not, regated."""


def parse(argv: Sequence[str]) -> tuple[str, list[str]]:
    """``(base, gate args)`` from ``<base> [-- <gate args>]``."""
    before, gate_args = list(argv), []
    if "--" in before:
        split = before.index("--")
        before, gate_args = before[:split], before[split + 1 :]
    parser = argparse.ArgumentParser(prog="mise run regate --", description=__doc__.splitlines()[0])
    parser.add_argument("base", help="the commit the branch's commits sit on, as in <base>..HEAD")
    return str(parser.parse_args(before).base), gate_args


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


def gate_lines(message: str) -> list[int]:
    """The indices of *message*'s body lines that the commit-msg hook reads as gate lines."""
    lines = message.rstrip("\n").split("\n")
    return [
        index for index, text in enumerate(lines) if index and check_commit_msg.is_gate_line(text)
    ]


def _with_claim(text: str, line: str) -> str:
    """Gate line *text* with its claim, from the first gate name to the last outcome, as *line*."""
    names = list(check_commit_msg.GATE_NAME.finditer(text))
    outcome = check_commit_msg.OUTCOME.match(text, names[-1].end())
    end = outcome.end() if outcome else names[-1].end()
    end += text.startswith(".", end)
    return text[: names[0].start()] + line + text[end:]


def with_gate_line(message: str, line: str) -> str:
    """*message* with its last gate line's claim replaced by *line*, or *line* added.

    The prose around the claim is kept. Without a gate line, *line* becomes its own paragraph,
    before the last paragraph when that holds only trailers.
    """
    lines = message.rstrip("\n").split("\n")
    if found := gate_lines(message):
        lines[found[-1]] = _with_claim(lines[found[-1]], line)
    else:
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
                if text.startswith(gate.GATE_LINE_PREFIX):
                    found = text.removeprefix(gate.GATE_LINE_PREFIX).strip()
    except OSError as error:
        raise RegateError(f"cannot run {command[0]}: {error}") from error
    return found if process.returncode == 0 and found else None


def _gate_one(command: Sequence[str], repo: Repo, sha: str, progress: str) -> str:
    """The gate line *sha* earns, checked out detached; raise ``RegateError`` when it earns none."""
    subject = repo.git("log", "-1", "--format=%h %s", sha)
    print(f"[regate] {progress} {subject}", flush=True)
    repo.git("checkout", "-q", "--detach", sha)
    line = _run_gate(command, repo)
    if line is None:
        raise RegateError(f"the gate failed at {subject}")
    if changed := repo.git("status", "--porcelain"):
        raise RegateError(f"the gate left the working tree changed at {subject}:\n{changed}")
    return line


def _gate_each(command: Sequence[str], repo: Repo, commits: list[str], branch: str) -> list[str]:
    """Each commit's gate line, gating them in order in a detached checkout.

    *branch* is checked out again afterwards, discarding what a gate wrote to tracked files and
    naming what is left; raise ``RegateError`` when it cannot be.
    """
    try:
        lines = [
            _gate_one(command, repo, sha, f"{number}/{len(commits)}")
            for number, sha in enumerate(commits, start=1)
        ]
    except BaseException:
        try:
            _check_out_again(repo, branch)
            if left := repo.git("status", "--porcelain"):
                print(
                    f"[regate] the gate left these, which the next regate refuses:\n{left}",
                    file=sys.stderr,
                )
        except RegateError as error:
            print(f"[regate] {error}", file=sys.stderr)
        raise
    _check_out_again(repo, branch)
    return lines


def _check_out_again(repo: Repo, branch: str) -> None:
    """Check *branch* out, overwriting the working tree's changes; raise when git refuses."""
    try:
        repo.git("checkout", "-q", "--force", branch)
    except RegateError as error:
        raise RegateError(
            f"cannot check {branch} out again, so HEAD is detached: {error}"
        ) from error


def _rebuild(repo: Repo, commits: list[str], lines: list[str]) -> str:
    """The new tip: each commit again on the same tree, people and dates, with its gate line."""
    tip = repo.git("rev-parse", f"{commits[0]}^")
    for sha, line in zip(commits, lines, strict=True):
        tree, *values = repo.git(
            "log", "-1", "--date=raw", "--format=" + "%x00".join(["%T", *PEOPLE]), sha
        ).split("\0")
        people = dict(zip(PEOPLE.values(), values, strict=True))
        message = with_gate_line(repo.git("log", "-1", "--format=%B", sha), line)
        tip = repo.git("commit-tree", tree, "-p", tip, "-F", "-", stdin=message, env=people)
    return tip


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
    for sha in commits:
        if len(found := gate_lines(repo.git("log", "-1", "--format=%B", sha))) > 1:
            subject = repo.git("log", "-1", "--format=%h %s", sha)
            raise RegateError(
                f"{subject} has {len(found)} gate lines and regate replaces one: reword the others"
            )
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
        # One transaction: the branch moves only if it is still at old_tip and the backup is written.
        repo.git(
            "update-ref",
            "--create-reflog",
            "-m",
            "regate",
            "--stdin",
            stdin=f"update refs/heads/{branch} {new_tip} {old_tip}\nupdate {backup} {old_tip}\n",
        )
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
