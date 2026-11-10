"""The failure report names who holds a file a test's ``PermissionError`` was refused."""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

import conftest
import file_holders

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.windows


def test_each_refused_path_is_named_with_its_holders() -> None:
    error = PermissionError(13, "Permission denied", "a.txt", None, "b.txt")
    held = {"a.txt": ["42 MsMpEng.exe"], "b.txt": []}

    assert file_holders.describe(error, held.__getitem__) == (
        "a.txt: held by 42 MsMpEng.exe\nb.txt: held by no process now (released, or pending delete)"
    )


def _refuse_then_fail() -> None:
    raise AssertionError("setup failed") from PermissionError(13, "Permission denied", "inner.txt")


def test_a_permission_error_behind_another_error_is_found() -> None:
    with pytest.raises(AssertionError) as failed:
        _refuse_then_fail()

    assert (
        file_holders.describe(failed.value, lambda _: ["7 x.exe"]) == "inner.txt: held by 7 x.exe"
    )


def test_an_error_without_a_refused_path_describes_nothing() -> None:
    assert file_holders.describe(ValueError("no file"), lambda _: ["7 x.exe"]) is None
    assert file_holders.describe(PermissionError("no path"), lambda _: ["7 x.exe"]) is None


@pytest.mark.skipif(sys.platform != "win32", reason="the Restart Manager is a Windows API")
def test_the_restart_manager_names_this_process_while_it_holds_the_file(tmp_path: Path) -> None:
    path = tmp_path / "held.txt"
    path.write_text("x", encoding="utf-8")

    assert file_holders.holders(str(path)) == []
    with path.open(encoding="utf-8"):
        assert [entry.split()[0] for entry in file_holders.holders(str(path))] == [str(os.getpid())]


def test_holders_off_windows_is_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert file_holders.holders(str(tmp_path)) == []


def test_a_failed_report_carries_the_holders(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_holders, "holders", lambda _: ["42 MsMpEng.exe"])
    with pytest.raises(PermissionError) as refused:
        raise PermissionError(13, "Permission denied", "held.toml")
    call = cast("pytest.CallInfo[None]", SimpleNamespace(excinfo=refused))
    report = cast("pytest.TestReport", SimpleNamespace(failed=True, sections=[]))

    hook = conftest.pytest_runtest_makereport(call)
    next(hook)
    with pytest.raises(StopIteration) as done:
        hook.send(report)

    assert done.value.value is report
    assert report.sections == [("file holders", "held.toml: held by 42 MsMpEng.exe")]
