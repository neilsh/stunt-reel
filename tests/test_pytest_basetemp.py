"""The pytest temporary root is per run and lives under the checkout's cache."""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

import pytest_helpers


def test_per_run_basetemp_differs_per_run() -> None:
    root = Path("/checkout")
    now = datetime(2026, 10, 25, 20, 0, 0, tzinfo=UTC)
    first = pytest_helpers.per_run_basetemp(root, now=now, suffix="aaaa")
    second = pytest_helpers.per_run_basetemp(root, now=now, suffix="bbbb")
    assert first != second
    assert first.parent == root / pytest_helpers.CACHE_DIRNAME
    assert first.name.startswith(pytest_helpers.BASETEMP_PREFIX)


def test_session_basetemp_is_per_run_and_under_the_cache(pytestconfig: pytest.Config) -> None:
    given = pytestconfig.option.basetemp
    assert given is not None
    path = Path(given)
    assert path.parent == pytestconfig.rootpath / pytest_helpers.CACHE_DIRNAME
    assert path.parent.is_dir()
    assert path.name.startswith(pytest_helpers.BASETEMP_PREFIX)


def test_prune_keeps_the_newest_runs(tmp_path: Path) -> None:
    for index in range(5):
        (tmp_path / f"{pytest_helpers.BASETEMP_PREFIX}20261025T20000{index}-aaaa").mkdir()
    pytest_helpers.prune_old_basetemps(tmp_path, keep=2)
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "basetemp-20261025T200003-aaaa",
        "basetemp-20261025T200004-aaaa",
    ]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sandbox workaround")
def test_mkdir_shim_keeps_a_0o700_directory_usable(tmp_path: Path) -> None:
    pytest_helpers.install_windows_mkdir_shim()
    child = tmp_path / "mode-700"
    os.mkdir(child, 0o700)
    assert list(child.iterdir()) == []
