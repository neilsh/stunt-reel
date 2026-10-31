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
