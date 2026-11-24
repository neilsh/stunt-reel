#!/usr/bin/env python3
"""Sync the owner's project board's Status and Priority fields from each issue's labels and state.

The board is the owner's dashboard; labels stay the source of truth
(``docs/agents/issue-tracker.md``). For each issue this adds it to the project, unarchives it if
it is open, and sets Status from :func:`derive_status` and Priority from :func:`derive_priority`
(clearing Priority when no ``priority:`` label is set). The ``project-sync`` workflow runs it on
issue events, daily and on demand.

Usage: ``mise run project-sync -- <issue number>...`` or ``-- --all`` (every open issue, plus
every unarchived project item from this repo). Needs ``gh`` authenticated with ``project``
scope. Exit status: ``0`` on success, ``2`` when ``gh`` fails.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

import labels

#: Seconds before a ``gh`` call counts as failed.
GH_TIMEOUT = 60

#: State label -> Status option, highest precedence first. An open issue with none of these is
#: ``Needs triage``, so an issue filed without a label shows up where the owner looks.
LABEL_STATUS = (
    (labels.IN_PROGRESS, "In progress"),
    (labels.NEEDS_INFO, "Needs info"),
    (labels.PLAN_REVIEW, "Plan review"),
    (labels.READY_FOR_HUMAN, "Ready for human"),
    (labels.NEEDS_PLAN, "Needs plan"),
    (labels.READY_FOR_AGENT, "Ready for agent"),
    (labels.NEEDS_TRIAGE, "Needs triage"),
)
LABEL_PRIORITY = (
    (labels.PRIORITY_P0, "P0"),
    (labels.PRIORITY_P1, "P1"),
    (labels.PRIORITY_P2, "P2"),
    (labels.PRIORITY_P3, "P3"),
)
DONE = "Done"
GOAL = "Goal"
TRIAGE = "Needs triage"

_PROJECT = """
query($owner: String!, $number: Int!) {
  user(login: $owner) {
    projectV2(number: $number) {
      id
      status: field(name: "Status") { ... on ProjectV2SingleSelectField { id options { id name } } }
      priority: field(name: "Priority") { ... on ProjectV2SingleSelectField { id options { id name } } }
    }
  }
}"""

_ITEMS = """
query($owner: String!, $number: Int!, $after: String) {
  user(login: $owner) {
    projectV2(number: $number) {
      items(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          isArchived
          content { ... on Issue { number repository { nameWithOwner } } }
        }
      }
    }
  }
}"""

_ADD = """
mutation($project: ID!, $content: ID!) {
  addProjectV2ItemById(input: {projectId: $project, contentId: $content}) {
    item {
      id
      isArchived
      status: fieldValueByName(name: "Status") { ... on ProjectV2ItemFieldSingleSelectValue { name } }
      priority: fieldValueByName(name: "Priority") { ... on ProjectV2ItemFieldSingleSelectValue { name } }
    }
  }
}"""

_UNARCHIVE = """
mutation($project: ID!, $item: ID!) {
  unarchiveProjectV2Item(input: {projectId: $project, itemId: $item}) { item { id } }
}"""

_SET = """
mutation($project: ID!, $item: ID!, $field: ID!, $option: String!) {
  updateProjectV2ItemFieldValue(input: {projectId: $project, itemId: $item, fieldId: $field,
                                        value: {singleSelectOptionId: $option}}) { projectV2Item { id } }
}"""

_CLEAR = """
mutation($project: ID!, $item: ID!, $field: ID!) {
  clearProjectV2ItemFieldValue(input: {projectId: $project, itemId: $item, fieldId: $field}) {
    projectV2Item { id }
  }
}"""


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


def graphql(query: str, **variables: str | int | None) -> Any:
    """The ``data`` of a GraphQL call; ``None`` variables are left out."""
    args = ["api", "graphql", "-f", f"query={query}"]
    for name, value in variables.items():
        if value is not None:
            args += ["-F" if isinstance(value, int) else "-f", f"{name}={value}"]
    return gh_json(*args)["data"]


def derive_status(names: set[str], state: str, sub_issues: int) -> str:
    """The Status an issue belongs in: closed is ``Done``, a parent ``Goal``, else its label's."""
    if state == "closed":
        return DONE
    if sub_issues > 0:
        return GOAL
    return next((status for label, status in LABEL_STATUS if label in names), TRIAGE)


def derive_priority(names: set[str]) -> str | None:
    """The Priority option an issue belongs in, or ``None`` when no ``priority:`` label is set."""
    return next((option for label, option in LABEL_PRIORITY if label in names), None)


@dataclass(frozen=True)
class Project:
    """The project's node id and its Status and Priority fields: id and option name -> option id."""

    id: str
    status_field: str
    status_options: dict[str, str]
    priority_field: str
    priority_options: dict[str, str]


def _load_single_select(
    field_node: dict[str, Any] | None, field_name: str, wanted: set[str]
) -> tuple[str, dict[str, str]]:
    if not field_node or "options" not in field_node:
        raise GhError(f"Project has no single-select field {field_name}")
    options = {option["name"]: option["id"] for option in field_node["options"]}
    if missing := sorted(wanted - options.keys()):
        raise GhError(f"{field_name} has no option {', '.join(missing)}")
    return field_node["id"], options


def load_project(owner: str, number: int) -> Project:
    """Read the project; raises :class:`GhError` if Status or Priority lacks an option sync sets."""
    node = graphql(_PROJECT, owner=owner, number=number)["user"]["projectV2"]
    status_field, status_options = _load_single_select(
        node.get("status"),
        "Status",
        {DONE, GOAL, *(status for _, status in LABEL_STATUS)},
    )
    priority_field, priority_options = _load_single_select(
        node.get("priority"),
        "Priority",
        {option for _, option in LABEL_PRIORITY},
    )
    return Project(node["id"], status_field, status_options, priority_field, priority_options)


def project_issues(owner: str, number: int, repo: str) -> set[int]:
    """Numbers of this repo's issues on the project that are not archived."""
    numbers: set[int] = set()
    after: str | None = None
    while True:
        page = graphql(_ITEMS, owner=owner, number=number, after=after)
        items = page["user"]["projectV2"]["items"]
        for node in items["nodes"]:
            content = node["content"] or {}
            if (
                not node["isArchived"]
                and content.get("repository", {}).get("nameWithOwner") == repo
            ):
                numbers.add(content["number"])
        if not items["pageInfo"]["hasNextPage"]:
            return numbers
        after = items["pageInfo"]["endCursor"]


def open_issues(repo: str) -> set[int]:
    """Numbers of the repo's open issues (REST lists PRs as issues too; they are dropped)."""
    pages = gh_json("api", "--paginate", "--slurp", f"repos/{repo}/issues?state=open&per_page=100")
    return {issue["number"] for page in pages for issue in page if "pull_request" not in issue}


def sync_issue(project: Project, repo: str, number: int) -> str | None:
    """Bring one issue's item in line; a line saying what changed, or ``None`` if nothing did."""
    issue = gh_json("api", f"repos/{repo}/issues/{number}")
    if "pull_request" in issue:
        return None
    names = {label["name"] for label in issue["labels"]}
    sub_issues = (issue.get("sub_issues_summary") or {}).get("total", 0)
    status = derive_status(names, issue["state"], sub_issues)
    priority = derive_priority(names)
    item = graphql(_ADD, project=project.id, content=issue["node_id"])["addProjectV2ItemById"][
        "item"
    ]
    changes = []
    if item["isArchived"] and issue["state"] == "open":
        graphql(_UNARCHIVE, project=project.id, item=item["id"])
        changes.append("unarchived")
    current_status = (item.get("status") or {}).get("name")
    if current_status != status:
        graphql(
            _SET,
            project=project.id,
            item=item["id"],
            field=project.status_field,
            option=project.status_options[status],
        )
        changes.append(f"{current_status or '(none)'} -> {status}")
    current_priority = (item.get("priority") or {}).get("name")
    if priority is not None and current_priority != priority:
        graphql(
            _SET,
            project=project.id,
            item=item["id"],
            field=project.priority_field,
            option=project.priority_options[priority],
        )
        changes.append(f"Priority: {current_priority or '(none)'} -> {priority}")
    elif priority is None and current_priority is not None:
        graphql(_CLEAR, project=project.id, item=item["id"], field=project.priority_field)
        changes.append(f"Priority: {current_priority} -> (none)")
    return f"#{number}: {', '.join(changes)}" if changes else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("issues", nargs="*", type=int, help="issue numbers to sync")
    parser.add_argument("--all", action="store_true", help="every open issue and project item")
    parser.add_argument("--repo", required=True, help="owner/name of the issues' repository")
    parser.add_argument("--owner", required=True, help="login of the user owning the project")
    parser.add_argument("--project", required=True, type=int, help="the project's number")
    args = parser.parse_args(argv)
    if not args.all and not args.issues:
        parser.error("name issue numbers or pass --all")
    try:
        project = load_project(args.owner, args.project)
        numbers = set(args.issues)
        if args.all:
            numbers |= open_issues(args.repo) | project_issues(args.owner, args.project, args.repo)
        for number in sorted(numbers):
            if line := sync_issue(project, args.repo, number):
                print(line)
    except GhError as err:
        print(f"project-sync: {err}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
