#!/usr/bin/env python3
"""Print the unattended queue: open PRs, then open ``ready-for-agent`` issues, one line each.

Each line names the item and either ``ready`` or why it is skipped, for the reasons that need no
judgement:

- a PR labelled ``ready-for-human``, or one whose auto-merge is armed and whose checks are
  pending or passed; an armed PR with a failed check is ``ready``, since it needs a fix;
- an issue labelled ``in-progress``, or ``local-only`` in a cloud session
  (``CLAUDE_CODE_REMOTE=true``; ``docs/agents/triage-labels.md`` § Environment roles);
- an issue with an open blocker or open sub-issue (``docs/agents/issue-tracker.md``, "Count open
  blockers"): a native dependency, a ``Blocked by: #<n>`` line naming an open issue, or an open
  issue whose body starts a line with ``Part of #<n>``;
- an issue an open PR names with ``Part of`` or a closing keyword, or by ``<n>-`` in its branch.

PRs come in stack order (a PR whose base is ``main`` before the PRs stacked on it), with ``draft``
and a non-``main`` base noted; issues come in number order. Everything is read over REST, which a
cloud session's proxy allows. Bodies are read here and never printed.

Usage: ``mise run queue``. Exit status: ``0`` on success, ``2`` when ``gh`` fails.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any

#: Seconds before a ``gh`` call counts as failed.
GH_TIMEOUT = 60

#: A PR's claim on issues: ``Part of`` or a GitHub closing keyword, then one or more ``#<n>``.
_CLAIM = re.compile(
    r"\b(?:part of|close[sd]?|fix(?:e[sd])?|resolve[sd]?):?\s+(#\d+(?:\s*(?:,|and)\s*#\d+)*)",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"#(\d+)")
_PART_OF_LINE = re.compile(r"^[ \t]*part of[ \t]+#(\d+)", re.IGNORECASE | re.MULTILINE)
_BLOCKED_BY_LINE = re.compile(r"^[ \t]*blocked by:?[ \t]*(.*)$", re.IGNORECASE | re.MULTILINE)
_BRANCH_ISSUE = re.compile(r"(?:^|/)(\d+)-")
_FAILED = {"failure", "cancelled", "timed_out", "action_required", "startup_failure"}


class GhError(RuntimeError):
    """``gh`` failed, stalled or returned something other than JSON."""


def gh_json(*args: str) -> Any:
    """``gh <args>``'s stdout parsed as JSON; raises :class:`GhError`."""
    exe = shutil.which("gh")
    if exe is None:
        raise GhError("gh not found on PATH")
    try:
        done = subprocess.run(  # noqa: S603 - gh with fixed arguments
            [exe, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=GH_TIMEOUT,
        )
    except subprocess.TimeoutExpired as err:
        raise GhError(f"gh {args[0]} stalled for {GH_TIMEOUT} s") from err
    if done.returncode != 0:
        raise GhError(done.stderr.strip() or f"gh {args[0]} exited {done.returncode}")
    try:
        return json.loads(done.stdout)
    except json.JSONDecodeError as err:
        raise GhError(f"gh {args[0]} returned no JSON: {err}") from err


@dataclass
class Item:
    """One queue line: ``PR`` or ``issue``, its number and title, and why it is skipped."""

    kind: str
    number: int
    title: str
    labels: list[str]
    skip: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def line(self) -> str:
        state = "skip: " + "; ".join(self.skip) if self.skip else "ready"
        extra = [f"[{', '.join(self.labels)}]"] if self.labels else []
        extra += self.notes
        title = " ".join(self.title.split())
        return f"{self.kind:<5} #{self.number:<5} {state:<28} {title}  {' '.join(extra)}".rstrip()


def _labels(raw: dict[str, Any]) -> list[str]:
    return sorted(label["name"] for label in raw.get("labels") or [])


def claimed_issues(text: str | None) -> set[int]:
    """The issues *text* (a PR's title or body) says it is part of, fixes, closes or resolves."""
    return {int(n) for span in _CLAIM.findall(text or "") for n in _NUMBER.findall(span)}


def parents_of(body: str | None) -> set[int]:
    """The issues an issue *body* names on a ``Part of #<n>`` line."""
    return {int(n) for n in _PART_OF_LINE.findall(body or "")}


def blocked_by_line(body: str | None) -> set[int]:
    """The issues an issue *body*'s ``Blocked by:`` line names."""
    return {int(n) for line in _BLOCKED_BY_LINE.findall(body or "") for n in _NUMBER.findall(line)}


def checks_state(runs: list[dict[str, Any]]) -> str:
    """``failed``, ``pending`` or ``passed`` for a commit's check runs; none yet is pending."""
    if any(run.get("conclusion") in _FAILED for run in runs):
        return "failed"
    if not runs or any(run.get("status") != "completed" for run in runs):
        return "pending"
    return "passed"


def stack_order(prs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """*prs* bottom layer first: each PR after the open PR whose head is its base."""
    heads = {pr["head"]["ref"]: pr for pr in prs}

    def depth(pr: dict[str, Any]) -> int:
        seen: set[str] = set()
        n = 0
        while pr["base"]["ref"] in heads and pr["base"]["ref"] not in seen:
            seen.add(pr["base"]["ref"])
            pr = heads[pr["base"]["ref"]]
            n += 1
        return n

    return sorted(prs, key=lambda pr: (depth(pr), pr["number"]))


def pr_items(prs: list[dict[str, Any]], checks: dict[int, str]) -> list[Item]:
    """A line per open REST PR, in stack order.

    *checks* is each armed PR's :func:`checks_state`, or ``conflict`` when it no longer merges.
    """
    items = []
    for pr in stack_order(prs):
        item = Item("PR", pr["number"], pr["title"], _labels(pr))
        if "ready-for-human" in item.labels:
            item.skip.append("ready-for-human")
        if pr.get("auto_merge"):
            state = checks.get(pr["number"], "pending")
            if state == "failed":
                item.notes.append("auto-merge armed, a check failed")
            elif state == "conflict":
                item.notes.append("auto-merge armed, conflicts with main")
            else:
                item.skip.append(f"armed, checks {state}")
        if pr.get("draft"):
            item.notes.append("draft")
        if pr["base"]["ref"] != "main":
            item.notes.append(f"base={pr['base']['ref']}")
        items.append(item)
    return items


def issue_items(
    open_issues: list[dict[str, Any]], prs: list[dict[str, Any]], *, cloud: bool
) -> list[Item]:
    """A line per open ``ready-for-agent`` issue among *open_issues*, in number order."""
    claimed: dict[int, int] = {}
    for pr in prs:
        found = claimed_issues(pr.get("body")) | claimed_issues(pr.get("title"))
        match = _BRANCH_ISSUE.search(pr["head"]["ref"])
        if match:
            found.add(int(match.group(1)))
        for n in found:
            claimed.setdefault(n, pr["number"])
    open_numbers = {issue["number"] for issue in open_issues}
    children: dict[int, int] = {}
    for issue in open_issues:
        for n in parents_of(issue.get("body")) - {issue["number"]}:
            children[n] = children.get(n, 0) + 1
    items = []
    for issue in sorted(open_issues, key=lambda i: i["number"]):
        labels = _labels(issue)
        if "ready-for-agent" not in labels:
            continue
        item = Item("issue", issue["number"], issue["title"], labels)
        if "in-progress" in labels:
            item.skip.append("in-progress")
        if cloud and "local-only" in labels:
            item.skip.append("local-only")
        native = (issue.get("issue_dependencies_summary") or {}).get("blocked_by", 0)
        blockers = native or len(blocked_by_line(issue.get("body")) & open_numbers)
        if blockers:
            item.skip.append(f"{blockers} open blocker(s)")
        sub = issue.get("sub_issues_summary") or {}
        open_subs = sub.get("total", 0) - sub.get("completed", 0) + children.get(item.number, 0)
        if open_subs:
            item.skip.append(f"{open_subs} open sub-issue(s)")
        if item.number in claimed:
            item.skip.append(f"PR #{claimed[item.number]}")
        items.append(item)
    return items


def armed_state(pr: dict[str, Any]) -> str:
    """``conflict`` when GitHub calls the armed *pr* unmergeable, else its :func:`checks_state`."""
    detail = gh_json("api", f"repos/{{owner}}/{{repo}}/pulls/{pr['number']}")
    if detail.get("mergeable_state") == "dirty":
        return "conflict"
    path = f"repos/{{owner}}/{{repo}}/commits/{pr['head']['sha']}/check-runs"
    return checks_state(gh_json("api", path)["check_runs"])


def _pages(path: str) -> list[dict[str, Any]]:
    """Every entry of a paginated REST list, flattened from ``--slurp``'s pages."""
    return [entry for page in gh_json("api", "--paginate", "--slurp", path) for entry in page]


def fetch() -> tuple[list[dict[str, Any]], dict[int, str], list[dict[str, Any]]]:
    """Every open PR, each armed PR's state for :func:`pr_items`, and every open issue (PRs dropped)."""
    prs = _pages("repos/{owner}/{repo}/pulls?state=open&per_page=100")
    checks = {pr["number"]: armed_state(pr) for pr in prs if pr.get("auto_merge")}
    issues = [
        i
        for i in _pages("repos/{owner}/{repo}/issues?state=open&per_page=100")
        if "pull_request" not in i
    ]
    return prs, checks, issues


def main() -> int:
    try:
        prs, checks, issues = fetch()
    except GhError as err:
        print(f"queue: {err}", file=sys.stderr)
        return 2
    cloud = os.environ.get("CLAUDE_CODE_REMOTE", "").lower() == "true"
    for item in pr_items(prs, checks) + issue_items(issues, prs, cloud=cloud):
        print(item.line())
    return 0


if __name__ == "__main__":
    sys.exit(main())
