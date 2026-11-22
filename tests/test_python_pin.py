"""The scripts a task runs on bare `python` take the pinned Python, never whichever PATH finds first.

``ensure``, ``init`` and ``seed`` run ``worktree_init.py`` with a bare ``python`` while the package
it imports uses ``lazy from`` (Python 3.15), so a 3.14 first on PATH died with a ``SyntaxError``
before a line of the script ran (issue #854). The gate tasks run ``gate.py`` the same way, so it
takes the same guard before it loads a ``stunt_reel`` module (issue #884).
"""

from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

import gate
import pytest
import python_pin

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "python" / "scripts"

# The fake interpreters are a .cmd on Windows and a shell script elsewhere, so the Windows smoke
# job runs this module too.
pytestmark = pytest.mark.windows


def _fake_executable(
    folder: Path, name: str, *, version: str, status: int = 0, record: Path | None = None
) -> Path:
    """An executable *name* that answers ``--version`` with *version*, else exits *status*.

    With *record*, it appends the arguments of each other run to that file.
    """
    folder.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        path = folder / f"{name}.cmd"
        path.write_text(
            f'@echo off\r\nif "%~1"=="--version" (\r\n  echo {version}\r\n  exit /b 0\r\n)\r\n'
            + (f'echo %* >>"{record}"\r\n' if record is not None else "")
            + f"exit /b {status}\r\n",
            encoding="ascii",
        )
    else:
        path = folder / name
        path.write_text(
            "#!/bin/sh\n"
            'if [ "$1" = "--version" ]; then\n'
            f"  echo '{version}'\n"
            "  exit 0\n"
            "fi\n"
            + (f"printf '%s\\n' \"$*\" >> '{record}'\n" if record is not None else "")
            + f"exit {status}\n",
            encoding="utf-8",
        )
        path.chmod(0o755)
    return path


def _fake_mise(folder: Path, python: Path, *, status: int = 0) -> Path:
    """An executable mise whose ``which python`` prints *python*."""
    folder.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        path = folder / "mise.cmd"
        path.write_text(f"@echo {python}\r\n@exit /b {status}\r\n", encoding="ascii")
    else:
        path = folder / "mise"
        path.write_text(f"#!/bin/sh\necho '{python}'\nexit {status}\n", encoding="utf-8")
        path.chmod(0o755)
    return path


def test_the_floor_comes_from_requires_python(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nrequires-python = ">=3.15"\n', encoding="utf-8")
    assert python_pin.required_python(pyproject) == (3, 15, 0)


def test_a_pyproject_without_a_floor_names_none(tmp_path: Path) -> None:
    """A checkout whose floor cannot be read is left to the import's own error."""
    assert python_pin.required_python(tmp_path / "pyproject.toml") is None
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname = 'x'\n", encoding="utf-8")
    assert python_pin.required_python(pyproject) is None
    pyproject.write_text("not toml", encoding="utf-8")
    assert python_pin.required_python(pyproject) is None


def test_the_pin_comes_from_mise_toml(tmp_path: Path) -> None:
    mise = tmp_path / "mise.toml"
    mise.write_text('[tools]\npython = "3.15.2"\n', encoding="utf-8")
    assert python_pin.pinned_version(mise) == "3.15.2"
    assert python_pin.pinned_version(tmp_path / "missing.toml") is None


def test_mise_names_the_pinned_interpreter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The lookup is ``mise which python``, run in the checkout so it reads that config."""
    pinned = _fake_executable(tmp_path / "installs", "python", version="Python 3.15.2")
    mise = _fake_mise(tmp_path / "bin", pinned)
    monkeypatch.setenv("PATH", str(mise.parent))
    assert python_pin.mise_python(tmp_path) == pinned


def test_a_mise_that_fails_names_no_interpreter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pinned = _fake_executable(tmp_path / "installs", "python", version="Python 3.15.2")
    mise = _fake_mise(tmp_path / "bin", pinned, status=1)
    monkeypatch.setenv("PATH", str(mise.parent))
    assert python_pin.mise_python(tmp_path) is None
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert python_pin.mise_python(tmp_path) is None


def test_an_interpreters_version_is_read_from_version_output(tmp_path: Path) -> None:
    pinned = _fake_executable(tmp_path, "python", version="Python 3.15.2")
    assert python_pin.interpreter_version(pinned) == (3, 15, 2)
    assert python_pin.interpreter_version(tmp_path / "absent") is None


def test_an_old_interpreter_runs_the_script_on_the_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 3.14 python hands the script to mise's 3.15 and returns that run's status."""
    pinned = _fake_executable(tmp_path / "installs", "python", version="Python 3.15.2", status=7)
    mise = _fake_mise(tmp_path / "bin", pinned)
    monkeypatch.setenv("PATH", str(mise.parent))
    monkeypatch.setattr(sys, "version_info", (3, 14, 7))
    assert python_pin.guard(tmp_path / "worktree_init.py", ["ensure"]) == 7


def test_a_pinned_interpreter_that_is_old_too_is_named_not_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """mise can name an interpreter older than the floor; running it would only fail again."""
    old = _fake_executable(tmp_path / "installs", "python", version="Python 3.14.5", status=9)
    mise = _fake_mise(tmp_path / "bin", old)
    monkeypatch.setenv("PATH", str(mise.parent))
    monkeypatch.setattr(sys, "version_info", (3, 14, 7))
    monkeypatch.setattr(sys, "executable", str(old))
    assert python_pin.guard(tmp_path / "worktree_init.py", ["init"]) == 1
    error = capsys.readouterr().err
    assert "Python 3.14.5" in error
    assert str(old) in error


def test_an_old_interpreter_with_no_pin_reports_both_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The message names the version needed and the interpreter PATH gave, never a traceback."""
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(sys, "version_info", (3, 14, 7))
    found = tmp_path / "Python314" / "python.exe"
    monkeypatch.setattr(sys, "executable", str(found))
    assert python_pin.guard(tmp_path / "worktree_init.py", ["init"]) == 1
    error = capsys.readouterr().err
    assert "cannot run worktree_init.py" in error, "the message must name the script it guards"
    assert "needs Python 3.15 or newer" in error
    assert "3.15.2" in error, "the message must name the version mise.toml pins"
    assert str(found) in error
    assert "SyntaxError" not in error


def test_ensure_ends_quietly_without_a_pinned_interpreter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """ensure only makes a first build faster; it must not stop the cargo task (ADR 0036)."""
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(sys, "version_info", (3, 14, 7))
    assert python_pin.guard(tmp_path / "worktree_init.py", ["ensure"]) == 0
    assert "3.15" in capsys.readouterr().err


def test_a_new_enough_interpreter_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    looked_up: list[str] = []
    monkeypatch.setattr(python_pin, "mise_python", lambda: looked_up.append("mise which"))
    assert python_pin.guard(Path("worktree_init.py"), ["ensure"]) is None
    assert looked_up == []


def test_the_guarded_scripts_parse_before_python_315() -> None:
    """Nothing a guarded entry point imports may use syntax an older interpreter cannot parse.

    ``lazy from`` is the 3.15 import that raised the SyntaxError, and ruff format writes Python
    3.14's unparenthesized ``except A, B:`` at py315: the guard exists for older interpreters, so
    it cannot report from a file they cannot read. ``gate.py`` runs on bare ``python`` too, so it
    must parse before ``python_pin.guard`` can hand it on (issue #884).
    """
    for name in ("gate.py", "python_pin.py", "worktree_init.py"):
        source = (SCRIPTS / name).read_text(encoding="utf-8")
        assert re.search(r"^\s*lazy\s+from\b", source, re.MULTILINE) is None, f"{name}: lazy from"
        assert re.search(r"^\s*except\s+[\w.]+\s*,", source, re.MULTILINE) is None, (
            f"{name}: an unparenthesized except names need Python 3.14"
        )


def test_the_entry_point_imports_the_package_after_the_guard() -> None:
    """A ``python`` too old to parse the package must reach the guard before importing it."""
    tree = ast.parse((SCRIPTS / "worktree_init.py").read_text(encoding="utf-8"))
    imported = {
        alias.name.split(".")[0]
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0] for node in tree.body if isinstance(node, ast.ImportFrom)
    }
    assert "stunt_reel" not in imported, "the package is imported before the guard runs"


def _calls(tree: ast.Module, name: str) -> list[int]:
    """The line number of each call to *name*, in source order."""
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name
    ]


def test_the_gate_runs_the_guard_before_loading_the_package() -> None:
    """``gate.py`` loads no ``stunt_reel`` module until the guard may have handed it on (#884)."""
    tree = ast.parse((SCRIPTS / "gate.py").read_text(encoding="utf-8"))
    guard, loads = _calls(tree, "_guard"), _calls(tree, "_load_stunt_reel")
    assert guard, "the gate never calls the guard"
    assert loads, "the gate loads no stunt_reel module"
    assert min(guard) < min(loads), "a stunt_reel module is loaded before the guard can report"


def test_an_old_interpreter_runs_the_gate_on_the_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 3.14 ``python`` hands the gate's arguments to mise's 3.15 and returns its status (#884)."""
    calls = tmp_path / "calls.log"
    pinned = _fake_executable(
        tmp_path / "installs", "python", version="Python 3.15.2", status=7, record=calls
    )
    mise = _fake_mise(tmp_path / "bin", pinned)
    monkeypatch.setenv("PATH", str(mise.parent))
    monkeypatch.setattr(sys, "version_info", (3, 14, 7))
    monkeypatch.setattr(sys, "argv", ["gate.py", "scope"])
    assert gate._guard() == 7
    forwarded = calls.read_bytes().split()
    assert forwarded[0].endswith(b"gate.py")
    assert forwarded[1:] == [b"scope"]


def test_a_too_old_interpreter_with_no_pin_names_the_gates_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The gate exits 1 naming the interpreter and version it needs, never a SyntaxError."""
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(sys, "version_info", (3, 14, 7))
    monkeypatch.setattr(sys, "argv", ["gate.py", "scope"])
    found = tmp_path / "Python314" / "python.exe"
    monkeypatch.setattr(sys, "executable", str(found))
    assert gate._guard() == 1
    error = capsys.readouterr().err
    assert "cannot run gate.py" in error, "the message must name the script it guards"
    assert "needs Python 3.15 or newer" in error
    assert "3.15.2" in error, "the message must name the version mise.toml pins"
    assert str(found) in error
    assert "SyntaxError" not in error
