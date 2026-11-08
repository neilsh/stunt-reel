"""`mise run work`: `new` makes this month's folder for an issue, `list` shows each one's status."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from stunt_reel.work_items import parse_folder, scan

SCRIPTS = Path(__file__).resolve().parent.parent / "python" / "scripts"
TODAY = date(2026, 11, 7)
ISSUE_TITLE = "Streamline docs into evergreen notes and dated work folders"
#: The commands `new` runs, by the first three words FakeRunner keys them on.
TITLE = "gh api repos/{owner}/{repo}/issues/307"
TARGET = "gh api repos/{owner}/{repo}"
CREATE = "gh api repos/neilsh/stunt-reel/issues"
#: Issues as `gh api --jq` prints them, one JSON object a line.
ISSUES = "".join(
    json.dumps({"number": number, "state": state, "state_reason": reason, "pull_request": None})
    + "\n"
    for number, state, reason in (
        (307, "open", None),
        (300, "closed", "completed"),
        (301, "closed", "not_planned"),
    )
)


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("work", SCRIPTS / "work.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


work = _load()


class FakeRunner:
    """Answers a command by its first three words, raising an answer that is an exception."""

    def __init__(self, answers: dict[str, str | Exception]) -> None:
        self.answers = answers
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> str:
        self.calls.append(args)
        answer = self.answers[" ".join(args[:3])]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def called(self, command: str) -> list[list[str]]:
        return [args for args in self.calls if " ".join(args).startswith(command)]


def _issue(title: str, pull_request: dict[str, str] | None = None) -> str:
    """The issue as `gh api --jq '{title, pull_request}'` prints it."""
    return json.dumps({"title": title, "pull_request": pull_request}) + "\n"


def _no_gh(args: list[str]) -> str:
    raise FileNotFoundError(2, "No such file or directory", args[0])


def _gh_signed_out(args: list[str]) -> str:
    raise subprocess.CalledProcessError(
        4, args, "", "To get started with GitHub CLI, run gh auth login"
    )


GH_FAILURES = pytest.mark.parametrize(
    "run", [_no_gh, _gh_signed_out], ids=["missing", "signed-out"]
)


def _main(root: Path, *argv: str, run: Any) -> int:
    code: int = work.main([*argv, "--root", str(root)], run=run, today=TODAY)
    return code


def _folder(root: Path, month: str, name: str, frontmatter: str) -> Path:
    path = root / month / name
    path.mkdir(parents=True)
    (path / "README.md").write_text(f"---\n{frontmatter}---\n\n# T\n", encoding="utf-8")
    return path


def _issue_folder(root: Path, month: str, issue: int, slug: str, outcome: str = "") -> Path:
    fields = f'title: Item {issue}\nstarted: {month}-01\nissue: {issue}\noutcome: "{outcome}"\n'
    return _folder(root, month, f"{issue}_{slug}", fields)


def _issue_less_folder(root: Path, month: str, slug: str, *, abandoned: bool = False) -> Path:
    status = "status: abandoned\n" if abandoned else ""
    fields = f"title: Item {slug}\nstarted: {month}-01\n{status}outcome: Moved\n"
    return _folder(root, month, slug, fields)


def _columns(out: str) -> list[list[str]]:
    """Month, folder and status of each line `list` printed."""
    return [line.split()[:3] for line in out.splitlines()]


def test_new_with_issue_makes_this_months_folder(tmp_path: Path) -> None:
    run = FakeRunner({TITLE: _issue(ISSUE_TITLE)})
    assert _main(tmp_path, "new", "docs-streamline", "--issue", "307", run=run) == 0
    path = tmp_path / "2026-11" / "307_docs-streamline"
    assert (path / "README.md").is_file()
    folder = parse_folder(path)
    assert (folder.issue, folder.slug, folder.title) == (307, "docs-streamline", ISSUE_TITLE)
    assert (folder.started, folder.outcome, folder.status) == (TODAY, "", None)
    assert run.calls == [
        ["gh", "api", "repos/{owner}/{repo}/issues/307", "--jq", "{title, pull_request}"]
    ]


def test_new_without_issue_files_one_after_checking_the_repo(tmp_path: Path) -> None:
    run = FakeRunner(
        {
            TARGET: "neilsh/stunt-reel\n",
            "git remote get-url": "https://github.com/neilsh/stunt-reel.git\n",
            CREATE: "https://github.com/neilsh/stunt-reel/issues/412\n",
        }
    )
    assert _main(tmp_path, "new", "docs-streamline", run=run) == 0
    folder = parse_folder(tmp_path / "2026-11" / "412_docs-streamline")
    assert (folder.issue, folder.title) == (412, "docs-streamline")
    [create] = run.called(CREATE)
    assert create[:5] == ["gh", "api", "repos/neilsh/stunt-reel/issues", "-X", "POST"]
    fields = [create[i + 1] for i, flag in enumerate(create) if flag == "-f"]
    assert fields[0] == "title=docs-streamline"
    assert fields[1].startswith("body=Filed by `mise run work -- new docs-streamline`")
    assert fields[2:] == ["labels[]=needs-triage"]
    assert run.calls.index(create) > run.calls.index(run.called(TARGET)[0])


@pytest.mark.parametrize(
    "origin", ["git@github.com:me/stunt-reel.git", "https://github.com/me/stunt-reel"]
)
def test_new_without_issue_refuses_a_repo_other_than_origin(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], origin: str
) -> None:
    run = FakeRunner({TARGET: "neilsh/stunt-reel\n", "git remote get-url": origin})
    assert _main(tmp_path, "new", "docs-streamline", run=run) == 1
    assert run.called(CREATE) == []
    assert list(tmp_path.iterdir()) == []
    err = capsys.readouterr().err
    assert "neilsh/stunt-reel" in err
    assert "me/stunt-reel" in err


@pytest.mark.parametrize("existing", ["2026-11/307_docs-streamline", "2026-10/307_old-name"])
def test_new_refuses_an_existing_folder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], existing: str
) -> None:
    month, name = existing.split("/")
    readme = _issue_folder(tmp_path, month, 307, name.partition("_")[2]) / "README.md"
    before = readme.read_bytes()
    run = FakeRunner({})
    assert _main(tmp_path, "new", "docs-streamline", "--issue", "307", run=run) == 1
    assert readme.read_bytes() == before
    assert run.calls == []
    assert existing in capsys.readouterr().err.replace("\\", "/")
    assert [f.path.name for f in scan(tmp_path)] == [name]


@pytest.mark.parametrize("argv", [["Docs_Streamline"], ["docs", "--issue", "0"]])
def test_new_checks_slug_and_issue_before_calling_gh(tmp_path: Path, argv: list[str]) -> None:
    run = FakeRunner({})
    assert _main(tmp_path, "new", *argv, run=run) == 1
    assert run.calls == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "run",
    [
        _no_gh,
        _gh_signed_out,
        FakeRunner(
            {
                TITLE: subprocess.CalledProcessError(
                    1, ["gh"], "", 'gh: Not Found (HTTP 404)\n{"message": "Not Found"}\n'
                )
            }
        ),
        FakeRunner({TITLE: "not json"}),
        FakeRunner({TITLE: json.dumps({"pull_request": None})}),
        FakeRunner({TITLE: _issue("A pull request", pull_request={"url": "u"})}),
    ],
    ids=["missing", "signed-out", "two-line-error", "garbled", "no-title", "pull-request"],
)
def test_new_with_issue_but_no_title_from_gh_titles_it_with_the_slug(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], run: Any
) -> None:
    assert _main(tmp_path, "new", "docs-streamline", "--issue", "307", run=run) == 0
    folder = parse_folder(tmp_path / "2026-11" / "307_docs-streamline")
    assert (folder.issue, folder.title, folder.outcome) == (307, "docs-streamline", "")
    out, err = capsys.readouterr()
    assert out.startswith("created ")
    assert len(err.splitlines()) == 1
    assert err.startswith("work: `gh ")
    assert err.endswith(
        "; titled the README with the slug, 'docs-streamline': retitle it. Issue 307 may not "
        "exist: if its number is mistyped, delete the new folder and make it again with the "
        "right number.\n"
    )
    assert "Traceback" not in err


@GH_FAILURES
def test_new_without_issue_or_gh_fails_cleanly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], run: Any
) -> None:
    assert _main(tmp_path, "new", "docs-streamline", run=run) == 1
    assert list(tmp_path.iterdir()) == []
    err = capsys.readouterr().err
    assert "gh" in err
    assert "Traceback" not in err


@pytest.mark.parametrize(
    "title", ["1942", "Why: the colon stays", 'Say "hi"', 'C:\\dir\\ "quoted\\"', " padded "]
)
def test_new_writes_a_title_that_parses_back(tmp_path: Path, title: str) -> None:
    run = FakeRunner({"gh api repos/{owner}/{repo}/issues/5": _issue(title)})
    assert _main(tmp_path, "new", "x", "--issue", "5", run=run) == 0
    assert parse_folder(tmp_path / "2026-11" / "5_x").title == title


@pytest.mark.parametrize("title", ["two\nlines", "line\u2028separator", "   "])
def test_new_refuses_a_title_that_cannot_be_one_frontmatter_line(
    tmp_path: Path, title: str
) -> None:
    run = FakeRunner({"gh api repos/{owner}/{repo}/issues/5": _issue(title)})
    assert _main(tmp_path, "new", "x", "--issue", "5", run=run) == 1
    assert list(tmp_path.iterdir()) == []


def test_list_maps_issue_states(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _issue_folder(tmp_path, "2026-11", 307, "docs-streamline")
    _issue_folder(tmp_path, "2026-11", 300, "shipped", outcome="Merged as #310")
    _issue_folder(tmp_path, "2026-11", 301, "dropped")
    _issue_folder(tmp_path, "2026-11", 302, "unlisted")
    _issue_less_folder(tmp_path, "2026-10", "parity-log")
    run = FakeRunner({"gh api --paginate": ISSUES})
    assert _main(tmp_path, "list", run=run) == 0
    out, err = capsys.readouterr()
    assert _columns(out) == [
        ["2026-10", "parity-log", "landed"],
        ["2026-11", "300_shipped", "landed"],
        ["2026-11", "301_dropped", "abandoned"],
        ["2026-11", "302_unlisted", "unknown"],
        ["2026-11", "307_docs-streamline", "active"],
    ]
    lines = out.splitlines()
    assert "Item parity-log" in lines[0]
    assert lines[0].endswith("Moved")
    assert "Item 300 " in lines[1]
    assert lines[1].endswith("  Merged as #310")
    assert lines[4] == lines[4].rstrip()
    assert err == ""
    assert len(run.calls) == 1


@GH_FAILURES
def test_list_without_gh_shows_unknown_and_one_note(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], run: Any
) -> None:
    _issue_folder(tmp_path, "2026-11", 307, "docs-streamline")
    _issue_folder(tmp_path, "2026-11", 300, "shipped")
    _issue_less_folder(tmp_path, "2026-10", "parity-log")
    assert _main(tmp_path, "list", run=run) == 0
    out, err = capsys.readouterr()
    assert _columns(out) == [
        ["2026-10", "parity-log", "landed"],
        ["2026-11", "300_shipped", "unknown"],
        ["2026-11", "307_docs-streamline", "unknown"],
    ]
    assert len(err.splitlines()) == 1
    assert "gh unavailable" in err


@pytest.mark.parametrize(
    ("status", "names"),
    [
        ("active", ["307_docs-streamline"]),
        ("landed", ["parity-log", "300_shipped"]),
        ("abandoned", ["301_dropped", "old-idea"]),
    ],
)
def test_list_filters_by_status(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], status: str, names: list[str]
) -> None:
    _issue_folder(tmp_path, "2026-11", 307, "docs-streamline")
    _issue_folder(tmp_path, "2026-11", 300, "shipped")
    _issue_folder(tmp_path, "2026-11", 301, "dropped")
    _issue_less_folder(tmp_path, "2026-10", "parity-log")
    _issue_less_folder(tmp_path, "2026-11", "old-idea", abandoned=True)
    assert (
        _main(tmp_path, "list", "--status", status, run=FakeRunner({"gh api --paginate": ISSUES}))
        == 0
    )
    assert [columns[1] for columns in _columns(capsys.readouterr().out)] == names


def test_list_reports_a_bad_folder_and_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _issue_folder(tmp_path, "2026-11", 307, "docs-streamline")
    (tmp_path / "2026-11" / "308_no-readme").mkdir()
    run = FakeRunner({})
    assert _main(tmp_path, "list", run=run) == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert "2026-11/308_no-readme: has no README.md" in err
    assert run.calls == []


def test_list_of_issue_less_folders_needs_no_gh(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _issue_less_folder(tmp_path, "2026-10", "parity-log")
    assert _main(tmp_path, "list", run=_no_gh) == 0
    out, err = capsys.readouterr()
    assert _columns(out) == [["2026-10", "parity-log", "landed"]]
    assert err == ""
