"""The uv version ``mise.toml`` pins, and whether the uv on PATH can run the repo's tasks.

A standalone uv earlier on PATH shadows mise's shim, and bare ``uv`` calls then fail with uv's
own "Required uv version" error. The gate, ``init`` and ``ensure`` say so before it happens.
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

__all__ = ["check_uv", "uv_pin", "uv_problem"]


def uv_pin(mise_toml: Path) -> str:
    """The uv version ``mise.toml`` pins under ``[tools]``."""
    with mise_toml.open("rb") as handle:
        return str(tomllib.load(handle)["tools"]["uv"])


def uv_problem(pin: str, found: str | None, version: str, every: Sequence[str]) -> str | None:
    """Why the uv at *found* (``uv --version`` printed *version*) cannot run the repo's tasks.

    *every* is each uv on PATH, in order, so the message names what shadows mise's. ``None``
    means *found* is the pinned uv.
    """
    if found is None:
        return f"uv is not on PATH; mise.toml pins {pin}: run tasks through mise"
    words = version.split()
    if len(words) >= 2 and words[1] == pin:
        return None
    running = words[1] if len(words) >= 2 else repr(version.strip())
    listed = "".join(f"\n  {path}" for path in every) or f"\n  {found}"
    return (
        f"uv {running} at {found} runs, but mise.toml pins {pin}. "
        f"Every uv on PATH, first wins:{listed}\n"
        "Remove the stale one, or run from a shell where mise's comes first."
    )


def _uvs_on_path() -> list[str]:
    """Every uv executable on PATH, in PATH order."""
    found: list[str] = []
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        hit = shutil.which("uv", path=folder) if folder else None
        if hit and hit not in found:
            found.append(hit)
    return found


def check_uv(mise_toml: Path) -> str | None:
    """The ``uv_problem`` for this process's PATH, against *mise_toml*'s pin.

    ``None`` when *mise_toml* names no pin, or when the uv on PATH is the pinned one.
    """
    try:
        pin = uv_pin(mise_toml)
    except OSError, KeyError, ValueError:
        return None
    found = shutil.which("uv")
    version = ""
    if found is not None:
        proc = subprocess.run(  # noqa: S603 - the resolved uv, fixed arguments
            [found, "--version"], capture_output=True, text=True, check=False
        )
        version = proc.stdout
    return uv_problem(pin, found, version, _uvs_on_path())
