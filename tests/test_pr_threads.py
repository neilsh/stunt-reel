"""`pr_threads` reduces review threads to one line each; the cases are synthetic, nothing calls gh."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

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
        "comments": {"totalCount": len(comments), "nodes": comments},
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
        "crates/stunt-parity/src/film.rs:22 [Major] Compare `all_sha256` before parity scoring.\n"
        "    id 111, 2 replies, last by neilsh"
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
