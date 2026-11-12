"""The pytest temporary root is per run and lives under the checkout's cache."""

from __future__ import annotations

import os
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

import pytest_helpers

pytestmark = pytest.mark.windows


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
    # An xdist worker (the gate runs pytest with -n auto) is handed a directory of its own
    # inside the run's root, named after the worker.
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if worker is not None:
        assert path.name == f"popen-{worker}"
        path = path.parent
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


def test_prune_removes_a_run_that_holds_read_only_files(tmp_path: Path) -> None:
    """git writes its objects read-only; a prune that skips them leaks every old run."""
    for index in range(3):
        objects = tmp_path / f"{pytest_helpers.BASETEMP_PREFIX}20261025T20000{index}-aaaa" / "o"
        objects.mkdir(parents=True)
        (objects / "blob").write_bytes(b"x")
        (objects / "blob").chmod(stat.S_IREAD)
        objects.chmod(stat.S_IREAD | stat.S_IEXEC)
    pytest_helpers.prune_old_basetemps(tmp_path, keep=1)
    assert [path.name for path in tmp_path.iterdir()] == ["basetemp-20261025T200002-aaaa"]


def test_only_the_controller_prunes(pytestconfig: pytest.Config) -> None:
    """Each xdist worker configuring itself would otherwise walk every old run again."""
    worker = os.environ.get("PYTEST_XDIST_WORKER") is not None
    assert pytest_helpers.prunes_basetemps(pytestconfig) is not worker


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sandbox workaround")
def test_mkdir_shim_keeps_a_0o700_directory_usable(tmp_path: Path) -> None:
    pytest_helpers.install_windows_mkdir_shim()
    child = tmp_path / "mode-700"
    os.mkdir(child, 0o700)  # noqa: PTH102 - exercising the os.mkdir shim
    assert list(child.iterdir()) == []
