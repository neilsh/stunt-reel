"""`merge_bar` judges a pull request from recorded `gh` JSON; nothing here calls gh."""

from __future__ import annotations

import ast
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
#: Fixture paths are built from this part so this file names no document path of its own for
#: ``test_code_cited_docs_exist`` to look up.
DOCS = "docs"


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


def test_an_alternatives_section_does_not_change_the_verdict() -> None:
    comment = (
        f"{CLEAN}\n\nNo findings.\n\nAlternatives (non-blocking)\n"
        "- Call the existing helper — drops the new loop — loses the batching.\n"
    )
    lines, reasons = merge_bar.evaluate(
        _pull(comments=[("OWNER", comment)]), threads=[], findings=[]
    )
    assert reasons == []
    assert "ok   review: comment at 8fe16b8 says clean" in lines


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


def test_a_present_attribution_line_is_one_condition() -> None:
    lines, reasons = merge_bar.evaluate(_pull(), threads=[], findings=[], attribution=[])
    assert reasons == []
    assert "ok   attribution: the body ends with an attribution line" in lines


def test_a_missing_attribution_line_is_a_note_not_a_failure() -> None:
    failure = "the last line is 'Thanks.', not an attribution line"
    lines, reasons = merge_bar.evaluate(_pull(), threads=[], findings=[], attribution=[failure])
    assert reasons == []
    assert "note attribution: 1 failure(s) (listed, not failed)" in lines
    assert any(failure in line for line in lines)
    assert not any(line.startswith("FAIL") for line in lines)


def test_the_pin_and_date_note_is_gone() -> None:
    """CI runs the pin and date checks now (#1049), so the report no longer names them."""
    lines, _ = merge_bar.evaluate(_pull(), threads=[], findings=[], attribution=[])
    assert not any("pin and date" in line for line in lines)


def test_a_pull_touching_no_gated_path_passes_the_human_paths_line() -> None:
    files = ["python/x.py", f"{DOCS}/howto/a.md", "research/parity/expected/a.toml"]
    lines, reasons = merge_bar.evaluate(_pull(files=files), threads=[], findings=[])
    assert reasons == []
    assert "ok   human paths: none of 3 changed files" in lines


def test_each_human_gated_path_fails_the_bar_and_is_named() -> None:
    files = [
        f"{DOCS}/adr/0099-new.md",
        "crates/stunt-core/Cargo.toml",
        "research/parity/references.toml",
        "crates/stunt-core/src/lib.rs",
        f"{DOCS}/adr-notes.md",
        "crates/other/Cargo.toml",
    ]
    _, reasons = merge_bar.evaluate(_pull(files=files), threads=[], findings=[])
    named = f"crates/stunt-core/Cargo.toml, {DOCS}/adr/0099-new.md, research/parity/references.toml"
    assert reasons == [f"touches human-gated paths: {named}; a reviewer or human decides"]


def test_pull_files_pages_and_includes_a_renames_old_path(monkeypatch: pytest.MonkeyPatch) -> None:
    first = [{"filename": f"f{i}"} for i in range(merge_bar.REST_PAGE - 1)]
    first.append({"filename": f"{DOCS}/new.md", "previous_filename": f"{DOCS}/adr/0001-old.md"})
    pages = {1: first, 2: [{"filename": "research/parity/references.toml"}]}
    routes: list[str] = []

    def gh(*args: str, **_k: Any) -> Any:
        routes.append(args[1])
        return pages[int(args[1].rsplit("page=", 1)[1])]

    monkeypatch.setattr(pr_threads, "_gh", gh)
    paths = merge_bar.pull_files("o", "r", 9)
    assert routes[0].startswith("repos/o/r/pulls/9/files?")
    assert merge_bar.human_gated(paths) == [
        f"{DOCS}/adr/0001-old.md",
        "research/parity/references.toml",
    ]


def test_main_fails_on_a_gated_path_on_both_paths(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    files = [{"filename": f"{DOCS}/adr/0100-x.md"}]
    monkeypatch.setattr(pr_threads, "read_threads", lambda *_a: [])
    monkeypatch.setattr(pr_threads, "read_reviews", lambda *_a: (None, []))

    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)

    def gh(*args: str, **_k: Any) -> Any:
        if args[0] == "pr":
            return _graphql_view()
        return files if "/pulls/9/files" in args[1] else {"full_name": "o/r"}

    monkeypatch.setattr(pr_threads, "_gh", gh)
    assert merge_bar.main(["9"], attribution=lambda _body: []) == 1
    last = capsys.readouterr().out.splitlines()[-1]
    assert (
        last
        == f"FAIL: touches human-gated paths: {DOCS}/adr/0100-x.md; a reviewer or human decides"
    )

    answers = _rest_answers(
        **{"repos/{owner}/{repo}": {"full_name": "o/r"}, "repos/o/r/pulls/9/files": files}
    )
    _install_rest(monkeypatch, answers)
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")
    assert merge_bar.main(["9"], attribution=lambda _body: []) == 1
    assert f"human paths: touches {DOCS}/adr/0100-x.md" in capsys.readouterr().out


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
    answers = _rest_answers(
        **{"repos/{owner}/{repo}": {"full_name": "o/r"}, "repos/o/r/pulls/9/files": []}
    )
    _install_rest(monkeypatch, answers)
    monkeypatch.setenv("CLAUDE_CODE_REMOTE", "true")
    monkeypatch.setattr(pr_threads, "read_threads", lambda *_a: [])
    monkeypatch.setattr(pr_threads, "read_reviews", lambda *_a: (None, []))
    assert merge_bar.main(["9"], attribution=lambda _body: []) == 0
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
        return [] if "/files" in args[1] else {"full_name": "o/r"}

    monkeypatch.setattr(pr_threads, "_gh", gh)
    monkeypatch.setattr(pr_threads, "read_threads", lambda *_a: [])
    monkeypatch.setattr(pr_threads, "read_reviews", lambda *_a: (None, []))
    assert merge_bar.main(["9"], attribution=lambda _body: []) == 1
    last = capsys.readouterr().out.splitlines()[-1]
    assert last == "FAIL: the body has no Fixes, Closes or Part of #N line; the PR is a draft"


def test_main_reports_a_missing_attribution_as_a_note(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)

    def gh(*args: str, **_k: Any) -> Any:
        if args[0] == "pr":
            return _graphql_view()
        return [] if "/files" in args[1] else {"full_name": "o/r"}

    monkeypatch.setattr(pr_threads, "_gh", gh)
    monkeypatch.setattr(pr_threads, "read_threads", lambda *_a: [])
    monkeypatch.setattr(pr_threads, "read_reviews", lambda *_a: (None, []))
    seen: list[str] = []

    def attribution(body: str) -> list[str]:
        seen.append(body)
        return ["the body is empty, so it has no attribution line"]

    assert merge_bar.main(["9"], attribution=attribution) == 0
    out = capsys.readouterr().out
    assert seen == ["Adds the task.\n\nFixes #863\n"]
    assert "note attribution: 1 failure(s) (listed, not failed)" in out
    assert "the body is empty, so it has no attribution line" in out
    assert out.splitlines()[-1] == "PASS"


def test_main_reports_a_gh_failure_as_exit_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def gh(*_a: str, **_k: Any) -> Any:
        raise pr_threads.GhError("no network")

    monkeypatch.setattr(pr_threads, "_gh", gh)
    assert merge_bar.main(["9"]) == 2
    assert "merge-bar: no network" in capsys.readouterr().err


def _title_runs(first: str, second: str) -> list[dict[str, Any]]:
    """`PR title` as #867 recorded it: a superseded run, then the rerun that replaced it."""
    return [
        {
            "__typename": "CheckRun",
            "name": "PR title",
            "status": "COMPLETED",
            "conclusion": first,
            "startedAt": "2026-11-20T20:52:55Z",
        },
        {
            "__typename": "CheckRun",
            "name": "PR title",
            "status": "COMPLETED",
            "conclusion": second,
            "startedAt": "2026-11-20T20:52:57Z",
        },
    ]


def test_graphql_keeps_only_the_newest_run_of_a_check(monkeypatch: pytest.MonkeyPatch) -> None:
    runs = _title_runs("CANCELLED", "SUCCESS")
    for ordered in (runs, runs[::-1]):
        monkeypatch.setattr(
            pr_threads,
            "_gh",
            lambda *_a, ordered=ordered, **_k: _graphql_view(statusCheckRollup=ordered),
        )
        pull = merge_bar.graphql_pull(9)
        assert pull is not None
        assert pull.checks == [("PR title", "ok")]
        assert _reasons(pull) == []


def test_graphql_a_newer_failure_still_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    runs = _title_runs("SUCCESS", "FAILURE")
    monkeypatch.setattr(pr_threads, "_gh", lambda *_a, **_k: _graphql_view(statusCheckRollup=runs))
    pull = merge_bar.graphql_pull(9)
    assert pull is not None
    assert _reasons(pull) == ["CI failed: PR title"]


def test_rest_keeps_only_the_newest_run_of_a_check(monkeypatch: pytest.MonkeyPatch) -> None:
    cancelled = {
        "id": 20,
        "name": "PR title",
        "status": "completed",
        "conclusion": "cancelled",
        "started_at": "2026-11-20T20:52:55Z",
    }
    passed = {**cancelled, "id": 10, "conclusion": "success", "started_at": "2026-11-20T20:52:57Z"}
    for runs in ([cancelled, passed], [passed, cancelled]):
        _install_rest(
            monkeypatch,
            _rest_answers(**{f"repos/o/r/commits/{HEAD}/check-runs": {"check_runs": runs}}),
        )
        pull = merge_bar.rest_pull("o", "r", 9)
        assert pull is not None
        assert ("PR title", "ok") in pull.checks
        assert [name for name, _ in pull.checks].count("PR title") == 1
        assert _reasons(pull) == []


def test_rest_runs_with_one_start_time_go_by_id(monkeypatch: pytest.MonkeyPatch) -> None:
    run = {"name": "x", "status": "completed", "started_at": "t"}
    runs = [{**run, "id": 2, "conclusion": "success"}, {**run, "id": 1, "conclusion": "failure"}]
    _install_rest(
        monkeypatch,
        _rest_answers(**{f"repos/o/r/commits/{HEAD}/check-runs": {"check_runs": runs}}),
    )
    pull = merge_bar.rest_pull("o", "r", 9)
    assert pull is not None
    assert ("x", "ok") in pull.checks


def test_every_page_of_status_contexts_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = {
        1: [{"context": f"c{i}", "state": "success", "id": i} for i in range(merge_bar.REST_PAGE)],
        2: [{"context": "late", "state": "failure", "id": 999}],
    }
    answers = _rest_answers()

    def gh(*args: str, **_k: Any) -> Any:
        route, _, query = args[1].partition("?")
        if route.endswith("/status"):
            return {"statuses": pages[int(query.rsplit("page=", 1)[1])]}
        return answers[route]

    monkeypatch.setattr(pr_threads, "_gh", gh)
    pull = merge_bar.rest_pull("o", "r", 9)
    assert pull is not None
    assert ("late", "failed") in pull.checks
    assert _reasons(pull) == ["CI failed: late"]


def test_a_clean_comment_at_the_head_stands_over_a_later_older_one() -> None:
    older = "Sonnet reviewer review at 1234567: needs changes"
    pull = _pull(comments=[("OWNER", CLEAN), ("OWNER", older)])
    assert merge_bar.review_verdict(pull) == ("8fe16b8", "clean")
    assert _reasons(pull) == []


def test_without_a_comment_at_the_head_the_newest_older_one_is_reported() -> None:
    pull = _pull(
        comments=[("OWNER", "a review at 1111111: clean"), ("OWNER", "a review at 2222222: clean")]
    )
    assert merge_bar.review_verdict(pull) == ("2222222", "clean")


def test_a_body_naming_another_issue_fails() -> None:
    lines, reasons = merge_bar.evaluate(_pull(body="Fixes #12"), threads=[], findings=[], issue=863)
    assert reasons == ["the body links #12, not #863"]
    assert any("has `Fixes #12` (wanted #863)" in line for line in lines)


def test_a_body_naming_the_issue_passes_and_every_link_is_printed() -> None:
    lines, reasons = merge_bar.evaluate(
        _pull(body="Part of #12\n\nFixes #863"), threads=[], findings=[], issue=863
    )
    assert reasons == []
    assert any("`Part of #12`, `Fixes #863` (wanted #863)" in line for line in lines)


def test_an_issue_number_is_not_a_prefix_match() -> None:
    assert merge_bar.evaluate(_pull(body="Fixes #8630"), threads=[], findings=[], issue=863)[1]


def test_main_passes_the_issue_to_the_body_check(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("CLAUDE_CODE_REMOTE", raising=False)

    def gh(*args: str, **_k: Any) -> Any:
        if args[0] == "pr":
            return _graphql_view()
        return [] if "/files" in args[1] else {"full_name": "o/r"}

    monkeypatch.setattr(pr_threads, "_gh", gh)
    monkeypatch.setattr(pr_threads, "read_threads", lambda *_a: [])
    monkeypatch.setattr(pr_threads, "read_reviews", lambda *_a: (None, []))
    assert merge_bar.main(["9", "--issue", "863"], attribution=lambda _body: []) == 0
    assert merge_bar.main(["9", "--issue", "12"], attribution=lambda _body: []) == 1
    assert capsys.readouterr().out.splitlines()[-1] == "FAIL: the body links #863, not #12"


def test_only_graphql_pull_runs_a_graphql_gh_command() -> None:
    """`LOCAL_ONLY` exempts the whole file, so pin where its one GraphQL call may be."""
    from test_gh_rest_only import graphql_calls  # noqa: PLC0415

    source = Path(merge_bar.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    func = next(
        n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "graphql_pull"
    )
    inside = range(func.lineno, (func.end_lineno or func.lineno) + 1)
    lines = [int(call.split(":", 1)[0]) for call in graphql_calls(source)]
    assert lines
    assert all(line in inside for line in lines), graphql_calls(source)


def test_the_graphql_gh_finder_sees_a_pr_view_outside_graphql_pull() -> None:
    from test_gh_rest_only import graphql_calls  # noqa: PLC0415

    assert graphql_calls('def rest_pull():\n    _gh("pr", "view", "1")\n') == ["2: gh pr view"]
