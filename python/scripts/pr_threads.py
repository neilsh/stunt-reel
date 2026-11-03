#!/usr/bin/env python3
"""Print a pull request's open review threads, one line each.

``gh pr view --comments`` and the REST comments endpoint return every comment whole, and a
bot review (CodeRabbit) wraps each finding in HTML comments, ``<details>`` blocks of analysis
scripts and agent prompts: one PR's comments ran past 60 KB. This reads the review threads
through GitHub's GraphQL API, keeps the unresolved ones, and prints for each its location, its
severity when the bot names one, its title, and the database id of its first comment, which is
the id ``gh api repos/{owner}/{repo}/pulls/<n>/comments/<id>/replies`` answers.

Usage: ``mise run pr-threads -- <number> [--all]``. ``--all`` keeps resolved threads, marked
``resolved``. Exit status: ``0`` on success, ``2`` when ``gh`` fails.
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
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100) {
        pageInfo { hasNextPage }
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


def main(argv: Sequence[str] | None = None) -> int:
    """Print the open review threads of the pull request named on the command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("number", type=int, help="pull request number")
    parser.add_argument("--all", action="store_true", help="include resolved threads")
    args = parser.parse_args(argv)
    try:
        repo = _gh("repo", "view", "--json", "nameWithOwner")["nameWithOwner"]
        owner, name = repo.split("/", 1)
        data = _gh(
            "api",
            "graphql",
            "-f",
            f"query={QUERY}",
            "-F",
            f"owner={owner}",
            "-F",
            f"name={name}",
            "-F",
            f"number={args.number}",
        )
    except GhError as err:
        print(f"pr-threads: {err}", file=sys.stderr)
        return 2
    pull = data["data"]["repository"]["pullRequest"]
    if pull is None:
        print(f"pr-threads: {repo} has no pull request {args.number}", file=sys.stderr)
        return 2
    threads = pull["reviewThreads"]
    lines = thread_lines(threads["nodes"], include_resolved=args.all)
    print(f"{len(lines)} {'review' if args.all else 'open review'} threads on {repo}#{args.number}")
    for line in lines:
        print(line)
    if threads["pageInfo"]["hasNextPage"]:
        print("(more than 100 threads; only the first 100 were read)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
