"""The uv version ``mise.toml`` pins, and the uvs on PATH that cannot run the repo's tasks.

A standalone uv earlier on PATH shadows mise's shim, and bare ``uv`` calls then fail with uv's
own "Required uv version" error. The gate checks the first uv on PATH, which every step
inherits. Under mise that first uv is the pin, but a stale uv further along PATH still runs once
mise's directories are gone, so ``init`` and ``ensure`` also name one outside mise's install.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tomllib
from typing import TYPE_CHECKING
lazy from pathlib import Path

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["check_uv", "uv_pin", "uv_problem", "uv_shadowed_problem"]


def uv_pin(mise_toml: Path) -> str:
    """The uv version ``mise.toml`` pins under ``[tools]``."""
    with mise_toml.open("rb") as handle:
        return str(tomllib.load(handle)["tools"]["uv"])


def uv_problem(pin: str, found: str | None, version: str, every: Sequence[str]) -> str | None:
    """Why the uv at *found* (``uv --version`` printed *version*) cannot run the gate, or None.

    *every* is each uv on PATH, in order, so the message names what shadows mise's.
    """
    if found is None:
        return f"uv is not on PATH; mise.toml pins {pin}: run the gate through 'mise run check'"
    words = version.split()
    if len(words) >= 2 and words[1] == pin:
        return None
    running = words[1] if len(words) >= 2 else repr(version.strip())
    listed = "".join(f"\n  {path}" for path in every) or f"\n  {found}"
    return (
        f"uv {running} at {found} runs, but mise.toml pins {pin}. "
        f"Every uv on PATH, first wins:{listed}\n"
        "Remove the stale one, or run the gate from a shell where mise's comes first."
    )


def uv_shadowed_problem(pin: str, found: str | None, every: Sequence[str]) -> str | None:
    """Why a uv outside mise's install, besides *found*, would fail the pin when mise's is gone.

    ``None`` when every uv further along PATH either sits under mise's install or runs *pin*.
    Only init and ensure ask: the gate checks the uv first on PATH, which every step inherits.
    """
    root = _mise_uv_root(found)
    stale: list[tuple[str, str]] = []
    for path in every:
        if path == found or (root is not None and _under(path, root)):
            continue
        running = _version(path)
        if running != pin:
            stale.append((path, running))
    if not stale:
        return None
    listed = "".join(f"\n  {path} ({running or 'version unreadable'})" for path, running in stale)
    return (
        f"mise.toml pins uv {pin}, but a uv outside mise's install runs another version. "
        f"Outside mise, a bare uv runs one of these:{listed}\n"
        "Remove the stale one, or keep mise's uv first on PATH."
    )


def _version(path: str) -> str:
    """The version word ``path --version`` prints, or an empty string when it prints none."""
    proc = subprocess.run(  # noqa: S603 - the resolved uv, fixed arguments
        [path, "--version"], capture_output=True, text=True, check=False
    )
    words = proc.stdout.split()
    return words[1] if len(words) >= 2 else proc.stdout.strip()


def _mise_uv_root(found: str | None) -> Path | None:
    """Mise's uv install directory, read off the first uv on PATH, or None when it is not mise's."""
    if found is None:
        return None
    parts = Path(found).parts
    folders = [part.lower() for part in parts]
    for index in range(len(parts) - 1):
        if folders[index] == "installs" and folders[index + 1] == "uv":
            return Path(*parts[: index + 2])
    return None


def _under(path: str, root: Path) -> bool:
    """Whether *path* sits inside *root*."""
    try:
        Path(path).resolve().relative_to(root.resolve())
    except OSError, ValueError:
        return False
    return True


def _uvs_on_path() -> list[str]:
    """Every uv executable on PATH, in PATH order."""
    found: list[str] = []
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        hit = shutil.which("uv", path=folder) if folder else None
        if hit and hit not in found:
            found.append(hit)
    return found


def check_uv(mise_toml: Path, *, shadowed: bool = False) -> str | None:
    """The uv problem for this process's PATH, against *mise_toml*'s pin.

    Raises OSError, KeyError or ValueError when *mise_toml* is missing, unreadable or has no
    pin; the gate needs it, while init and ensure catch those and stay quiet. ``None`` when the
    uv first on PATH is the pin; with *shadowed*, also when no uv further along PATH, outside
    mise's install, runs another version.
    """
    pin = uv_pin(mise_toml)
    every = _uvs_on_path()
    found = shutil.which("uv")
    version = ""
    if found is not None:
        proc = subprocess.run(  # noqa: S603 - the resolved uv, fixed arguments
            [found, "--version"], capture_output=True, text=True, check=False
        )
        version = proc.stdout
    problem = uv_problem(pin, found, version, every)
    if problem is not None or not shadowed:
        return problem
    return uv_shadowed_problem(pin, found, every)
