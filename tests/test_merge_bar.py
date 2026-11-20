"""`merge_bar` judges a pull request from recorded `gh` JSON; nothing here calls gh."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import merge_bar  # noqa: E402
import pr_threads  # noqa: E402

HEAD = "8fe16b8c9d9208416e2a964b7a74ac167bc6ad5d"
CLEAN = "Sonnet reviewer review at 8fe16b8: clean"


def _graphql_view(**changes: Any) -> dict[str, Any]:
    """`gh pr view --json ...` for a PR that meets the bar, as recorded from GitHub."""
    view: dict[str, Any] = {
        "headRefOid": HEAD,
        "baseRefName": "main",
        "isDraft": False,
        "state": "OPEN",
        "body": "Adds the task.\n\nFixes #863\n",
        "comments": [
            {"authorAssociation": "NONE", "body": "needs changes"},
            {"authorAssociation": "OWNER", "body": f"{CLEAN}\n\nDetails."},
        ],
        "statusCheckRollup": [
            {
                "__typename": "CheckRun",
                "name": "Scope",
                "status": "COMPLETED",
                "conclusion": "SUCCESS",
            },
            {
                "__typename": "CheckRun",
                "name": "CodeRabbit",
                "status": "COMPLETED",
                "conclusion": "SKIPPED",
            },
            {"__typename": "StatusContext", "context": "legacy", "state": "SUCCESS"},
        ],
    }
    view.update(changes)
    return view


def _rest_answers(**changes: Any) -> dict[str, Any]:
    """The REST answers `rest_pull` reads for the same PR, keyed by route."""
    pull: dict[str, Any] = {
        "head": {"sha": HEAD},
        "base": {"ref": "main"},
        "draft": False,
        "state": "open",
        "merged": False,
        "body": "Adds the task.\n\nFixes #863\n",
    }
    comments = [
        {"author_association": "NONE", "body": "needs changes"},
        {"author_association": "MEMBER", "body": CLEAN},
    ]
    runs = [
        {"name": "Scope", "status": "completed", "conclusion": "success"},
        {"name": "build", "status": "completed", "conclusion": "success"},
    ]
    answers: dict[str, Any] = {
        "repos/o/r/pulls/9": pull,
        f"repos/o/r/commits/{HEAD}/check-runs": {"check_runs": runs},
        f"repos/o/r/commits/{HEAD}/status": {
            "statuses": [{"context": "legacy", "state": "success"}]
        },
        "repos/o/r/issues/9/comments": comments,
    }
    answers.update(changes)
    return answers


def _install_rest(
    monkeypatch: pytest.MonkeyPatch, answers: dict[str, Any]
) -> list[tuple[str, ...]]:
    """Answer `gh api <route>?per_page=...` from *answers*; the calls made, in order."""
    calls: list[tuple[str, ...]] = []

    def gh(*args: str, **_k: Any) -> Any:
        calls.append(args)
        assert args[0] == "api", args
        route = args[1].split("?", 1)[0]
        return answers[route]

    monkeypatch.setattr(pr_threads, "_gh", gh)
    return calls


def _pull(**changes: Any) -> merge_bar.Pull:
    """A `Pull` that meets the bar, with *changes* applied."""
    pull = merge_bar.Pull(
        head=HEAD,
        base="main",
        draft=False,
        state="OPEN",
        body="Fixes #863",
        comments=[("OWNER", CLEAN)],
        checks=[("Scope", "ok")],
    )
    for key, value in changes.items():
        setattr(pull, key, value)
    return pull


def _reasons(pull: merge_bar.Pull, *, threads: list[str] | None = None) -> list[str]:
    return merge_bar.evaluate(pull, threads=threads or [], findings=[])[1]


def test_a_pull_that_meets_the_bar_has_no_reasons() -> None:
    lines, reasons = merge_bar.evaluate(_pull(), threads=[], findings=[])
    assert reasons == []
    assert not any(line.startswith("FAIL") for line in lines)
    assert "ok   head and base: 8fe16b8 on base main" in lines


def test_a_stacked_base_fails() -> None:
    assert _reasons(_pull(base="feature")) == ["base is feature, not main"]


def test_a_failed_check_fails_and_names_itself() -> None:
    pull = _pull(checks=[("Scope", "ok"), ("Quality gate", "failed")])
    assert _reasons(pull) == ["CI failed: Quality gate"]


def test_pending_checks_are_listed_but_do_not_fail() -> None:
    lines, reasons = merge_bar.evaluate(
        _pull(checks=[("Scope", "ok"), ("Windows smoke", "pending")]), threads=[], findings=[]
    )
    assert reasons == []
    assert any("1 pending (Windows smoke)" in line for line in lines)


def test_no_review_comment_fails() -> None:
    assert _reasons(_pull(comments=[])) == ["no clean review comment at 8fe16b8"]


def test_a_clean_comment_by_a_stranger_does_not_count() -> None:
    assert _reasons(_pull(comments=[("NONE", CLEAN)])) == ["no clean review comment at 8fe16b8"]


def test_a_clean_comment_at_an_older_head_fails() -> None:
    stale = "Sonnet reviewer review at 1234567: clean"
    lines, reasons = merge_bar.evaluate(_pull(comments=[("OWNER", stale)]), threads=[], findings=[])
    assert reasons == ["no clean review comment at 8fe16b8"]
    assert any("newest review comment is at 1234567" in line for line in lines)


def test_the_newest_comment_at_the_head_decides() -> None:
    changes = "Sonnet reviewer review at 8fe16b8: needs changes"
    assert _reasons(_pull(comments=[("OWNER", CLEAN), ("OWNER", changes)])) != []
    assert _reasons(_pull(comments=[("OWNER", changes), ("OWNER", CLEAN)])) == []


def test_only_a_comments_first_line_is_its_verdict() -> None:
    buried = "Details first.\n" + CLEAN
    assert _reasons(_pull(comments=[("OWNER", buried)])) != []


def test_a_body_without_a_linking_line_fails() -> None:
    assert _reasons(_pull(body="Adds the task.")) == [
        "the body has no Fixes, Closes or Part of #N line"
    ]
    assert _reasons(_pull(body="Part of #861, then more")) == []
    assert _reasons(_pull(body="Closes #12")) == []


def test_an_open_thread_fails_and_is_listed() -> None:
    thread = "a.py:3 [Major] Rename. | id 7, 0 replies, last by bot"
    lines, reasons = merge_bar.evaluate(_pull(), threads=[thread], findings=[])
    assert reasons == ["1 open review threads"]
    assert any(thread in line for line in lines)


def test_review_body_findings_are_listed_without_failing() -> None:
    finding = "a.py:3 [Minor] Typo | outside diff, review 5"
    lines, reasons = merge_bar.evaluate(_pull(), threads=[], findings=[finding])
    assert reasons == []
    assert any(finding in line for line in lines)
    assert any(line.startswith("note findings: 1 review-body") for line in lines)


def test_a_draft_fails() -> None:
    assert _reasons(_pull(draft=True)) == ["the PR is a draft"]


def test_a_closed_unmerged_pull_fails_and_a_merged_one_does_not() -> None:
    assert _reasons(_pull(state="CLOSED")) == ["the PR is closed unmerged"]
    assert _reasons(_pull(state="MERGED")) == []


def test_graphql_json_reads_into_a_pull(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pr_threads, "_gh", lambda *_a, **_k: _graphql_view())
    pull = merge_bar.graphql_pull(9)
    assert pull is not None
    assert (pull.head, pull.base, pull.draft, pull.state) == (HEAD, "main", False, "OPEN")
    assert pull.checks == [("Scope", "ok"), ("CodeRabbit", "ok"), ("legacy", "ok")]
    assert _reasons(pull) == []


@pytest.mark.parametrize(
    ("check", "expected"),
    [
        ({"status": "COMPLETED", "conclusion": "FAILURE"}, "failed"),
        ({"status": "COMPLETED", "conclusion": "CANCELLED"}, "failed"),
        ({"status": "IN_PROGRESS", "conclusion": ""}, "pending"),
        ({"status": "QUEUED", "conclusion": None}, "pending"),
        ({"status": "COMPLETED", "conclusion": "SKIPPED"}, "ok"),
    ],
)
def test_graphql_check_runs_map_to_a_state(
    monkeypatch: pytest.MonkeyPatch, check: dict[str, Any], expected: str
) -> None:
    run = {"__typename": "CheckRun", "name": "x", **check}
    context = {"__typename": "StatusContext", "context": "ctx", "state": "ERROR"}
    monkeypatch.setattr(
        pr_threads, "_gh", lambda *_a, **_k: _graphql_view(statusCheckRollup=[run, context])
    )
    pull = merge_bar.graphql_pull(9)
    assert pull is not None
    assert pull.checks == [("x", expected), ("ctx", "failed")]


def test_graphql_failures_each_fail_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    cases = {
        "base": _graphql_view(baseRefName="feature"),
        "body": _graphql_view(body="No link."),
        "draft": _graphql_view(isDraft=True),
        "review": _graphql_view(comments=[]),
        "ci": _graphql_view(
            statusCheckRollup=[
                {
                    "__typename": "CheckRun",
                    "name": "x",
                    "status": "COMPLETED",
                    "conclusion": "FAILURE",
                }
            ]
        ),
    }
    for name, view in cases.items():
        monkeypatch.setattr(pr_threads, "_gh", lambda *_a, view=view, **_k: view)
        pull = merge_bar.graphql_pull(9)
        assert pull is not None
        assert len(_reasons(pull)) == 1, name


def test_a_missing_pull_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def gh(*_a: str, **_k: Any) -> Any:
        raise pr_threads.GhError(
            "GraphQL: Could not resolve to a PullRequest with the number of 9."
        )

    monkeypatch.setattr(pr_threads, "_gh", gh)
    assert merge_bar.graphql_pull(9) is None


def test_the_cloud_path_reads_rest_only(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_rest(monkeypatch, _rest_answers())
    pull = merge_bar.rest_pull("o", "r", 9)
    assert pull is not None
    assert (pull.head, pull.base, pull.state) == (HEAD, "main", "OPEN")
    assert pull.checks == [("Scope", "ok"), ("build", "ok"), ("legacy", "ok")]
    assert _reasons(pull) == []
    assert all(call[0] == "api" and "graphql" not in call for call in calls)


def test_the_cloud_path_reports_each_single_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    pull_route = "repos/o/r/pulls/9"
    base = _rest_answers()[pull_route]
    cases: dict[str, dict[str, Any]] = {
        "base": {pull_route: {**base, "base": {"ref": "feature"}}},
        "body": {pull_route: {**base, "body": None}},
        "draft": {pull_route: {**base, "draft": True}},
        "review": {"repos/o/r/issues/9/comments": []},
        "ci": {
            f"repos/o/r/commits/{HEAD}/check-runs": {
                "check_runs": [{"name": "build", "status": "completed", "conclusion": "failure"}]
            }
        },
    }
    for name, changes in cases.items():
        _install_rest(monkeypatch, _rest_answers(**changes))
        pull = merge_bar.rest_pull("o", "r", 9)
        assert pull is not None
        assert len(_reasons(pull)) == 1, name


def test_the_cloud_path_reads_a_merged_pull_as_merged(monkeypatch: pytest.MonkeyPatch) -> None:
    base = _rest_answers()["repos/o/r/pulls/9"]
    _install_rest(
        monkeypatch,
        _rest_answers(**{"repos/o/r/pulls/9": {**base, "state": "closed", "merged": True}}),
    )
    pull = merge_bar.rest_pull("o", "r", 9)
    assert pull is not None
    assert pull.state == "MERGED"


def test_rest_lists_are_read_page_by_page(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = {1: [{"n": i} for i in range(merge_bar.REST_PAGE)], 2: [{"n": -1}]}

    def gh(*args: str, **_k: Any) -> Any:
        return pages[int(args[1].rsplit("page=", 1)[1])]

    monkeypatch.setattr(pr_threads, "_gh", gh)
    assert len(merge_bar._rest_pages("repos/o/r/x")) == merge_bar.REST_PAGE + 1


def test_main_uses_rest_in_a_cloud_session_and_prints_pass(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    answers = _rest_answers(**{"repos/{owner}/{repo}": {"full_name": "o/r"}})
    _install_rest(monkeypatch, answers)
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")
    monkeypatch.setattr(pr_threads, "read_threads", lambda *_a: [])
    monkeypatch.setattr(pr_threads, "read_reviews", lambda *_a: (None, []))
    assert merge_bar.main(["9"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "o/r#9"
    assert out.splitlines()[-1] == "PASS"


def test_main_prints_every_failure_reason_and_exits_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)

    def gh(*args: str, **_k: Any) -> Any:
        if args[0] == "pr":
            return _graphql_view(isDraft=True, body="none")
        return {"full_name": "o/r"}

    monkeypatch.setattr(pr_threads, "_gh", gh)
    monkeypatch.setattr(pr_threads, "read_threads", lambda *_a: [])
    monkeypatch.setattr(pr_threads, "read_reviews", lambda *_a: (None, []))
    assert merge_bar.main(["9"]) == 1
    last = capsys.readouterr().out.splitlines()[-1]
    assert last == "FAIL: the body has no Fixes, Closes or Part of #N line; the PR is a draft"


def test_main_reports_a_gh_failure_as_exit_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def gh(*_a: str, **_k: Any) -> Any:
        raise pr_threads.GhError("no network")

    monkeypatch.setattr(pr_threads, "_gh", gh)
    assert merge_bar.main(["9"]) == 2
    assert "merge-bar: no network" in capsys.readouterr().err
