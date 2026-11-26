"""Run GitHub CLI commands and decode their JSON output."""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

GH_TIMEOUT = 60


class GhError(RuntimeError):
    """``gh`` failed, stalled or returned something other than JSON."""


def gh_json(*args: str) -> Any:
    """``gh <args>``'s stdout parsed as JSON; raises :class:`GhError`."""
    exe = shutil.which("gh")
    if exe is None:
        raise GhError("gh not found on PATH")
    try:
        done = subprocess.run(  # noqa: S603 - gh with fixed arguments
            [exe, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=GH_TIMEOUT,
        )
    except subprocess.TimeoutExpired as err:
        raise GhError(f"gh {args[0]} stalled for {GH_TIMEOUT} s") from err
    if done.returncode != 0:
        raise GhError(done.stderr.strip() or f"gh {args[0]} exited {done.returncode}")
    try:
        return json.loads(done.stdout)
    except json.JSONDecodeError as err:
        raise GhError(f"gh {args[0]} returned no JSON: {err}") from err
