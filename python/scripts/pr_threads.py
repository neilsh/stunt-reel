#!/usr/bin/env python3
"""Print a pull request's open review threads and outside-diff findings, one line each.

``gh pr view --comments`` and the REST comments endpoint return every comment whole, and a
bot review (CodeRabbit) wraps each finding in HTML comments, ``<details>`` blocks of analysis
scripts and agent prompts: one PR's comments ran past 60 KB. This reads the review threads
through GitHub's GraphQL API, keeps the unresolved ones, and prints for each its location, its
severity when the bot names one, its title, and the database id of its first comment, which is
the id ``gh api repos/{owner}/{repo}/pulls/<n>/comments/<id>/replies`` answers.

A finding CodeRabbit cannot anchor to a changed line ("Outside diff range") lives only in its
review's body and has no thread to resolve, so it is answered with a PR comment. Those print
after the threads, from every review submitted since the head commit; the commit date stands in
for "not yet answered by a push".

Usage: ``mise run pr-threads -- <number> [--all]``. ``--all`` keeps resolved threads, marked
``resolved``, and outside-diff findings from every review. Every page of threads and reviews
is read. Exit status: ``0`` on success, ``2`` when ``gh`` fails or the query returns errors.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

QUERY = """
query($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          isResolved
          isOutdated
          path
          line
          originalLine
          comments(first: 1) {
            totalCount
            nodes { databaseId author { login } body }
          }
          latest: comments(last: 1) { nodes { author { login } } }
        }
      }
    }
  }
}
"""

REVIEWS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      commits(last: 1) { nodes { commit { committedDate } } }
      reviews(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes { databaseId submittedAt body }
      }
    }
  }
}
"""

#: Severity words CodeRabbit sets in bold at the top of a finding.
SEVERITIES = ("Critical", "Major", "Minor", "Trivial", "Nitpick")
TITLE_LIMIT = 160
#: Seconds either gh call may take before the task gives up.
GH_TIMEOUT = 60

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_DETAILS = re.compile(r"<details>.*?</details>", re.DOTALL | re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
#: C0 and C1 control characters: a comment or path holding an escape sequence could drive the
#: terminal it is printed to.
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_SEVERITY = re.compile(r"\*\*\s*(" + "|".join(SEVERITIES) + r")\s*\*\*")
#: A line that is one bold span: ``**...**`` with no ``**`` inside.
_BOLD_LINE = re.compile(r"^\*\*((?:(?!\*\*).)+)\*\*$")
#: The heading of the blockquote that holds a review's outside-diff findings.
_OUTSIDE = re.compile(r"Outside diff range comments \(\d+\)")
#: One outside-diff finding's summary line: severity, title and ``path:line``, split by ``·``.
_OUTSIDE_FINDING = re.compile(
    r"<summary><strong>.*?\b(" + "|".join(SEVERITIES) + r")</strong>\s*·\s*(.+?)\s*·\s*"
    r"<code>([^<]+)</code></summary>"
)


class GhError(Exception):
    """A ``gh`` command failed or printed something other than the expected JSON."""


def summarize(body: str) -> tuple[str | None, str]:
    """A comment's severity, when it names one, and its title line, without markup."""
    text = _TAG.sub("", _DETAILS.sub("", _HTML_COMMENT.sub("", body)))
    match = _SEVERITY.search(text)
    severity = match.group(1) if match else None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    title = next(
        (m.group(1) for m in map(_BOLD_LINE.match, lines) if m and m.group(1) not in SEVERITIES),
        None,
    )
    if title is None:
        # The severity line is the only bold line, or there is none: take the first prose line.
        title = next((line for line in lines if not _SEVERITY.search(line)), "")
    if len(title) > TITLE_LIMIT:
        title = title[: TITLE_LIMIT - 1] + "…"
    return severity, title


def _printable(text: str) -> str:
    """*text* with every control character replaced by ``?``."""
    return _CONTROL.sub("?", text)


def thread_line(thread: dict[str, Any]) -> str:
    """One thread as ``path:line [severity] title | id N, R replies, last by L``."""
    first = thread["comments"]["nodes"][0]
    severity, title = summarize(first["body"])
    title = _printable(title)
    line = thread["line"] if thread["line"] is not None else thread["originalLine"]
    where = f"{_printable(thread['path'])}:{line if line is not None else '?'}"
    marks = [
        m
        for m in (
            "resolved" if thread["isResolved"] else None,
            "outdated" if thread["isOutdated"] else None,
        )
        if m
    ]
    tag = f" [{severity}]" if severity else ""
    flags = f" ({', '.join(marks)})" if marks else ""
    replies = thread["comments"]["totalCount"] - 1
    latest = thread["latest"]["nodes"]
    last = ((latest[0]["author"] if latest else None) or {}).get("login", "?")
    return (
        f"{where}{tag} {title}{flags} | id {first['databaseId']}, {replies} replies, last by {last}"
    )


def thread_lines(threads: Iterable[dict[str, Any]], *, include_resolved: bool) -> list[str]:
    """The lines for *threads*, skipping resolved ones unless *include_resolved*."""
    return [
        thread_line(t)
        for t in threads
        if t["comments"]["nodes"] and (include_resolved or not t["isResolved"])
    ]


def outside_diff(body: str) -> list[tuple[str, str, str]]:
    """A review body's outside-diff findings as ``(where, severity, title)``."""
    heading = _OUTSIDE.search(body)
    if heading is None:
        return []
    block: list[str] = []
    for line in body[heading.end() :].splitlines()[1:]:
        if not line.startswith(">"):
            break
        block.append(line)
    return [
        (_printable(m.group(3)), m.group(1), _printable(_TAG.sub("", m.group(2))))
        for m in _OUTSIDE_FINDING.finditer("\n".join(block))
    ]


def outside_lines(
    reviews: Iterable[dict[str, Any]], since: str | None, *, include_all: bool
) -> list[str]:
    """One line per outside-diff finding of each review submitted after *since*.

    *since* is an ISO 8601 UTC timestamp, so string order is time order; with *include_all*,
    or when it is ``None``, every review counts.
    """
    return [
        f"{where} [{severity}] {title} | outside diff, review {review['databaseId']}"
        for review in reviews
        if include_all or since is None or (review["submittedAt"] or "") > since
        for where, severity, title in outside_diff(review["body"] or "")
    ]


def _gh(*args: str) -> Any:
    gh = shutil.which("gh")
    if gh is None:
        raise GhError("gh is not on PATH")
    try:
        result = subprocess.run(  # noqa: S603 - gh with fixed arguments
            [gh, *args], capture_output=True, text=True, check=False, timeout=GH_TIMEOUT
        )
    except subprocess.TimeoutExpired as err:
        raise GhError(f"gh {args[0]} gave no answer in {GH_TIMEOUT} s") from err
    if result.returncode != 0:
        raise GhError(result.stderr.strip() or f"gh {args[0]} exited {result.returncode}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as err:
        raise GhError(f"gh {args[0]} printed no JSON") from err


def read_threads(owner: str, name: str, number: int) -> list[dict[str, Any]] | None:
    """Every review thread of pull request *number*, page by page; ``None`` when it is absent."""
    found = _read_pages(QUERY, "reviewThreads", owner, name, number)
    return None if found is None else found[1]


def read_reviews(
    owner: str, name: str, number: int
) -> tuple[str | None, list[dict[str, Any]]] | None:
    """The head commit's date and every review of pull request *number*; ``None`` if absent."""
    found = _read_pages(REVIEWS_QUERY, "reviews", owner, name, number)
    if found is None:
        return None
    commits = found[0]["commits"]["nodes"]
    return (commits[0]["commit"]["committedDate"] if commits else None), found[1]


def _read_pages(
    query: str, connection: str, owner: str, name: str, number: int
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """The pull request's first page and every node of its *connection*, page by page."""
    nodes: list[dict[str, Any]] = []
    first: dict[str, Any] | None = None
    after: str | None = None
    while True:
        args = ["api", "graphql", "-f", f"query={query}", "-F", f"owner={owner}"]
        args += ["-F", f"name={name}", "-F", f"number={number}"]
        if after is not None:
            args += ["-f", f"after={after}"]
        data = _gh(*args)
        if data.get("errors"):
            messages = "; ".join(str(e.get("message", e)) for e in data["errors"])
            raise GhError(f"graphql: {messages}")
        pull = data["data"]["repository"]["pullRequest"]
        if pull is None:
            return None
        first = first or pull
        page = pull[connection]
        nodes += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            return first, nodes
        after = page["pageInfo"]["endCursor"]


def main(argv: Sequence[str] | None = None) -> int:
    """Print the open review threads of the pull request named on the command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("number", type=int, help="pull request number")
    parser.add_argument(
        "--all",
        action="store_true",
        help="include resolved threads and outside-diff findings from every review",
    )
    args = parser.parse_args(argv)
    try:
        repo = _gh("repo", "view", "--json", "nameWithOwner")["nameWithOwner"]
        owner, name = repo.split("/", 1)
        nodes = read_threads(owner, name, args.number)
        reviews = read_reviews(owner, name, args.number) if nodes is not None else None
    except GhError as err:
        print(f"pr-threads: {err}", file=sys.stderr)
        return 2
    if nodes is None or reviews is None:
        print(f"pr-threads: {repo} has no pull request {args.number}", file=sys.stderr)
        return 2
    lines = thread_lines(nodes, include_resolved=args.all)
    print(f"{len(lines)} {'review' if args.all else 'open review'} threads on {repo}#{args.number}")
    for line in lines:
        print(line)
    outside = outside_lines(reviews[1], reviews[0], include_all=args.all)
    if outside:
        scope = "every review" if args.all else "reviews since the head commit"
        print(f"{len(outside)} outside-diff findings from {scope} (answer with gh pr comment)")
        for line in outside:
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
