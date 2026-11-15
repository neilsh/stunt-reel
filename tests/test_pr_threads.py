"""`pr_threads` reduces review threads to one line each; the cases are synthetic, nothing calls gh."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import pr_threads  # noqa: E402

# The shape of a CodeRabbit finding: markup, a bold severity line, a bold title, then details.
_BOT_BODY = """<!-- coderabbit-ai-generated:v1 -->

**<picture><img src="major-16.svg" alt=""></picture> Major** · **Data Integrity** · **Quick win**

<details>
<summary>Supported by static analysis</summary>
Script executed: **not the title**
</details>

**Compare `all_sha256` before parity scoring.**

`FilmId` now carries the archive hash, but the warning checks only the name.

<details><summary>Prompt for AI Agents</summary>very long prompt</details>
"""


def _thread(
    body: str, *, resolved: bool = False, line: int | None = 22, replies: int = 0
) -> dict[str, Any]:
    comments = [{"databaseId": 111, "author": {"login": "coderabbitai"}, "body": body}]
    comments += [
        {"databaseId": 200 + i, "author": {"login": "neilsh"}, "body": "Fixed."}
        for i in range(replies)
    ]
    return {
        "isResolved": resolved,
        "isOutdated": False,
        "path": "crates/stunt-parity/src/film.rs",
        "line": line,
        "originalLine": 20,
        "comments": {"totalCount": len(comments), "nodes": comments[:1]},
        "latest": {"nodes": comments[-1:]},
    }


def test_a_bot_finding_reduces_to_its_severity_and_title() -> None:
    assert pr_threads.summarize(_BOT_BODY) == (
        "Major",
        "Compare `all_sha256` before parity scoring.",
    )


def test_a_plain_comment_titles_with_its_first_line() -> None:
    assert pr_threads.summarize("Rename this.\n\nIt shadows the module.") == (None, "Rename this.")


def test_a_long_title_is_cut() -> None:
    _, title = pr_threads.summarize("x" * 500)
    assert len(title) == pr_threads.TITLE_LIMIT
    assert title.endswith("…")


def test_a_thread_line_names_where_what_and_the_id_to_answer() -> None:
    line = pr_threads.thread_line(_thread(_BOT_BODY, replies=2))
    assert line == (
        "crates/stunt-parity/src/film.rs:22 [Major] Compare `all_sha256` before parity scoring. "
        "| id 111, 2 replies, last by neilsh"
    )


def test_an_outdated_thread_falls_back_to_its_original_line() -> None:
    assert pr_threads.thread_line(_thread("Note.", line=None)).startswith(
        "crates/stunt-parity/src/film.rs:20 Note."
    )


def test_resolved_threads_are_left_out_unless_asked_for() -> None:
    threads = [_thread("Open."), _thread("Done.", resolved=True)]
    assert len(pr_threads.thread_lines(threads, include_resolved=False)) == 1
    kept = pr_threads.thread_lines(threads, include_resolved=True)
    assert len(kept) == 2
    assert "(resolved)" in kept[1]


def test_control_characters_in_the_title_and_path_are_masked() -> None:
    thread = _thread("**Look \x1b[2Jhere**")
    thread["path"] = "a\x1b]0;x\x07.py"
    line = pr_threads.thread_line(thread)
    assert "\x1b" not in line
    assert "\x07" not in line
    assert line.startswith("a?]0;x?.py:22 Look ?[2Jhere")


def test_a_stalled_gh_is_reported_as_a_gh_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def stall(command: list[str], **kwargs: float) -> None:
        raise subprocess.TimeoutExpired(cmd=command, timeout=kwargs["timeout"])

    monkeypatch.setattr(shutil, "which", lambda _name: "gh")
    monkeypatch.setattr(subprocess, "run", stall)
    with pytest.raises(pr_threads.GhError, match="no answer"):
        pr_threads._gh("repo", "view")


def _page(nodes: list[dict[str, Any]], cursor: str | None) -> dict[str, Any]:
    threads = {"nodes": nodes, "pageInfo": {"hasNextPage": cursor is not None, "endCursor": cursor}}
    return {"data": {"repository": {"pullRequest": {"reviewThreads": threads}}}}


def test_every_page_of_threads_is_read(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = {None: _page([_thread("**One**")], "c1"), "c1": _page([_thread("**Two**")], None)}
    seen: list[str | None] = []

    def gh(*args: str) -> dict[str, Any]:
        after = next((a.removeprefix("after=") for a in args if a.startswith("after=")), None)
        seen.append(after)
        return pages[after]

    monkeypatch.setattr(pr_threads, "_gh", gh)
    nodes = pr_threads.read_threads("o", "r", 1)
    assert seen == [None, "c1"]
    assert nodes is not None
    assert [pr_threads.summarize(n["comments"]["nodes"][0]["body"])[1] for n in nodes] == [
        "One",
        "Two",
    ]


def test_graphql_errors_are_a_gh_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pr_threads, "_gh", lambda *_a: {"data": None, "errors": [{"message": "bad cursor"}]}
    )
    with pytest.raises(pr_threads.GhError, match="bad cursor"):
        pr_threads.read_threads("o", "r", 1)


# The shape of a CodeRabbit review body with findings it could not anchor to a changed line.
_REVIEW_BODY = """<!-- coderabbit-ai-generated:v1 -->

> [!CAUTION]
> Some comments are outside the diff and can't be posted inline due to GitHub limitations.
>
> **⚠️ Outside diff range comments (2)**
>
> <details>
> <summary><strong><picture><img src="amber-16.svg" alt=""></picture> Minor</strong> · Fix the import. · <code>tests/test_x.py:17</code></summary><blockquote>
> <summary>Suggested fix</summary>
> </blockquote></details>
> <details>
> <summary><strong><picture></picture> Major</strong> · Count the \x1b[2Jbytes. · <code>pair.py:84-91</code></summary><blockquote>
> </blockquote></details>

<details>
<summary><strong>Minor</strong> · Not an outside-diff finding. · <code>elsewhere.py:1</code></summary>
</details>
"""


def test_a_review_body_yields_its_outside_diff_findings() -> None:
    assert pr_threads.outside_diff(_REVIEW_BODY) == [
        ("tests/test_x.py:17", "Minor", "Fix the import."),
        ("pair.py:84-91", "Major", "Count the ?[2Jbytes."),
    ]
    assert pr_threads.outside_diff("**Actionable comments posted: 1**") == []


# The shape of CodeRabbit's review-body section for findings it could not post inline at all.
_ADDITIONAL_BODY = """<!-- coderabbit-ai-generated:v1 -->

<details>
<summary><picture><img src="message-square-off.svg" alt=""></picture> Additional comments: 2</summary><blockquote>
<dl>
<dd>
<br>

<details>
<summary>.agents/skills/running-unattended/pr-and-filing.md-39-39: 1</summary><blockquote>
<dl>
<dd>
<br>

`39-39`: **<picture><img src="major-16.svg" alt=""></picture> Major** · **Functional Correctness** · **Heavy lift**

<picture><img src="pre-merge-checks-warning.svg" alt=""></picture> **Unverified finding**
Verification ran but could not confirm this finding. It is shown for review, not as a verified issue.

**Bind the clean verdict to the dispatched review.**

The filter checks only comment text.

<!-- cr-comment:v1:7971929275265c14eca49140 -->

</dd>
</dl>
</blockquote></details>

<details>
<summary>python/scripts/pr_threads.py-84-91: 1</summary><blockquote>
<dl>
<dd>
<br>

`84-91`: **<picture><img src="minor-16.svg" alt=""></picture> Minor** · **Maintainability** · **Quick win**

**Keep the parser and the printer in step.**

</dd>
</dl>
</blockquote></details>

</dd>
</dl>
</blockquote></details>
"""


#: CodeRabbit wraps a finding's line range in backticks; built without one in the source.
_MARK = chr(96)


def _additional_section(raw: str, summary: str = "a/b.py-10-40: 1") -> str:
    """A minimal CodeRabbit Additional comments section holding *raw* finding markup."""
    return f"""<details>
<summary>Additional comments: 1</summary><blockquote>
<dl>
<dd>
<br>

<details>
<summary>{summary}</summary><blockquote>
<dl>
<dd>
<br>

{raw}

</dd>
</dl>
</blockquote></details>

</dd>
</dl>
</blockquote></details>
"""


def test_one_file_block_may_hold_several_findings() -> None:
    """CodeRabbit groups a file's findings under one summary with a count (review of #558)."""
    raw = (
        f"{_MARK}10-12{_MARK}: **Major** · **Correctness**\n\n**First title.**\n\n"
        f"{_MARK}40-40{_MARK}: **Critical** · **Security**\n\n**Second title.**"
    )

    assert pr_threads.additional_diff(_additional_section(raw, "a/b.py-10-40: 2")) == [
        ("a/b.py:10-12", "Major", "First title."),
        ("a/b.py:40", "Critical", "Second title."),
    ]


def test_a_finding_without_a_severity_does_not_borrow_one_from_a_later_section() -> None:
    """The Additional slice ends where the section does, not at the review body's end."""
    raw = (
        f"{_MARK}7-7{_MARK}: **Functional Correctness** · **Heavy lift**\n\n"
        "**No severity in this block.**"
    )
    body = _additional_section(raw, "a/b.py-7-7: 1") + "\n\n**Major**\n\nA later section."

    assert pr_threads.additional_diff(body) == []


def test_a_finding_without_a_bold_title_falls_back_like_a_comment() -> None:
    """With no bold title, the first prose line, cut to the title limit (review of #558)."""
    raw = f"{_MARK}5-5{_MARK}: **Minor** · **Maintainability**\n\nA plain prose title."
    assert pr_threads.additional_diff(_additional_section(raw, "a/b.py-5-5: 1")) == [
        ("a/b.py:5", "Minor", "A plain prose title.")
    ]
    long = "y" * (pr_threads.TITLE_LIMIT + 40)
    body = _additional_section(
        f"{_MARK}6-6{_MARK}: ** Minor** · **Maintainability** · **Quick win**\n\n" + long,
        "a/b.py-6-6: 1",
    )
    (_, _, title) = pr_threads.additional_diff(body)[0]
    assert title == "y" * (pr_threads.TITLE_LIMIT - 1) + "…"


def test_outside_diff_findings_come_from_reviews_after_the_head_commit() -> None:
    reviews = [
        {"databaseId": 1, "submittedAt": "2026-11-04T10:00:00Z", "body": _REVIEW_BODY},
        {"databaseId": 2, "submittedAt": "2026-11-04T12:00:00Z", "body": _REVIEW_BODY},
    ]
    since = "2026-11-04T11:00:00Z"
    lines = pr_threads.outside_lines(reviews, since, include_all=False)
    assert lines == [
        "tests/test_x.py:17 [Minor] Fix the import. | outside diff, review 2",
        "pair.py:84-91 [Major] Count the ?[2Jbytes. | outside diff, review 2",
    ]
    assert len(pr_threads.outside_lines(reviews, since, include_all=True)) == 4


def test_a_review_body_yields_its_additional_comment_findings() -> None:
    assert pr_threads.additional_diff(_ADDITIONAL_BODY) == [
        (
            ".agents/skills/running-unattended/pr-and-filing.md:39",
            "Major",
            "Bind the clean verdict to the dispatched review.",
        ),
        ("python/scripts/pr_threads.py:84-91", "Minor", "Keep the parser and the printer in step."),
    ]


def test_outside_and_additional_findings_print_from_one_review_body() -> None:
    reviews = [{"databaseId": 7, "submittedAt": None, "body": _REVIEW_BODY + _ADDITIONAL_BODY}]
    assert pr_threads.outside_lines(reviews, None, include_all=False) == [
        "tests/test_x.py:17 [Minor] Fix the import. | outside diff, review 7",
        "pair.py:84-91 [Major] Count the ?[2Jbytes. | outside diff, review 7",
        (
            ".agents/skills/running-unattended/pr-and-filing.md:39 [Major] "
            "Bind the clean verdict to the dispatched review. | additional comments, review 7"
        ),
        (
            "python/scripts/pr_threads.py:84-91 [Minor] Keep the parser and the printer in step. "
            "| additional comments, review 7"
        ),
    ]


def test_every_page_of_reviews_is_read_with_the_head_commit_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def page(n: int, cursor: str | None) -> dict[str, Any]:
        reviews = {
            "nodes": [{"databaseId": n, "submittedAt": None, "body": ""}],
            "pageInfo": {"hasNextPage": cursor is not None, "endCursor": cursor},
        }
        commits = {"nodes": [{"commit": {"committedDate": f"date{n}"}}]}
        return {"data": {"repository": {"pullRequest": {"commits": commits, "reviews": reviews}}}}

    pages = {None: page(1, "c1"), "c1": page(2, None)}

    def gh(*args: str) -> dict[str, Any]:
        after = next((a.removeprefix("after=") for a in args if a.startswith("after=")), None)
        return pages[after]

    monkeypatch.setattr(pr_threads, "_gh", gh)
    found = pr_threads.read_reviews("o", "r", 1)
    assert found is not None
    assert found[0] == "date1"
    assert [r["databaseId"] for r in found[1]] == [1, 2]


class _FakeGh:
    """Stands in for ``pr_threads._gh``: records each call and answers from the thread list."""

    def __init__(self, threads: list[dict[str, Any]], *, resolves: bool = True) -> None:
        """Answer from *threads*; the mutation reports *resolves* as the thread's state."""
        self.threads = threads
        self.resolves = resolves
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *args: str) -> dict[str, Any]:
        """Record *args* and give the answer gh would for that call."""
        self.calls.append(args)
        if args[:2] == ("api", "repos/{owner}/{repo}"):
            return {"full_name": "o/r"}
        if args[:3] == ("api", "-X", "POST"):
            return {"id": 999, "html_url": "https://example.test/r/pull/7#discussion_r999"}
        query = next(a for a in args if a.startswith("query="))
        if "resolveReviewThread" in query:
            return {"data": {"resolveReviewThread": {"thread": {"isResolved": self.resolves}}}}
        return _page(self.threads, None)


def _threads() -> list[dict[str, Any]]:
    """An open thread headed by comment 111 and a resolved one headed by comment 222."""
    first, second = _thread("Open."), _thread("Done.", resolved=True)
    first["id"], second["id"] = "PRRT_open", "PRRT_done"
    second["comments"]["nodes"][0]["databaseId"] = 222
    return [first, second]


def _is_mutation(call: tuple[str, ...]) -> bool:
    """Whether *call* sends the ``resolveReviewThread`` mutation."""
    return any("resolveReviewThread" in a for a in call)


def test_reply_posts_the_body_to_the_comments_replies_endpoint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--reply`` posts once, to the replies endpoint of the named comment."""
    gh = _FakeGh(_threads())
    monkeypatch.setattr(pr_threads, "_gh", gh)
    assert pr_threads.main(["7", "--reply", "111", "--body", "Fixed in abc123."]) == 0
    assert gh.calls[1:] == [
        (
            "api",
            "-X",
            "POST",
            "repos/o/r/pulls/7/comments/111/replies",
            "-f",
            "body=Fixed in abc123.",
        )
    ]
    assert "discussion_r999" in capsys.readouterr().out


def test_reply_reads_its_body_from_a_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``--body-file`` sends the file's text unchanged, newlines and all."""
    body = tmp_path / "reply.md"
    body.write_text("Line one.\n\nLine two.\n", encoding="utf-8")
    gh = _FakeGh(_threads())
    monkeypatch.setattr(pr_threads, "_gh", gh)
    assert pr_threads.main(["7", "--reply", "111", "--body-file", str(body)]) == 0
    assert gh.calls[1][-1] == "body=Line one.\n\nLine two.\n"


def test_a_missing_body_file_fails_before_posting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An unreadable ``--body-file`` exits 2 without posting anything."""
    gh = _FakeGh(_threads())
    monkeypatch.setattr(pr_threads, "_gh", gh)
    assert pr_threads.main(["7", "--reply", "111", "--body-file", str(tmp_path / "no")]) == 2
    assert len(gh.calls) == 1


def test_resolve_maps_the_comment_id_to_its_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """``--resolve`` sends the mutation for the thread the comment heads."""
    gh = _FakeGh(_threads())
    monkeypatch.setattr(pr_threads, "_gh", gh)
    assert pr_threads.main(["7", "--resolve", "111"]) == 0
    assert _is_mutation(gh.calls[-1])
    assert "thread=PRRT_open" in gh.calls[-1]


def test_reply_comes_before_resolve_when_both_are_given(monkeypatch: pytest.MonkeyPatch) -> None:
    """With both actions, the reply is posted before the thread is resolved."""
    gh = _FakeGh(_threads())
    monkeypatch.setattr(pr_threads, "_gh", gh)
    assert pr_threads.main(["7", "--reply", "111", "--body", "Done.", "--resolve", "111"]) == 0
    assert gh.calls[1][:3] == ("api", "-X", "POST")
    assert _is_mutation(gh.calls[-1])
    assert "thread=PRRT_open" in gh.calls[-1]


def test_an_already_resolved_thread_is_left_alone(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A thread that is already resolved gets no mutation, and the output says so."""
    gh = _FakeGh(_threads())
    monkeypatch.setattr(pr_threads, "_gh", gh)
    assert pr_threads.main(["7", "--resolve", "222"]) == 0
    assert not any(_is_mutation(call) for call in gh.calls)
    assert "already resolved" in capsys.readouterr().out


def test_resolving_a_comment_that_starts_no_thread_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A comment id that heads no thread exits 2 and names the id."""
    monkeypatch.setattr(pr_threads, "_gh", _FakeGh(_threads()))
    assert pr_threads.main(["7", "--resolve", "333"]) == 2
    assert "starts with comment 333" in capsys.readouterr().err


def test_a_comment_id_past_32_bits_round_trips_from_listing_to_resolve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An id above 2**31 comes from ``fullDatabaseId``, prints whole, and finds its thread."""
    threads = _threads()
    big = threads[0]["comments"]["nodes"][0]
    big["databaseId"], big["fullDatabaseId"] = None, "4488219292"
    assert "| id 4488219292," in pr_threads.thread_line(threads[0])
    gh = _FakeGh(threads)
    monkeypatch.setattr(pr_threads, "_gh", gh)
    assert pr_threads.main(["7", "--resolve", "4488219292"]) == 0
    assert "thread=PRRT_open" in gh.calls[-1]


def test_a_mutation_that_leaves_the_thread_open_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mutation whose answer shows the thread still open exits 2."""
    monkeypatch.setattr(pr_threads, "_gh", _FakeGh(_threads(), resolves=False))
    assert pr_threads.main(["7", "--resolve", "111"]) == 2


@pytest.mark.parametrize(
    "argv",
    [["7", "--reply", "111"], ["7", "--body", "orphan"], ["7", "--resolve", "1", "--body", "x"]],
)
def test_reply_and_its_body_go_together(argv: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """``--reply`` without a body, or a body without ``--reply``, is a usage error."""
    gh = _FakeGh(_threads())
    monkeypatch.setattr(pr_threads, "_gh", gh)
    with pytest.raises(SystemExit):
        pr_threads.main(argv)
    assert gh.calls == []


_REFUSED = "HTTP 403: GitHub GraphQL is not available from Claude Code sessions; use the REST API"


class _RestGh:
    """Stands in for ``pr_threads._gh`` behind the cloud proxy: GraphQL refused, REST answered.

    Pull 7 has one open thread of comments 111 and 112 and one resolved thread of comment 222.
    """

    def __init__(self, *, resolves: bool = True) -> None:
        """A resolve POST marks the open thread resolved when *resolves*."""
        self.resolves = resolves
        self.resolved = False
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *args: str, empty_ok: bool = False) -> Any:
        """Record *args* and give the answer gh would behind the proxy."""
        self.calls.append(args)
        path = args[-1] if args[:3] != ("api", "-X", "POST") else args[3]
        if args[1] == "graphql":
            raise pr_threads.GhError(_REFUSED)
        if path == "repos/{owner}/{repo}":
            return {"full_name": "o/r"}
        if path.startswith("repos/o/r/pulls/8"):
            raise pr_threads.GhError("Not Found (HTTP 404)")
        if path == "repos/o/r/pulls/7":
            return {"head": {"sha": "abc"}}
        if path == "repos/o/r/commits/abc":
            return {"commit": {"committer": {"date": "2026-11-09T00:00:00Z"}}}
        if path.startswith("repos/o/r/pulls/7/comments?"):
            return [
                {
                    "id": 111,
                    "user": {"login": "coderabbitai[bot]"},
                    "body": _BOT_BODY,
                    "original_line": 20,
                },
                {"id": 112, "user": {"login": "claude"}, "body": "Fixed."},
                {"id": 222, "user": {"login": "coderabbitai[bot]"}, "body": "Done."},
            ]
        if path.startswith("repos/o/r/pulls/7/reviews?"):
            return [{"id": 5, "submitted_at": "2026-11-09T01:00:00Z", "body": ""}]
        if path == "repos/o/r/pulls/7/ccr/review_threads":
            return [
                {
                    "resolved": self.resolved,
                    "outdated": True,
                    "path": "a.md",
                    "line": None,
                    "comment_ids": [111, 112],
                },
                {
                    "resolved": True,
                    "outdated": False,
                    "path": "b.md",
                    "line": 3,
                    "comment_ids": [222],
                },
            ]
        if path == "repos/o/r/pulls/7/ccr/comments/111/resolve":
            assert empty_ok, "the resolve route answers with an empty body"
            self.resolved = self.resolves
            return None
        raise AssertionError(f"unexpected gh call {args}")


def test_a_refused_graphql_lists_threads_through_rest(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Behind the cloud proxy the listing comes from the ccr route and the comments list."""
    monkeypatch.setattr(pr_threads, "_gh", _RestGh())
    assert pr_threads.main(["7"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out == [
        "1 open review threads on o/r#7",
        (
            "a.md:20 [Major] Compare `all_sha256` before parity scoring. (outdated) | id 111, "
            "1 replies, last by claude"
        ),
    ]


def test_a_refused_graphql_resolves_through_the_ccr_route(monkeypatch: pytest.MonkeyPatch) -> None:
    """``--resolve`` posts to the proxy's resolve route and checks the thread then reads resolved."""
    gh = _RestGh()
    monkeypatch.setattr(pr_threads, "_gh", gh)
    assert pr_threads.main(["7", "--resolve", "111"]) == 0
    assert ("api", "-X", "POST", "repos/o/r/pulls/7/ccr/comments/111/resolve") in gh.calls
    assert pr_threads.main(["7", "--resolve", "222"]) == 0
    assert gh.calls.count(("api", "-X", "POST", "repos/o/r/pulls/7/ccr/comments/222/resolve")) == 0


def test_a_rest_resolve_that_leaves_the_thread_open_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """A resolve POST after which the thread still reads unresolved exits 2."""
    monkeypatch.setattr(pr_threads, "_gh", _RestGh(resolves=False))
    assert pr_threads.main(["7", "--resolve", "111"]) == 2


def test_a_missing_pull_through_rest_is_reported(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A 404 on the pull request reads as no such pull request, not a gh failure."""
    monkeypatch.setattr(pr_threads, "_gh", _RestGh())
    assert pr_threads.main(["8"]) == 2
    assert "has no pull request 8" in capsys.readouterr().err


def test_rest_reviews_carry_the_head_commit_date(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reviews through REST keep the GraphQL shape the outside-diff filter reads."""
    monkeypatch.setattr(pr_threads, "_gh", _RestGh())
    assert pr_threads.read_reviews("o", "r", 7) == (
        "2026-11-09T00:00:00Z",
        [{"databaseId": 5, "submittedAt": "2026-11-09T01:00:00Z", "body": ""}],
    )


def test_a_rest_list_reads_pages_by_number_until_a_short_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A full page asks for the next by number, never through ``--paginate``."""
    calls: list[tuple[str, ...]] = []

    def gh(*args: str) -> list[dict[str, int]]:
        calls.append(args)
        page = int(args[-1].rsplit("=", 1)[1])
        return [{"id": i} for i in range(pr_threads.REST_PAGE if page == 1 else 1)]

    monkeypatch.setattr(pr_threads, "_gh", gh)
    assert len(pr_threads._rest_list("repos/o/r/pulls/7/comments")) == pr_threads.REST_PAGE + 1
    assert [c[-1].rsplit("&", 1)[1] for c in calls] == ["page=1", "page=2"]
    assert all("--paginate" not in c for c in calls)


def test_another_gh_error_is_not_taken_for_a_refused_graphql(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the proxy's refusal switches to REST; any other GraphQL failure is reported."""

    def gh(*_args: str) -> Any:
        raise pr_threads.GhError("HTTP 502: Bad Gateway")

    monkeypatch.setattr(pr_threads, "_gh", gh)
    with pytest.raises(pr_threads.GhError, match="502"):
        pr_threads.read_threads("o", "r", 7)


def test_empty_stdout_is_a_gh_error_unless_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only a caller that expects no body gets ``None``; any other empty answer is a GhError."""

    def run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess([], 0, stdout="", stderr="")

    monkeypatch.setattr(shutil, "which", lambda _name: "gh")
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(pr_threads.GhError, match="no JSON"):
        pr_threads._gh("api", "graphql")
    assert pr_threads._gh("api", "-X", "POST", "x", empty_ok=True) is None
