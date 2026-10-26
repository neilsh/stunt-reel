"""Per-run pytest temporary roots, shaped for DSH's Windows sandbox.

pytest deletes a --basetemp directory it finds on disk and resets the permissions
of a cache directory it creates.  A sandboxed run may do neither, so the checkout
keeps a cache directory it creates itself and names the temporary root after the
run: there is nothing stale to delete, and pytest never resets a directory the
sandbox already provisioned.
"""

from __future__ import annotations

import os
import secrets
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

CACHE_DIRNAME = ".pytest_cache"
BASETEMP_PREFIX = "basetemp-"
KEEP_BASETEMPS = 3

_SHIM_INSTALLED = False


def install_windows_mkdir_shim() -> None:
    """Ignore the POSIX mode on Windows, once per process.

    A directory created with mkdir(mode=0o700) cannot be listed or removed by the
    process that created it under DSH's Windows sandbox; pytest creates its
    basetemp and numbered temp dirs that way.  Windows ignores the mode anyway, so
    dropping it changes no behaviour outside the sandbox.
    """
    global _SHIM_INSTALLED
    if _SHIM_INSTALLED or sys.platform != "win32":
        return
    real_mkdir = os.mkdir

    def mkdir(
        path: str | os.PathLike[str], mode: int = 0o777, *, dir_fd: int | None = None
    ) -> None:
        del mode  # Windows ignores it; keeping the name keeps keyword callers working
        real_mkdir(path, 0o777, dir_fd=dir_fd)

    os.mkdir = mkdir  # type: ignore[assignment]
    _SHIM_INSTALLED = True


def cache_dir(rootpath: Path) -> Path:
    """Return the checkout's pytest cache directory, creating it without a chmod."""
    cache = rootpath / CACHE_DIRNAME
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def per_run_basetemp(
    rootpath: Path, *, now: datetime | None = None, suffix: str | None = None
) -> Path:
    """Return a fresh basetemp path under rootpath; it must not exist yet."""
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%S")
    suffix = suffix if suffix is not None else secrets.token_hex(2)
    return rootpath / CACHE_DIRNAME / f"{BASETEMP_PREFIX}{stamp}-{suffix}"


def prune_old_basetemps(cache: Path, *, keep: int = KEEP_BASETEMPS) -> None:
    """Remove the older per-run basetemps, best effort; the sandbox may refuse."""
    try:
        runs = sorted(
            path
            for path in cache.iterdir()
            if path.is_dir() and path.name.startswith(BASETEMP_PREFIX)
        )
    except OSError:
        return
    for path in runs[: max(0, len(runs) - keep)]:
        shutil.rmtree(path, ignore_errors=True)
