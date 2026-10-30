"""Shared pytest configuration: registers the TAC mock fixtures as a plugin.

The temporary root is per run and lives in the checkout's pytest cache directory.
pytest deletes a --basetemp it finds on disk and resets a cache directory it
creates, and a sandboxed run may do neither; naming the root after the run means
there is nothing stale to delete, and creating the cache directory first means
pytest never resets it.  On Windows the mkdir mode shim keeps pytest's own
0o700 temporary directories usable under the sandbox.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from pytest_helpers import (
    cache_dir,
    install_windows_mkdir_shim,
    per_run_basetemp,
    prune_old_basetemps,
)

if TYPE_CHECKING:
    import pytest

pytest_plugins = ["tac_mock"]


def pytest_configure(config: pytest.Config) -> None:
    """Give the run a fresh temporary root inside the checkout's pytest cache."""
    install_windows_mkdir_shim()
    rootpath = Path(config.rootpath)
    prune_old_basetemps(cache_dir(rootpath))
    if config.option.basetemp is None:
        config.option.basetemp = str(per_run_basetemp(rootpath))
