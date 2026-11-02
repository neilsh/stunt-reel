"""The gate's lane map stays in step with its one step list (ADR 0016).

The gate is one plan of leaf tasks (ADR 0014) that runs as concurrent lanes (ADR 0016). These
checks hold the two together: a step added to `STEPS` without a lane must fail here, before the
gate refuses to start at run time, and a lane must never reorder or drop a step of its plan.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import gate  # noqa: E402


def test_lane_map_covers_every_step_exactly_once() -> None:
    steps = [*gate.STEPS["rust"], *gate.STEPS["py"]]
    assert len(steps) == len(set(steps)), "a step is listed twice in STEPS"
    assert sorted(gate.STEP_LANES) == sorted(steps), (
        "STEP_LANES must name every step, and only steps"
    )


def test_halves_are_subsets_of_the_whole_plan() -> None:
    assert gate._plan("all") == [*gate.STEPS["rust"], *gate.STEPS["py"]]
    assert gate._plan("rust") == gate.STEPS["rust"]
    assert gate._plan("py") == gate.STEPS["py"]


def test_lanes_keep_plan_order_and_drop_no_step() -> None:
    for half in ("all", "rust", "py"):
        plan = gate._plan(half)
        lanes = gate._lane_plan(plan)
        scheduled = [task for _, tasks in lanes for task in tasks]
        assert sorted(scheduled) == sorted(plan)
        for _, tasks in lanes:
            positions = [plan.index(task) for task in tasks]
            assert positions == sorted(positions), "a lane reordered its steps"


def test_the_gate_has_no_staged_half() -> None:
    """The commit hooks run through prek now (ADR 0026), not a plan of the gate's own."""
    with pytest.raises(SystemExit):
        gate.main(["staged"])


def _verdict(failed: list[str], half: str) -> str:
    return gate._verdict(failed, gate._plan(half), half, 43.0)


def test_a_passing_run_names_no_next_command() -> None:
    line = _verdict([], "all")
    assert line.startswith("[gate] PASS 9/9 steps")
    assert "re-run" not in line
    assert "fix:" not in line


def test_a_rust_failure_names_the_rust_rerun() -> None:
    line = _verdict(["test-rust"], "all")
    assert line.endswith("; re-run: mise run check-rust")
    assert "fix:" not in line


def test_a_python_failure_names_the_python_rerun() -> None:
    line = _verdict(["typecheck"], "all")
    assert line.endswith("; re-run: mise run check-py")


def test_a_mixed_failure_names_both_reruns() -> None:
    line = _verdict(["doc", "test-py"], "all")
    assert "re-run: mise run check-rust, mise run check-py" in line


def test_a_scoped_task_never_suggests_itself() -> None:
    assert "re-run" not in _verdict(["test-rust"], "rust")
    assert "re-run" not in _verdict(["test-py"], "py")


def test_a_step_in_neither_half_names_no_rerun() -> None:
    assert "re-run" not in _verdict(["not-a-step"], "all")


def test_scoped_tasks_are_the_mise_tasks_that_run_each_half() -> None:
    tasks = tomllib.loads((ROOT / "mise.toml").read_text(encoding="utf-8"))["tasks"]
    for half, scoped in gate.SCOPED_TASKS.items():
        assert tasks[scoped]["run"] == f"python python/scripts/gate.py {half}"


def test_fixable_steps_are_gate_steps_and_get_the_fix_hint() -> None:
    assert set(gate.STEP_LANES) >= gate.FIXABLE_STEPS
    for step in gate.FIXABLE_STEPS:
        assert "fix: mise run fix" in _verdict([step], "all")
    for step in set(gate.STEP_LANES) - gate.FIXABLE_STEPS:
        assert "fix:" not in _verdict([step], "all")


def test_fix_task_applies_what_the_fixable_steps_check() -> None:
    tasks = tomllib.loads((ROOT / "mise.toml").read_text(encoding="utf-8"))["tasks"]
    assert tasks[gate.FIX_TASK]["description"]
    commands = " | ".join(
        c if isinstance(c, str) else c.get("task", "") for c in tasks[gate.FIX_TASK]["run"]
    )
    assert "ruff check --fix" in commands
    assert "fmt-py" in commands
    assert "fmt-rust" in commands
