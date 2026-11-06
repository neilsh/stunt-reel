"""Tests for ``skill_eval.outcome``, which reads a headless ``claude -p`` stream-json run."""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from skill_eval import RunOutcome, outcome  # noqa: E402


def _result(*, is_error: bool = False, subtype: str = "success") -> str:
    return json.dumps(
        {
            "type": "result",
            "subtype": subtype,
            "is_error": is_error,
            "result": "the plan",
            "total_cost_usd": 0.5,
        }
    )


def _tool_calls(*calls: tuple[str, dict[str, str]]) -> str:
    content = [{"type": "tool_use", "name": name, "input": data} for name, data in calls]
    return json.dumps({"type": "assistant", "message": {"content": content}})


def test_outcome_lists_skill_tool_calls() -> None:
    lines = [
        json.dumps({"type": "system", "subtype": "init", "skills": ["changing-seam-contracts"]}),
        _tool_calls(
            ("Skill", {"skill": "changing-seam-contracts"}),
            ("Read", {"file_path": "x"}),
        ),
        "not json",
        _result(),
    ]

    assert outcome(lines, 0, "changing-seam-contracts") == RunOutcome(
        True, ["changing-seam-contracts"], False, 0.5, "the plan", False
    )


def test_reading_a_skill_file_loads_that_skill() -> None:
    path = "E:\\repo\\.agents\\skills\\improving-render-parity\\SKILL.md"
    lines = [_tool_calls(("Read", {"file_path": path})), _result()]

    assert outcome(lines, 0, "x").skills == ["improving-render-parity"]


def test_reading_the_plan_is_peeking() -> None:
    lines = [
        _tool_calls(("Read", {"file_path": "docs/process/plans/agents-md-split-2026-11-05.md"})),
        _result(),
    ]

    assert outcome(lines, 0, "x").peeked


def test_an_error_result_failed() -> None:
    lines = [_result(is_error=True, subtype="error_max_budget_usd")]

    assert outcome(lines, 0, "x").failed


def test_a_run_without_a_result_line_failed() -> None:
    result = outcome([], 0, "x")

    assert result.failed
    assert result.text is None


def test_a_nonzero_exit_failed() -> None:
    assert outcome([_result()], 1, "x").failed
