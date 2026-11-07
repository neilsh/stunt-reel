"""Tests for ``skill_eval.outcome``, which reads a headless ``claude -p`` stream-json run."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

lazy import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import skill_eval  # noqa: E402
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


def test_a_tool_result_quoting_the_plan_is_peeking() -> None:
    hit = "docs/process/plans/agents-md-split-2026-11-05.md:190: complete once meta.json exists"
    tool_result = {"type": "tool_result", "tool_use_id": "t1", "content": hit}
    lines = [
        _tool_calls(("Grep", {"pattern": "meta.json"})),
        json.dumps({"type": "user", "message": {"content": [tool_result]}}),
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


def test_a_run_without_a_result_line_prints_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("do the thing", encoding="utf-8")
    monkeypatch.setattr(skill_eval, "REPO_ROOT", tmp_path)
    monkeypatch.setattr("skill_eval.shutil.which", lambda _name: "claude")

    def truncated(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, stdout="", stderr="")

    monkeypatch.setattr("skill_eval.subprocess.run", truncated)
    argv = ["--skill", "x", "--model", "haiku", "--phase", "with", "--reps", "1"]

    assert skill_eval.main([*argv, "--prompt-file", str(prompt)]) == 1
    assert "FAILED" in capsys.readouterr().out


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)  # noqa: S603, S607


def test_uncommitted_skill_files_names_untracked_and_modified(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    (tmp_path / "AGENTS.md").write_text("rules\n", encoding="utf-8")
    (tmp_path / "other.md").write_text("x\n", encoding="utf-8")
    _git(tmp_path, "add", "AGENTS.md", "other.md")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
    assert skill_eval.uncommitted_skill_files(tmp_path) == []

    (tmp_path / "AGENTS.md").write_text("changed\n", encoding="utf-8")
    (tmp_path / ".agents" / "skills" / "new").mkdir(parents=True)
    (tmp_path / ".agents" / "skills" / "new" / "SKILL.md").write_text("x\n", encoding="utf-8")
    (tmp_path / "other.md").write_text("ignored\n", encoding="utf-8")

    assert skill_eval.uncommitted_skill_files(tmp_path) == [
        ".agents/skills/new/SKILL.md",
        "AGENTS.md",
    ]


def test_a_dirty_skill_tree_refuses_before_any_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("do the thing", encoding="utf-8")
    monkeypatch.setattr("skill_eval.shutil.which", lambda _name: "claude")
    monkeypatch.setattr(skill_eval, "uncommitted_skill_files", lambda _root: ["AGENTS.md"])

    def never(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError("claude ran on a dirty tree")

    monkeypatch.setattr("skill_eval.subprocess.run", never)
    argv = ["--skill", "x", "--model", "haiku", "--phase", "with", "--reps", "1"]

    assert skill_eval.main([*argv, "--prompt-file", str(prompt)]) == 1
    out = capsys.readouterr().out
    assert "AGENTS.md" in out
    assert "commit or stash" in out
