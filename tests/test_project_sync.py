"""`project_sync` derives Status from labels and writes only what changed; nothing calls gh."""

from __future__ import annotations

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
    "F",
    {name: f"opt-{name}" for name in (ps.DONE, ps.GOAL, *(s for _, s in ps.LABEL_STATUS))},
)


@pytest.mark.parametrize(
    ("labels", "state", "subs", "status"),
    [
        ({"ready-for-agent", "local-only"}, "open", 0, "Ready for agent"),
        ({"ready-for-agent", "in-progress"}, "open", 0, "In progress"),
        ({"ready-for-human"}, "open", 0, "Ready for human"),
        ({"needs-info"}, "open", 0, "Needs info"),
        ({"research"}, "open", 0, "Needs triage"),
        (set(), "open", 0, "Needs triage"),
        ({"ready-for-agent"}, "open", 3, "Goal"),
        ({"wayfinder:map"}, "open", 2, "Goal"),
        ({"wayfinder:task"}, "open", 0, None),
        ({"wontfix"}, "closed", 0, "Done"),
        (set(), "closed", 4, "Done"),
    ],
)
def test_status_follows_state_then_parenthood_then_labels(
    labels: set[str], state: str, subs: int, status: str | None
) -> None:
    assert ps.derive_status(labels, state, subs) == status


def _issue(number: int, *labels: str, state: str = "open", subs: int = 0) -> dict[str, Any]:
    return {
        "number": number,
        "node_id": f"I{number}",
        "state": state,
        "labels": [{"name": name} for name in labels],
        "sub_issues_summary": {"total": subs, "completed": 0},
    }


def _fake(
    monkeypatch: pytest.MonkeyPatch, issue: dict[str, Any], status: str | None, archived: bool
) -> list[str]:
    """Answer the REST read and the add mutation; record each mutation by its name."""
    writes: list[str] = []

    def gh(*args: str) -> Any:
        if args[1] != "graphql":
            return issue
        query = args[3].removeprefix("query=")
        if "addProjectV2ItemById" in query:
            value = {"name": status} if status else None
            return {
                "data": {
                    "addProjectV2ItemById": {
                        "item": {"id": "IT", "isArchived": archived, "fieldValueByName": value}
                    }
                }
            }
        names = {ps._SET: "set", ps._CLEAR: "clear", ps._UNARCHIVE: "unarchive"}
        option = next((a.removeprefix("option=") for a in args if a.startswith("option=")), None)
        writes.append(f"{names[query]} {option}" if option else names[query])
        return {"data": {}}

    monkeypatch.setattr(ps, "gh_json", gh)
    return writes


def test_an_item_already_right_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    writes = _fake(monkeypatch, _issue(7, "ready-for-agent"), "Ready for agent", archived=False)
    assert ps.sync_issue(PROJECT, REPO, 7) is None
    assert writes == []


def test_a_claim_moves_the_item_to_in_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    writes = _fake(monkeypatch, _issue(7, "in-progress"), "Ready for agent", archived=False)
    assert ps.sync_issue(PROJECT, REPO, 7) == "#7: Ready for agent -> In progress"
    assert writes == ["set opt-In progress"]


def test_a_reopened_issue_comes_back_from_the_archive(monkeypatch: pytest.MonkeyPatch) -> None:
    writes = _fake(monkeypatch, _issue(7, "needs-triage"), "Done", archived=True)
    assert ps.sync_issue(PROJECT, REPO, 7) == "#7: unarchived, Done -> Needs triage"
    assert writes == ["unarchive", "set opt-Needs triage"]


def test_a_wayfinder_ticket_has_its_status_cleared(monkeypatch: pytest.MonkeyPatch) -> None:
    writes = _fake(monkeypatch, _issue(7, "wayfinder:task"), "Todo", archived=False)
    assert ps.sync_issue(PROJECT, REPO, 7) == "#7: Todo -> (none)"
    assert writes == ["clear"]


def test_a_closed_archived_issue_stays_archived(monkeypatch: pytest.MonkeyPatch) -> None:
    writes = _fake(monkeypatch, _issue(7, state="closed"), "Done", archived=True)
    assert ps.sync_issue(PROJECT, REPO, 7) is None
    assert writes == []


def test_a_status_missing_from_the_project_fails_before_any_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    node = {"id": "P", "field": {"id": "F", "options": [{"id": "1", "name": "Todo"}]}}
    monkeypatch.setattr(ps, "gh_json", lambda *_a: {"data": {"user": {"projectV2": node}}})
    with pytest.raises(ps.GhError, match="Goal"):
        ps.load_project("o", 1)
