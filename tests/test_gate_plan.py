"""The gate's lane map stays in step with its one step list (ADR 0016).

The gate is one plan of leaf tasks (ADR 0014) that runs as concurrent lanes (ADR 0016). These
checks hold the two together: a step added to `STEPS` without a lane must fail here, before the
gate refuses to start at run time, and a lane must never reorder or drop a step of its plan.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
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
