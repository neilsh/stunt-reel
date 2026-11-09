"""Start a work item's folder under ``work/``, or list every work folder with its status.

A work item is a GitHub issue. Its folder is ``work/<YYYY-MM>/<issue>_<slug>/``, named for the
month the work started, and the README's frontmatter is the folder's record
(``stunt_reel.work_items`` holds the rules).

``new <slug> --issue N`` makes this month's folder for issue N, its README titled as the issue
is; when ``gh`` cannot give the title, the README takes the slug and one note on stderr says
so, and that the issue may not exist. Without ``--issue`` it needs ``gh`` to file the issue
first, titled with the slug and labelled ``needs-triage``, into the repository ``gh`` targets,
and only when that is the one the ``origin`` remote names: in a fork ``gh`` can target the
upstream parent (``docs/agents/issue-tracker.md``). It refuses an issue that already has a
folder, in any month.

``list`` prints one line per folder: month, folder, status, title, outcome. An issue folder's
status is its issue's, read in one ``gh`` call; when ``gh`` is missing or fails, it is
``unknown`` and one note on stderr says so. A folder with no issue is ``landed``, or
``abandoned`` when its README says ``status: abandoned``. ``--status`` keeps the folders with
that status.

Usage: ``mise run work -- new <slug> [--issue N]`` or ``mise run work -- list [--status
active|landed|abandoned]``; either takes ``--root DIR`` for a work root other than ``work/``.
Exit status: ``0`` on success, ``1`` when ``new`` cannot make the folder or ``list`` finds a
folder that breaks the layout, ``2`` for bad arguments.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

from stunt_reel.work_items import (
    MONTH_PATTERN,
    WORK_ROOT,
    Runner,
    WorkFolderError,
    folder_name,
    issue_statuses,
    readme_text,
    run_command,
    scan,
)

STATUSES = ("active", "landed", "abandoned")
_ISSUE_URL = re.compile(r"/issues/([1-9][0-9]*)$")
# `owner/name` at the end of a remote URL: https, ssh (`git@host:owner/name.git`) or a proxy.
_REMOTE_REPO = re.compile(r"([^/:]+/[^/:]+?)(?:\.git)?/?$")


class _RefusedError(Exception):
    """`new` cannot go on; the message says why."""


def create_folder(slug: str, issue: int, title: str, today: date, root: Path) -> Path:
    """Make ``<root>/<today's month>/<issue>_<slug>/README.md`` and return the folder.

    The README's frontmatter holds *title*, *today* as ``started``, *issue* and an empty
    ``outcome``. Raises WorkFolderError for a bad slug or issue or a title that is not one
    non-blank line, and FileExistsError when *issue* has a folder in any month.
    """
    name = folder_name(issue, slug)
    readme = readme_text(title, today, "", issue=issue)
    _refuse_a_second_folder(root, issue)
    path = root / today.strftime("%Y-%m") / name
    path.mkdir(parents=True)
    (path / "README.md").write_text(readme, encoding="utf-8", newline="\n")
    return path


def main(
    argv: list[str] | None = None, run: Runner = run_command, today: date | None = None
) -> int:
    """Run ``new`` or ``list`` from *argv*, with *run* for gh and git and *today* as the date."""
    args = _parser().parse_args(argv)
    if args.command == "new":
        return _new(
            args.slug, args.issue, args.root, run, today or datetime.now().astimezone().date()
        )
    return _list(args.root, args.status, run)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mise run work --",
        description="Start a work item's folder under work/, or list every work folder.",
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--root", type=Path, default=WORK_ROOT, help="the work root (default: work/)"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser(
        "new", parents=[common], help="make this month's folder for an issue, filing one if none"
    )
    new.add_argument("slug", help="lowercase kebab-case, as in docs-streamline")
    new.add_argument("--issue", type=int, help="the issue's number; without it, file one")
    listing = commands.add_parser("list", parents=[common], help="list work folders")
    listing.add_argument("--status", choices=STATUSES, help="keep folders with this status")
    return parser


def _new(slug: str, issue: int | None, root: Path, run: Runner, today: date) -> int:
    try:
        folder_name(issue, slug)
        if issue is None:
            issue = _file_issue(slug, run)
            title = slug
        else:
            _refuse_a_second_folder(root, issue)
            title = _issue_title(issue, slug, run)
        path = create_folder(slug, issue, title, today, root)
    except (WorkFolderError, FileExistsError, _RefusedError) as error:
        print(f"work: {error}", file=sys.stderr)
        return 1
    print(f"created {path / 'README.md'}")
    return 0


def _issue_title(issue: int, slug: str, run: Runner) -> str:
    """Issue *issue*'s title as gh gives it; else *slug*, with one line on stderr saying why."""
    # REST, not `gh issue view`: a cloud session's proxy refuses the GraphQL that `gh issue` uses.
    # The issues route also answers for a pull request, which this refuses as `gh issue view` did.
    view = [
        "gh",
        "api",
        f"repos/{{owner}}/{{repo}}/issues/{issue}",
        "--jq",
        "{title, pull_request}",
    ]
    reason = "`gh api` answered without an issue's title"
    try:
        answer = json.loads(_output(run, view))
        title = answer["title"]
    except _RefusedError as error:
        reason = str(error)
    # ValueError is malformed JSON; KeyError and TypeError are JSON of another shape.
    except ValueError, KeyError, TypeError:
        pass
    else:
        if answer.get("pull_request") is not None:
            reason = f"`gh api` found pull request {issue}, not an issue"
        elif isinstance(title, str):
            return title
    reason = " ".join(reason.split())
    print(
        f"work: {reason}; titled the README with the slug, {slug!r}: retitle it. Issue {issue} "
        "may not exist: if its number is mistyped, delete the new folder and make it again with "
        "the right number.",
        file=sys.stderr,
    )
    return slug


def _file_issue(slug: str, run: Runner) -> int:
    """File an issue titled *slug* where gh targets, once that is origin's repository."""
    # REST throughout, as in _issue_title: `gh repo view` and `gh issue create` use GraphQL.
    target = _output(run, ["gh", "api", "repos/{owner}/{repo}", "--jq", ".full_name"]).strip()
    remote = _output(run, ["git", "remote", "get-url", "origin"]).strip()
    origin = match[1] if (match := _REMOTE_REPO.search(remote)) else remote
    if target.lower() != origin.lower():
        raise _RefusedError(
            f"gh would file the issue in {target}, but origin is {origin}: run "
            f"`gh repo set-default {origin}`, or file the issue yourself and pass --issue"
        )
    body = (
        f"Filed by `mise run work -- new {slug}`, which titled it with the slug: retitle it to "
        "state the problem or question, and describe it here."
    )
    create = ["gh", "api", f"repos/{target}/issues", "-X", "POST", "-f", f"title={slug}"]
    fields = ["-f", f"body={body}", "-f", "labels[]=needs-triage", "--jq", ".html_url"]
    url = _output(run, [*create, *fields]).strip()
    if not (match := _ISSUE_URL.search(url)):
        raise _RefusedError(f"`gh api` printed {url!r}, not an issue URL; was the issue filed?")
    print(f"filed {url}")
    return int(match[1])


def _output(run: Runner, args: list[str]) -> str:
    """*args*' stdout through *run*; raises _RefusedError naming the command if it cannot run or fails."""
    command = " ".join(args[:3])
    try:
        return run(args)
    except OSError as error:
        raise _RefusedError(f"`{command}` cannot run, {args[0]} unavailable: {error}") from error
    except subprocess.CalledProcessError as error:
        detail = str(error.stderr or "").strip() or f"exit status {error.returncode}"
        raise _RefusedError(f"`{command}` failed: {detail}") from error


def _refuse_a_second_folder(root: Path, issue: int) -> None:
    found = (p for p in root.glob(f"*/{issue}_*") if MONTH_PATTERN.fullmatch(p.parent.name))
    if existing := next((p for p in sorted(found) if p.is_dir()), None):
        raise FileExistsError(f"issue {issue} already has a work folder: {existing}")


def _list(root: Path, wanted: str | None, run: Runner) -> int:
    try:
        folders = scan(root)
    except WorkFolderError as error:
        print(f"work: {error}", file=sys.stderr)
        return 1
    statuses = issue_statuses((f.issue for f in folders if f.issue is not None), run)
    if statuses is None:
        print(
            "work: gh unavailable or signed out, so issue status shows as unknown", file=sys.stderr
        )
        statuses = {}
    rows = []
    for folder in folders:
        if folder.issue is None:
            status: str = folder.status or "unknown"
        else:
            status = statuses.get(folder.issue, "unknown")
        if wanted is None or status == wanted:
            rows.append((folder.month, folder.path.name, status, folder.title, folder.outcome))
    widths = [max((len(row[column]) for row in rows), default=0) for column in range(4)]
    for row in rows:
        cells = [cell.ljust(width) for cell, width in zip(row[:4], widths, strict=True)]
        print("  ".join([*cells, row[4]]).rstrip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
