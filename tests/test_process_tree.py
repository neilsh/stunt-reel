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

#: Outlives the wait for its kill, so a grandchild found gone was killed: no load can make it
#: exit on its own first, as an elapsed-time bound would (issue #571).
_GRANDCHILD = "import time; time.sleep(180)"
#: Starts a grandchild that inherits the output pipe and prints its pid, then sleeps. Its own
#: 30 s sleep bounds the test when the kill is broken.
_CHILD = (
    "import subprocess, sys, time\n"
    f"p = subprocess.Popen([sys.executable, '-c', {_GRANDCHILD!r}])\n"
    "print('grandchild', p.pid, flush=True)\n"
    "time.sleep(30)\n"
)
#: Seconds to wait for a killed process to disappear: a bound on a hang, not a timing claim.
_GONE_WITHIN = 60.0


def _spawned(monkeypatch: pytest.MonkeyPatch) -> list[subprocess.Popen[str]]:
    """Record each process `process_tree.run` spawns, to read its exit code afterwards."""
    procs: list[subprocess.Popen[str]] = []
    real_spawn = process_tree.spawn

    def spawn(*args: Any, **kwargs: Any) -> subprocess.Popen[str]:
        procs.append(real_spawn(*args, **kwargs))
        return procs[-1]

    monkeypatch.setattr(process_tree, "spawn", spawn)
    return procs


#: procfs states in which a process no longer runs: ``Z`` awaits its reaper, ``X``/``x`` is one
#: being reaped (issue #851).
_DEAD_STATES = frozenset({"Z", "X", "x"})


def _alive_in_stat(stat: str) -> bool:
    """Whether the procfs *stat* line says its process still runs.

    The state is the field after the last ``)``: the command name before it may hold spaces
    and parentheses of its own.
    """
    return stat.rsplit(")", 1)[1].split(maxsplit=1)[0] not in _DEAD_STATES


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
        return _alive_in_stat(Path(f"/proc/{pid}/stat").read_text(encoding="utf-8"))
    except OSError:
        # A zombie passes the kill above and its reaper can run before this read, so a missing
        # entry means reaped, not running. Only without procfs (macOS) is the kill all we know.
        return not Path("/proc/self/stat").exists()


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


def _describe(pid: int, since: float) -> str:
    """What procfs says of a surviving *pid*, to tell a stuck exit, a reused pid and an
    undelivered kill apart; *since* is the test's ``time.time()`` at its start.

    The start offset is good to about a second: the kernel's boot time is whole seconds.
    """
    proc = Path(f"/proc/{pid}")
    if not Path("/proc/self/stat").exists():
        return f"pid {pid} (no procfs)"
    lines = [f"pid {pid}"]
    try:
        stat = (proc / "stat").read_text(encoding="utf-8")
        lines.append(f"stat: {stat.strip()}")
        ticks = int(stat.rsplit(")", 1)[1].split()[19])
        boot = next(
            int(line.split()[1])
            for line in Path("/proc/stat").read_text(encoding="utf-8").splitlines()
            if line.startswith("btime ")
        )
        # ``os.sysconf`` exists only off Windows, which this branch never runs on.
        born = boot + ticks / getattr(os, "sysconf", lambda _name: 100)("SC_CLK_TCK")
        lines.append(f"started {born - since:+.2f} s from the test's start")
    except (OSError, ValueError, IndexError, StopIteration) as error:
        lines.append(f"stat: {error!r}")
    keys = ("State:", "PPid:", "SigPnd:", "ShdPnd:", "SigBlk:", "SigIgn:")
    for name in ("status", "cmdline", "wchan"):
        try:
            text = (proc / name).read_bytes().decode("utf-8", "replace")
        except OSError as error:
            lines.append(f"{name}: {error!r}")
            continue
        if name == "status":
            lines.extend(line for line in text.splitlines() if line.startswith(keys))
        else:
            lines.append(f"{name}: {text.replace(chr(0), ' ').strip()}")
    return "\n".join(lines)


@pytest.mark.skipif(not Path("/proc/self/stat").exists(), reason="reads procfs")
def test_a_survivor_is_described_by_its_state_signals_and_start() -> None:
    since = time.time()
    with subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"]) as proc:
        try:
            text = _describe(proc.pid, since)
        finally:
            proc.kill()
    for needle in ("State:", "PPid:", "SigPnd:", "cmdline:", "wchan:", "s from the test's start"):
        assert needle in text, text


def _grandchild(output: str) -> int:
    for line in output.splitlines():
        if line.startswith("grandchild "):
            return int(line.split()[1])
    raise AssertionError(output)


@pytest.mark.skipif(not Path("/proc/self/stat").exists(), reason="reads procfs")
def test_a_zombie_reaped_during_the_check_is_not_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    """The timeout test's grandchild is reaped by whichever process adopts it, at any moment.

    Reaping between ``_alive``'s ``kill(pid, 0)`` and its procfs read once reported the dead
    grandchild alive, failing that test on CI (PRs #387 and #388).
    """
    zombie = subprocess.Popen([sys.executable, "-c", "pass"])
    deadline = time.monotonic() + 20.0
    while _alive(zombie.pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(zombie.pid), "the child never exited"
    real_kill = os.kill

    def kill_then_reap(pid: int, sig: int) -> None:
        real_kill(pid, sig)
        zombie.wait()

    monkeypatch.setattr(os, "kill", kill_then_reap)
    assert not _alive(zombie.pid)


@pytest.mark.parametrize(
    ("state", "alive"),
    [("Z", False), ("X", False), ("x", False), ("R", True), ("S", True)],
)
def test_a_stat_line_state_says_whether_the_process_runs(state: str, alive: bool) -> None:
    """``Z``, ``X`` and ``x`` are all dead, the last two racing the reaper as ``Z`` does (#851).

    The line is synthetic, with spaces and a ``)`` in its command name, so this parse is tested
    off Linux too.
    """
    stat = f"1234 (python ) 3) {state} 1 1234 1234 0 -1 4194304 0 0 0 0 0 0 0 0 20 0 1 0"
    assert _alive_in_stat(stat) is alive


def test_a_finished_command_keeps_its_exit_code_and_output() -> None:
    # Under concurrent gates the child's start alone outlasted 30 s (issue #571); 600 s still
    # fails a hung child rather than hanging the run.
    code, output = process_tree.run(
        [sys.executable, "-c", "import sys; print('out'); sys.exit(3)"], 600.0
    )
    assert code == 3
    assert "out" in output


def test_timeout_kills_the_grandchild_too() -> None:
    """A surviving grandchild holds the pipe, so the read would wait out its sleep.

    The grandchild's pid is read before the timeout starts, so a loaded machine cannot start it
    only after the kill (issue #571).
    """
    grandchild = 0
    since = time.time()
    survivor = ""
    # Checked inside the block: with the kill disabled, the block's exit on Windows did not return
    # until the grandchild's sleep ended, so a check after it passed (issue #571).
    with process_tree.spawn([sys.executable, "-c", _CHILD]) as proc:
        try:
            assert proc.stdout is not None
            grandchild = _grandchild(proc.stdout.readline())
            code, _output = process_tree.wait(proc, 0.5)
            deadline = time.monotonic() + _GONE_WITHIN
            while time.monotonic() < deadline:
                if not _alive(grandchild):
                    break
                time.sleep(0.1)
            else:
                # The ``else`` runs only on timeout, so a second ``_alive()`` call cannot catch
                # ``X`` after the loop saw ``Z`` and describe a process already reaped (issue #851).
                survivor = _describe(grandchild, since)
        finally:
            if grandchild and _alive(grandchild):
                _kill(grandchild)
    assert code == process_tree.TIMEOUT_EXIT
    assert not survivor, f"the grandchild outlived the kill\n{survivor}"


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
    procs = _spawned(monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        process_tree.run([sys.executable, "-c", "import time; time.sleep(30)"], 60)
    assert len(killed) == 1
    # Killed, not slept out: a child left to finish its sleep exits 0. An elapsed-time bound
    # here failed under concurrent gates (issue #571).
    assert procs[0].returncode not in (None, 0)


def test_a_tree_kill_that_does_nothing_still_ends_the_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The direct kill keeps ``Popen``'s exit wait from hanging when the tree kill fails."""
    monkeypatch.setattr(os, "killpg", lambda *_a: None, raising=False)
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: None)
    procs = _spawned(monkeypatch)
    code, _output = process_tree.run([sys.executable, "-c", "import time; time.sleep(30)"], 1)
    assert code == process_tree.TIMEOUT_EXIT
    assert procs[0].returncode not in (None, 0), "the child slept out its 30 s"
