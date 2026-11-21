"""Spawn a child with a timeout and end its whole process tree when it runs out.

A plain ``subprocess.run`` timeout kills only the direct child, which leaks whatever the child
started (an emulator, a test binary) and leaves a grandchild holding the output pipe, so the read
never returns. Here the child leads a new process group, a timeout or an interrupt kills the
group, and every wait after the kill is bounded.

Standard library only: ``gate.py`` runs as plain ``python`` (ADR 0014) and loads this file by
path. Do not import from the rest of ``stunt_reel``.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "REAP_SECONDS",
    "TIMEOUT_EXIT",
    "end",
    "kill_tree",
    "process_names",
    "run",
    "spawn",
    "stuntreel_running",
    "wait",
]

#: The exit code reported for a command killed on its timeout, as coreutils ``timeout`` does.
TIMEOUT_EXIT = 124
#: Seconds the tree kill and the reap after it may each take before the caller stops waiting.
REAP_SECONDS = 10.0

_NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
#: The image names of the renderer binary, compared case-blind.
_STUNTREEL = frozenset({"stuntreel", "stuntreel.exe"})


def spawn(
    argv: Sequence[str], *, cwd: Path | None = None, env: Mapping[str, str] | None = None
) -> subprocess.Popen[str]:
    """Start *argv* in a new process group with stdout and stderr merged into one text pipe."""
    windows = sys.platform == "win32"
    return subprocess.Popen(  # noqa: S603 - callers pass fixed argument vectors, no shell
        list(argv),
        cwd=cwd,
        env=None if env is None else dict(env),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=_NEW_GROUP if windows else 0,
        start_new_session=not windows,
    )


def kill_tree(proc: subprocess.Popen[Any]) -> None:
    """Kill *proc* and every process it started, then *proc* itself; never waits unbounded.

    The direct kill covers a tree kill that failed or timed out. A child that already exited
    has nothing left to kill.
    """
    if sys.platform == "win32":
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            subprocess.run(  # noqa: S603 - fixed taskkill invocation with a pid we own
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],  # noqa: S607 - Windows built-in
                capture_output=True,
                check=False,
                timeout=REAP_SECONDS,
            )
    else:
        # The child leads its own session (``spawn``), so its group is its pid.
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)
    with contextlib.suppress(OSError):
        proc.kill()


def end(proc: subprocess.Popen[str], reap: float = REAP_SECONDS) -> str:
    """Kill *proc*'s tree and return what it wrote, giving up on the output after *reap* seconds.

    A descendant the kill missed may still hold the pipe, in which case the output is ``""``.
    """
    kill_tree(proc)
    try:
        output, _ = proc.communicate(timeout=reap)
    except subprocess.TimeoutExpired:
        return ""
    return output or ""


def wait(
    proc: subprocess.Popen[str],
    timeout: float | None,
    *,
    reap: float = REAP_SECONDS,
) -> tuple[int, str]:
    """Wait for *proc*; returns ``(exit code, combined output)``.

    Past *timeout* seconds the tree is killed and the code is :data:`TIMEOUT_EXIT` with whatever
    output the child had written. An interrupt ends the tree too before it propagates: the child's
    own group never sees Ctrl+C.
    """
    try:
        output, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        return TIMEOUT_EXIT, end(proc, reap)
    except BaseException:
        end(proc, reap)
        raise
    return proc.returncode, output or ""


def run(
    argv: Sequence[str],
    timeout: float | None,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[int, str]:
    """Run *argv* to completion or *timeout*; returns ``(exit code, combined output)``."""
    with spawn(argv, cwd=cwd, env=env) as proc:
        return wait(proc, timeout)


def _listing(argv: Sequence[str]) -> list[str]:
    """*argv*'s non-empty stdout lines; empty when it cannot run."""
    try:
        done = subprocess.run(  # noqa: S603 - fixed argument vectors
            list(argv), capture_output=True, text=True, errors="replace", check=False, timeout=30
        )
    except OSError, subprocess.TimeoutExpired:
        return []
    return [line.strip() for line in done.stdout.splitlines() if line.strip()]


def _proc_names(proc: Path) -> list[str]:
    """Each ``/proc/<pid>/comm`` that can still be read."""
    names: list[str] = []
    for comm in proc.glob("[0-9]*/comm"):
        with contextlib.suppress(OSError):
            names.append(comm.read_text(encoding="utf-8").strip())
    return names


def process_names() -> list[str]:
    """The image name of every process this user can see; empty when they cannot be listed."""
    if sys.platform == "win32":
        rows = _listing(["tasklist", "/FO", "CSV", "/NH"])
        names = [row.split(",", 1)[0].strip('"') for row in rows]
    elif Path("/proc").is_dir():
        names = _proc_names(Path("/proc"))
    else:
        names = [Path(row).name for row in _listing(["ps", "-A", "-o", "comm="])]
    return names


def stuntreel_running(names: Sequence[str] | None = None) -> bool:
    """Whether a ``stuntreel`` process runs: among *names*, or else :func:`process_names`."""
    listed = process_names() if names is None else names
    return any(name.lower() in _STUNTREEL for name in listed)
