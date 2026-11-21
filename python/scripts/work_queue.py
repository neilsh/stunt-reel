#!/usr/bin/env python3
"""Print the unattended queue: open PRs, then open ``ready-for-agent`` issues, one line each.

Each line names the item and either ``ready`` or why it is skipped, for the reasons that need no
judgement:

- a PR labelled ``ready-for-human``, or ``local-only`` in a cloud session; one stacked on another
  open PR, which waits for its base to merge; or one whose auto-merge is armed and whose checks are pending. An armed PR with a
  failed check, a conflict, or passed checks yet still open is ``ready``, since it needs work;
- an issue labelled ``in-progress``, or ``local-only`` in a cloud session
  (``CLAUDE_CODE_REMOTE=true`` or ``/home/antigravity``; ``docs/agents/triage-labels.md`` § Environment roles);
- an issue with an open blocker or open sub-issue (``docs/agents/issue-tracker.md``, "Count open
  blockers"): a native dependency, a ``Blocked by: #<n>`` line naming an open issue, or an open
  issue whose body starts a line with ``Part of #<n>``;
- an issue an open PR names with ``Part of`` or a closing keyword, or by ``<n>-`` in its branch.

PRs come in stack order (a PR whose base is ``main`` before the PRs stacked on it), with ``draft``
and a non-``main`` base noted; issues come in number order. Everything is read over REST, which a
cloud session's proxy allows. Bodies are read here and never printed.
When a class agreement batch is due (``stunt_reel.class_agreement.due``), a line says why, in
both environments.
A local run ends with the free-disk line for the primary checkout's drive, naming the action
``loop-and-bounds.md`` asks at the threshold it crosses; a cloud session prints none.

Usage: ``mise run queue``. Exit status: ``0`` on success, ``2`` when ``gh`` fails.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import merge_bar

from stunt_reel.class_agreement import AGREEMENT_FILE, due, read_agreement, renderer_commits_since
from stunt_reel.dataroot import REPO_ROOT

#: Seconds before a ``gh`` call counts as failed.
GH_TIMEOUT = 60

#: Seconds before the ``git`` call naming the primary checkout counts as failed.
GIT_TIMEOUT = 60

#: Entries requested per REST page; a shorter page is the last.
PER_PAGE = 100

#: A PR's claim on issues: ``Part of`` or a GitHub closing keyword, then one or more ``#<n>``.
_CLAIM = re.compile(
    r"\b(?:part of|close[sd]?|fix(?:e[sd])?|resolve[sd]?):?\s+(#\d+(?:\s*(?:,|and)\s*#\d+)*)",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"#(\d+)")
_PART_OF_LINE = re.compile(r"^[ \t]*part of[ \t]+#(\d+)", re.IGNORECASE | re.MULTILINE)
_BLOCKED_BY_LINE = re.compile(r"^[ \t]*blocked by:?[ \t]*(.*)$", re.IGNORECASE | re.MULTILINE)
#: A branch named for an issue, ``feat/440-slug``; not ``0044-…`` nor a date, ``2026-11-…``.
_BRANCH_ISSUE = re.compile(r"(?:^|/)([1-9]\d*)-[a-z]", re.IGNORECASE)
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


def _check_state(run: dict[str, Any]) -> str:
    """A REST check run's ``failed``, ``pending`` or ``passed``, from its status and conclusion."""
    if run.get("conclusion") in _FAILED:
        return "failed"
    return "pending" if run.get("status") != "completed" else "passed"


def checks_state(runs: list[dict[str, Any]]) -> str:
    """``failed``, ``pending`` or ``passed`` for a commit's check runs; none yet is pending.

    Only the newest run of each check name counts, as in ``gh pr checks``: a concurrency group
    cancels the run a newer one supersedes, so a cancelled run beside its passing rerun is not a
    failure (:func:`merge_bar._newest_runs`).
    """
    newest = merge_bar._newest_runs(
        [
            (
                str(run.get("name") or "?"),
                _check_state(run),
                (run.get("started_at") or "", int(run.get("id") or 0)),
            )
            for run in runs
        ]
    )
    states = [state for _, state in newest]
    if "failed" in states:
        return "failed"
    if not states or "pending" in states:
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


def pr_items(
    prs: list[dict[str, Any]], checks: dict[int, str], *, cloud: bool = False
) -> list[Item]:
    """A line per open REST PR, in stack order.

    *checks* is each armed PR's :func:`armed_state`; *cloud* skips ``local-only`` PRs.
    """
    heads = {pr["head"]["ref"]: pr["number"] for pr in prs}
    armed_notes = {
        "failed": "auto-merge armed, a check failed",
        "conflict": "auto-merge armed, conflicts with main",
        "passed": "auto-merge armed, checks passed but not merged",
    }
    items = []
    for pr in stack_order(prs):
        item = Item("PR", pr["number"], pr["title"], _labels(pr))
        if "ready-for-human" in item.labels:
            item.skip.append("ready-for-human")
        if cloud and "local-only" in item.labels:
            item.skip.append("local-only")
        if pr["base"]["ref"] in heads:
            item.skip.append(f"base #{heads[pr['base']['ref']]} open")
        if pr.get("auto_merge"):
            state = checks.get(pr["number"], "pending")
            if state in armed_notes:
                item.notes.append(armed_notes[state])
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
        # A native sub-issue may also say "Part of #n": count one source, not both.
        open_subs = sub.get("total", 0) - sub.get("completed", 0) or children.get(item.number, 0)
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
    path = f"repos/{{owner}}/{{repo}}/commits/{pr['head']['sha']}/check-runs?per_page=100"
    return checks_state(gh_json("api", path)["check_runs"])


def _pages(path: str) -> list[dict[str, Any]]:
    """Every entry of a REST list at *path* (no ``per_page`` or ``page``), read page by page.

    Pages go by number because ``gh api --paginate`` follows GitHub's next links, which name the
    repository by id (``repositories/<id>/...``), and a cloud session's proxy refuses those
    (``docs/cloud-sessions.md``).
    """
    entries: list[dict[str, Any]] = []
    page = 1
    while True:
        sep = "&" if "?" in path else "?"
        batch = gh_json("api", f"{path}{sep}per_page={PER_PAGE}&page={page}")
        entries.extend(batch)
        if len(batch) < PER_PAGE:
            return entries
        page += 1


def fetch() -> tuple[list[dict[str, Any]], dict[int, str], list[dict[str, Any]]]:
    """Every open PR, each armed PR's state for :func:`pr_items`, and every open issue (PRs dropped)."""
    prs = _pages("repos/{owner}/{repo}/pulls?state=open")
    checks = {pr["number"]: armed_state(pr) for pr in prs if pr.get("auto_merge")}
    issues = [
        i for i in _pages("repos/{owner}/{repo}/issues?state=open") if "pull_request" not in i
    ]
    return prs, checks, issues


#: Present on Antigravity cloud VMs (``working-in-an-environment`` skill).
ANTIGRAVITY_HOME = Path("/home/antigravity")


def is_cloud_session() -> bool:
    """True on Claude Code cloud or Antigravity cloud VMs."""
    return os.environ.get("CLAUDE_CODE_REMOTE", "").lower() == "true" or ANTIGRAVITY_HOME.is_dir()


#: GiB in a byte count, so free space and the thresholds read in GB as ``loop-and-bounds.md`` does.
GIB = 1 << 30

#: Under this many GB free the run creates no new worktrees and cleans an idle kept one.
LOW_FREE_GB = 10

#: Under this many GB free the run shuts down.
SHUTDOWN_FREE_GB = 5


def primary_checkout() -> Path | None:
    """The primary checkout, whose ``.git`` is the repository's git common dir, or None.

    The common dir is what a linked worktree and the primary checkout share, so the drive found
    is the primary checkout's from any worktree.
    """
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],  # noqa: S607 - git from PATH
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=GIT_TIMEOUT,
            cwd=Path(__file__).resolve().parents[2],
        )
    except OSError, subprocess.TimeoutExpired:
        return None
    common = done.stdout.strip()
    if done.returncode != 0 or not common:
        return None
    return Path(common).parent


def disk_line(primary: Path) -> str:
    """The free-disk line for the volume holding *primary*, ending the queue's output.

    Under 10 GB free it adds create no new worktrees and run ``mise run clean``, and under 5 GB
    free run Shutdown, wording the thresholds as ``loop-and-bounds.md`` § Clock and disk space
    does.
    """
    free = shutil.disk_usage(primary).free
    drive = primary.drive or primary.anchor
    line = f"free disk: {free / GIB:.1f} GB on {drive}"
    advice: list[str] = []
    if free < LOW_FREE_GB * GIB:
        advice.append(f"under {LOW_FREE_GB} GB free: create no new worktrees; run mise run clean")
    if free < SHUTDOWN_FREE_GB * GIB:
        advice.append(f"under {SHUTDOWN_FREE_GB} GB free: run Shutdown")
    return f"{line} ({'; '.join(advice)})" if advice else line


def agreement_line(repo: Path = REPO_ROOT, today: dt.date | None = None) -> str | None:
    """``agreement batch due: <reason>`` for *repo*'s pinned agreement against ``origin/main``; ``None`` when not due."""
    pinned = read_agreement(repo / AGREEMENT_FILE)
    commits = None if pinned is None else renderer_commits_since(pinned.crates, repo=repo)
    reason = due(pinned, commits, today or dt.datetime.now(dt.UTC).date())
    return None if reason is None else f"agreement batch due: {reason}"


def main() -> int:
    try:
        prs, checks, issues = fetch()
    except GhError as err:
        print(f"queue: {err}", file=sys.stderr)
        return 2
    cloud = is_cloud_session()
    for item in pr_items(prs, checks, cloud=cloud) + issue_items(issues, prs, cloud=cloud):
        print(item.line())
    batch = agreement_line()
    if batch is not None:
        print(batch)
    if not cloud:
        primary = primary_checkout()
        if primary is None:
            print(
                "queue: free disk unknown: git did not name the primary checkout", file=sys.stderr
            )
        else:
            print(disk_line(primary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
