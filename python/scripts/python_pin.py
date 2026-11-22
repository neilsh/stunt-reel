"""Which Python runs the bootstrap scripts, and the guard that hands them to the pinned one.

``init``, ``ensure`` and ``seed`` run ``worktree_init.py`` with a bare ``python``, before this
checkout has a virtualenv, while the package it imports uses ``lazy from`` (PEP 810, Python 3.15):
an older ``python`` cannot parse that, so the import raises ``SyntaxError`` before a line of the
script runs (issue #854). ``guard`` runs first, compares this interpreter with
``requires-python`` in ``pyproject.toml``, and runs the script again on the interpreter
``mise which python`` names when this one is too old. When mise cannot name one, it reports the
interpreter it found and the version needed. ``gate.py`` takes the same guard, for the same
reason (issue #884).

``stunt_reel/uv.py`` is the same idea for uv. This module sits in ``python/scripts`` because it
must import without the package, whose ``__init__`` imports ``tac``, and it keeps to the standard
library and away from ``lazy from`` for that reason.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

#: The checkout this module belongs to: ``python/scripts/python_pin.py``, three folders up.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

#: ``mise which python`` resolves for this checkout's config, for callers that name no root.
PYPROJECT = REPO_ROOT / "pyproject.toml"
MISE_TOML = REPO_ROOT / "mise.toml"

#: A ``mise which`` or ``--version`` past this counts as no answer: a guess would hold a task.
_TIMEOUT_S = 60.0

#: What "unavailable" looks like: a file that is missing, unreadable or not TOML, or a command
#: that will not start or answer in time. The types are named once in a tuple because ruff format
#: writes Python 3.14's unparenthesized `except A, B:` at py315, and this module must still parse
#: on an older interpreter, the very case it reports.
_UNAVAILABLE = (OSError, KeyError, TypeError, ValueError, subprocess.TimeoutExpired)


def _numbers(text: str) -> tuple[int, int, int] | None:
    """The first three integers in *text*, zero-filled (``>=3.15`` -> ``(3, 15, 0)``), or None."""
    parts = [int(part) for part in re.findall(r"\d+", text)[:3]]
    if not parts:
        return None
    major, minor, patch = [*parts, 0, 0, 0][:3]
    return (major, minor, patch)


def _dotted(version: tuple[int, ...]) -> str:
    """*version* as dotted text, without a trailing zero: ``(3, 15, 0)`` -> ``3.15``."""
    parts = [str(part) for part in version]
    return ".".join(parts[:-1] if len(parts) > 2 and parts[-1] == "0" else parts)


def _same_file(one: Path, other: Path) -> bool:
    """Whether two paths name one file; Path equality folds case where the platform does."""
    try:
        return one.resolve() == other.resolve()
    except OSError:
        # A path this platform refuses to resolve still compares as it was given.
        return one.absolute() == other.absolute()


def required_python(pyproject: Path = PYPROJECT) -> tuple[int, int, int] | None:
    """The version *pyproject*'s ``requires-python`` floor names, or None when it names none."""
    try:
        with pyproject.open("rb") as handle:
            floor = str(tomllib.load(handle)["project"]["requires-python"])
    except _UNAVAILABLE:
        return None
    return _numbers(floor)


def pinned_version(mise_toml: Path = MISE_TOML) -> str | None:
    """The Python version *mise_toml* pins under ``[tools]``, or None when it pins none."""
    try:
        with mise_toml.open("rb") as handle:
            return str(tomllib.load(handle)["tools"]["python"])
    except _UNAVAILABLE:
        return None


def mise_python(root: Path = REPO_ROOT) -> Path | None:
    """The interpreter ``mise which python`` names for *root*, or None when mise names none."""
    mise = shutil.which("mise")
    if mise is None:
        return None
    try:
        listed = subprocess.run(  # noqa: S603 - the resolved mise, fixed arguments
            [mise, "which", "python"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=_TIMEOUT_S,
        )
    except _UNAVAILABLE:
        return None
    if listed.returncode != 0:
        return None
    named = [line.strip() for line in listed.stdout.splitlines() if line.strip()]
    return Path(named[-1]) if named else None


def interpreter_version(python: Path) -> tuple[int, int, int] | None:
    """The version *python* answers ``--version`` with, or None when it answers none."""
    try:
        reported = subprocess.run(  # noqa: S603 - the resolved interpreter, fixed arguments
            [str(python), "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_TIMEOUT_S,
        )
    except _UNAVAILABLE:
        return None
    return _numbers(reported.stdout or reported.stderr)


def not_runnable(
    required: tuple[int, int, int],
    script: Path,
    found: Path,
    running: tuple[int, int, int],
    pin: str | None,
    candidate: Path | None,
    candidate_version: tuple[int, int, int] | None,
) -> str:
    """The report for a ``python`` too old to parse the package, naming the script and interpreter."""
    message = [
        (
            f"  ! python {_dotted(running)} at {found} cannot run {script.name}: "
            f"it needs Python {_dotted(required)} or newer (requires-python in pyproject.toml)."
        )
    ]
    if candidate is not None:
        reports = (
            f"Python {_dotted(candidate_version)}"
            if candidate_version is not None
            else "no readable version"
        )
        message.append(f"  ! mise which python names {candidate}, which reports {reports}.")
        return "\n".join(message)
    pinned = f"mise.toml pins Python {pin}" if pin else "mise.toml names no Python pin"
    message.append(
        f"  ! mise which python named no interpreter, and {pinned}. "
        "Run this through 'mise run' so mise's Python comes first on PATH."
    )
    return "\n".join(message)


def guard(script: Path, argv: list[str]) -> int | None:
    """Run *script* again on the pinned interpreter when this one cannot parse the package.

    None when this interpreter is new enough, or has just run *script* through the one mise
    names. Otherwise the status the command ends with: 0 for ``ensure``, which only makes a
    first build faster and must never stop a task (ADR 0036), and 1 for the rest.
    """
    required = required_python()
    running = (int(sys.version_info[0]), int(sys.version_info[1]), int(sys.version_info[2]))
    if required is None or running[:2] >= required[:2]:
        return None
    found = Path(sys.executable)
    candidate = mise_python()
    candidate_version = interpreter_version(candidate) if candidate is not None else None
    if (
        candidate is not None
        and candidate_version is not None
        and candidate_version[:2] >= required[:2]
        and not _same_file(candidate, found)
    ):
        try:
            return subprocess.run(  # noqa: S603 - the pinned interpreter, fixed arguments
                [str(candidate), str(script), *argv], check=False
            ).returncode
        except OSError:
            # It vanished between the lookup and the run: report below, do not raise.
            pass
    print(
        not_runnable(
            required, script, found, running, pinned_version(), candidate, candidate_version
        ),
        file=sys.stderr,
    )
    return 0 if argv[:1] == ["ensure"] else 1
