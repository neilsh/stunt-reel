"""Numbered run directories: claim the next free number without a race.

A film's frame captures and archives are ``001``, ``002``, ... (ADR 0024).  Two sessions can
look for the next number at once, so the claim is the ``mkdir`` itself: it fails for the
loser, who looks again.  Entries such as ``003.lock`` or ``003.partial`` hold their number.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from stunt_reel import parity_layout

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["claim_run", "run_numbers"]

_RUN = re.compile(r"(\d+)(?:\..*)?")


def run_numbers(parent: Path) -> list[int]:
    """The run numbers already present in *parent*, ascending; none when it is absent."""
    if not parent.is_dir():
        return []
    found = {int(m.group(1)) for item in parent.iterdir() if (m := _RUN.fullmatch(item.name))}
    return sorted(found)


def claim_run(parent: Path, suffix: str = "") -> str:
    """Create the next free ``<run><suffix>`` directory in *parent* and return the run id.

    ``mkdir`` without ``exist_ok`` is the atomic claim; losing a race retries with the next
    number.  *suffix* (``.lock``) lets a publisher claim a number before its directory exists.
    """
    parent.mkdir(parents=True, exist_ok=True)
    while True:
        numbers = run_numbers(parent)
        run = parity_layout.run_id(numbers[-1] + 1 if numbers else 1)
        try:
            (parent / f"{run}{suffix}").mkdir()
        except FileExistsError:
            continue
        return run
