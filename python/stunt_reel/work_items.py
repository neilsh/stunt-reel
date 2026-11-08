"""The work folders that hold dated records: `work/<YYYY-MM>/<issue>_<slug>/` or `<slug>/`.

A folder's README frontmatter carries `title`, `started` (ISO date, in the folder's month),
`outcome` (empty until the work lands) and exactly one of `issue` (the number in the folder's
name) or `status` (`landed` or `abandoned`, for a folder with no issue), and no other key. An
issue folder's status is its issue's, read through `gh` by `issue_statuses`.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal
lazy from collections.abc import Callable, Iterable
lazy from pathlib import Path

from stunt_reel.dataroot import REPO_ROOT
from stunt_reel.frontmatter import FrontmatterError, read_frontmatter

__all__ = [
    "MONTH_PATTERN",
    "WORK_ROOT",
    "IssueStatus",
    "Runner",
    "Status",
    "WorkFolder",
    "WorkFolderError",
    "folder_name",
    "folder_paths",
    "issue_statuses",
    "parse_folder",
    "readme_text",
    "run_command",
    "scan",
]

WORK_ROOT = REPO_ROOT / "work"
#: A month directory's name, `YYYY-MM`.
MONTH_PATTERN = re.compile(r"[0-9]{4}-(0[1-9]|1[0-2])")

type Status = Literal["landed", "abandoned"]
#: A work item's status as its GitHub issue gives it.
type IssueStatus = Literal["active", "landed", "abandoned"]
#: Runs a command and returns its stdout; raises OSError (FileNotFoundError for a missing
#: program) or subprocess.CalledProcessError. `run_command` is the real one.
type Runner = Callable[[list[str]], str]

_SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
_ISSUE_NAME = re.compile(rf"([1-9][0-9]*)_({_SLUG})")
_SLUG_NAME = re.compile(_SLUG)
_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_STATUSES: dict[str | int, Status] = {"landed": "landed", "abandoned": "abandoned"}
_REQUIRED = ("title", "started", "outcome")
_KEYS = frozenset((*_REQUIRED, "issue", "status"))
_ISSUE_LIST = ("gh", "issue", "list", "--state", "all", "--limit", "2000", "--json")
_ISSUE_FIELDS = "number,state,stateReason"
_GIVEN_UP = frozenset(("NOT_PLANNED", "DUPLICATE"))


class WorkFolderError(ValueError):
    """A work folder's name or README frontmatter breaks the layout; the message names it."""


@dataclass(frozen=True)
class WorkFolder:
    """One parsed work folder; exactly one of `issue` and `status` is set."""

    path: Path
    month: str
    issue: int | None
    slug: str
    title: str
    started: date
    outcome: str
    status: Status | None


def folder_name(issue: int | None, slug: str) -> str:
    """The folder name for *issue* and *slug*: `307_docs-streamline`, or the bare slug.

    Raises WorkFolderError for a slug that is not lowercase kebab-case or an issue below 1.
    """
    if not _SLUG_NAME.fullmatch(slug):
        raise WorkFolderError(f"slug {slug!r} is not lowercase kebab-case")
    if issue is None:
        return slug
    if issue < 1:
        raise WorkFolderError(f"issue {issue} is not a GitHub issue number")
    return f"{issue}_{slug}"


def readme_text(
    title: str, started: date, outcome: str, *, issue: int | None = None, status: str | None = None
) -> str:
    """A work folder's whole README.md: its frontmatter, then a `# <title>` heading line.

    *title* and *outcome* are written quoted, so `parse_folder` reads them back unchanged.
    Raises WorkFolderError for a title that is not one non-blank line, an outcome of more than
    one line, or anything but exactly one of an *issue* of 1 or more and a *status* of
    `landed` or `abandoned`.
    """
    if title.splitlines() != [title] or not title.strip():
        raise WorkFolderError(f"title {title!r} is not one non-blank line")
    if outcome.splitlines() not in ([], [outcome]):
        raise WorkFolderError(f"outcome {outcome!r} is not one line")
    if (issue is None) == (status is None):
        raise WorkFolderError("a work folder needs exactly one of issue and status")
    if issue is not None:
        if issue < 1:
            raise WorkFolderError(f"issue {issue} is not a GitHub issue number")
        record = f"issue: {issue}"
    else:
        if status not in _STATUSES:
            raise WorkFolderError(f"status {status!r} is not landed or abandoned")
        record = f"status: {status}"
    return (
        f"---\ntitle: {_quoted(title)}\nstarted: {started.isoformat()}\n{record}\n"
        f"outcome: {_quoted(outcome)}\n---\n\n# {title}\n"
    )


def parse_folder(path: Path) -> WorkFolder:
    """The work folder at *path*, from its name, its month directory and its README.md.

    Raises WorkFolderError, starting `<month>/<name>: `, for the first rule the folder breaks.
    """
    try:
        return _parse(path)
    except WorkFolderError as error:
        raise WorkFolderError(f"{path.parent.name}/{path.name}: {error}") from error


def folder_paths(root: Path = WORK_ROOT) -> list[Path]:
    """The directories in *root*'s `YYYY-MM` directories, sorted: every work folder, valid or not.

    Other entries in *root* and files in month directories are skipped. A missing *root* has
    none.
    """
    if not root.is_dir():
        return []
    months = [d for d in root.iterdir() if d.is_dir() and MONTH_PATTERN.fullmatch(d.name)]
    return sorted(path for month in months for path in month.iterdir() if path.is_dir())


def scan(root: Path = WORK_ROOT) -> list[WorkFolder]:
    """The `folder_paths` of *root*, parsed, by month, then issue, then issue-less by slug.

    Raises one WorkFolderError naming every bad folder, a line each.
    """
    folders: list[WorkFolder] = []
    problems: list[str] = []
    for path in folder_paths(root):
        try:
            folders.append(parse_folder(path))
        except WorkFolderError as error:
            problems.append(str(error))
    if problems:
        lines = "\n".join(f"  {problem}" for problem in sorted(problems))
        raise WorkFolderError(f"{len(problems)} work folder(s) invalid:\n{lines}")
    return sorted(folders, key=lambda f: (f.month, f.issue is None, f.issue or 0, f.slug))


def issue_statuses(numbers: Iterable[int], run: Runner) -> dict[int, IssueStatus] | None:
    """The status of each of *numbers*' issues, read with one `gh issue list` through *run*.

    An open issue is `active`; a closed one is `abandoned` when closed as not planned or as a
    duplicate, else `landed`. A number gh does not list is left out. None when gh cannot run,
    fails or answers with anything but a list of issues with the fields asked for; no call,
    and `{}`, for no numbers.
    """
    wanted = set(numbers)
    if not wanted:
        return {}
    try:
        issues = json.loads(run([*_ISSUE_LIST, _ISSUE_FIELDS]))
        return {
            issue["number"]: _issue_status(issue) for issue in issues if issue["number"] in wanted
        }
    # ValueError is malformed JSON; KeyError and TypeError are JSON of another shape.
    except OSError, subprocess.CalledProcessError, ValueError, KeyError, TypeError:
        return None


def run_command(args: list[str]) -> str:
    """The default Runner: *args*' stdout, run in the repository root with no stdin, as UTF-8.

    Raises OSError when the program cannot start (FileNotFoundError when it is missing) and
    subprocess.CalledProcessError, carrying stderr, when it exits non-zero.
    """
    done = subprocess.run(  # noqa: S603 - callers pass fixed gh and git commands
        args,
        cwd=REPO_ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return done.stdout


def _quoted(value: str) -> str:
    """*value* as a double-quoted frontmatter scalar, which `read_frontmatter` unquotes."""
    escaped = value.replace('"', '\\"')
    return f'"{escaped}"'


def _issue_status(issue: dict[str, Any]) -> IssueStatus:
    if issue["state"] == "OPEN":
        return "active"
    return "abandoned" if issue["stateReason"] in _GIVEN_UP else "landed"


def _parse(path: Path) -> WorkFolder:
    month = path.parent.name
    if not MONTH_PATTERN.fullmatch(month):
        raise WorkFolderError("its parent is not a YYYY-MM month directory")
    name_issue, slug = _split_name(path.name)
    fields = _read_fields(path / "README.md")
    title, outcome = fields["title"], fields["outcome"]
    if not isinstance(title, str) or not title.strip():
        raise WorkFolderError("title must be non-empty text (quote a title of digits)")
    if not isinstance(outcome, str):
        raise WorkFolderError("outcome must be text (quote an outcome of digits)")
    started = _started(fields["started"], month)
    issue, status = _issue_or_status(fields, name_issue)
    return WorkFolder(path, month, issue, slug, title, started, outcome, status)


def _split_name(name: str) -> tuple[int | None, str]:
    if match := _ISSUE_NAME.fullmatch(name):
        return int(match[1]), match[2]
    if _SLUG_NAME.fullmatch(name):
        return None, name
    raise WorkFolderError(
        "name is not '<issue>_<slug>' or '<slug>' with a lowercase kebab-case slug"
    )


def _read_fields(readme: Path) -> dict[str, str | int]:
    if not readme.is_file():
        raise WorkFolderError("has no README.md")
    try:
        fields, _ = read_frontmatter(readme.read_text(encoding="utf-8"))
    except (FrontmatterError, UnicodeDecodeError) as error:
        raise WorkFolderError(f"README.md: {error}") from error
    if unknown := sorted(fields.keys() - _KEYS):
        raise WorkFolderError(f"README.md frontmatter has unknown keys: {', '.join(unknown)}")
    if missing := [key for key in _REQUIRED if key not in fields]:
        raise WorkFolderError(f"README.md frontmatter lacks {', '.join(missing)}")
    return fields


def _started(value: str | int, month: str) -> date:
    # A strict pattern first: fromisoformat also takes `20261107` and week dates.
    if not isinstance(value, str) or not _ISO_DATE.fullmatch(value):
        raise WorkFolderError(f"started {value!r} is not an ISO date, YYYY-MM-DD")
    try:
        started = date.fromisoformat(value)
    except ValueError:
        raise WorkFolderError(f"started {value} is not a calendar date") from None
    if started.strftime("%Y-%m") != month:
        raise WorkFolderError(f"started {value} is not in the folder's month, {month}")
    return started


def _issue_or_status(
    fields: dict[str, str | int], name_issue: int | None
) -> tuple[int | None, Status | None]:
    if ("issue" in fields) == ("status" in fields):
        raise WorkFolderError("frontmatter needs exactly one of issue and status")
    if "status" in fields:
        status = _STATUSES.get(fields["status"])
        if status is None:
            raise WorkFolderError(f"status {fields['status']!r} is not landed or abandoned")
        if name_issue is not None:
            raise WorkFolderError(f"name carries issue {name_issue} but frontmatter has status")
        return None, status
    issue = fields["issue"]
    if not isinstance(issue, int):
        raise WorkFolderError(f"issue {issue!r} is not an unquoted number")
    if name_issue is None:
        raise WorkFolderError(f"frontmatter has issue {issue} but the name has no issue number")
    if issue != name_issue:
        raise WorkFolderError(f"frontmatter issue {issue} differs from the name's {name_issue}")
    return issue, None
