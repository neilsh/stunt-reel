"""The gate fails fast on a stale uv and never waits forever on a hung step.

A stale uv earlier on PATH (`~/.local/bin`, from a standalone install) once failed `test-py` with
uv's own "Required uv version" error, after the other steps had run. A hung `test-rust` once held
the gate until the whole task was stopped by hand.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

lazy import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import gate  # noqa: E402
import gate_record  # noqa: E402


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
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
        "print('started', flush=True); time.sleep(60)"
    )
    started = time.monotonic()
    code, output = gate.run_bounded([sys.executable, "-c", script], env=None, timeout=2.0)
    assert time.monotonic() - started < 30
    assert code == gate.TIMEOUT_EXIT
    assert "started" in output
    assert "timed out after 2s" in output


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
