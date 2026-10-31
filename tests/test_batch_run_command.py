"""`batch_parity._run_command` ends the whole process tree on a timeout, not just the direct child.

The children here are plain Python processes; nothing launches an emulator.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import batch_parity  # noqa: E402

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
        code, output = batch_parity._run_command([sys.executable, "-c", _CHILD, str(pid_file)], 2.0)
        assert time.monotonic() - started < 8.0
        assert pid_file.exists()
        grandchild = int(pid_file.read_text())
        assert code == batch_parity._TIMEOUT_EXIT
        assert "timeout" in output
        deadline = time.monotonic() + 3.0
        while _alive(grandchild) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not _alive(grandchild)
    finally:
        if grandchild or pid_file.exists():
            _kill(grandchild or int(pid_file.read_text()))
