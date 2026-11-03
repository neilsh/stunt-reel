"""`parity_pipeline.run_command` ends the whole process tree on a timeout, not just the direct child.

The children here are plain Python processes; nothing launches an emulator.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import time
from typing import Any
lazy from pathlib import Path

import pytest

from stunt_reel import parity_pipeline

_GRANDCHILD = "import time; time.sleep(30)"
_CHILD = (
    "import subprocess, sys, time\n"
    f"p = subprocess.Popen([sys.executable, '-c', {_GRANDCHILD!r}])\n"
    "open(sys.argv[1], 'w').write(str(p.pid))\n"
    "time.sleep(30)\n"
)


WINDOWS = os.name == "nt"


def _alive(pid: int) -> bool:
    if WINDOWS:
        command = ["tasklist", "/FI", f"PID eq {pid}", "/NH"]
        out = subprocess.run(command, capture_output=True, text=True, check=False).stdout  # noqa: S603
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _kill(pid: int) -> None:
    if WINDOWS:
        command = ["taskkill", "/T", "/F", "/PID", str(pid)]
        subprocess.run(command, capture_output=True, check=False)  # noqa: S603
    else:
        with contextlib.suppress(OSError):
            os.kill(pid, 9)


def test_timeout_kills_the_grandchild_too(tmp_path: Path) -> None:
    pid_file = tmp_path / "grandchild.pid"
    grandchild = 0
    try:
        started = time.monotonic()
        code, output = parity_pipeline.run_command(
            [sys.executable, "-c", _CHILD, str(pid_file)], None, 2.0
        )
        assert time.monotonic() - started < 8.0
        assert pid_file.exists()
        grandchild = int(pid_file.read_text())
        assert code == parity_pipeline.TIMEOUT_EXIT
        assert "timeout" in output
        deadline = time.monotonic() + 3.0
        while _alive(grandchild) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not _alive(grandchild)
    finally:
        if grandchild or pid_file.exists():
            _kill(grandchild or int(pid_file.read_text()))


def test_an_interrupt_kills_the_tree_and_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    """The child runs in its own process group, so Ctrl+C must be passed on as a tree kill."""
    killed: list[int] = []
    real_kill = parity_pipeline._kill_tree
    real_communicate: Any = subprocess.Popen.communicate
    interrupted: list[bool] = []

    def kill(pid: int) -> None:
        killed.append(pid)
        real_kill(pid)

    def communicate(self: Any, *args: Any, **kwargs: Any) -> Any:
        if not interrupted:
            interrupted.append(True)
            raise KeyboardInterrupt
        return real_communicate(self, *args, **kwargs)

    monkeypatch.setattr(parity_pipeline, "_kill_tree", kill)
    monkeypatch.setattr(subprocess.Popen, "communicate", communicate)
    started = time.monotonic()
    with pytest.raises(KeyboardInterrupt):
        parity_pipeline.run_command([sys.executable, "-c", "import time; time.sleep(30)"], None, 60)
    assert len(killed) == 1
    assert time.monotonic() - started < 20


def test_a_failed_tree_kill_still_ends_the_child(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the tree kill does nothing, the direct kill keeps Popen's exit wait from hanging."""
    monkeypatch.setattr(parity_pipeline, "_kill_tree", lambda _pid: None)
    started = time.monotonic()
    code, _tail = parity_pipeline.run_command(
        [sys.executable, "-c", "import time; time.sleep(30)"], None, 1
    )
    assert code == parity_pipeline.TIMEOUT_EXIT
    assert time.monotonic() - started < 20
