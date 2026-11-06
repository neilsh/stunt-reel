#!/usr/bin/env python3
"""Repair, or else reject, staged text files that have CRLF line endings in the working copy.

``.gitattributes`` stores every text file with LF, so the index and the repository never hold
CRLF; but ``ruff format --check`` and the other tools read the working copy, and a Python
text-mode write on Windows leaves CRLF there. The format check then fails only after a full
gate run. This hook reads the working-tree bytes of each staged file (the index is already
normalised, so it cannot show the problem) and finds every file that has a CRLF, at commit
time.

A file whose working copy equals its index blob once each CRLF is replaced by LF holds nothing
the commit does not already have, so the hook repairs it: it removes the file and ``git checkout-index``
writes git's own LF copy in its place, the file is named as repaired, and the commit goes on. Any other file with
a CRLF (one with unstaged edits, or whose index blob itself holds a CRLF) is named and rejects
the commit, and its working copy is left untouched.

What is checked follows ``.gitattributes`` rather than a list kept here. A file is skipped when
git attributes mark it binary (``text`` unset), when its ``eol`` attribute is ``crlf`` (the
Windows launchers, ``*.bat`` and ``*.cmd``), or when it contains a NUL byte, which catches
binary files the attributes do not name. Deleted files, symlinks and submodules have no text
to read and are skipped.

Usage: ``mise run crlf-check`` (a pre-commit hook; it takes no arguments and reads the staged
paths from git). Exit status: ``0`` when no file is left with CRLF, ``1`` when one is, ``2``
when git cannot be run.
"""

from __future__ import annotations

import stat
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


def crlf_copy_of_index(root: Path, path: str) -> bytes | None:
    """The working copy of *path* when it is its index blob with some LFs written as CRLF.

    ``None`` when it differs in anything else, when the blob holds any CR (a CR the working copy
    adds before a CRLF would then pass the comparison), when there is no stage-0 blob (an
    unresolved conflict).
    """
    target = root / path
    try:
        # Stage 0 named outright: for a file named ``0:x``, ``:0:x`` is stage 0 of ``x``.
        blob = _git(root, "cat-file", "blob", f":0:{path}")
    except GitError:
        return None
    if b"\r" in blob:
        return None
    data = target.read_bytes()
    return data if data.replace(CRLF, b"\n") == blob else None


def mode_changes(root: Path) -> set[str]:
    """Paths whose working-tree file mode differs from the index, as git sees it.

    Git's own view, so ``core.filemode=false`` (the Windows default) reports none. One call
    over the whole tree: ``diff-files`` compares stat data only, and a path list could outrun
    the Windows command-line limit.
    """
    fields = _split(_git(root, "diff-files", "--raw", "-z"))
    changed: set[str] = set()
    for index in range(0, len(fields) - 1, 2):
        header, path = fields[index : index + 2]
        old_mode, new_mode = header.lstrip(":").split()[:2]
        # A deleted file shows mode 000000; it has no working copy to repair anyway.
        if old_mode != new_mode:
            changed.add(path)
    return changed


def _put_back(target: Path, data: bytes, mode: int) -> None:
    """Put back a removed working copy's bytes and permission bits, unless another writer's are there.

    The file is missing, holds git's copy (the same text in other line endings), or holds what
    some other process wrote since the hook removed it, which is kept.
    """
    try:
        current = target.read_bytes()
    except FileNotFoundError:
        current = None
    if current is not None and current.replace(CRLF, b"\n") != data.replace(CRLF, b"\n"):
        return
    target.write_bytes(data)
    target.chmod(mode)


def repair(root: Path, paths: Sequence[str]) -> tuple[list[str], list[str]]:
    """Rewrite from the index each of *paths* that differs from it only in line endings.

    Returns ``(repaired, rest)``, each in the order given. A path whose file mode differs from
    the index is left in *rest*; so is one whose rewritten copy is missing or still holds a CRLF
    (git set to write CRLF), which gets its old bytes back. A file written by another process
    meanwhile is neither removed nor overwritten. Raises :class:`GitError` if git fails, after
    putting every removed file back.
    """
    # ``git checkout-index -f`` skips a file whose stat data matches the index entry, as it does
    # right after ``git add`` of a CRLF file, so each file is removed first (its bytes kept to
    # put back) and git runs without ``-f``.
    candidates: dict[str, tuple[bytes, int]] = {}
    moved = mode_changes(root) if paths else set()
    for path in paths:
        if path in moved:
            continue
        data = crlf_copy_of_index(root, path)
        if data is None:
            continue
        try:
            candidates[path] = (data, stat.S_IMODE((root / path).stat().st_mode))
        except OSError:
            continue
    saved: dict[str, tuple[bytes, int]] = {}
    try:
        # Removed together, just before git writes them, so each is missing only briefly.
        for path, (data, mode) in candidates.items():
            target = root / path
            try:
                if target.read_bytes() != data:  # written since it was compared
                    continue
                target.unlink()
            except OSError:  # held open on Windows: leave it to be reported
                continue
            saved[path] = (data, mode)
        if saved:
            # On stdin, so no number of paths can outrun the Windows command-line limit.
            stdin = b"".join(path.encode("utf-8", "surrogateescape") + b"\0" for path in saved)
            _git(root, "checkout-index", "-z", "--stdin", stdin=stdin)
    except BaseException:
        # Git may have rewritten some paths before it failed: put every one back as it was.
        for path, (data, mode) in saved.items():
            _put_back(root / path, data, mode)
        raise
    repaired: list[str] = []
    for path, (data, mode) in saved.items():
        try:
            written = (root / path).read_bytes()
        except FileNotFoundError:
            written = CRLF
        if CRLF in written:
            _put_back(root / path, data, mode)
        else:
            repaired.append(path)
    rest = [path for path in paths if path not in repaired]
    return repaired, rest


def main(argv: Sequence[str] | None = None) -> int:
    """Run the hook from the repository (or any directory in it)."""
    del argv
    try:
        root = Path(_git(None, "rev-parse", "--show-toplevel").decode("utf-8").strip())
        repaired, bad = repair(root, offenders(root))
    except GitError as error:
        print(f"crlf-check: {error}", file=sys.stderr)
        return 2
    if repaired:
        print("crlf-check: rewrote these working copies from the index as LF:", file=sys.stderr)
        for path in repaired:
            print(f"  {path}", file=sys.stderr)
    if not bad:
        return 0
    print(
        "crlf-check: staged files with CRLF line endings in a working copy that differs from the\n"
        "index beyond line endings (unstaged edits), so not repaired:",
        file=sys.stderr,
    )
    for path in bad:
        print(f"  {path}", file=sys.stderr)
    print(
        "The repository stores LF (.gitattributes), but the format checks read the working copy.\n"
        "Convert each file to LF (an editor setting, or `dos2unix <file>`), or stage the edits\n"
        "too, after which the hook rewrites the file as LF from the index itself.\n"
        "From Python, write with newline='\\n' or Path.write_bytes.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
