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
        if args[:2] == ("repo", "view"):
            return {"nameWithOwner": "o/r"}
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
