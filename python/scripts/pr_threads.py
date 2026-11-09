#!/usr/bin/env python3
"""Print a pull request's open review threads and outside-diff findings, one line each.

``gh pr view --comments`` and the REST comments endpoint return every comment whole, and a
bot review (CodeRabbit) wraps each finding in HTML comments, ``<details>`` blocks of analysis
scripts and agent prompts: one PR's comments ran past 60 KB. This reads the review threads
through GitHub's GraphQL API, keeps the unresolved ones, and prints for each its location, its
severity when the bot names one, its title, and the database id of its first comment, which is
the id ``--reply`` and ``--resolve`` take. GitHub's REST API neither lists threads nor
resolves one. A cloud session's proxy refuses GraphQL but offers REST routes that do
(``/pulls/{n}/ccr/review_threads`` and ``.../ccr/comments/{id}/resolve``;
``docs/cloud-sessions.md``), so when GraphQL is refused this reads and resolves threads through
them instead, with each thread's comments from the REST comments list.

A finding CodeRabbit cannot anchor to a changed line ("Outside diff range") lives only in its
review's body and has no thread to resolve, so it is answered with a PR comment. Those print
after the threads, from every review submitted since the head commit; the commit date stands in
for "not yet answered by a push".

Usage: ``mise run pr-threads -- <number> [--all]``. ``--all`` keeps resolved threads, marked
``resolved``, and outside-diff findings from every review. Every page of threads and reviews
is read.

To answer a thread: ``mise run pr-threads -- <number> --reply <id> --body <text>`` (or
``--body-file <path>``, ``-`` for stdin) posts a reply in the thread whose first comment has
database id *id*, and ``--resolve <id>`` resolves that thread. Given together, the reply is
posted first. Either one replaces the listing.

Exit status: ``0`` on success, ``2`` when ``gh`` fails, the query returns errors, or no thread
starts with the comment ``--resolve`` names.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
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
          id
          isResolved
          isOutdated
          path
          line
          originalLine
          comments(first: 1) {
            totalCount
            nodes { databaseId fullDatabaseId author { login } body }
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

RESOLVE_MUTATION = """
mutation($thread: ID!) {
  resolveReviewThread(input: {threadId: $thread}) { thread { isResolved } }
}
"""

#: Severity words CodeRabbit sets in bold at the top of a finding.
SEVERITIES = ("Critical", "Major", "Minor", "Trivial", "Nitpick")
TITLE_LIMIT = 160
#: Seconds either gh call may take before the task gives up.
GH_TIMEOUT = 60
#: What the cloud proxy's 403 says when it refuses a GraphQL request.
GRAPHQL_REFUSED = "GraphQL is not available"
#: Items per page of a REST list; a shorter page is the last.
REST_PAGE = 100

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
    return f"{where}{tag} {title}{flags} | id {comment_db_id(first)}, {replies} replies, last by {last}"


def comment_db_id(comment: dict[str, Any]) -> int | None:
    """A comment's REST id: ``fullDatabaseId``, else the 32-bit ``databaseId``.

    Review comment ids have passed 2**31, past GraphQL's ``Int``, so ``databaseId`` can be null
    or wrong; ``fullDatabaseId`` is a ``BigInt`` sent as a string.
    """
    full = comment.get("fullDatabaseId")
    if full is not None:
        return int(full)
    short = comment.get("databaseId")
    return None if short is None else int(short)


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
    if not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as err:
        raise GhError(f"gh {args[0]} printed no JSON") from err


def read_threads(owner: str, name: str, number: int) -> list[dict[str, Any]] | None:
    """Every review thread of pull request *number*, page by page; ``None`` when it is absent.

    Through REST (:func:`rest_threads`) when GraphQL is refused.
    """
    try:
        found = _read_pages(QUERY, "reviewThreads", owner, name, number)
    except GhError as err:
        if GRAPHQL_REFUSED not in str(err):
            raise
        return rest_threads(owner, name, number)
    return None if found is None else found[1]


def read_reviews(
    owner: str, name: str, number: int
) -> tuple[str | None, list[dict[str, Any]]] | None:
    """The head commit's date and every review of pull request *number*; ``None`` if absent.

    Through REST (:func:`rest_reviews`) when GraphQL is refused.
    """
    try:
        found = _read_pages(REVIEWS_QUERY, "reviews", owner, name, number)
    except GhError as err:
        if GRAPHQL_REFUSED not in str(err):
            raise
        return rest_reviews(owner, name, number)
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
        pull = _graphql_data(_gh(*args))["repository"]["pullRequest"]
        if pull is None:
            return None
        first = first or pull
        page = pull[connection]
        nodes += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            return first, nodes
        after = page["pageInfo"]["endCursor"]


def _rest_list(path: str) -> list[dict[str, Any]]:
    """Every item of the REST list at *path*, page by page by number.

    Not ``gh api --paginate``: it follows GitHub's next links, which name the repository by id
    (``repositories/<id>/...``), and the cloud proxy refuses those.
    """
    items: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = _gh("api", f"{path}?per_page={REST_PAGE}&page={page}") or []
        items += batch
        if len(batch) < REST_PAGE:
            return items
        page += 1


def _rest_pull(owner: str, name: str, number: int) -> dict[str, Any] | None:
    """The REST pull request *number*, or ``None`` when GitHub answers 404."""
    try:
        pull: dict[str, Any] = _gh("api", f"repos/{owner}/{name}/pulls/{number}")
    except GhError as err:
        if "HTTP 404" in str(err):
            return None
        raise
    return pull


def rest_threads(owner: str, name: str, number: int) -> list[dict[str, Any]] | None:
    """Every review thread of pull request *number*, through REST, in the GraphQL query's shape.

    The ``ccr/review_threads`` route gives each thread's state, place and comment ids, oldest
    first; the comments list gives each comment's author and body. A thread carries no GraphQL
    ``id`` here, since :func:`resolve` goes by comment id. ``None`` when the pull is absent.
    """
    if _rest_pull(owner, name, number) is None:
        return None
    base = f"repos/{owner}/{name}/pulls/{number}"
    comments = {c["id"]: c for c in _rest_list(f"{base}/comments")}
    threads: list[dict[str, Any]] = []
    for raw in _gh("api", f"{base}/ccr/review_threads") or []:
        ids = raw["comment_ids"]
        first = comments.get(ids[0]) if ids else None
        last = comments.get(ids[-1]) if ids else None
        nodes = (
            [
                {
                    "fullDatabaseId": str(first["id"]),
                    "author": {"login": (first.get("user") or {}).get("login", "?")},
                    "body": first.get("body") or "",
                }
            ]
            if first
            else []
        )
        threads.append(
            {
                "id": None,
                "isResolved": raw["resolved"],
                "isOutdated": raw["outdated"],
                "path": raw["path"],
                "line": raw["line"],
                "originalLine": first.get("original_line") if first else None,
                "comments": {"totalCount": len(ids), "nodes": nodes},
                "latest": {"nodes": [{"author": last.get("user")}] if last else []},
            }
        )
    return threads


def rest_reviews(
    owner: str, name: str, number: int
) -> tuple[str | None, list[dict[str, Any]]] | None:
    """:func:`read_reviews` through REST: the head commit's committer date and every review."""
    pull = _rest_pull(owner, name, number)
    if pull is None:
        return None
    commit = _gh("api", f"repos/{owner}/{name}/commits/{pull['head']['sha']}")
    reviews = [
        {"databaseId": r["id"], "submittedAt": r.get("submitted_at"), "body": r.get("body")}
        for r in _rest_list(f"repos/{owner}/{name}/pulls/{number}/reviews")
    ]
    return commit["commit"]["committer"]["date"], reviews


def _graphql_data(answer: dict[str, Any]) -> dict[str, Any]:
    """The ``data`` of a GraphQL *answer*; a :class:`GhError` when it carries errors."""
    if answer.get("errors"):
        messages = "; ".join(str(e.get("message", e)) for e in answer["errors"])
        raise GhError(f"graphql: {messages}")
    data: dict[str, Any] = answer["data"]
    return data


def reply(owner: str, name: str, number: int, comment_id: int, body: str) -> str:
    """Post *body* as a reply in the thread of review comment *comment_id*; the reply's URL."""
    answer = _gh(
        "api",
        "-X",
        "POST",
        f"repos/{owner}/{name}/pulls/{number}/comments/{comment_id}/replies",
        "-f",
        f"body={body}",
    )
    return str(answer.get("html_url") or f"comment {answer.get('id', '?')}")


def thread_of(threads: Iterable[dict[str, Any]], comment_id: int) -> dict[str, Any] | None:
    """The thread whose first comment has database id *comment_id*, or ``None``."""
    return next(
        (
            t
            for t in threads
            if t["comments"]["nodes"] and comment_db_id(t["comments"]["nodes"][0]) == comment_id
        ),
        None,
    )


def resolve(owner: str, name: str, number: int, comment_id: int) -> bool | None:
    """Resolve the thread comment *comment_id* starts.

    ``True`` when this call resolved it, ``False`` when it already was, ``None`` when no thread
    of the pull request starts with that comment or the pull request is absent.
    """
    thread = thread_of(read_threads(owner, name, number) or [], comment_id)
    if thread is None:
        return None
    if thread["isResolved"]:
        return False
    if thread["id"] is None:  # read through REST: resolve through the proxy's route too
        _gh(
            "api",
            "-X",
            "POST",
            f"repos/{owner}/{name}/pulls/{number}/ccr/comments/{comment_id}/resolve",
        )
        after = thread_of(rest_threads(owner, name, number) or [], comment_id)
        if after is None or not after["isResolved"]:
            raise GhError(f"the thread of comment {comment_id} is still unresolved")
        return True
    data = _graphql_data(
        _gh("api", "graphql", "-f", f"query={RESOLVE_MUTATION}", "-f", f"thread={thread['id']}")
    )
    if not data["resolveReviewThread"]["thread"]["isResolved"]:
        raise GhError(f"the thread of comment {comment_id} is still unresolved")
    return True


def _reply_body(args: argparse.Namespace) -> str:
    """The reply text from ``--body`` or ``--body-file`` (``-`` reads stdin)."""
    if args.body is not None:
        return str(args.body)
    if args.body_file == "-":
        return sys.stdin.read()
    return Path(args.body_file).read_text(encoding="utf-8")


def _answer(args: argparse.Namespace, owner: str, name: str) -> int:
    """Post ``--reply``, then apply ``--resolve``; the exit status."""
    if args.reply is not None:
        url = reply(owner, name, args.number, args.reply, _reply_body(args))
        print(f"replied to comment {args.reply}: {url}")
    if args.resolve is not None:
        done = resolve(owner, name, args.number, args.resolve)
        if done is None:
            where = f"{owner}/{name}#{args.number}"
            print(
                f"pr-threads: no thread on {where} starts with comment {args.resolve}",
                file=sys.stderr,
            )
            return 2
        print(f"thread of comment {args.resolve} {'resolved' if done else 'was already resolved'}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """List, answer or resolve the review threads of the pull request on the command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("number", type=int, help="pull request number")
    parser.add_argument(
        "--all",
        action="store_true",
        help="include resolved threads and outside-diff findings from every review",
    )
    parser.add_argument(
        "--reply", type=int, metavar="COMMENT_ID", help="reply in the thread this comment starts"
    )
    text = parser.add_mutually_exclusive_group()
    text.add_argument("--body", help="the reply text")
    text.add_argument(
        "--body-file", metavar="PATH", help="read the reply text from PATH (- for stdin)"
    )
    parser.add_argument(
        "--resolve", type=int, metavar="COMMENT_ID", help="resolve the thread this comment starts"
    )
    args = parser.parse_args(argv)
    if (args.reply is None) != (args.body is None and args.body_file is None):
        parser.error("--reply and --body (or --body-file) go together")
    try:
        # REST, not `gh repo view`, which goes through GraphQL.
        repo = _gh("api", "repos/{owner}/{repo}")["full_name"]
        owner, name = repo.split("/", 1)
        if args.reply is not None or args.resolve is not None:
            return _answer(args, owner, name)
        nodes = read_threads(owner, name, args.number)
        reviews = read_reviews(owner, name, args.number) if nodes is not None else None
    except (GhError, OSError) as err:
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
