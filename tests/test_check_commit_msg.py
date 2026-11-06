"""The commit-msg hook: a Conventional Commit subject, and a gate line in any body (AGENTS.md, Committing)."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import gate_record
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


def test_a_body_with_the_gate_line_passes(hook: Any) -> None:
    message = f"fix: a thing\n\nWhy it changed.\n\nmise run check passes.\n\n{TRAILER}\n"
    assert hook.problems(message) == []


def test_a_gate_line_naming_what_did_not_run_passes(hook: Any) -> None:
    message = "docs: a note\n\nWhy.\n\nmise run check-py passes; check-rust not run.\n"
    assert hook.problems(message) == []


def test_a_gate_line_that_does_not_run_the_gate_passes(hook: Any) -> None:
    message = (
        "fix: a mode bit\n\nWhy.\n\nmise run check not run: a mode-only change, checked by CI.\n"
    )
    assert hook.problems(message) == []


@pytest.mark.parametrize(
    "line",
    [
        "mise run check failed.",
        "Run mise run check before merging.",
        "mise run check failed; CI passes.",
        "mise run check failed; check-rust passes.",
        "mise run check failed; mise run check-py passes.",
        "mise run check-py passes; check-rust failed.",
        "mise run check failed, the fix is not run yet.",
    ],
)
def test_a_gate_line_must_report_an_outcome(hook: Any, line: str) -> None:
    [problem] = hook.problems(f"fix: a thing\n\nWhy it changed.\n\n{line}\n")
    assert "gate line" in problem


def test_a_body_without_a_gate_line_is_named(hook: Any) -> None:
    [problem] = hook.problems(f"fix: a thing\n\nWhy it changed.\n\n{TRAILER}\n")
    assert "mise run check" in problem


def test_trailers_alone_are_not_a_body(hook: Any) -> None:
    assert hook.problems(f"chore: rename a file\n\n{TRAILER}\n") == []


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
    assert hook.problems(subject + "\n\nno gate line here\n") == []


def test_the_script_checks_a_message_file(tmp_path: Path) -> None:
    good, bad = tmp_path / "good", tmp_path / "bad"
    good.write_text("fix: a thing\n", encoding="utf-8")
    bad.write_text("a thing\n", encoding="utf-8")
    run = [sys.executable, str(SCRIPT)]
    assert subprocess.run([*run, str(good)], check=False).returncode == 0  # noqa: S603
    failed = subprocess.run(  # noqa: S603
        [*run, str(bad)], capture_output=True, text=True, check=False
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


GATE_LINE = "mise run check passes."


def _message(tmp_path: Path, gate_line: str = GATE_LINE) -> Path:
    path = tmp_path.parent / f"{tmp_path.name}.msg"
    path.write_text(f"fix: a thing\n\nWhy it changed.\n\n{gate_line}\n", encoding="utf-8")
    return path


def _stage(git: Git, tmp_path: Path, text: str) -> None:
    (tmp_path / "notes.txt").write_text(text, encoding="utf-8")
    git("add", "notes.txt")


def test_a_passes_claim_with_no_recorded_run_is_refused(
    hook: Any, repo: Git, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _stage(repo, tmp_path, "a change\n")
    assert hook.main([str(_message(tmp_path))]) == 1
    assert "no passing run of mise run check" in capsys.readouterr().err


def test_a_recorded_run_of_the_staged_tree_proves_the_line(
    hook: Any, repo: Git, tmp_path: Path
) -> None:
    _stage(repo, tmp_path, "a change\n")
    gate_record.record("check", gate_record.working_tree())
    assert hook.main([str(_message(tmp_path))]) == 0


def test_a_run_of_another_tree_is_refused_naming_the_paths(
    hook: Any, repo: Git, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _stage(repo, tmp_path, "what the gate saw\n")
    gate_record.record("check", gate_record.working_tree())
    _stage(repo, tmp_path, "edited after the gate\n")
    assert hook.main([str(_message(tmp_path))]) == 1
    assert "notes.txt" in capsys.readouterr().err


def test_an_unstaged_file_the_gate_tested_is_refused(
    hook: Any, repo: Git, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _stage(repo, tmp_path, "a change\n")
    (tmp_path / "helper.txt").write_text("the gate needed this\n", encoding="utf-8")
    gate_record.record("check", gate_record.working_tree())
    assert hook.main([str(_message(tmp_path))]) == 1
    assert "helper.txt" in capsys.readouterr().err


def test_a_recorded_tree_git_no_longer_has_asks_for_a_rerun(
    hook: Any, repo: Git, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A recorded tree is a loose object nothing references, so ``git gc`` may prune it."""
    _stage(repo, tmp_path, "a change\n")
    gate_record.record("check", "1" * 40)
    assert hook.main([str(_message(tmp_path))]) == 1
    error = capsys.readouterr().err
    assert "is no longer in the repository" in error
    assert "rerun mise run check" in error


def test_a_full_check_proves_a_half(hook: Any, repo: Git, tmp_path: Path) -> None:
    _stage(repo, tmp_path, "a change\n")
    gate_record.record("check", gate_record.working_tree())
    line = "mise run check-py passes; check-rust not run."
    assert hook.main([str(_message(tmp_path, line))]) == 0


def test_a_half_does_not_prove_the_full_check(
    hook: Any, repo: Git, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _stage(repo, tmp_path, "a change\n")
    gate_record.record("check-py", gate_record.working_tree())
    assert hook.main([str(_message(tmp_path))]) == 1
    assert "no passing run of mise run check" in capsys.readouterr().err


def test_a_gate_reported_not_run_needs_no_record(hook: Any, repo: Git, tmp_path: Path) -> None:
    _stage(repo, tmp_path, "a change\n")
    assert hook.main([str(_message(tmp_path, "mise run check not run."))]) == 0


def test_recording_a_run_leaves_the_real_index_alone(repo: Git, tmp_path: Path) -> None:
    (tmp_path / "unstaged.txt").write_text("not staged\n", encoding="utf-8")
    gate_record.working_tree()
    assert repo("status", "--porcelain") == "?? unstaged.txt"
