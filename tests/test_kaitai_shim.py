"""The Kaitai compiler launcher on Windows: a ``.bat`` shim runs through ``COMSPEC``.

The compiler is installed as a batch file there, so the resolver has to look for
``kaitai-struct-compiler.bat`` first and start it through the command interpreter; a native
launcher runs directly.  The catalog tests need the JVM, so they stay out of the pull-request
Windows job; this covers the branch they would leave untested.
"""

from __future__ import annotations

import os
import shutil
lazy from collections.abc import Callable

import pytest

from stunt_reel import kaitai

pytestmark = pytest.mark.windows


def _which(found: dict[str, str], asked: list[str] | None = None) -> Callable[[str], str | None]:
    """A ``shutil.which`` stand-in answering from *found* and recording each name it is asked."""

    def which(name: str) -> str | None:
        if asked is not None:
            asked.append(name)
        return found.get(name)

    return which


def test_a_windows_batch_shim_runs_through_comspec(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setenv("COMSPEC", r"C:\Windows\System32\cmd.exe")
    asked: list[str] = []
    monkeypatch.setattr(
        shutil,
        "which",
        _which({"kaitai-struct-compiler.bat": r"C:\tools\ksc.bat"}, asked),
    )

    assert kaitai.ksc_command() == [r"C:\Windows\System32\cmd.exe", "/c", r"C:\tools\ksc.bat"]
    assert asked[0] == "kaitai-struct-compiler.bat"


def test_a_windows_batch_shim_defaults_to_cmd_exe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.delenv("COMSPEC", raising=False)
    monkeypatch.setattr(
        shutil, "which", _which({"kaitai-struct-compiler.bat": r"C:\tools\ksc.bat"})
    )

    assert kaitai.ksc_command() == ["cmd.exe", "/c", r"C:\tools\ksc.bat"]


def test_a_windows_native_launcher_runs_directly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(shutil, "which", _which({"kaitai-struct-compiler": r"C:\tools\ksc.exe"}))

    assert kaitai.ksc_command() == [r"C:\tools\ksc.exe"]


def test_a_posix_host_never_asks_for_the_batch_shim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "name", "posix")
    asked: list[str] = []
    monkeypatch.setattr(
        shutil,
        "which",
        _which({"kaitai-struct-compiler": "/usr/local/bin/kaitai-struct-compiler"}, asked),
    )

    assert kaitai.ksc_command() == ["/usr/local/bin/kaitai-struct-compiler"]
    assert "kaitai-struct-compiler.bat" not in asked


def test_a_missing_compiler_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr(shutil, "which", _which({}))

    assert kaitai.ksc_command() is None
