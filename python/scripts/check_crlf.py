#!/usr/bin/env python3
"""Fail when a staged text file has CRLF line endings in the working copy.

``.gitattributes`` stores every text file with LF, so the index and the repository never hold
CRLF; but ``ruff format --check`` and the other tools read the working copy, and a Python
text-mode write on Windows leaves CRLF there. The format check then fails only after a full
gate run. This hook reads the working-tree bytes of each staged file (the index is already
normalised, so it cannot show the problem) and names every file that has a CRLF, at commit
time.

What is checked follows ``.gitattributes`` rather than a list kept here. A file is skipped when
git attributes mark it binary (``text`` unset), when its ``eol`` attribute is ``crlf`` (the
Windows launchers, ``*.bat`` and ``*.cmd``), or when it contains a NUL byte, which catches
binary files the attributes do not name. Deleted files, symlinks and submodules have no text
to read and are skipped.

Usage: ``mise run crlf-check`` (a pre-commit hook; it takes no arguments and reads the staged
paths from git). Exit status: ``0`` when no file has CRLF, ``1`` when one does, ``2`` when git
cannot be run.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

CRLF = b"\r\n"


class GitError(Exception):
    """A git command the hook depends on failed."""


def _git(root: Path | None, *args: str, stdin: bytes | None = None) -> bytes:
    """Standard output of ``git *args`` run in *root* (the current directory when ``None``)."""
    try:
        done = subprocess.run(  # noqa: S603 - fixed git arguments
            ["git", *args],  # noqa: S607 - git from PATH, as every task
            cwd=root,
            input=stdin,
            capture_output=True,
            check=False,
        )
    except OSError as error:
        raise GitError(f"cannot run git: {error}") from error
    if done.returncode != 0:
        detail = done.stderr.decode("utf-8", "replace").strip()
        raise GitError(f"git {' '.join(args)} failed: {detail}")
    return done.stdout


def _split(output: bytes) -> list[str]:
    """The NUL-terminated entries of ``-z`` output, decoded."""
    return [item.decode("utf-8", "surrogateescape") for item in output.split(b"\0") if item]


def staged_paths(root: Path) -> list[str]:
    """Added, copied, modified and renamed paths in the index, relative to *root*."""
    output = _git(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    return _split(output)


def attributes(root: Path, paths: Sequence[str]) -> dict[str, dict[str, str]]:
    """``text`` and ``eol`` attributes of each path, as ``git check-attr`` reports them."""
    stdin = b"".join(path.encode("utf-8", "surrogateescape") + b"\0" for path in paths)
    fields = _split(_git(root, "check-attr", "-z", "--stdin", "text", "eol", stdin=stdin))
    found: dict[str, dict[str, str]] = {path: {} for path in paths}
    for index in range(0, len(fields) - 2, 3):
        path, name, value = fields[index : index + 3]
        found[path][name] = value
    return found


def has_crlf(path: Path, attrs: dict[str, str]) -> bool:
    """Whether the working copy at *path* is text that should be LF but holds a CRLF."""
    if attrs.get("text") == "unset" or attrs.get("eol") == "crlf":
        return False
    if path.is_symlink() or not path.is_file():
        return False
    data = path.read_bytes()
    return CRLF in data and b"\0" not in data


def offenders(root: Path) -> list[str]:
    """The staged paths whose working copy has CRLF endings, in index order."""
    paths = staged_paths(root)
    if not paths:
        return []
    attrs = attributes(root, paths)
    return [path for path in paths if has_crlf(root / path, attrs[path])]


def main(argv: Sequence[str] | None = None) -> int:
    """Run the hook from the repository (or any directory in it)."""
    del argv
    try:
        root = Path(_git(None, "rev-parse", "--show-toplevel").decode("utf-8").strip())
        bad = offenders(root)
    except GitError as error:
        print(f"crlf-check: {error}", file=sys.stderr)
        return 2
    if not bad:
        return 0
    print("crlf-check: staged files with CRLF line endings in the working copy:", file=sys.stderr)
    for path in bad:
        print(f"  {path}", file=sys.stderr)
    print(
        "The repository stores LF (.gitattributes), but the format checks read the working copy.\n"
        "Convert each file to LF (an editor setting, or `dos2unix <file>`) and stage it again.\n"
        "From Python, write with newline='\\n' or Path.write_bytes.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
