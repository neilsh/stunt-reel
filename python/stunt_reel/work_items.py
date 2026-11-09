"""The work folders that hold dated records: `work/<YYYY-MM>/<issue>_<slug>/` or `<slug>/`.

A folder's README frontmatter carries `title`, `started` (ISO date, in the folder's month),
`outcome` (empty until the work lands) and, in an issue folder, `issue` (the number in the
folder's name), and no other key. An issue folder's status is its issue's, read through `gh`
by `issue_statuses`. A folder with no issue is a landed record, migrated history or a
distillation, unless its frontmatter carries `status: abandoned`, the one status a folder may
carry, for dropped work.

A folder whose README has a non-empty `outcome` is frozen (work/README.md, Lifecycle):
`frozen_violations` names each file added to one and each change to its `outcome` line.
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
from stunt_reel.git_env import isolated_env

__all__ = [
    "ISSUE_PAGE",
    "MONTH_PATTERN",
    "WORK_ROOT",
    "FrozenViolation",
    "IssueStatus",
    "Runner",
    "Status",
    "WorkFolder",
    "WorkFolderError",
    "folder_name",
    "folder_paths",
    "frozen_violations",
    "is_dated",
    "issue_list",
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
_REQUIRED = ("title", "started", "outcome")
_KEYS = frozenset((*_REQUIRED, "issue", "status"))
# REST, not `gh issue list`: a cloud session's proxy refuses the GraphQL that `gh issue` uses.
# gh fills {owner}/{repo} from the repository it targets; --jq prints one object a line.
#: Issues per page of the issue list; a shorter page is the last.
ISSUE_PAGE = 100
_GIVEN_UP = frozenset(("not_planned", "duplicate"))
_ADDED = "adds a file to a frozen work folder"
_OUTCOME_CHANGED = "changes the outcome of a frozen work folder"


class WorkFolderError(ValueError):
    """A work folder's name or README frontmatter breaks the layout; the message names it."""


@dataclass(frozen=True)
class WorkFolder:
    """One parsed work folder; exactly one of `issue` and `status` is set.

    `status` is derived: `abandoned` when the README says so, else `landed`, for a folder with
    no issue.
    """

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


def is_dated(path: str) -> bool:
    """Whether repo-relative POSIX *path* is a dated record: a month directory of `work/` or in one."""
    parts = path.split("/")
    return len(parts) >= 2 and parts[0] == "work" and MONTH_PATTERN.fullmatch(parts[1]) is not None


def readme_text(
    title: str, started: date, outcome: str, *, issue: int | None = None, status: str | None = None
) -> str:
    """A work folder's whole README.md: its frontmatter, then a `# <title>` heading line.

    *title* and *outcome* are written quoted, so `parse_folder` reads them back unchanged.
    With neither *issue* nor *status*, the README is a landed record's. Raises WorkFolderError
    for a title that is not one non-blank line, an outcome of more than one line, an *issue*
    below 1, a *status* other than `abandoned`, or both an *issue* and a *status*.
    """
    if title.splitlines() != [title] or not title.strip():
        raise WorkFolderError(f"title {title!r} is not one non-blank line")
    if outcome.splitlines() not in ([], [outcome]):
        raise WorkFolderError(f"outcome {outcome!r} is not one line")
    record = ""
    if status is not None:
        _check_status(status)
        if issue is not None:
            raise WorkFolderError("a work folder with an issue takes its status from the issue")
        record = f"status: {status}\n"
    if issue is not None:
        if issue < 1:
            raise WorkFolderError(f"issue {issue} is not a GitHub issue number")
        record = f"issue: {issue}\n"
    return (
        f"---\ntitle: {_quoted(title)}\nstarted: {started.isoformat()}\n{record}"
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


@dataclass(frozen=True)
class FrozenViolation:
    """One change a frozen work folder refuses: the repo-relative POSIX *path* and the *rule*."""

    path: str
    rule: str


def frozen_violations(
    revision: str, paths: Iterable[str], *, staged: bool = False, repo: Path = REPO_ROOT
) -> list[FrozenViolation]:
    """The changes in *paths* that break a work folder frozen at *revision*, sorted by path.

    A folder is frozen when its README.md at *revision* has a non-empty `outcome`. A path in
    one that *revision* lacks but the new side has is added; a README.md whose `outcome` line
    differs on the new side, or is gone, changes the outcome. Edits to other existing files,
    and deletions, pass. The new side is the index when *staged*, else *repo*'s working tree.
    Raises OSError when git cannot run, subprocess.CalledProcessError when *revision* is not
    a commit.
    """
    _git_text(repo, "rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}", check=True)
    by_folder: dict[str, list[str]] = {}
    for path in paths:
        parts = path.split("/")
        if len(parts) >= 4 and is_dated(path):
            by_folder.setdefault("/".join(parts[:3]), []).append(path)
    violations: list[FrozenViolation] = []
    for folder, changed in by_folder.items():
        readme = f"{folder}/README.md"
        old = _git_text(repo, "cat-file", "blob", f"{revision}:{readme}")
        if old is None or not _frozen(old):
            continue
        for path in changed:
            new = _new_text(repo, path, staged=staged)
            if path == readme:
                if new is None or _outcome_line(new) != _outcome_line(old):
                    violations.append(FrozenViolation(path, _OUTCOME_CHANGED))
                continue
            existed = _git_text(repo, "cat-file", "-e", f"{revision}:{path}") is not None
            if new is not None and not existed:
                violations.append(FrozenViolation(path, _ADDED))
    return sorted(violations, key=lambda v: v.path)


def issue_statuses(numbers: Iterable[int], run: Runner) -> dict[int, IssueStatus] | None:
    """The status of each of *numbers*' issues, read through *run* one `issue_list` page at a time.

    An open issue is `active`; a closed one is `abandoned` when closed as not planned or as a
    duplicate, else `landed`. A number gh does not list, or that is a pull request, is left
    out. None when gh cannot run, fails or answers with anything but lines of issues with the
    fields asked for; no call, and `{}`, for no numbers.
    """
    wanted = set(numbers)
    if not wanted:
        return {}
    try:
        issues = []
        page = 1
        while True:
            lines = [line for line in run(issue_list(page)).splitlines() if line]
            issues += [json.loads(line) for line in lines]
            if len(lines) < ISSUE_PAGE:
                break
            page += 1
        return {
            issue["number"]: _issue_status(issue)
            for issue in issues
            if issue["number"] in wanted and issue["pull_request"] is None
        }
    # ValueError is malformed JSON; KeyError and TypeError are JSON of another shape.
    except OSError, subprocess.CalledProcessError, ValueError, KeyError, TypeError:
        return None


def issue_list(page: int) -> list[str]:
    """The `gh api` command for *page* (from 1) of the issue list: one JSON object per line.

    Pages go by number because `gh api --paginate` follows GitHub's next links, which name the
    repository by id (`repositories/<id>/...`), and a cloud session's proxy refuses those
    (`docs/cloud-sessions.md`).
    """
    return [
        "gh",
        "api",
        f"repos/{{owner}}/{{repo}}/issues?state=all&per_page={ISSUE_PAGE}&page={page}",
        "--jq",
        ".[] | {number, state, state_reason, pull_request}",
    ]


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


def _git_text(repo: Path, *args: str, check: bool = False) -> str | None:
    """``git *args``' stdout in *repo* as UTF-8, or None when it exits non-zero and not *check*."""
    # The index stays the caller's: check_work_frozen reads the one `git commit -- <paths>` builds.
    env = isolated_env(keep_index=True)
    done = subprocess.run(  # noqa: S603 - fixed git arguments
        ["git", *args],  # noqa: S607 - git from PATH, as every task
        cwd=repo,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=check,
    )
    if done.returncode != 0:
        return None
    return done.stdout.decode("utf-8", errors="replace")


def _new_text(repo: Path, path: str, *, staged: bool) -> str | None:
    """*path*'s text in the index when *staged*, else in *repo*'s working tree; None if absent."""
    if staged:
        return _git_text(repo, "cat-file", "blob", f":{path}")
    file = repo / path
    return file.read_bytes().decode("utf-8", errors="replace") if file.is_file() else None


def _frozen(readme: str) -> bool:
    """Whether README text *readme* has a frontmatter `outcome` that is not empty."""
    try:
        fields, _ = read_frontmatter(readme)
    except FrontmatterError:
        return False
    return str(fields.get("outcome", "")).strip() != ""


def _outcome_line(readme: str) -> str | None:
    """The `outcome:` line of README text *readme*'s frontmatter, or None without one."""
    lines = readme.splitlines()
    if not lines or lines[0] != "---":
        return None
    for line in lines[1:]:
        if line == "---":
            return None
        if line.startswith("outcome:"):
            return line
    return None


def _quoted(value: str) -> str:
    """*value* as a double-quoted frontmatter scalar, which `read_frontmatter` unquotes."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _issue_status(issue: dict[str, Any]) -> IssueStatus:
    if issue["state"] == "open":
        return "active"
    return "abandoned" if issue["state_reason"] in _GIVEN_UP else "landed"


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


def _check_status(value: object) -> None:
    """Raise WorkFolderError unless *value* is `abandoned`, the one status a folder may carry."""
    if value == "landed":
        raise WorkFolderError("status landed is implied: omit status for a landed record")
    if value != "abandoned":
        raise WorkFolderError(
            f"status {value!r} is not abandoned, the one status a folder may carry"
        )


def _issue_or_status(
    fields: dict[str, str | int], name_issue: int | None
) -> tuple[int | None, Status | None]:
    if "issue" in fields and "status" in fields:
        raise WorkFolderError(
            "frontmatter has both issue and status; an issue folder's status is its issue's"
        )
    if "status" in fields:
        if name_issue is not None:
            raise WorkFolderError(f"name carries issue {name_issue} but frontmatter has status")
        _check_status(fields["status"])
        return None, "abandoned"
    if "issue" not in fields:
        if name_issue is not None:
            raise WorkFolderError(f"name carries issue {name_issue} but frontmatter has no issue")
        return None, "landed"
    issue = fields["issue"]
    if not isinstance(issue, int):
        raise WorkFolderError(f"issue {issue!r} is not an unquoted number")
    if name_issue is None:
        raise WorkFolderError(f"frontmatter has issue {issue} but the name has no issue number")
    if issue != name_issue:
        raise WorkFolderError(f"frontmatter issue {issue} differs from the name's {name_issue}")
    return issue, None
