"""`stunt_reel.process_tree` ends the whole process tree on a timeout, not just the direct child.

The one real-process suite for the shared runner behind the gate, the parity pipeline and the
render watcher. The children are plain Python processes; nothing launches an emulator.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from stunt_reel import process_tree

pytestmark = pytest.mark.windows

_GRANDCHILD = "import time; time.sleep(30)"
#: Starts a grandchild that inherits the output pipe and prints its pid, then sleeps.
_CHILD = (
    "import subprocess, sys, time\n"
    f"p = subprocess.Popen([sys.executable, '-c', {_GRANDCHILD!r}])\n"
    "print('grandchild', p.pid, flush=True)\n"
    "time.sleep(30)\n"
)


def _alive(pid: int) -> bool:
    """Whether process *pid* still runs; a zombie awaiting its reaper does not."""
    if os.name == "nt":
        command = ["tasklist", "/FI", f"PID eq {pid}", "/NH"]
        out = subprocess.run(command, capture_output=True, text=True, check=False).stdout  # noqa: S603
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        return ") Z " not in Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return True


def _diag(pid: int, child: int, kill_at: float) -> str:  # DIAGNOSTIC, temporary
    import platform  # noqa: PLC0415

    lines = [f"child={child} now={time.monotonic():.3f} kill_at~{kill_at:.3f}"]
    lines.append(f"uptime={Path('/proc/uptime').read_text()} clk={os.sysconf('SC_CLK_TCK')}")
    lines.append(
        f"pid_max={Path('/proc/sys/kernel/pid_max').read_text().strip()} kernel={platform.release()}"
    )
    lines.append(f"self={os.getpid()} pgid={os.getpgid(0)} sid={os.getsid(0)}")
    for f in ("stat", "status", "cmdline", "wchan", "environ"):
        try:
            data = Path(f"/proc/{pid}/{f}").read_bytes()
            if f == "environ":
                data = b" ".join(
                    x for x in data.split(b"\0") if x.startswith((b"PYTEST", b"RUNNER_TRACKING"))
                )
            lines.append(f"--{f}: {data!r}")
        except OSError as e:
            lines.append(f"--{f}: {e!r}")
    try:
        ppid = int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[1])
        lines.append(f"--parent {ppid}: {Path(f'/proc/{ppid}/cmdline').read_bytes()!r}")
    except (OSError, ValueError, IndexError) as e:
        lines.append(f"--parent: {e!r}")
    return "\n".join(lines)


def _kill(pid: int) -> None:
    """Kill process *pid*, a test's leftover."""
    if os.name == "nt":
        subprocess.run(  # noqa: S603
            ["taskkill", "/T", "/F", "/PID", str(pid)],  # noqa: S607
            capture_output=True,
            check=False,
        )
    else:
        with contextlib.suppress(OSError):
            os.kill(pid, 9)


def _grandchild(output: str) -> int:
    for line in output.splitlines():
        if line.startswith("grandchild "):
            return int(line.split()[1])
    raise AssertionError(output)


def test_a_finished_command_keeps_its_exit_code_and_output() -> None:
    code, output = process_tree.run(
        [sys.executable, "-c", "import sys; print('out'); sys.exit(3)"], 30.0
    )
    assert code == 3
    assert "out" in output


def test_timeout_kills_the_grandchild_too() -> None:
    """A surviving grandchild holds the pipe, so the read would wait out its 30 s sleep."""
    grandchild = 0
    seen: list[str] = []
    try:
        started = time.monotonic()
        with process_tree.spawn([sys.executable, "-c", _CHILD]) as proc:
            code, output = process_tree.wait(proc, 2.0, on_timeout=lambda _p: seen.append("hook"))
        kill_at = time.monotonic()
        assert time.monotonic() - started < 20.0
        assert code == process_tree.TIMEOUT_EXIT
        assert seen == ["hook"]
        grandchild = _grandchild(output)
        deadline = time.monotonic() + 5.0
        while _alive(grandchild) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not _alive(grandchild), (
            f"the grandchild outlived the kill\n{_diag(grandchild, proc.pid, kill_at)}"
        )
    finally:
        if grandchild and _alive(grandchild):
            _kill(grandchild)


def test_an_interrupt_kills_the_tree_and_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    """The child runs in its own process group, so Ctrl+C must be passed on as a tree kill."""
    killed: list[int] = []
    real_kill = process_tree.kill_tree
    real_communicate: Any = subprocess.Popen.communicate
    interrupted: list[bool] = []

    def kill(proc: subprocess.Popen[Any]) -> None:
        killed.append(proc.pid)
        real_kill(proc)

    def communicate(self: Any, *args: Any, **kwargs: Any) -> Any:
        if not interrupted:
            interrupted.append(True)
            raise KeyboardInterrupt
        return real_communicate(self, *args, **kwargs)

    monkeypatch.setattr(process_tree, "kill_tree", kill)
    monkeypatch.setattr(subprocess.Popen, "communicate", communicate)
    started = time.monotonic()
    with pytest.raises(KeyboardInterrupt):
        process_tree.run([sys.executable, "-c", "import time; time.sleep(30)"], 60)
    assert len(killed) == 1
    assert time.monotonic() - started < 20


def test_a_tree_kill_that_does_nothing_still_ends_the_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The direct kill keeps ``Popen``'s exit wait from hanging when the tree kill fails."""
    monkeypatch.setattr(os, "killpg", lambda *_a: None, raising=False)
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: None)
    started = time.monotonic()
    code, _output = process_tree.run([sys.executable, "-c", "import time; time.sleep(30)"], 1)
    assert code == process_tree.TIMEOUT_EXIT
    assert time.monotonic() - started < 20
