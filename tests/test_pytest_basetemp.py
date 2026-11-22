"""The pytest temporary root is per run and lives under the checkout's cache."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

import pytest_helpers

pytestmark = pytest.mark.windows


def _config(*, basetemp: str | None, worker: bool = False) -> pytest.Config:
    """A stand-in for the config pytest hands the configure hook."""
    config = SimpleNamespace(option=SimpleNamespace(basetemp=basetemp))
    if worker:
        config = SimpleNamespace(**vars(config), workerinput={})
    return cast("pytest.Config", config)


def _link(link: Path, target: Path) -> None:
    """Point *link* at *target*, with a junction on Windows and a symlink elsewhere."""
    if os.name == "nt":
        # A junction needs neither elevation nor Developer Mode, unlike a symlink.
        made = subprocess.run(  # noqa: S603 - fixed cmd arguments
            [os.environ.get("COMSPEC", "cmd.exe"), "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if made.returncode == 0:
            return
        pytest.skip(f"cannot make a junction here: {made.stderr or made.stdout}")
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as err:
        pytest.skip(f"cannot make a symlink here: {err}")


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
    pytest_helpers.prune_old_basetemps(tmp_path, keep=2, fresh_for=timedelta(0))
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "basetemp-20261025T200003-aaaa",
        "basetemp-20261025T200004-aaaa",
    ]


def test_prune_keeps_a_run_modified_within_the_fresh_window(tmp_path: Path) -> None:
    """A recent basetemp may belong to a run still going, so the age guard spares it."""
    now = datetime(2026, 10, 25, 20, 10, tzinfo=UTC)
    stale = now - pytest_helpers.BASETEMP_FRESH_FOR - timedelta(minutes=1)
    fresh = now - timedelta(minutes=1)
    for index in range(4):
        path = tmp_path / f"{pytest_helpers.BASETEMP_PREFIX}20261025T20000{index}-aaaa"
        path.mkdir()
        modified = fresh if index == 2 else stale
        os.utime(path, (modified.timestamp(), modified.timestamp()))
    pytest_helpers.prune_old_basetemps(tmp_path, keep=1, now=now)
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "basetemp-20261025T200002-aaaa",
        "basetemp-20261025T200003-aaaa",
    ]


def test_prune_removes_a_run_that_holds_read_only_files(tmp_path: Path) -> None:
    """git writes its objects read-only; a prune that skips them leaks every old run."""
    for index in range(3):
        objects = tmp_path / f"{pytest_helpers.BASETEMP_PREFIX}20261025T20000{index}-aaaa" / "o"
        objects.mkdir(parents=True)
        (objects / "blob").write_bytes(b"x")
        (objects / "blob").chmod(stat.S_IREAD)
        objects.chmod(stat.S_IREAD | stat.S_IEXEC)
    pytest_helpers.prune_old_basetemps(tmp_path, keep=1, fresh_for=timedelta(0))
    assert [path.name for path in tmp_path.iterdir()] == ["basetemp-20261025T200002-aaaa"]


def test_short_basetemp_is_outside_the_checkout() -> None:
    """An inner run's root must not lengthen nested paths under a long checkout (#925)."""
    repo = Path(__file__).resolve().parents[1]
    basetemp = pytest_helpers.short_basetemp()
    assert repo not in basetemp.parents
    # pytest resolves a given --basetemp and git prints real paths, so the comparison
    # only works on a resolved parent; a %TEMP% behind a link would break it.
    assert basetemp.parent == basetemp.parent.resolve()
    assert not basetemp.exists()


def test_short_basetemp_resolves_a_linked_temp_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A %TEMP% behind a junction or symlink must still name the path git prints (#925).

    pytest resolves the --basetemp it is given, so the inner run's tmp_path and its fixture
    worktrees are named by the real path; an unresolved root could never contain them, and
    the worktree test's isolation assertion could not fail.
    """
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    _link(link, real)
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(link))
    basetemp = pytest_helpers.short_basetemp()
    assert basetemp.parent == real.resolve()
    assert not basetemp.exists()


def test_remove_basetemp_removes_read_only_files() -> None:
    """git writes its objects read-only; the inner run must leave no temporary directory."""
    basetemp = pytest_helpers.short_basetemp()
    basetemp.mkdir()
    blob = basetemp / "blob"
    blob.write_bytes(b"x")
    blob.chmod(stat.S_IREAD)
    pytest_helpers.remove_basetemp(basetemp)
    assert not basetemp.exists()


def test_only_the_controller_prunes() -> None:
    """Each xdist worker configuring itself would otherwise walk every old run again."""
    assert pytest_helpers.prunes_basetemps(_config(basetemp=None)) is True
    assert pytest_helpers.prunes_basetemps(_config(basetemp=None, worker=True)) is False


def test_an_explicit_basetemp_prunes_nothing() -> None:
    """That directory may belong to a concurrent run, so it is not ours to prune."""
    assert pytest_helpers.prunes_basetemps(_config(basetemp="C:/given/basetemp")) is False


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sandbox workaround")
def test_mkdir_shim_keeps_a_0o700_directory_usable(tmp_path: Path) -> None:
    pytest_helpers.install_windows_mkdir_shim()
    child = tmp_path / "mode-700"
    os.mkdir(child, 0o700)  # noqa: PTH102 - exercising the os.mkdir shim
    assert list(child.iterdir()) == []
