"""`project_sync` derives Status and Priority from labels and writes only what changed."""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import project_sync as ps  # noqa: E402

REPO = "o/r"
PROJECT = ps.Project(
    "P",
    "SF",
    {name: f"opt-{name}" for name in (ps.DONE, ps.GOAL, *(s for _, s in ps.LABEL_STATUS))},
    "PF",
    {name: f"pri-{name}" for _, name in ps.LABEL_PRIORITY},
)


@pytest.mark.parametrize(
    ("names", "state", "subs", "status"),
    [
        ({"status:ready-for-agent", "env:local-only"}, "open", 0, "Ready for agent"),
        ({"status:needs-plan"}, "open", 0, "Needs plan"),
        ({"status:plan-review"}, "open", 0, "Plan review"),
        ({"status:ready-for-agent", "status:in-progress"}, "open", 0, "In progress"),
        ({"status:ready-for-human"}, "open", 0, "Ready for human"),
        ({"status:needs-info"}, "open", 0, "Needs info"),
        ({"type:research"}, "open", 0, "Needs triage"),
        (set(), "open", 0, "Needs triage"),
        ({"status:ready-for-agent"}, "open", 3, "Goal"),
        ({"status:in-progress"}, "closed", 0, "Done"),
        (set(), "closed", 4, "Done"),
    ],
)
def test_status_follows_state_then_parenthood_then_labels(
    names: set[str], state: str, subs: int, status: str
) -> None:
    assert ps.derive_status(names, state, subs) == status


@pytest.mark.parametrize(
    ("names", "priority"),
    [
        (set(), None),
        ({"status:ready-for-agent"}, None),
        ({"priority:p0"}, "P0"),
        ({"priority:p1"}, "P1"),
        ({"priority:p2"}, "P2"),
        ({"priority:p3"}, "P3"),
        ({"priority:p3", "priority:p1"}, "P1"),
    ],
)
def test_derive_priority_picks_highest_precedence_or_none(
    names: set[str], priority: str | None
) -> None:
    assert ps.derive_priority(names) == priority


def _issue(number: int, *labels: str, state: str = "open", subs: int = 0) -> dict[str, Any]:
    return {
        "number": number,
        "node_id": f"I{number}",
        "state": state,
        "labels": [{"name": name} for name in labels],
        "sub_issues_summary": {"total": subs, "completed": 0},
    }


def _fake(
    monkeypatch: pytest.MonkeyPatch,
    issue: dict[str, Any],
    status: str,
    archived: bool,
    priority: str | None = None,
) -> list[str]:
    """Answer the REST read and the add mutation; record each mutation by its name."""
    writes: list[str] = []

    def gh(*args: str) -> Any:
        if args[1] != "graphql":
            return issue
        query = args[3].removeprefix("query=")
        if "addProjectV2ItemById" in query:
            return {
                "data": {
                    "addProjectV2ItemById": {
                        "item": {
                            "id": "IT",
                            "isArchived": archived,
                            "status": {"name": status},
                            "priority": {"name": priority} if priority is not None else None,
                        }
                    }
                }
            }
        names = {ps._SET: "set", ps._CLEAR: "clear", ps._UNARCHIVE: "unarchive"}
        field = next((a.removeprefix("field=") for a in args if a.startswith("field=")), None)
        option = next((a.removeprefix("option=") for a in args if a.startswith("option=")), None)
        parts = [names[query]]
        if field:
            parts.append(field)
        if option:
            parts.append(option)
        writes.append(" ".join(parts))
        return {"data": {}}

    monkeypatch.setattr(ps, "gh_json", gh)
    return writes


def test_an_item_already_right_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    writes = _fake(
        monkeypatch,
        _issue(7, "status:ready-for-agent", "priority:p1"),
        "Ready for agent",
        archived=False,
        priority="P1",
    )
    assert ps.sync_issue(PROJECT, REPO, 7) is None
    assert writes == []


def test_a_claim_moves_the_item_to_in_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    writes = _fake(monkeypatch, _issue(7, "status:in-progress"), "Ready for agent", archived=False)
    assert ps.sync_issue(PROJECT, REPO, 7) == "#7: Ready for agent -> In progress"
    assert writes == ["set SF opt-In progress"]


def test_a_reopened_issue_comes_back_from_the_archive(monkeypatch: pytest.MonkeyPatch) -> None:
    writes = _fake(monkeypatch, _issue(7, "status:needs-triage"), "Done", archived=True)
    assert ps.sync_issue(PROJECT, REPO, 7) == "#7: unarchived, Done -> Needs triage"
    assert writes == ["unarchive", "set SF opt-Needs triage"]


def test_a_closed_archived_issue_stays_archived(monkeypatch: pytest.MonkeyPatch) -> None:
    writes = _fake(monkeypatch, _issue(7, state="closed"), "Done", archived=True)
    assert ps.sync_issue(PROJECT, REPO, 7) is None
    assert writes == []


def test_priority_is_set_updated_and_cleared(monkeypatch: pytest.MonkeyPatch) -> None:
    writes_set = _fake(
        monkeypatch,
        _issue(7, "status:needs-plan", "priority:p0"),
        "Needs plan",
        archived=False,
        priority=None,
    )
    assert ps.sync_issue(PROJECT, REPO, 7) == "#7: Priority: (none) -> P0"
    assert writes_set == ["set PF pri-P0"]

    writes_update = _fake(
        monkeypatch,
        _issue(7, "status:needs-plan", "priority:p1"),
        "Needs triage",
        archived=False,
        priority="P2",
    )
    assert ps.sync_issue(PROJECT, REPO, 7) == "#7: Needs triage -> Needs plan, Priority: P2 -> P1"
    assert writes_update == ["set SF opt-Needs plan", "set PF pri-P1"]

    writes_clear = _fake(
        monkeypatch,
        _issue(7, "status:plan-review"),
        "Plan review",
        archived=False,
        priority="P2",
    )
    assert ps.sync_issue(PROJECT, REPO, 7) == "#7: Priority: P2 -> (none)"
    assert writes_clear == ["clear PF"]


def test_a_status_or_priority_missing_from_the_project_fails_before_any_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node_missing_status = {
        "id": "P",
        "status": {"id": "SF", "options": [{"id": "1", "name": "Todo"}]},
        "priority": {"id": "PF", "options": [{"id": "2", "name": "P0"}]},
    }
    monkeypatch.setattr(
        ps, "gh_json", lambda *_a: {"data": {"user": {"projectV2": node_missing_status}}}
    )
    with pytest.raises(ps.GhError, match="Goal"):
        ps.load_project("o", 1)

    valid_status = {
        "id": "SF",
        "options": [
            {"id": f"opt-{name}", "name": name}
            for name in (ps.DONE, ps.GOAL, *(s for _, s in ps.LABEL_STATUS))
        ],
    }
    node_missing_priority = {"id": "P", "status": valid_status, "priority": None}
    monkeypatch.setattr(
        ps, "gh_json", lambda *_a: {"data": {"user": {"projectV2": node_missing_priority}}}
    )
    with pytest.raises(ps.GhError, match="Priority"):
        ps.load_project("o", 1)

    node_missing_priority_option = {
        "id": "P",
        "status": valid_status,
        "priority": {"id": "PF", "options": [{"id": "1", "name": "P0"}]},
    }
    monkeypatch.setattr(
        ps, "gh_json", lambda *_a: {"data": {"user": {"projectV2": node_missing_priority_option}}}
    )
    with pytest.raises(ps.GhError, match="P3"):
        ps.load_project("o", 1)


def test_bare_runner_scripts_parse_as_python_3_12() -> None:
    for name in ("labels.py", "project_sync.py"):
        path = SCRIPTS_DIR / name
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 12))
