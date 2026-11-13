"""The commit-msg hook: a Conventional Commit subject and the fresh review (AGENTS.md, Committing)."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "python" / "scripts" / "check_commit_msg.py"
TRAILER = "Co-Authored-By: Someone <someone@example.com>"


@pytest.fixture(scope="module")
def hook() -> Any:
    spec = importlib.util.spec_from_file_location("check_commit_msg", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "subject",
    [
        "feat(core): add a parser",
        "fix: refuse a bad manifest",
        "docs(research)!: renumber the items",
        "chore(deps): bump toml",
    ],
)
def test_a_conventional_subject_with_no_body_passes(hook: Any, subject: str) -> None:
    assert hook.problems(subject + "\n") == []


@pytest.mark.parametrize(
    "subject", ["Add a parser", "feat add a parser", "feature: add a parser", "fix(): empty scope"]
)
def test_any_other_subject_is_named(hook: Any, subject: str) -> None:
    [problem] = hook.problems(subject + "\n")
    assert "Conventional Commit" in problem
    assert subject in problem


def test_any_body_passes(hook: Any) -> None:
    message = f"fix: a thing\n\nWhy it changed.\n\n{TRAILER}\n"
    assert hook.problems(message) == []


def test_git_comments_and_the_scissors_are_ignored(hook: Any) -> None:
    message = (
        "fix: a thing\n# Please enter the commit message\n"
        "# ------------------------ >8 ------------------------\n"
        "diff --git a/x b/x\nWhy it changed.\n"
    )
    assert hook.problems(message) == []


@pytest.mark.parametrize(
    "subject",
    [
        "Merge branch 'main' into feat/x",
        'Revert "feat: add a parser"',
        "fixup! feat: add a parser",
        "squash! feat: add a parser",
        "amend! feat: add a parser",
    ],
)
def test_git_generated_subjects_are_left_alone(hook: Any, subject: str) -> None:
    assert hook.problems(subject + "\n\nany body\n") == []


def test_the_script_checks_a_message_file(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)  # noqa: S603, S607
    good, bad = tmp_path / "good", tmp_path / "bad"
    good.write_text("fix: a thing\n", encoding="utf-8")
    bad.write_text("a thing\n", encoding="utf-8")
    run = [sys.executable, str(SCRIPT)]
    assert subprocess.run([*run, str(good)], cwd=tmp_path, check=False).returncode == 0  # noqa: S603
    failed = subprocess.run(  # noqa: S603
        [*run, str(bad)], cwd=tmp_path, capture_output=True, text=True, check=False
    )
    assert failed.returncode == 1
    assert "Conventional Commit" in failed.stderr


Git = Callable[..., str]


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Git:
    """A scratch repository as the working directory, holding one commit; returns its git."""

    def git(*args: str) -> str:
        done = subprocess.run(  # noqa: S603
            ["git", *args],  # noqa: S607
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        )
        return done.stdout.strip()

    git("init", "-q", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.com")
    git("commit", "-q", "--allow-empty", "-m", "chore: start")
    monkeypatch.chdir(tmp_path)
    return git


def _stub_github(
    hook: Any, monkeypatch: pytest.MonkeyPatch, merged: list[int] | Exception
) -> list[str]:
    """Answer every ``_merged_pulls`` call with *merged*, or raise it; returns the hashes asked."""
    asked: list[str] = []

    def merged_pulls(sha: str) -> list[int]:
        asked.append(sha)
        if isinstance(merged, Exception):
            raise merged
        return merged

    monkeypatch.setattr(hook, "_merged_pulls", merged_pulls)
    return asked


def test_the_script_checks_a_commit_range(
    hook: Any, repo: Git, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    base = repo("rev-parse", "HEAD")
    repo("commit", "-q", "--allow-empty", "-m", "feat: fine")
    repo("commit", "-q", "--allow-empty", "-m", "not conventional")
    asked = _stub_github(hook, monkeypatch, [])
    assert hook.main(["--range", f"{base}..HEAD"]) == 1
    stderr = capsys.readouterr().err
    assert "not conventional" in stderr
    assert "feat: fine" not in stderr
    assert asked == [repo("rev-parse", "HEAD")], "GitHub is asked only about failing commits"


def test_a_commit_merged_in_another_pull_request_is_skipped(
    hook: Any, repo: Git, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    base = repo("rev-parse", "HEAD")
    repo("commit", "-q", "--allow-empty", "-m", "the stacked parent's commit")
    _stub_github(hook, monkeypatch, [224, 228])
    assert hook.main(["--range", f"{base}..HEAD", "--pr", "228"]) == 0
    stderr = capsys.readouterr().err
    assert f"skip {repo('rev-parse', '--short', 'HEAD')}: merged in #224" in stderr
    assert "Conventional Commit" not in stderr


def test_a_commit_only_in_this_pull_request_is_checked(
    hook: Any, repo: Git, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    base = repo("rev-parse", "HEAD")
    repo("commit", "-q", "--allow-empty", "-m", "not conventional")
    _stub_github(hook, monkeypatch, [228])
    assert hook.main(["--range", f"{base}..HEAD", "--pr", "228"]) == 1
    stderr = capsys.readouterr().err
    assert "skip" not in stderr
    assert "not conventional" in stderr


def test_a_commit_whose_patch_is_in_the_base_is_skipped_without_github(
    hook: Any,
    repo: Git,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo("switch", "-q", "-c", "stacked")
    (tmp_path / "notes.txt").write_text("a change\n", encoding="utf-8")
    repo("add", "notes.txt")
    repo("commit", "-q", "-m", "not conventional")
    repo("switch", "-q", "main")
    (tmp_path / "notes.txt").write_text("a change\n", encoding="utf-8")
    repo("add", "notes.txt")
    repo("commit", "-q", "-m", "docs: the same change, squash-merged")
    asked = _stub_github(hook, monkeypatch, RuntimeError("GitHub must not be asked"))
    assert hook.main(["--range", "main..stacked"]) == 0
    assert "its patch is already in the base" in capsys.readouterr().err
    assert asked == []


def test_an_empty_commit_is_not_skipped_for_an_empty_commit_in_the_base(
    hook: Any, repo: Git, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo("switch", "-q", "-c", "stacked")
    repo("commit", "-q", "--allow-empty", "-m", "not conventional")
    repo("switch", "-q", "main")
    repo("commit", "-q", "--allow-empty", "-m", "chore: an empty commit in the base")
    _stub_github(hook, monkeypatch, [])
    assert hook.main(["--range", "main..stacked"]) == 1
    stderr = capsys.readouterr().err
    assert "skip" not in stderr
    assert "not conventional" in stderr


def test_github_is_asked_only_for_pull_requests_into_this_repository(
    hook: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[list[str]] = []

    def answer(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="[224]\n", stderr="")

    monkeypatch.setattr(hook.shutil, "which", lambda _name: "gh")
    monkeypatch.setattr(hook.subprocess, "run", answer)
    assert hook._merged_pulls("a" * 40) == [224]
    assert f"oid={'a' * 40}" in commands[0]
    jq = commands[0][commands[0].index("--jq") + 1]
    assert ".baseRepository.nameWithOwner == $r.nameWithOwner" in jq, "a fork's merge never counts"


def test_without_github_every_failing_commit_counts(
    hook: Any, repo: Git, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    base = repo("rev-parse", "HEAD")
    repo("commit", "-q", "--allow-empty", "-m", "not conventional")
    repo("commit", "-q", "--allow-empty", "-m", "also not conventional")
    asked = _stub_github(hook, monkeypatch, hook.GitHubUnavailableError("offline"))
    assert hook.main(["--range", f"{base}..HEAD", "--pr", "228"]) == 1
    stderr = capsys.readouterr().err
    assert "cannot ask GitHub" in stderr
    assert "offline" in stderr
    assert "not conventional" in stderr
    assert "also not conventional" in stderr
    assert len(asked) == 1, "a failed call is not repeated for every commit"


def test_github_is_unavailable_without_gh(hook: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hook.shutil, "which", lambda _name: None)
    with pytest.raises(hook.GitHubUnavailableError, match="gh"):
        hook._merged_pulls("0" * 40)


def test_a_gh_call_that_times_out_makes_github_unavailable(
    hook: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    def hang(command: list[str], **kwargs: Any) -> None:
        calls.append(kwargs)
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(hook.shutil, "which", lambda _name: "gh")
    monkeypatch.setattr(hook.subprocess, "run", hang)
    with pytest.raises(hook.GitHubUnavailableError, match="timed out"):
        hook._merged_pulls("0" * 40)
    assert calls[0]["timeout"] == hook.GH_TIMEOUT
    assert calls[0]["stdin"] is subprocess.DEVNULL


def _path(*parts: str) -> str:
    """A repository-relative path from *parts*, so the doc checks do not read it as a citation."""
    return "/".join(parts)


REVIEW = "Fresh-review: a subagent read the diff and the notes it cites"


@pytest.mark.parametrize(
    ("path", "at_commit"),
    [
        (_path("work", "2026-11", "440_target-frame-adoption", "spec.md"), True),
        (_path("work", "2026-11", "440_target-frame-adoption", "plan.md"), True),
        (_path("work", "2026-11", "440_target-frame-adoption", "journal.md"), False),
        (_path("work", "README.md"), False),
        (_path("research", "parity", "metric-bench.md"), False),
        ("NOTICE.md", False),
        (_path("docs", "howto", "score-a-render-change.md"), False),
        (_path("docs", "SPEC.md"), False),
        (_path("docs", "adr", "0001-x.md"), False),
        ("python/scripts/check_commit_msg.py", False),
    ],
)
def test_which_paths_need_a_fresh_review(hook: Any, path: str, at_commit: bool) -> None:
    assert hook.reviewed_at_commit(path) is at_commit


def test_a_staged_spec_needs_the_trailer(hook: Any) -> None:
    spec = _path("work", "2026-11", "440_x", "spec.md")
    [problem] = hook.review_problems("docs(work): a spec\n", [spec, "README.md"])
    assert spec in problem
    assert "Fresh-review:" in problem
    assert hook.review_problems(f"docs(work): a spec\n\n{REVIEW}\n", [spec]) == []
    assert hook.review_problems("docs(work): a spec\n\nFresh-review:\n", [spec]) != []


def test_the_hook_reads_the_staged_paths(repo: Git, tmp_path: Path) -> None:
    spec = tmp_path / "work" / "2026-11" / "440_x" / "spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# Spec\n", encoding="utf-8")
    repo("add", "work")
    unreviewed, reviewed = tmp_path / "unreviewed", tmp_path / "reviewed"
    unreviewed.write_text("docs(work): a spec\n", encoding="utf-8")
    reviewed.write_text(f"docs(work): a spec\n\n{REVIEW}\n", encoding="utf-8")
    run = [sys.executable, str(SCRIPT)]
    failed = subprocess.run(  # noqa: S603
        [*run, str(unreviewed)], cwd=tmp_path, capture_output=True, text=True, check=False
    )
    assert failed.returncode == 1
    assert "Fresh-review:" in failed.stderr
    assert subprocess.run([*run, str(reviewed)], cwd=tmp_path, check=False).returncode == 0  # noqa: S603


@pytest.mark.parametrize(
    "subject", ["Merge branch 'spec'", 'Revert "docs(work): a spec"', "fixup! docs(work): a spec"]
)
def test_git_subjects_need_no_review(hook: Any, subject: str) -> None:
    spec = _path("work", "2026-11", "440_x", "spec.md")
    assert hook.review_problems(subject + "\n", [spec]) == []


def test_the_hook_fails_closed_outside_a_repository(tmp_path: Path) -> None:
    message = tmp_path / "message"
    message.write_text("fix: a thing\n", encoding="utf-8")
    failed = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), str(message)],
        cwd=tmp_path,
        env={**os.environ, "GIT_CEILING_DIRECTORIES": str(tmp_path.parent)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert failed.returncode == 2
    assert "cannot read the staged paths" in failed.stderr


def test_a_non_ascii_path_is_read_unquoted(repo: Git, tmp_path: Path, hook: Any) -> None:
    note = tmp_path / "research" / "café.md"
    note.parent.mkdir()
    note.write_text("x\n", encoding="utf-8")
    repo("add", "research")
    assert hook._staged_paths() == [_path("research", "café.md")]
