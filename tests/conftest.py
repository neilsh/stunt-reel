"""Shared pytest configuration: registers the TAC mock fixtures as a plugin.

The temporary root is per run and lives in the checkout's pytest cache directory.
pytest deletes a --basetemp it finds on disk and resets a cache directory it
creates, and a sandboxed run may do neither; naming the root after the run means
there is nothing stale to delete, and creating the cache directory first means
pytest never resets it.  On Windows the mkdir mode shim keeps pytest's own
0o700 temporary directories usable under the sandbox.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

import file_holders
from pytest_helpers import (
    cache_dir,
    install_windows_mkdir_shim,
    per_run_basetemp,
    prune_old_basetemps,
    prunes_basetemps,
)
from stunt_reel import dataroot, parity_layout, references
from stunt_reel.git_env import COMMAND_SCOPE, git_location_vars

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator

pytest_plugins = ["tac_mock"]


@pytest.fixture(autouse=True)
def _no_caller_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset git's repository variables, so git in a test acts only on the test's own repository.

    A suite run under a git hook or ``git rebase --exec`` inherits them, and a test's
    ``git config`` would otherwise write the caller's ``.git/config``.  ``git_location_vars``
    names them, and keeps the core four when git cannot be run (issue #868).
    """
    for name in git_location_vars() | COMMAND_SCOPE:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="session", autouse=True)
def _git_core_longpaths(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Give git in every child of the session ``core.longpaths`` on Windows.

    ``GIT_CONFIG_GLOBAL`` points at a basetemp file that includes the global config files git
    would otherwise read and adds ``core.longpaths = true``, so the setting joins them instead
    of replacing them.
    """
    # ``GIT_CONFIG_COUNT`` is not enough: a local fetch's ``upload-pack`` child drops the
    # command-scope variables (``connect.c``'s ``local_repo_env``), so it cannot read its long
    # objects.
    # The work sits in the platform branch, never after an early return, so mypy analysing for
    # either platform finds no unreachable statement.
    if sys.platform == "win32":
        inherited = os.environ.get("GIT_CONFIG_GLOBAL")
        if inherited:
            caller_configs = [Path(inherited).resolve()]
        else:
            # git finds ``~`` through HOME, which on Windows may not be Path.home()'s USERPROFILE.
            home = Path(os.environ.get("HOME") or os.environ.get("USERPROFILE") or Path.home())
            xdg = os.environ.get("XDG_CONFIG_HOME")
            # Git reads the XDG file first and ``~/.gitconfig`` second, so later includes win.
            caller_configs = [
                Path(xdg) / "git" / "config" if xdg else home / ".config" / "git" / "config",
                home / ".gitconfig",
            ]
        included = [
            f'[include]\n\tpath = "{path.as_posix()}"' for path in caller_configs if path.is_file()
        ]
        config = tmp_path_factory.getbasetemp() / "gitconfig"
        config.write_text(
            "\n".join([*included, "[core]", "\tlongpaths = true"]) + "\n", encoding="utf-8"
        )
        os.environ["GIT_CONFIG_GLOBAL"] = config.as_posix()


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
    cache = cache_dir(rootpath)
    if prunes_basetemps(config):
        prune_old_basetemps(cache)
    if config.option.basetemp is None:
        config.option.basetemp = str(per_run_basetemp(rootpath))


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    call: pytest.CallInfo[None],
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """Add the processes holding the file to a report that failed on a ``PermissionError``."""
    report: pytest.TestReport = yield
    if report.failed and call.excinfo is not None:
        try:
            held = file_holders.describe(call.excinfo.value)
        except OSError as error:
            held = f"could not ask the Restart Manager: {error}"
        if held:
            report.sections.append(("file holders", held))
    return report


@pytest.fixture
def rows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty ``references.toml`` in a stand-in checkout, which ``references`` reads instead.

    A test writes the rows it needs into the returned file, so a change to the committed rows
    breaks only the ``test_committed_*`` tests that check them.
    """
    checkout = tmp_path / "references-checkout"
    pointers = checkout / parity_layout.REFERENCES_FILE
    pointers.parent.mkdir(parents=True)
    pointers.write_text("", encoding="utf-8")
    monkeypatch.setattr(references, "REPO_ROOT", checkout)
    return pointers


@pytest.fixture
def bench_fixture() -> Path:
    """The synthetic parity-bench fixture: capture, render, render_before and golden."""
    return Path(__file__).resolve().parent / "fixtures" / "parity" / "bench"
