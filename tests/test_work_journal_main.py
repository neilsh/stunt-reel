"""A work journal line the branch adds may name main only a commit main holds (issue #1005).

`branch_violations` reads the lines the branch adds to a work folder's `journal.md` and names each
``main`` at ``<sha>`` whose commit is not an ancestor of the gate's base; a line the branch does
not add is not read, so an older journal's shas never fail it. `check_work_journal_main.py` runs
the rule, and the documentation test at the end of this module runs it on the branch since the
gate's base, so the gate and CI check it too.
"""

from __future__ import annotations

import os
import shutil
import subprocess
lazy from pathlib import Path

import check_work_journal_main
import gate
import pytest
from added_lines import AddedLine

from stunt_reel.dataroot import REPO_ROOT

pytestmark = pytest.mark.docs

# The fixtures build their paths from this part, so this file names no journal path of its own
# for test_code_cited_docs_exist to look up.
WORK = "work"
JOURNAL = f"{WORK}/2026-11/1005_journal-main/journal.md"
#: A sha git cannot resolve, well formed so the claim regex reads it.
UNKNOWN = "0" * 40

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def _git(repo: Path, *args: str) -> str:
    """Run git args in repo with a fixed identity; return its stdout."""
    git = shutil.which("git")
    assert git is not None, "git is not on PATH"
    done = subprocess.run(  # noqa: S603 - fixed git arguments
        [git, *args],
        cwd=repo,
        env={**os.environ, **_GIT_ENV},
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    # Quote git's own reason: one exit 128 under concurrent gates lost it (issue #571).
    assert done.returncode == 0, f"git {' '.join(args)}: exit {done.returncode}, {done.stderr!r}"
    return done.stdout


def _write(repo: Path, name: str, text: str) -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def _journal(*lines: str) -> str:
    return "# Journal\n\n## 2026-11-23: an entry\n\n" + "\n".join(lines) + "\n"


def _add(repo: Path, *lines: str) -> None:
    """Append lines to the journal in the working tree, uncommitted."""
    path = repo / JOURNAL
    path.write_text(path.read_text(encoding="utf-8") + "\n".join(lines) + "\n", encoding="utf-8")


def _head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").strip()


def _branch_only_commit(repo: Path) -> str:
    """A commit on a ``feat`` branch that main does not hold; returns its sha."""
    _git(repo, "switch", "-q", "-c", "feat")
    _write(repo, "notes.md", "branch work\n")
    _git(repo, "add", "notes.md")
    _git(repo, "commit", "-qm", "branch work")
    return _head(repo)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """One commit on `main` holding a work folder's journal."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _write(root, JOURNAL, _journal("An entry."))
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "base")
    return root


def test_a_claim_on_a_branch_only_commit_fails(repo: Path) -> None:
    branch = _branch_only_commit(repo)
    _add(repo, f"**Method**: `main` at `{branch}`.")

    violations = check_work_journal_main.branch_violations(repo)

    assert [(v.path, v.sha) for v in violations] == [(JOURNAL, branch)]


def test_a_claim_on_a_commit_main_holds_passes(repo: Path) -> None:
    base = _head(repo)
    _branch_only_commit(repo)
    _add(repo, f"**Method**: `main` at `{base}`.")

    assert check_work_journal_main.branch_violations(repo) == []


def test_an_unknown_sha_fails(repo: Path) -> None:
    _branch_only_commit(repo)
    _add(repo, f"**Method**: `main` at `{UNKNOWN}`.")

    assert [v.sha for v in check_work_journal_main.branch_violations(repo)] == [UNKNOWN]


def test_a_line_the_branch_does_not_add_is_not_read(repo: Path) -> None:
    _write(repo, JOURNAL, _journal(f"An older entry: `main` at `{UNKNOWN}`."))
    _git(repo, "add", JOURNAL)
    _git(repo, "commit", "-qm", "an old claim main never held")
    _branch_only_commit(repo)
    _add(repo, "A new entry that names no commit.")

    assert check_work_journal_main.branch_violations(repo) == []


def test_an_untracked_journal_is_read(repo: Path) -> None:
    branch = _branch_only_commit(repo)
    untracked = f"{WORK}/2026-11/1006_new/journal.md"
    _write(repo, untracked, _journal(f"**Method**: `main` at `{branch}`."))

    assert [v.path for v in check_work_journal_main.branch_violations(repo)] == [untracked]


@pytest.mark.parametrize(
    ("text", "sha"),
    [
        ("`main` at `abc1234`", "abc1234"),
        ("on `main` at `9549ef5f`: static", "9549ef5f"),
        ("`origin/main` at `abc1234`", None),
        ("`main` at `the time`", None),
        ("main at abc1234", None),
        ("`main` at `abc12`", None),
    ],
)
def test_claims_matches_the_claim_format(text: str, sha: str | None) -> None:
    found = check_work_journal_main.claims([AddedLine(JOURNAL, 1, text)])

    assert [claim.sha for claim in found] == ([] if sha is None else [sha])


def test_holds_an_ancestor_and_refuses_a_branch_commit(repo: Path) -> None:
    base = _head(repo)
    branch = _branch_only_commit(repo)

    assert check_work_journal_main.holds(repo, base, "main")
    assert check_work_journal_main.holds(repo, base[:7], "main")
    assert not check_work_journal_main.holds(repo, branch, "main")
    assert not check_work_journal_main.holds(repo, UNKNOWN, "main")


def test_the_check_names_the_line_and_suggests_the_branch(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    branch = _branch_only_commit(repo)
    line = f"**Method**: `main` at `{branch}`."
    _add(repo, line)
    number = (repo / JOURNAL).read_text(encoding="utf-8").splitlines().index(line) + 1
    monkeypatch.chdir(repo)

    assert check_work_journal_main.main([]) == 1
    err = capsys.readouterr().err
    assert f"{JOURNAL}:{number}: `main` at `{branch}`" in err
    assert f"the branch at `{branch}`" in err


def test_the_check_passes_when_main_holds_the_commit(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _head(repo)
    _branch_only_commit(repo)
    _add(repo, f"**Method**: `main` at `{base}`.")
    monkeypatch.chdir(repo)

    assert check_work_journal_main.main([]) == 0


def test_the_check_returns_two_when_no_base_resolves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A repository with no main nor origin/main has no base to judge a claim against."""
    repo = tmp_path / "trunk-only"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "trunk")
    _write(repo, "README.md", "no main here\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "trunk")
    monkeypatch.chdir(repo)

    assert check_work_journal_main.main([]) == 2
    assert "git failed" in capsys.readouterr().err


def test_this_branch_names_only_main_commits_as_mains() -> None:
    """The gate's half of the rule: the branch since the gate's base (origin/main, else main)."""
    try:
        violations = check_work_journal_main.branch_violations(REPO_ROOT)
    except gate.ChangedPathsError as error:
        pytest.skip(f"git cannot give the branch's changes: {error}")
    assert violations == [], "\n".join(
        f"{v.path}:{v.number}: `main` at `{v.sha}`" for v in violations
    )
