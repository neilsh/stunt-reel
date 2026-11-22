#!/usr/bin/env python3
"""Report whether a pull request meets the unattended merge bar, one line per condition.

Checks what a script can read: the head commit and base, CI at the head, the dispatched
review's ``clean`` comment at the head, a ``Fixes``/``Closes``/``Part of`` line in the body, the
body's attribution line (a note, never a failure), open review threads, review-body findings,
and draft state. It never arms, merges, comments or edits. What it cannot read stays with the
coordinator: that ``mise run check`` passed locally on the head, that a CodeRabbit review a
person requested has been checked, the worker's acceptance report, and the ``env:local-only`` and
human-path rules (``.agents/skills/running-unattended/pr-and-filing.md`` step 5). It does not
run ``pr_lint``'s pin and date checks: they read a working tree, and the coordinator never
checks out the branch, so they are pre-push only, in the implementer's checkout.

Locally it reads the pull request through ``gh pr view`` (GraphQL); in a cloud session
(``CLAUDE_CODE_REMOTE=true``), whose proxy refuses GraphQL, through REST. Threads and
review-body findings come from ``pr_threads.py``.

Usage: ``mise run merge-bar -- <number> [--issue N]``; with ``--issue`` the body must link
that issue, not just any. Exit status: ``0`` for ``PASS``, ``1`` for
``FAIL``, ``2`` when ``gh`` fails or the pull request is absent.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pr_lint
import pr_threads

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

#: The only base a pull request may be armed on: a stacked PR's base has no ruleset.
BASE = "main"
#: ``author_association`` values whose comments count as the review's verdict.
TRUSTED = ("OWNER", "MEMBER", "COLLABORATOR")
#: Check-run conclusions and status states that fail a check; anything else finished is fine.
FAILED = frozenset({"FAILURE", "TIMED_OUT", "CANCELLED", "STARTUP_FAILURE", "ACTION_REQUIRED"})
FAILED_STATES = frozenset({"FAILURE", "ERROR"})
#: Status-context states that are not yet decided.
PENDING_STATES = frozenset({"PENDING", "EXPECTED"})
#: A review comment's first line: ``<reviewer> review at <sha>: <verdict>``.
_REVIEW_LINE = re.compile(r"^[^:]+ review at ([0-9a-f]+): (.*)$")
#: A body's closing keyword and issue number.
_LINKED = re.compile(r"(?:Fixes|Closes|Part of) #(\d+)(?!\d)")
#: Items per page of a REST list; a shorter page is the last.
REST_PAGE = 100


@dataclass
class Pull:
    """The parts of a pull request the bar reads, the same from GraphQL and from REST."""

    head: str
    base: str
    draft: bool
    state: str
    body: str
    #: ``(author association, body)`` of each issue comment, oldest first.
    comments: list[tuple[str, str]] = field(default_factory=list)
    #: ``(name, "failed" | "pending" | "ok")`` of each check at the head.
    checks: list[tuple[str, str]] = field(default_factory=list)


def _check_state(status: str, conclusion: str) -> str:
    """A check run's ``failed``, ``pending`` or ``ok``, from its status and conclusion."""
    if status.upper() != "COMPLETED":
        return "pending"
    return "failed" if conclusion.upper() in FAILED else "ok"


def _context_state(state: str) -> str:
    """A commit status's ``failed``, ``pending`` or ``ok``."""
    if state.upper() in FAILED_STATES:
        return "failed"
    return "pending" if state.upper() in PENDING_STATES else "ok"


def _newest_runs(runs: Sequence[tuple[str, str, tuple[str, int]]]) -> list[tuple[str, str]]:
    """``(name, state)`` of the newest run of each check name, in order of first appearance.

    A concurrency group cancels a superseded run, so a name often has a ``CANCELLED`` run
    followed by its passing rerun; only the newest counts, as in ``gh pr checks``. Each run
    carries ``(name, state, (start time, id))``, and the larger key is newer.
    """
    newest: dict[str, tuple[str, tuple[str, int]]] = {}
    for name, state, key in runs:
        if name not in newest or key > newest[name][1]:
            newest[name] = (state, key)
    return [(name, state) for name, (state, _) in newest.items()]


def graphql_pull(number: int) -> Pull | None:
    """Pull request *number* through ``gh pr view``; ``None`` when it does not exist."""
    fields = "headRefOid,baseRefName,isDraft,state,body,comments,statusCheckRollup"
    try:
        raw = pr_threads._gh("pr", "view", str(number), "--json", fields)
    except pr_threads.GhError as err:
        if "Could not resolve to a PullRequest" in str(err):
            return None
        raise
    checks = _newest_runs(
        [
            (
                str(c.get("name") or c.get("context") or "?"),
                _context_state(c.get("state") or "")
                if c.get("__typename") == "StatusContext"
                else _check_state(c.get("status") or "", c.get("conclusion") or ""),
                (c.get("startedAt") or "", index),
            )
            for index, c in enumerate(raw["statusCheckRollup"] or [])
        ]
    )
    return Pull(
        head=raw["headRefOid"],
        base=raw["baseRefName"],
        draft=raw["isDraft"],
        state=raw["state"],
        body=raw["body"] or "",
        comments=[(c["authorAssociation"], c["body"]) for c in raw["comments"]],
        checks=checks,
    )


def _rest_pages(path: str, key: str | None = None) -> list[dict[str, Any]]:
    """Every item of the REST list at *path*, page by page by number.

    *key* names the list inside an object answer (``check_runs``); without it the answer is
    the list.
    """
    items: list[dict[str, Any]] = []
    page = 1
    while True:
        answer = pr_threads._gh("api", f"{path}?per_page={REST_PAGE}&page={page}")
        batch = (answer[key] if key else answer) or []
        items += batch
        if len(batch) < REST_PAGE:
            return items
        page += 1


def rest_pull(owner: str, name: str, number: int) -> Pull | None:
    """Pull request *number* through REST, for a cloud session; ``None`` on a 404."""
    repo = f"repos/{owner}/{name}"
    try:
        raw = pr_threads._gh("api", f"{repo}/pulls/{number}")
    except pr_threads.GhError as err:
        if "HTTP 404" in str(err):
            return None
        raise
    head = raw["head"]["sha"]
    runs = [
        (
            r["name"],
            _check_state(r.get("status") or "", r.get("conclusion") or ""),
            (r.get("started_at") or "", int(r.get("id") or 0)),
        )
        for r in _rest_pages(f"{repo}/commits/{head}/check-runs", "check_runs")
    ]
    runs += [
        (
            c["context"],
            _context_state(c["state"]),
            (c.get("updated_at") or "", int(c.get("id") or 0)),
        )
        for c in _rest_pages(f"{repo}/commits/{head}/status", "statuses")
    ]
    checks = _newest_runs(runs)
    return Pull(
        head=head,
        base=raw["base"]["ref"],
        draft=bool(raw.get("draft")),
        state="MERGED" if raw.get("merged") else str(raw["state"]).upper(),
        body=raw.get("body") or "",
        comments=[
            (c["author_association"], c["body"])
            for c in _rest_pages(f"{repo}/issues/{number}/comments")
        ],
        checks=checks,
    )


def review_verdict(pull: Pull) -> tuple[str, str] | None:
    """The review comment's ``(sha, verdict)``, or ``None`` when no trusted comment is one.

    Among trusted comments whose first line names the head's SHA it is the newest, as in the
    step 5 command this replaces, whatever later comments say of older SHAs. With none at the
    head it is the newest at any other SHA, so the caller can say the review is stale.
    """
    head = pull.head[:7]
    newest: tuple[str, str] | None = None
    at_head: tuple[str, str] | None = None
    for association, body in pull.comments:
        if association not in TRUSTED:
            continue
        line = body.split("\n", 1)[0].rstrip("\r")
        match = _REVIEW_LINE.match(line)
        if match:
            newest = (match.group(1), match.group(2))
            if match.group(1) == head:
                at_head = newest
    return at_head or newest


def _list(names: Sequence[str]) -> str:
    return ", ".join(names)


def evaluate(
    pull: Pull,
    *,
    threads: Sequence[str],
    findings: Sequence[str],
    issue: int | None = None,
    attribution: Sequence[str] = (),
) -> tuple[list[str], list[str]]:
    """The report lines and the failure reasons for *pull*.

    *threads* and *findings* are ``pr_threads``' lines for the open review threads and the
    review-body findings since the head commit. With *issue*, the body must link that issue.
    *attribution* is ``pr_lint.attribution_failures``' lines, listed as a note, never a failure.
    """
    head = pull.head[:7]
    lines: list[str] = []
    reasons: list[str] = []

    def record(ok: bool, label: str, detail: str, reason: str) -> None:
        lines.append(f"{'ok  ' if ok else 'FAIL'} {label}: {detail}")
        if not ok:
            reasons.append(reason)

    record(
        pull.base == BASE,
        "head and base",
        f"{head} on base {pull.base}" + ("" if pull.base == BASE else f" (not {BASE})"),
        f"base is {pull.base}, not {BASE}",
    )
    record(
        pull.state != "CLOSED",
        "state",
        pull.state.lower(),
        "the PR is closed unmerged",
    )

    failed = [n for n, s in pull.checks if s == "failed"]
    pending = [n for n, s in pull.checks if s == "pending"]
    detail = f"{len(failed)} failed" + (f" ({_list(failed)})" if failed else "")
    detail += f", {len(pending)} pending" + (f" ({_list(pending)})" if pending else "")
    detail += f", {len(pull.checks)} checks at {head}"
    record(not failed, "ci", detail, f"CI failed: {_list(failed)}")

    verdict = review_verdict(pull)
    if verdict is None:
        review = f"no review comment by {'/'.join(TRUSTED)}"
    elif verdict[0] != head:
        review = f"newest review comment is at {verdict[0]}, not {head}"
    else:
        review = f"comment at {head} says {verdict[1]}"
    clean = (
        verdict is not None
        and verdict[0] == head
        and (verdict[1] == "clean" or verdict[1].endswith(": clean"))
    )
    record(clean, "review", review, f"no clean review comment at {head}")

    links = list(_LINKED.finditer(pull.body))
    numbers = [int(m.group(1)) for m in links]
    if not links:
        link_detail = "no `Fixes`, `Closes` or `Part of #N` line"
        link_reason = "the body has no Fixes, Closes or Part of #N line"
    else:
        link_detail = "has " + ", ".join(f"`{m.group(0)}`" for m in links)
        link_reason = f"the body links {', '.join(f'#{n}' for n in numbers)}, not #{issue}"
    if issue is not None:
        link_detail += f" (wanted #{issue})"
    record(bool(links) if issue is None else issue in numbers, "body", link_detail, link_reason)

    record(
        not threads,
        "threads",
        f"{len(threads)} open review threads",
        f"{len(threads)} open review threads",
    )
    lines += [f"       {line}" for line in threads]
    note = f"{len(findings)} review-body findings since the head commit"
    lines.append(f"{'note' if findings else 'ok  '} findings: {note}")
    lines += [f"       {line}" for line in findings]

    if attribution:
        lines.append(f"note attribution: {len(attribution)} failure(s) (listed, not failed)")
    else:
        lines.append("ok   attribution: the body ends with an attribution line")
    lines += [f"       {line}" for line in attribution]
    lines.append(
        "note pin and date: pre-push only (mise run pr-lint in the implementer's checkout)"
    )

    record(
        not pull.draft, "draft", "draft" if pull.draft else "ready for review", "the PR is a draft"
    )
    return lines, reasons


def _is_cloud() -> bool:
    return os.environ.get("CLAUDE_CODE_REMOTE") == "true"


def main(
    argv: Sequence[str] | None = None,
    *,
    attribution: Callable[[str], Sequence[str]] = pr_lint.attribution_failures,
) -> int:
    """Print the merge-bar report for the pull request on the command line.

    *attribution* is the body's attribution lint; tests pass a stub,
    ``pr_lint.attribution_failures`` by default.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("number", type=int, help="pull request number")
    parser.add_argument(
        "--issue",
        type=int,
        metavar="N",
        help="the issue the work is for: the body's Fixes, Closes or Part of line must name it",
    )
    args = parser.parse_args(argv)
    try:
        # REST, not `gh repo view`, which goes through GraphQL.
        repo = pr_threads._gh("api", "repos/{owner}/{repo}")["full_name"]
        owner, name = repo.split("/", 1)
        pull = rest_pull(owner, name, args.number) if _is_cloud() else graphql_pull(args.number)
        nodes = pr_threads.read_threads(owner, name, args.number) if pull else None
        reviews = pr_threads.read_reviews(owner, name, args.number) if pull else None
    except (pr_threads.GhError, OSError) as err:
        print(f"merge-bar: {err}", file=sys.stderr)
        return 2
    if pull is None or nodes is None or reviews is None:
        print(f"merge-bar: {repo} has no pull request {args.number}", file=sys.stderr)
        return 2
    threads = pr_threads.thread_lines(nodes, include_resolved=False)
    findings = pr_threads.outside_lines(reviews[1], reviews[0], include_all=False)
    lines, reasons = evaluate(
        pull,
        threads=threads,
        findings=findings,
        issue=args.issue,
        attribution=attribution(pull.body),
    )
    print(f"{repo}#{args.number}")
    print(*lines, sep="\n")
    if reasons:
        print(f"FAIL: {'; '.join(reasons)}")
        return 1
    print(
        "PASS (answer the review-body findings by hand)" if findings else "PASS",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
