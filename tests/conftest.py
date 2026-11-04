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

import pytest

from pytest_helpers import (
    cache_dir,
    install_windows_mkdir_shim,
    per_run_basetemp,
    prune_old_basetemps,
)
from stunt_reel import dataroot

if TYPE_CHECKING:
    from collections.abc import Iterator

pytest_plugins = ["tac_mock"]


@pytest.fixture(autouse=True)
def _no_machine_data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Give every test an empty data root of its own, and undo any a test's ``--data-root`` sets.

    Without it a test that does not name one reads the machine's ``<primary>.data``, and passes
    only while that holds nothing the test did not expect. ``dataroot.use_data_root`` writes the
    variable for the process, so one test's flag would also become the next test's data root.
    """
    monkeypatch.setenv(dataroot.DATA_ENV, str(tmp_path / "no-data-root"))
    dataroot.data_root.cache_clear()
    yield
    dataroot.data_root.cache_clear()


def pytest_configure(config: pytest.Config) -> None:
    """Give the run a fresh temporary root inside the checkout's pytest cache."""
    install_windows_mkdir_shim()
    rootpath = Path(config.rootpath)
    prune_old_basetemps(cache_dir(rootpath))
    if config.option.basetemp is None:
        config.option.basetemp = str(per_run_basetemp(rootpath))


@pytest.fixture
def bench_fixture() -> Path:
    """The synthetic parity-bench fixture: capture, render, render_before and golden."""
    return Path(__file__).resolve().parent / "fixtures" / "parity" / "bench"
