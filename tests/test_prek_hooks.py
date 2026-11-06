"""prek checks what is being committed, and CI runs its built-ins (ADR 0026).

`gate.py staged` once listed the staged paths and then checked the working tree, so an unstaged
edit could fail a clean commit or pass a broken one. prek sets unstaged edits aside before it runs
the hooks; the scratch-repository test below holds it to that both ways. It needs prek, so it
skips where prek is absent unless `STUNT_REQUIRE_PREK` is set, which the gate's `test-py` step
does, the way `STUNT_REQUIRE_KSC` guards the schema test.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import textwrap
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

GIT = shutil.which("git")

#: Variables that point git at another repository. Git sets them while it runs a hook, so a
#: suite started from one would otherwise configure and commit in the outer repository.
_GIT_LOCATION_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")

#: A prek configuration of one built-in that parses the staged file.
_CONFIG = '[[repos]]\nrepo = "builtin"\n\n[[repos.hooks]]\nid = "check-toml"\n'


@pytest.fixture(autouse=True)
def _isolate_git(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _GIT_LOCATION_ENV:
        monkeypatch.delenv(name, raising=False)
    # A suite run from inside a prek hook inherits its SKIP list.
    monkeypatch.delenv("SKIP", raising=False)


@pytest.fixture
def prek() -> str:
    found = shutil.which("prek")
    if found is None:
        if os.environ.get("STUNT_REQUIRE_PREK"):
            pytest.fail("prek is not on PATH and STUNT_REQUIRE_PREK is set")
        pytest.skip("prek is not on PATH")
    if GIT is None:
        pytest.skip("git is not on PATH")
    return found


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed test arguments
        list(args), cwd=repo, capture_output=True, text=True, check=False
    )


def _repo(path: Path) -> Path:
    assert GIT is not None
    _run(path, GIT, "init", "-q")
    _run(path, GIT, "config", "user.name", "test")
    _run(path, GIT, "config", "user.email", "test@example.invalid")
    # A user's commit.gpgSign would otherwise make every fixture commit fail without a key.
    _run(path, GIT, "config", "commit.gpgSign", "false")
    (path / "prek.toml").write_text(_CONFIG, encoding="utf-8", newline="\n")
    (path / "a.toml").write_text("x = 1\n", encoding="utf-8", newline="\n")
    _run(path, GIT, "add", "prek.toml", "a.toml")
    assert _run(path, GIT, "commit", "-q", "-m", "one").returncode == 0
    return path


def test_prek_checks_the_staged_content(prek: str, tmp_path: Path) -> None:
    assert GIT is not None
    repo = _repo(tmp_path)
    target = repo / "a.toml"

    # Staged valid, unstaged broken: passes, and the broken edit is back afterwards.
    target.write_text("x = 2\n", encoding="utf-8", newline="\n")
    _run(repo, GIT, "add", "a.toml")
    target.write_text("x = \n", encoding="utf-8", newline="\n")
    result = _run(repo, prek, "run", "--config", "prek.toml")
    assert result.returncode == 0, result.stdout + result.stderr
    assert target.read_text(encoding="utf-8") == "x = \n"

    # Staged broken, unstaged fixed: fails.
    _run(repo, GIT, "add", "a.toml")
    target.write_text("x = 3\n", encoding="utf-8", newline="\n")
    result = _run(repo, prek, "run", "--config", "prek.toml")
    assert result.returncode != 0, result.stdout + result.stderr
    assert target.read_text(encoding="utf-8") == "x = 3\n"


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("log.md", "one\n<<<<<<< HEAD\ntwo\n=======\nthree\n>>>>>>> main\n"),
        ("blob.txt", "x" * 600_000 + "\n"),
    ],
    ids=["conflict-markers", "large-file"],
)
def test_ci_built_ins_catch_a_committed_change(
    prek: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, content: str
) -> None:
    """CI stages nothing and is not mid-merge, so the built-ins must judge committed files.

    A commit made with --no-verify reaches CI as a commit range; without `--enforce-all` and
    `--assume-in-merge` the large-file and conflict-marker built-ins pass it unread.
    """
    assert GIT is not None
    repo = _repo(tmp_path)
    shutil.copyfile(REPO_ROOT / "prek.toml", repo / "prek.toml")
    _run(repo, GIT, "add", "prek.toml")
    assert _run(repo, GIT, "commit", "-q", "-m", "config").returncode == 0
    (repo / name).write_text(content, encoding="utf-8", newline="\n")
    _run(repo, GIT, "add", name)
    assert _run(repo, GIT, "commit", "-q", "--no-verify", "-m", "bad").returncode == 0
    monkeypatch.setenv("SKIP", _ci_skip())
    result = _run(
        repo, prek, "run", "--config", "prek.toml", "--from-ref", "HEAD~1", "--to-ref", "HEAD"
    )
    assert result.returncode != 0, result.stdout + result.stderr


def _ci_skip() -> str:
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    return str(re.findall(r"\bSKIP: (\S+)", ci)[0])


def test_ci_skips_exactly_the_local_hooks() -> None:
    """The gate covers the local hooks, so CI's prek step skips them and only them."""
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    with (REPO_ROOT / "prek.toml").open("rb") as handle:
        repos = tomllib.load(handle)["repos"]
    local = [hook["id"] for entry in repos if entry["repo"] == "local" for hook in entry["hooks"]]
    skips = re.findall(r"\bSKIP: (\S+)", ci)
    assert len(skips) == 1, "CI runs prek in exactly one step"
    assert skips[0].split(",") == local


def test_ci_fails_an_empty_pull_request_before_installing() -> None:
    """Issue #216: an empty pull request fails on git alone, before any toolchain installs."""
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    diff = ci.index('git diff --quiet "origin/$BASE_REF...HEAD"')
    step = ci[ci.rindex("- name:", 0, diff) : diff]
    assert "if: github.event_name == 'pull_request'" in step
    assert "BASE_REF: ${{ github.base_ref }}" in step
    assert diff < ci.index("Install lavapipe"), "the check runs before the slow steps"


def _empty_diff_script() -> str:
    """The `run:` body of CI's empty-diff step, as the runner hands it to bash."""
    lines = (
        (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8").splitlines()
    )
    diff = next(i for i, line in enumerate(lines) if 'git diff --quiet "origin/' in line)
    run = max(i for i in range(diff) if lines[i].strip() == "run: |")
    indent = len(lines[run]) - len(lines[run].lstrip())
    body: list[str] = []
    for line in lines[run + 1 :]:
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        body.append(line)
    return textwrap.dedent("\n".join(body)) + "\n"


def _bash() -> str | None:
    # Git for Windows' own bash first: the bash.exe on a Windows PATH may be WSL's launcher,
    # which runs in another filesystem. Elsewhere no such file exists and PATH's bash serves.
    if GIT is not None:
        bundled = Path(GIT).resolve().parent.parent / "bin" / "bash.exe"
        if bundled.is_file():
            return str(bundled)
    return shutil.which("bash")


@pytest.mark.parametrize(
    ("change", "fails"),
    [("none", True), ("file", False), ("unrelated", True)],
    ids=["empty-diff-fails", "a-change-passes", "no-merge-base-fails"],
)
def test_ci_empty_diff_step_judges_the_tree(tmp_path: Path, change: str, *, fails: bool) -> None:
    """Issue #216: the step fails a pull request whose tree matches its base, and passes one
    that changes a file; a branch with no merge base fails rather than passing unread."""
    bash = _bash()
    if bash is None or GIT is None:
        pytest.skip("bash or git is not available")
    repo = _repo(tmp_path)
    _run(repo, GIT, "update-ref", "refs/remotes/origin/main", "HEAD")
    if change == "file":
        (repo / "b.txt").write_text("b\n", encoding="utf-8", newline="\n")
        _run(repo, GIT, "add", "b.txt")
    elif change == "unrelated":
        _run(repo, GIT, "checkout", "-q", "--orphan", "unrelated")
    # A squash-merged branch's commits stay ahead of the base while its tree adds nothing.
    assert _run(repo, GIT, "commit", "-q", "--allow-empty", "-m", "two").returncode == 0
    result = subprocess.run(  # noqa: S603 - fixed test arguments
        [bash, "-e", "-c", _empty_diff_script()],
        cwd=repo,
        env={**os.environ, "BASE_REF": "main"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode != 0) is fails, result.stdout + result.stderr
    assert ("changes no files" in result.stdout) is (change == "none"), result.stdout
