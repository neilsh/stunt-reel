"""Runs ``stuntreel link``: a film's ``.ALL`` recorded as a manifest, and rebuilt from one.

The linking is Rust (``crates/stunt-cli/src/link.rs``); this module only builds the argv,
runs the release binary and turns its exit code into an exception: 0 returns, 3 raises
:class:`NotLinkable` (the archive holds content the game's ``RES/`` lacks), anything else
raises :class:`LinkError`. It also owns the binary's location and the command that builds it.
It must not import ``all_archive`` or ``parity_pipeline``, which import it.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from stunt_reel.dataroot import REPO_ROOT

__all__ = [
    "BUILD_ARGV",
    "EXIT_NOT_LINKABLE",
    "LinkError",
    "NotLinkable",
    "Runner",
    "binary_locked",
    "binary_path",
    "build_archive",
    "ensure_binary",
    "extract_manifest",
]

#: Builds the release binary; ``parity_pipeline.build_release`` runs the same command.
BUILD_ARGV: tuple[str, ...] = ("cargo", "build", "--release", "-p", "stunt-cli")

#: ``stuntreel link``'s exit code for an archive with no manifest (``EXIT_NOT_LINKABLE`` in Rust).
EXIT_NOT_LINKABLE = 3

#: Runs an argv in a directory to completion, capturing text output.
Runner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]


class LinkError(RuntimeError):
    """``stuntreel link`` failed: I/O, a hash, a malformed manifest, a rebuild that differs."""


class NotLinkable(LinkError):  # noqa: N818 - a verdict on the archive, not a failure of the tool
    """The archive holds content the game's ``RES/`` lacks, so it has no manifest (exit 3)."""


def _run(argv: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603 - argv built here: the release binary or cargo
            list(argv), cwd=cwd, capture_output=True, text=True, check=False
        )
    except OSError as exc:
        raise LinkError(f"cannot run {argv[0]}: {exc}") from exc


def binary_path() -> Path:
    """The release binary every render and score runs."""
    return REPO_ROOT / "target" / "release" / ("stuntreel.exe" if os.name == "nt" else "stuntreel")


def binary_locked(path: Path) -> bool:
    """Whether a process holds ``path`` open for writing (Windows refuses that on a running exe)."""
    if os.name != "nt" or not path.is_file():
        return False
    try:
        with path.open("r+b"):
            return False
    except PermissionError:
        return True


def ensure_binary(*, run: Runner = _run) -> Path:
    """Builds the release binary unless it is running, and returns its path.

    An older binary has no ``link`` subcommand, so callers build first; cargo makes that a no-op
    when the binary is current. A running binary cannot be replaced on Windows, so it is used
    as it is rather than failing the caller.
    """
    path = binary_path()
    if not binary_locked(path):
        _check(run(BUILD_ARGV, REPO_ROOT))
    return path


def build_archive(manifest: Path, game: Path, out: Path, *, cwd: Path, run: Runner = _run) -> None:
    """Rebuilds the archive *manifest* describes from the game tree *game* into *out*."""
    argv = [str(binary_path()), "link", "build", str(manifest), "--game", str(game), "-o", str(out)]
    _check(run(argv, cwd))


def extract_manifest(
    archive: Path,
    flm: Path,
    game: str,
    makeone_sha256: str,
    out: Path,
    *,
    cwd: Path,
    run: Runner = _run,
) -> None:
    """Writes *archive*'s manifest to *out*; *game* is recorded verbatim as its ``game_root``."""
    argv = [
        str(binary_path()),
        "link",
        "extract",
        str(archive),
        "--flm",
        str(flm),
        "--game",
        game,
        "--makeone-sha256",
        makeone_sha256,
        "-o",
        str(out),
    ]
    _check(run(argv, cwd))


def _check(result: subprocess.CompletedProcess[str]) -> None:
    if result.returncode == 0:
        return
    message = result.stderr.strip() or f"{result.args[0]} exited {result.returncode}"
    if result.returncode == EXIT_NOT_LINKABLE:
        raise NotLinkable(message)
    raise LinkError(message)
