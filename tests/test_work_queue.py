"""`work_queue` reduces open PRs and issues to one line each; the cases are synthetic, nothing calls gh."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import work_queue as q  # noqa: E402


def _pr(number: int, head: str, base: str = "main", **extra: Any) -> dict[str, Any]:
    return {
        "number": number,
        "title": f"PR {number}",
        "head": {"ref": head, "sha": f"sha{number}"},
        "base": {"ref": base},
        "draft": False,
        "labels": [],
        "body": "",
        "auto_merge": None,
        **extra,
    }


def _issue(number: int, *labels: str, **extra: Any) -> dict[str, Any]:
    return {
        "number": number,
        "title": f"Issue {number}",
        "labels": [{"name": name} for name in ("ready-for-agent", *labels)],
        "body": "",
        "issue_dependencies_summary": {"blocked_by": 0},
        "sub_issues_summary": {"total": 0, "completed": 0},
        **extra,
    }


def _skips(items: list[Any]) -> dict[int, list[str]]:
    return {item.number: item.skip for item in items}


def test_stacked_prs_follow_the_pr_they_build_on() -> None:
    prs = [
        _pr(5, "b-top", base="b-bottom"),
        _pr(3, "top", base="mid"),
        _pr(2, "mid", base="bottom"),
        _pr(4, "b-bottom"),
        _pr(1, "bottom"),
        _pr(6, "orphan", base="gone"),
    ]
    assert [item.number for item in q.pr_items(prs, {})] == [1, 4, 6, 2, 5, 3]


def test_a_stack_cycle_ends() -> None:
    prs = [_pr(1, "a", base="b"), _pr(2, "b", base="a")]
    assert [item.number for item in q.pr_items(prs, {})] == [1, 2]


def test_a_pr_for_a_human_is_skipped_and_drafts_are_noted() -> None:
    first, second = q.pr_items(
        [_pr(1, "a", labels=[{"name": "ready-for-human"}]), _pr(2, "b", base="a", draft=True)], {}
    )
    assert first.skip == ["ready-for-human"]
    assert (second.skip, second.notes) == (["base #1 open"], ["draft", "base=a"])


@pytest.mark.parametrize(
    ("state", "skip", "notes"),
    [
        ("pending", ["armed, checks pending"], []),
        ("passed", [], ["auto-merge armed, checks passed but not merged"]),
        ("failed", [], ["auto-merge armed, a check failed"]),
        ("conflict", [], ["auto-merge armed, conflicts with main"]),
    ],
)
def test_an_armed_pr_needs_work_only_when_a_check_failed(
    state: str, skip: list[str], notes: list[str]
) -> None:
    (item,) = q.pr_items([_pr(1, "a", auto_merge={"merge_method": "squash"})], {1: state})
    assert (item.skip, item.notes) == (skip, notes)


def test_check_runs_reduce_to_one_state() -> None:
    done = {"status": "completed", "conclusion": "success"}
    assert q.checks_state([done, {"status": "completed", "conclusion": "skipped"}]) == "passed"
    assert q.checks_state([done, {"status": "in_progress", "conclusion": None}]) == "pending"
    assert q.checks_state([{"status": "in_progress"}, {"conclusion": "failure"}]) == "failed"
    assert q.checks_state([]) == "pending"


def test_a_blocked_by_line_never_reads_the_next_line() -> None:
    assert q.blocked_by_line("Blocked by:\n#5 is related") == set()
    assert q.parents_of("Part of\n#5") == set()


def test_issues_without_ready_for_agent_are_left_out() -> None:
    other = _issue(7)
    other["labels"] = [{"name": "needs-triage"}]
    assert [item.number for item in q.issue_items([other, _issue(8)], [], cloud=False)] == [8]


def test_each_mechanical_skip_names_its_reason() -> None:
    issues = [
        _issue(1, "in-progress"),
        _issue(2, issue_dependencies_summary={"blocked_by": 2}),
        _issue(3, sub_issues_summary={"total": 3, "completed": 1}),
        _issue(4),
        _issue(5),
        _issue(6, body="Context.\nPart of #5"),
        _issue(7, body="Blocked by: #6, #99"),
    ]
    skips = _skips(q.issue_items(issues, [_pr(9, "feat/4-thing")], cloud=False))
    assert skips == {
        1: ["in-progress"],
        2: ["2 open blocker(s)"],
        3: ["2 open sub-issue(s)"],
        4: ["PR #9"],
        5: ["1 open sub-issue(s)"],
        6: [],
        7: ["1 open blocker(s)"],
    }


def test_a_sub_issue_named_both_ways_counts_once() -> None:
    issues = [
        _issue(5, sub_issues_summary={"total": 1, "completed": 0}),
        _issue(6, body="Part of #5"),
    ]
    assert _skips(q.issue_items(issues, [], cloud=False))[5] == ["1 open sub-issue(s)"]


@pytest.mark.parametrize(
    ("branch", "claims"),
    [
        ("feat/440-slug", True),
        ("440-slug", True),
        ("docs/0044-adr", False),
        ("chore/2026-11-x", False),
    ],
)
def test_only_an_issue_number_in_a_branch_claims_it(branch: str, claims: bool) -> None:
    issues = [_issue(n) for n in (440, 44, 2026)]
    skipped = {
        n
        for n, skip in _skips(q.issue_items(issues, [_pr(9, branch)], cloud=False)).items()
        if skip
    }
    assert bool(skipped) is claims


def test_a_closing_keyword_in_an_issue_body_is_no_sub_issue() -> None:
    issues = [_issue(5), _issue(6, body="Fixes #5 once it lands; closes #5 too.")]
    assert _skips(q.issue_items(issues, [], cloud=False))[5] == []


def test_a_pr_claims_every_issue_its_title_or_body_names() -> None:
    prs = [
        _pr(9, "chore/no-number", body="Part of #4. Resolved: #5, #6 and #7"),
        _pr(10, "chore/other", title="fix(x): thing (fixed #8)"),
    ]
    issues = [_issue(n) for n in (4, 5, 6, 7, 8, 11)]
    skips = _skips(q.issue_items(issues, prs, cloud=False))
    assert skips == {4: ["PR #9"], 5: ["PR #9"], 6: ["PR #9"], 7: ["PR #9"], 8: ["PR #10"], 11: []}


@pytest.mark.parametrize(("cloud", "skip"), [(False, []), (True, ["local-only"])])
def test_local_only_is_skipped_only_in_a_cloud_session(cloud: bool, skip: list[str]) -> None:
    assert q.issue_items([_issue(1, "local-only")], [], cloud=cloud)[0].skip == skip


def test_a_line_names_the_item_its_state_and_its_labels() -> None:
    item = q.Item("issue", 12, "A  title\nover lines", ["tooling"], skip=["in-progress"])
    assert item.line() == "issue #12    skip: in-progress            A title over lines  [tooling]"


def _fake_gh(monkeypatch: pytest.MonkeyPatch, replies: dict[str, Any]) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []

    def gh(*args: str) -> Any:
        calls.append(args)
        for key, reply in replies.items():
            if key in args[-1]:
                return reply
        raise AssertionError(args)

    monkeypatch.setattr(q, "gh_json", gh)
    return calls


def test_fetch_flattens_pages_drops_prs_and_reads_checks_only_for_armed_prs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    armed = _pr(2, "b", auto_merge={"merge_method": "squash"})
    conflicted = _pr(5, "c", auto_merge={"merge_method": "squash"})
    calls = _fake_gh(
        monkeypatch,
        {
            "/pulls?": [[_pr(1, "a")], [armed, conflicted]],
            "/issues?": [[_issue(3), {**_issue(1), "pull_request": {}}], [_issue(4)]],
            "/pulls/2": {"mergeable_state": "blocked"},
            "/pulls/5": {"mergeable_state": "dirty"},
            "/commits/sha2/check-runs?per_page=100": {"check_runs": [{"status": "queued"}]},
        },
    )
    prs, checks, issues = q.fetch()
    assert [pr["number"] for pr in prs] == [1, 2, 5]
    assert checks == {2: "pending", 5: "conflict"}
    assert [issue["number"] for issue in issues] == [3, 4]
    assert len(calls) == 5


def test_a_gh_failure_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(*_args: str) -> Any:
        raise q.GhError("HTTP 502")

    monkeypatch.setattr(q, "gh_json", fail)
    assert q.main() == 2
    assert capsys.readouterr().err == "queue: HTTP 502\n"


def test_main_reads_the_cloud_flag(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _fake_gh(monkeypatch, {"/pulls?": [[]], "/issues?": [[_issue(1, "local-only")]]})
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")
    assert q.main() == 0
    assert "skip: local-only" in capsys.readouterr().out
