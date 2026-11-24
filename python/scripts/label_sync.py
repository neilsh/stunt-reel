"""Dry-run or apply the canonical GitHub issue labels from ``labels.py`` via REST.

Compares ``labels.CATALOG`` against the repository's existing labels over GitHub's REST API
(so cloud sessions' GraphQL-blocking proxy allows it). Creates missing labels and updates
drifted color, description, or case; never deletes extra labels already on the remote.

Usage: ``mise run label-sync [-- --apply] [--repo OWNER/NAME]``.
Exit status: ``0`` on success, ``2`` when ``gh`` fails.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.parse
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import labels

if TYPE_CHECKING:
    from collections.abc import Sequence

#: Seconds before a ``gh`` call counts as failed.
GH_TIMEOUT = 60

#: Entries requested per REST page; a shorter page is the last.
PER_PAGE = 100


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


def fetch_labels(repo: str) -> list[dict[str, Any]]:
    """Return every existing label on *repo* via numbered REST pages."""
    entries: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = gh_json("api", f"repos/{repo}/labels?per_page={PER_PAGE}&page={page}")
        entries.extend(batch)
        if len(batch) < PER_PAGE:
            return entries
        page += 1


@dataclass(frozen=True)
class Action:
    """One planned label create or update on GitHub."""

    kind: str  # "create" or "update"
    spec: labels.LabelSpec
    current_name: str = ""
    reasons: tuple[str, ...] = ()


def plan_sync(
    existing: Sequence[dict[str, Any]],
    catalog: Sequence[labels.LabelSpec] | None = None,
) -> tuple[list[Action], list[str]]:
    """Compute creates/updates for *catalog* and extra remote label names not in *catalog*."""
    active_catalog = labels.CATALOG if catalog is None else catalog
    by_lower: dict[str, dict[str, Any]] = {}
    for raw in existing:
        name = str(raw["name"])
        by_lower[name.lower()] = raw

    actions: list[Action] = []
    seen_lower: set[str] = set()
    for spec in active_catalog:
        key = spec.name.lower()
        seen_lower.add(key)
        remote = by_lower.get(key)
        if remote is None:
            actions.append(Action("create", spec))
            continue
        reasons: list[str] = []
        current_name = str(remote["name"])
        if current_name != spec.name:
            reasons.append(f"name {current_name!r} -> {spec.name!r}")
        current_color = str(remote.get("color") or "").upper()
        if current_color != spec.color:
            reasons.append(f"color {current_color} -> {spec.color}")
        current_desc = str(remote.get("description") or "")
        if current_desc != spec.description:
            reasons.append("description")
        if reasons:
            actions.append(
                Action("update", spec, current_name=current_name, reasons=tuple(reasons))
            )

    extras = sorted(str(raw["name"]) for lower, raw in by_lower.items() if lower not in seen_lower)
    return actions, extras


def apply_action(repo: str, action: Action) -> None:
    """Execute one *action* against *repo* via GitHub REST."""
    spec = action.spec
    if action.kind == "create":
        gh_json(
            "api",
            "-X",
            "POST",
            f"repos/{repo}/labels",
            "-f",
            f"name={spec.name}",
            "-f",
            f"color={spec.color}",
            "-f",
            f"description={spec.description}",
        )
        return
    encoded = urllib.parse.quote(action.current_name, safe="")
    gh_json(
        "api",
        "-X",
        "PATCH",
        f"repos/{repo}/labels/{encoded}",
        "-f",
        f"new_name={spec.name}",
        "-f",
        f"color={spec.color}",
        "-f",
        f"description={spec.description}",
    )


def format_action(action: Action, *, apply: bool) -> str:
    """Format one line summarizing *action*."""
    verb = (
        ("created" if apply else "create")
        if action.kind == "create"
        else ("updated" if apply else "update")
    )
    detail = f" ({', '.join(action.reasons)})" if action.reasons else ""
    return f"{verb}: {action.spec.name} #{action.spec.color}{detail}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="create and update labels on GitHub")
    parser.add_argument(
        "--repo",
        default="{owner}/{repo}",
        help="owner/name repository (default: resolved from git remote by gh api)",
    )
    args = parser.parse_args(argv)
    try:
        existing = fetch_labels(args.repo)
        actions, extras = plan_sync(existing)
        for action in actions:
            if args.apply:
                apply_action(args.repo, action)
            print(format_action(action, apply=args.apply))
    except GhError as err:
        print(f"label-sync: {err}", file=sys.stderr)
        return 2
    if not actions:
        print("unchanged: all canonical labels match")
    for extra in extras:
        print(f"extra on remote: {extra}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
