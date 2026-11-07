"""The gate fails fast on a stale uv and never waits forever on a hung step.

A stale uv earlier on PATH (`~/.local/bin`, from a standalone install) once failed `test-py` with
uv's own "Required uv version" error, after the other steps had run. A hung `test-rust` once held
the gate until the whole task was stopped by hand.
"""

from __future__ import annotations

import contextlib
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import gate  # noqa: E402
import gate_record  # noqa: E402

# The process-tree kill differs by platform, so the Windows job runs this module too.
pytestmark = pytest.mark.windows


def test_the_uv_pin_is_read_from_mise_toml() -> None:
    pin = gate.uv_pin(ROOT / "mise.toml")
    assert pin.count(".") == 2, pin


def test_a_matching_uv_passes() -> None:
    assert gate.uv_problem("0.13.1", "/mise/uv", "uv 0.13.1 (62faed335 2026-10-13)", []) is None


def test_a_stale_uv_is_named_with_every_uv_on_path() -> None:
    problem = gate.uv_problem(
        "0.13.1",
        "/home/u/.local/bin/uv",
        "uv 0.10.9 (f675560f3 2026-03-06)",
        ["/home/u/.local/bin/uv", "/mise/installs/uv/0.13.1/uv"],
    )
    assert problem is not None
    assert "0.10.9" in problem
    assert "0.13.1" in problem
    assert "/home/u/.local/bin/uv" in problem
    assert "/mise/installs/uv/0.13.1/uv" in problem


def test_no_uv_on_path_is_a_problem() -> None:
    problem = gate.uv_problem("0.13.1", None, "", [])
    assert problem is not None
    assert "not on PATH" in problem


def test_a_hung_command_is_killed_with_its_children() -> None:
    # The child spawns a grandchild that inherits the output pipes: killing only the child
    # would leave the pipes open and the read would block, the way the hung test-rust did.
    script = (
        "import subprocess, sys, time;"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
        "print('started', p.pid, flush=True); time.sleep(60)"
    )
    started = time.monotonic()
    code, output = gate.run_bounded([sys.executable, "-c", script], env=None, timeout=2.0)
    assert time.monotonic() - started < 30
    assert code == gate.TIMEOUT_EXIT
    assert "timed out after 2s" in output
    match = re.search(r"started (\d+)", output)
    assert match is not None, output
    grandchild = int(match.group(1))
    try:
        deadline = time.monotonic() + 10
        while _alive(grandchild) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not _alive(grandchild), "the grandchild outlived the kill"
    finally:
        if _alive(grandchild):
            _kill(grandchild)


def _alive(pid: int) -> bool:
    """Whether process *pid* still runs."""
    if sys.platform == "win32":
        listing = subprocess.run(  # noqa: S603 - a pid this test read
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],  # noqa: S607 - tasklist from PATH
            capture_output=True,
            text=True,
            check=False,
        )
        alive = str(pid) in listing.stdout
    else:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        # A killed child of a dead parent may linger as a zombie until init reaps it.
        if not Path("/proc/self").exists():
            return True  # no procfs (macOS): the signal check is the whole answer
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        except FileNotFoundError:
            return False  # it exited after the signal check
        alive = ") Z " not in stat
    return alive


def _kill(pid: int) -> None:
    """Kill process *pid*, a test's leftover."""
    if sys.platform == "win32":
        subprocess.run(  # noqa: S603 - a pid this test read
            ["taskkill", "/F", "/PID", str(pid)],  # noqa: S607 - taskkill from PATH
            capture_output=True,
            check=False,
        )
    else:
        with contextlib.suppress(ProcessLookupError):  # it exited after the liveness check
            os.kill(pid, signal.SIGKILL)


def test_a_finished_command_keeps_its_exit_code_and_output() -> None:
    code, output = gate.run_bounded(
        [sys.executable, "-c", "import sys; print('out'); sys.exit(3)"], env=None, timeout=30.0
    )
    assert code == 3
    assert "out" in output


def test_the_step_timeout_fits_a_cold_ci_build() -> None:
    assert gate.STEP_TIMEOUT_S >= 1200


def test_a_uv_problem_stops_the_gate_before_any_step(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ran: list[str] = []

    def step(_mise: str, task: str, _timeout: float) -> tuple[int, str, float]:
        ran.append(task)
        return 0, "", 0.0

    monkeypatch.setattr(gate, "LOG_PATH", tmp_path / "check.log")
    monkeypatch.setattr(gate, "_mise", lambda: "mise")
    monkeypatch.setattr(gate, "_check_uv", lambda: "uv 0.10.9 at /stale/uv runs")
    monkeypatch.setattr(gate, "_step", step)
    assert gate.main(["py"]) == 1
    assert ran == []
    assert "FAIL before any step: uv 0.10.9 at /stale/uv runs" in capsys.readouterr().out


def test_the_rust_half_needs_no_uv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def no_uv_check() -> str:
        raise AssertionError("the rust half ran the uv check")

    monkeypatch.setattr(gate, "LOG_PATH", tmp_path / "check.log")
    monkeypatch.setattr(gate, "_mise", lambda: "mise")
    monkeypatch.setattr(gate, "_check_uv", no_uv_check)
    # A passing run records the tree it tested; keep this stubbed run off the real record.
    monkeypatch.setattr(gate_record, "working_tree", lambda: "tested-tree")
    monkeypatch.setattr(gate_record, "record", lambda *_pair: None)
    monkeypatch.setattr(gate, "_step", lambda _m, _t, _s: (0, "", 0.0))
    assert gate.main(["rust"]) == 0


def test_cancel_kills_a_running_step(monkeypatch: pytest.MonkeyPatch) -> None:
    # Steps run in their own session on POSIX, where Ctrl-C does not reach them: an interrupted
    # gate must kill them itself rather than wait out the step timeout.
    monkeypatch.setattr(gate, "_CANCEL", threading.Event())
    done: list[tuple[int, str]] = []
    worker = threading.Thread(
        target=lambda: done.append(
            gate.run_bounded([sys.executable, "-c", "import time; time.sleep(60)"], None, 600.0)
        )
    )
    worker.start()
    deadline = time.monotonic() + 10
    while not gate._ACTIVE and time.monotonic() < deadline:
        time.sleep(0.05)
    assert gate._ACTIVE, "the step never registered as running"
    gate.cancel_steps()
    worker.join(timeout=15)
    assert not worker.is_alive()
    assert done
    assert done[0][0] != 0
    assert not gate._ACTIVE


def test_a_cancelled_lane_starts_no_further_step(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ran: list[str] = []

    def step(_mise: str, task: str, _timeout: float) -> tuple[int, str, float]:
        ran.append(task)
        return 0, "", 0.0

    cancel = threading.Event()
    cancel.set()
    monkeypatch.setattr(gate, "_CANCEL", cancel)
    monkeypatch.setattr(gate, "_step", step)
    results: dict[str, tuple[int, str, float]] = {}
    with (tmp_path / "log").open("w", encoding="utf-8") as log:
        gate._run_lane("mise", ["lint-rust", "doc"], log, threading.Lock(), results, 600.0)
    assert ran == []
    assert results == {}


def test_a_step_started_after_a_cancel_is_killed_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A lane can pass its cancel check just before Ctrl-C lands; the step it then starts must
    # not run on to the timeout.
    cancel = threading.Event()
    cancel.set()
    monkeypatch.setattr(gate, "_CANCEL", cancel)
    started = time.monotonic()
    code, _ = gate.run_bounded([sys.executable, "-c", "import time; time.sleep(60)"], None, 600.0)
    assert time.monotonic() - started < 30
    assert code != 0
