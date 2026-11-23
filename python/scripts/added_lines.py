#!/usr/bin/env python3
"""Every line a branch adds to its working tree over the merge base with a base ref.

``claim_words`` reads these lines for rule 5's over-broad words and ``pr_lint`` dates them, so
the diff is read once here: one ``git diff`` over the covered paths together, renames followed,
untracked files read whole, and a hunk consumed by its line counts so added content that looks
like a header is still content.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING
lazy from pathlib import Path

import gate

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

__all__ = ["AddedLine", "added_lines", "file_lines"]

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass(frozen=True)
class AddedLine:
    """One line the branch adds: repository-relative path, 1-based number, and text."""

    path: str
    number: int
    text: str


def _git(repo: Path, *args: str) -> str:
    """The stdout of git args in repo; raises CalledProcessError or OSError."""
    done = subprocess.run(  # noqa: S603 - fixed git arguments
        ["git", *args],  # noqa: S607 - git from PATH
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return done.stdout


def _untracked(repo: Path) -> set[str]:
    """The paths git does not track, relative to repo."""
    listed = _git(repo, "ls-files", "--others", "--exclude-standard", "-z")
    return {path for path in listed.split("\0") if path}


def file_lines(repo: Path, path: str) -> list[str]:
    """The working-tree lines of *path*, or none when it is gone or not UTF-8 text.

    A binary file raises ``UnicodeDecodeError``, a ``ValueError``, from the read; it has no lines
    to date or scan, so it is skipped rather than failing the run that read it.
    """
    try:
        return (repo / path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError, ValueError:
        return []


def _diff_added(repo: Path, base: str, paths: Sequence[str]) -> list[AddedLine]:
    """The lines the tracked paths add between base and the working tree, renames followed.

    One diff over every path, so rename detection keeps a moved note's unchanged lines out of the
    result. A hunk is consumed by its line counts, so added content that looks like a header is
    still content.
    """
    output = _git(
        repo,
        "diff",
        "-M",
        "--unified=0",
        "--no-color",
        "--no-ext-diff",
        base,
        "--",
        *paths,
    )
    added: list[AddedLine] = []
    path: str | None = None
    number = 0
    old_left = 0
    new_left = 0
    for line in output.splitlines():
        if old_left > 0 or new_left > 0:
            if line.startswith("+"):
                if path is not None:
                    added.append(AddedLine(path, number, line[1:]))
                number += 1
                new_left -= 1
            elif line.startswith("-"):
                old_left -= 1
            elif line.startswith(" "):
                number += 1
                old_left -= 1
                new_left -= 1
            continue
        if line.startswith("+++ b/"):
            path = line[6:]
        elif line.startswith(("+++ ", "diff --git ")):
            path = None
        hunk = _HUNK.match(line)
        if hunk is not None:
            number = int(hunk.group(3))
            old_left = int(hunk.group(2) or 1)
            new_left = int(hunk.group(4) or 1)
    return added


def added_lines(
    repo: Path, base: str | None = None, *, covered: Callable[[str], bool] | None = None
) -> list[AddedLine]:
    """Every line the working tree adds over its merge base with *base*, in path order.

    *base* defaults to ``gate.default_base(repo)``: ``origin/main`` when it resolves, else ``main``.
    *covered* limits the repository-relative POSIX paths read; None reads every path. Rename
    detection runs over the covered paths together, so a moved file's unchanged lines stay out,
    and a covered untracked file is read whole. Raises gate.ChangedPathsError when git cannot
    name the merge base or the changed paths, and OSError or subprocess.CalledProcessError when
    another git call fails.
    """
    base = base or gate.default_base(repo)
    try:
        merge_base = _git(repo, "merge-base", "HEAD", base).strip()
    except subprocess.CalledProcessError as error:
        # A shallow or no-base checkout exits 128 here; report the missing base the way
        # gate.changed_paths does, so every caller's existing skip or exit 2 covers it.
        raise gate.ChangedPathsError(f"no merge base between HEAD and {base}") from error
    if not merge_base:
        raise gate.ChangedPathsError(f"no merge base between HEAD and {base}")
    untracked = _untracked(repo)
    changed = [path for path in gate.changed_paths(repo, base) if covered is None or covered(path)]
    tracked = [path for path in changed if path not in untracked]
    found = _diff_added(repo, merge_base, tracked) if tracked else []
    for path in changed:
        if path in untracked:
            found.extend(
                AddedLine(path, number, text)
                for number, text in enumerate(file_lines(repo, path), start=1)
            )
    found.sort(key=lambda line: (line.path, line.number))
    return found
