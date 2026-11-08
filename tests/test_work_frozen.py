"""A work folder whose README carries an `outcome` is frozen (work/README.md, Lifecycle).

`frozen_violations` rejects a file added to a frozen folder and any change to its README's
`outcome` line; edits to existing files pass, since a link fix cannot be told from another
edit. `check_work_frozen.py` runs it on the index before a commit and, as the documentation
test at the end of this module, on the branch since the gate's base, so CI runs it too.
"""

from __future__ import annotations

import os
import shutil
import subprocess
lazy from pathlib import Path

import check_work_frozen
import gate
import pytest

from stunt_reel.dataroot import REPO_ROOT
from stunt_reel.work_items import FrozenViolation, frozen_violations

pytestmark = pytest.mark.docs

FROZEN = "work/2026-11/1_done"
OPEN = "work/2026-11/3_open"

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


@pytest.fixture(autouse=True)
def _isolate_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep git in these tests on their own repositories when pytest runs under a git hook."""
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        monkeypatch.delenv(name, raising=False)


def _git(repo: Path, *args: str) -> None:
    git = shutil.which("git")
    assert git is not None, "git is not on PATH"
    subprocess.run(  # noqa: S603
        [git, *args], cwd=repo, env={**os.environ, **_GIT_ENV}, capture_output=True, check=True
    )


def _write(repo: Path, name: str, text: str) -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def _readme(issue: int, outcome: str) -> str:
    return (
        f'---\ntitle: "T"\nstarted: 2026-11-07\nissue: {issue}\noutcome: "{outcome}"\n---\n\n'
        "# T\n\nSee [the plan](plan.md).\n"
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """One commit on `main`: a folder frozen by its outcome and one still open."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _write(root, f"{FROZEN}/README.md", _readme(1, "Landed in #2."))
    _write(root, f"{FROZEN}/journal.md", "# Journal\n")
    _write(root, f"{OPEN}/README.md", _readme(3, ""))
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "base")
    return root


def test_a_file_added_to_a_frozen_folder_fails(repo: Path) -> None:
    _write(repo, f"{FROZEN}/plan.md", "# Plan\n")

    assert frozen_violations("HEAD", [f"{FROZEN}/plan.md"], repo=repo) == [
        FrozenViolation(f"{FROZEN}/plan.md", "adds a file to a frozen work folder")
    ]


def test_a_file_added_under_a_frozen_folders_images_fails(repo: Path) -> None:
    _write(repo, f"{FROZEN}/images/ctry-422-sky.png", "png")

    violations = frozen_violations("HEAD", [f"{FROZEN}/images/ctry-422-sky.png"], repo=repo)

    assert [v.path for v in violations] == [f"{FROZEN}/images/ctry-422-sky.png"]


def test_an_outcome_edit_in_a_frozen_folder_fails(repo: Path) -> None:
    _write(repo, f"{FROZEN}/README.md", _readme(1, "Landed in #2 and #4."))

    assert frozen_violations("HEAD", [f"{FROZEN}/README.md"], repo=repo) == [
        FrozenViolation(f"{FROZEN}/README.md", "changes the outcome of a frozen work folder")
    ]


def test_deleting_a_frozen_folders_readme_changes_its_outcome(repo: Path) -> None:
    (repo / FROZEN / "README.md").unlink()

    violations = frozen_violations("HEAD", [f"{FROZEN}/README.md"], repo=repo)

    assert [v.rule for v in violations] == ["changes the outcome of a frozen work folder"]


def test_an_edit_to_an_existing_file_in_a_frozen_folder_passes(repo: Path) -> None:
    _write(repo, f"{FROZEN}/journal.md", "# Journal\n\nA fixed [link](../../../docs/SPEC.md).\n")
    readme = _readme(1, "Landed in #2.").replace("plan.md", "spec.md")
    _write(repo, f"{FROZEN}/README.md", readme)

    paths = [f"{FROZEN}/journal.md", f"{FROZEN}/README.md"]
    assert frozen_violations("HEAD", paths, repo=repo) == []


def test_a_folder_that_is_not_frozen_is_unrestricted(repo: Path) -> None:
    _write(repo, f"{OPEN}/plan.md", "# Plan\n")
    _write(repo, f"{OPEN}/README.md", _readme(3, "").replace("# T", "# T, retitled"))

    new_folder = "work/2026-12/9_new"
    _write(repo, f"{new_folder}/README.md", _readme(9, ""))

    paths = [f"{OPEN}/plan.md", f"{OPEN}/README.md", f"{new_folder}/README.md"]
    assert frozen_violations("HEAD", paths, repo=repo) == []


def test_the_finishing_pr_writes_the_outcome(repo: Path) -> None:
    _write(repo, f"{OPEN}/README.md", _readme(3, "Landed in #5."))
    _write(repo, f"{OPEN}/journal.md", "# Journal\n")

    paths = [f"{OPEN}/README.md", f"{OPEN}/journal.md"]
    assert frozen_violations("HEAD", paths, repo=repo) == []


def test_staged_reads_the_index_not_the_working_copy(repo: Path) -> None:
    _write(repo, f"{FROZEN}/README.md", _readme(1, "Rewritten."))
    _git(repo, "add", f"{FROZEN}/README.md")
    _write(repo, f"{FROZEN}/README.md", _readme(1, "Landed in #2."))

    paths = [f"{FROZEN}/README.md"]
    assert frozen_violations("HEAD", paths, repo=repo) == []
    assert [v.path for v in frozen_violations("HEAD", paths, staged=True, repo=repo)] == paths


def test_an_unknown_revision_raises(repo: Path) -> None:
    with pytest.raises(subprocess.CalledProcessError):
        frozen_violations("no-such-rev", [f"{FROZEN}/plan.md"], repo=repo)


def test_the_hook_rejects_a_staged_file_in_a_frozen_folder(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(repo, f"{FROZEN}/plan.md", "# Plan\n")
    _git(repo, "add", f"{FROZEN}/plan.md")
    monkeypatch.chdir(repo)

    assert check_work_frozen.main([]) == 1
    assert f"{FROZEN}/plan.md: adds a file to a frozen work folder" in capsys.readouterr().err


def test_the_hook_ignores_an_unstaged_file(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(repo, f"{FROZEN}/plan.md", "# Plan\n")
    monkeypatch.chdir(repo)

    assert check_work_frozen.main([]) == 0


def test_the_hook_passes_a_staged_edit(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(repo, f"{FROZEN}/journal.md", "# Journal, fixed\n")
    _git(repo, "add", f"{FROZEN}/journal.md")
    monkeypatch.chdir(repo)

    assert check_work_frozen.main([]) == 0


def test_the_hook_passes_the_first_commit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _git(tmp_path, "init", "-q", "-b", "main")
    _write(tmp_path, f"{FROZEN}/README.md", _readme(1, "Landed in #2."))
    _git(tmp_path, "add", ".")
    monkeypatch.chdir(tmp_path)

    assert check_work_frozen.main([]) == 0


def test_the_branch_check_counts_from_the_base(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _git(repo, "switch", "-q", "-c", "feat")
    _write(repo, f"{FROZEN}/plan.md", "# Plan\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "feat")
    monkeypatch.chdir(repo)

    assert check_work_frozen.main(["--branch"]) == 1
    assert f"{FROZEN}/plan.md: adds a file" in capsys.readouterr().err
    assert check_work_frozen.main(["--branch", "--base", "feat"]) == 0


def test_this_branch_leaves_frozen_work_folders_frozen() -> None:
    """The gate's half of the rule: the branch since the gate's base (origin/main, else main)."""
    try:
        violations = check_work_frozen.branch_violations(REPO_ROOT)
    except gate.ChangedPathsError as error:
        pytest.skip(f"git cannot give the branch's changes: {error}")
    assert violations == [], "\n".join(f"{v.path}: {v.rule}" for v in violations)
