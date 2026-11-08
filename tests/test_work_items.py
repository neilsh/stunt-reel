"""A work folder under `work/<YYYY-MM>/` parses from its name and README frontmatter, or raises."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from stunt_reel.dataroot import REPO_ROOT
from stunt_reel.work_items import (
    WorkFolderError,
    folder_name,
    issue_statuses,
    parse_folder,
    run_command,
    scan,
)

ISSUE_README = 'title: Docs streamline\nstarted: 2026-11-07\nissue: 307\noutcome: ""\n'
LANDED_README = 'title: T\nstarted: 2026-11-07\nstatus: landed\noutcome: ""\n'


def _folder(root: Path, month: str, name: str, frontmatter: str | None) -> Path:
    path = root / month / name
    path.mkdir(parents=True)
    if frontmatter is not None:
        (path / "README.md").write_text(f"---\n{frontmatter}---\n\n# Title\n", encoding="utf-8")
    return path


def test_folder_name_is_bare_issue_then_slug() -> None:
    assert folder_name(307, "docs-streamline") == "307_docs-streamline"
    assert folder_name(None, "parity-log") == "parity-log"


@pytest.mark.parametrize(("issue", "slug"), [(307, "Docs"), (307, "a_b"), (0, "x"), (None, "-x")])
def test_folder_name_refuses_what_parse_folder_would(issue: int | None, slug: str) -> None:
    with pytest.raises(WorkFolderError):
        folder_name(issue, slug)


def test_parses_an_issue_folder(tmp_path: Path) -> None:
    path = _folder(tmp_path, "2026-11", "307_docs-streamline", ISSUE_README)
    folder = parse_folder(path)
    assert folder.path == path
    assert folder.month == "2026-11"
    assert folder.issue == 307
    assert folder.slug == "docs-streamline"
    assert folder.title == "Docs streamline"
    assert folder.started == date(2026, 11, 7)
    assert folder.outcome == ""
    assert folder.status is None


@pytest.mark.parametrize("status", ["landed", "abandoned"])
def test_parses_an_issue_less_folder(tmp_path: Path, status: str) -> None:
    frontmatter = f"title: Parity log\nstarted: 2026-10-01\nstatus: {status}\noutcome: Moved\n"
    folder = parse_folder(_folder(tmp_path, "2026-10", "parity-log", frontmatter))
    assert folder.issue is None
    assert folder.status == status
    assert folder.slug == "parity-log"
    assert folder.outcome == "Moved"


# problem: (month directory, folder name, README frontmatter or None for no README, reason)
INVALID: dict[str, tuple[str, str, str | None, str]] = {
    "both issue and status": (
        "2026-11",
        "307_x",
        ISSUE_README + "status: landed\n",
        "exactly one of issue and status",
    ),
    "neither issue nor status": (
        "2026-11",
        "x",
        'title: T\nstarted: 2026-11-07\noutcome: ""\n',
        "exactly one of issue and status",
    ),
    "status: active": (
        "2026-11",
        "x",
        LANDED_README.replace("landed", "active"),
        "not landed or abandoned",
    ),
    "issue in name but not frontmatter": (
        "2026-11",
        "307_x",
        LANDED_README,
        "name carries issue 307",
    ),
    "issue in frontmatter but not name": (
        "2026-11",
        "x",
        ISSUE_README,
        "the name has no issue number",
    ),
    "frontmatter issue differs from name": (
        "2026-11",
        "308_x",
        ISSUE_README,
        "differs from the name's 308",
    ),
    "issue quoted": (
        "2026-11",
        "307_x",
        ISSUE_README.replace("307", '"307"'),
        "not an unquoted number",
    ),
    "issue padded in name": ("2026-11", "0307_x", ISSUE_README, "name is not"),
    "started month differs from parent month": (
        "2026-10",
        "307_x",
        ISSUE_README,
        "not in the folder's month",
    ),
    "started not an ISO date": (
        "2026-11",
        "307_x",
        ISSUE_README.replace("2026-11-07", "7 Nov"),
        "not an ISO date",
    ),
    "started not a calendar date": (
        "2026-11",
        "307_x",
        ISSUE_README.replace("-07", "-31"),
        "not a calendar date",
    ),
    "parent not a month": ("misc", "307_x", ISSUE_README, "not a YYYY-MM month directory"),
    "slug with capitals": ("2026-11", "307_Docs-Streamline", ISSUE_README, "name is not"),
    "slug with a trailing hyphen": ("2026-11", "307_docs-", ISSUE_README, "name is not"),
    "missing README.md": ("2026-11", "307_x", None, "no README.md"),
    "malformed frontmatter": ("2026-11", "307_x", "title T\n", "not a 'key: value' pair"),
    "missing title": (
        "2026-11",
        "307_x",
        ISSUE_README.replace("title: Docs streamline\n", ""),
        "lacks title",
    ),
    "missing outcome": (
        "2026-11",
        "307_x",
        ISSUE_README.replace('outcome: ""\n', ""),
        "lacks outcome",
    ),
    "title of digits": (
        "2026-11",
        "307_x",
        ISSUE_README.replace("Docs streamline", "1942"),
        "title must be non-empty text",
    ),
    "unknown key": ("2026-11", "307_x", ISSUE_README + "owner: me\n", "unknown keys: owner"),
}


@pytest.mark.parametrize("problem", list(INVALID))
def test_invalid_folders_raise(tmp_path: Path, problem: str) -> None:
    month, name, frontmatter, reason = INVALID[problem]
    with pytest.raises(WorkFolderError, match=rf"^{month}/{name}: .*{re.escape(reason)}"):
        parse_folder(_folder(tmp_path, month, name, frontmatter))


def test_scan_sorts_by_month_then_issue_with_issue_less_last(tmp_path: Path) -> None:
    def readme(month: str, issue: int | None) -> str:
        tail = f"issue: {issue}\n" if issue is not None else "status: landed\n"
        return f'title: T\nstarted: {month}-01\noutcome: ""\n{tail}'

    for month, issue, slug in [
        ("2026-11", None, "b"),
        ("2026-11", 307, "x"),
        ("2026-11", None, "a"),
        ("2026-11", 99, "y"),
        ("2026-10", 400, "z"),
    ]:
        _folder(tmp_path, month, folder_name(issue, slug), readme(month, issue))
    (tmp_path / "README.md").write_text("# Work\n", encoding="utf-8")
    names = [f"{f.month}/{f.path.name}" for f in scan(tmp_path)]
    assert names == ["2026-10/400_z", "2026-11/99_y", "2026-11/307_x", "2026-11/a", "2026-11/b"]


def test_scan_names_every_bad_folder_in_one_error(tmp_path: Path) -> None:
    _folder(tmp_path, "2026-11", "307_x", ISSUE_README)
    _folder(tmp_path, "2026-11", "Bad", ISSUE_README)
    _folder(tmp_path, "2026-11", "308_y", None)
    with pytest.raises(WorkFolderError) as raised:
        scan(tmp_path)
    message = str(raised.value)
    assert "2026-11/Bad: " in message
    assert "2026-11/308_y: " in message
    assert "307_x" not in message


def test_scan_of_a_missing_root_is_empty(tmp_path: Path) -> None:
    assert scan(tmp_path / "work") == []


ISSUE_LIST = [
    "gh",
    "issue",
    "list",
    "--state",
    "all",
    "--limit",
    "2000",
    "--json",
    "number,state,stateReason",
]


def test_issue_statuses_reads_every_issue_in_one_gh_call() -> None:
    issues = [
        {"number": 307, "state": "OPEN", "stateReason": ""},
        {"number": 306, "state": "OPEN", "stateReason": "REOPENED"},
        {"number": 300, "state": "CLOSED", "stateReason": "COMPLETED"},
        {"number": 301, "state": "CLOSED", "stateReason": "NOT_PLANNED"},
        {"number": 302, "state": "CLOSED", "stateReason": "DUPLICATE"},
        {"number": 5, "state": "OPEN", "stateReason": ""},
    ]
    calls: list[list[str]] = []

    def run(args: list[str]) -> str:
        calls.append(args)
        return json.dumps(issues)

    assert issue_statuses([307, 306, 300, 301, 302, 999], run) == {
        307: "active",
        306: "active",
        300: "landed",
        301: "abandoned",
        302: "abandoned",
    }
    assert calls == [ISSUE_LIST]


@pytest.mark.parametrize(
    "error",
    [FileNotFoundError(2, "No such file", "gh"), subprocess.CalledProcessError(4, ISSUE_LIST)],
)
def test_issue_statuses_is_none_when_gh_cannot_answer(error: Exception) -> None:
    def run(_args: list[str]) -> str:
        raise error

    assert issue_statuses([307], run) is None


@pytest.mark.parametrize(
    "answer",
    [
        "gh: not JSON",
        '{"number": 307}',
        '[{"number": 307, "state": "OPEN"}, {"number": 300, "state": "CLOSED"}]',
        '[{"state": "OPEN", "stateReason": ""}]',
        "[307]",
    ],
    ids=["not-json", "not-a-list", "no-state-reason", "no-number", "not-objects"],
)
def test_issue_statuses_is_none_when_gh_answers_unexpected_json(answer: str) -> None:
    assert issue_statuses([307, 300], lambda _args: answer) is None


def test_issue_statuses_of_no_issues_calls_nothing() -> None:
    def run(args: list[str]) -> str:
        raise AssertionError(args)

    assert issue_statuses([], run) == {}


def test_run_command_returns_stdout_or_raises() -> None:
    utf8 = r"import sys; sys.stdout.buffer.write('\u00e9'.encode())"
    assert run_command([sys.executable, "-c", utf8]) == "\u00e9"
    with pytest.raises(subprocess.CalledProcessError) as failed:
        run_command([sys.executable, "-c", "import sys; sys.exit('no auth')"])
    assert "no auth" in failed.value.stderr
    with pytest.raises(FileNotFoundError):
        run_command(["stunt-reel-no-such-command"])


def test_run_command_runs_in_the_repository_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(REPO_ROOT / "python")
    where = run_command([sys.executable, "-c", "import os; print(os.getcwd())"])
    assert Path(where.strip()).resolve() == REPO_ROOT.resolve()
