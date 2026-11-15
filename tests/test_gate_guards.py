"""The gate fails fast on a stale uv and never waits forever on a hung step.

A stale uv earlier on PATH (`~/.local/bin`, from a standalone install) once failed `test-py` with
uv's own "Required uv version" error, after the other steps had run. A hung `test-rust` once held
the gate until the whole task was stopped by hand.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from stunt_reel import uv

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import gate  # noqa: E402

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


def test_the_shared_uv_check_reads_the_pin_and_the_uv_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gate, init and ensure share one check, so a shadowed uv is named the same way."""
    (tmp_path / "mise.toml").write_text('[tools]\nuv = "0.13.1"\n', encoding="utf-8")
    monkeypatch.setattr(shutil, "which", lambda _name, **_kwargs: "/stale/uv")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, "uv 0.10.9 (x)\n", ""),
    )
    problem = uv.check_uv(tmp_path / "mise.toml")
    assert problem is not None
    assert "0.10.9" in problem
    assert "0.13.1" in problem

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0, "uv 0.13.1 (x)\n", ""),
    )
    assert uv.check_uv(tmp_path / "mise.toml") is None


def test_the_shared_uv_check_needs_the_pin(tmp_path: Path) -> None:
    """The gate cannot check the first uv without a pin, so it raises as it did inline."""
    with pytest.raises(FileNotFoundError):
        uv.check_uv(tmp_path / "missing.toml")


def _fake_uv(folder: Path, version: str) -> Path:
    """An executable uv that prints *version* for --version."""
    folder.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        path = folder / "uv.cmd"
        path.write_text(f"@echo uv {version} (fake)\r\n", encoding="ascii")
    else:
        path = folder / "uv"
        path.write_text(f"#!/bin/sh\necho 'uv {version} (fake)'\n", encoding="utf-8")
        path.chmod(0o755)
    return path


def test_a_stale_uv_outside_mise_is_named_when_the_pinned_uv_is_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under mise the pin is first; a stale uv further along PATH still runs outside mise."""
    pinned = _fake_uv(tmp_path / "mise" / "installs" / "uv" / "0.13.1", "0.13.1")
    stale = _fake_uv(tmp_path / "local" / "bin", "0.10.9")
    monkeypatch.setenv("PATH", os.pathsep.join((str(pinned.parent), str(stale.parent))))
    mise = tmp_path / "mise.toml"
    mise.write_text('[tools]\nuv = "0.13.1"\n', encoding="utf-8")

    assert uv.check_uv(mise) is None
    problem = uv.check_uv(mise, shadowed=True)
    assert problem is not None
    assert "0.10.9" in problem
    assert "0.13.1" in problem
    assert str(stale.parent) in problem


def test_a_matching_uv_outside_mise_is_quiet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pinned = _fake_uv(tmp_path / "mise" / "installs" / "uv" / "0.13.1", "0.13.1")
    other = _fake_uv(tmp_path / "local" / "bin", "0.13.1")
    monkeypatch.setenv("PATH", os.pathsep.join((str(pinned.parent), str(other.parent))))
    mise = tmp_path / "mise.toml"
    mise.write_text('[tools]\nuv = "0.13.1"\n', encoding="utf-8")

    assert uv.check_uv(mise, shadowed=True) is None


def test_a_hung_command_times_out_with_a_note() -> None:
    """The tree kill itself is covered in `test_process_tree.py`; the gate adds the note."""
    started = time.monotonic()
    code, output = gate.run_bounded(
        [sys.executable, "-c", "import time; time.sleep(60)"], env=None, timeout=2.0
    )
    assert time.monotonic() - started < 30
    assert code == gate.TIMEOUT_EXIT
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
