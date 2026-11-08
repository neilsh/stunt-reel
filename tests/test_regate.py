"""``mise run regate``: gate each commit after a rebase, then give each its gate line.

Every test runs on a temporary repository with a stub gate, never the real one: the stub fails
on a commit whose tree holds ``FAIL`` and otherwise prints the gate line the tree's ``LINE``
names, so each commit can earn a different one.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
lazy from pathlib import Path

import pytest
import regate

GIT = shutil.which("git") or "git"
pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not on PATH")

STUB = """\
import os, pathlib, sys
log = pathlib.Path(sys.argv[1])
seen = sorted(name for name in os.environ if name.startswith("GIT_") and name != "GIT_TRACE")
with log.open("a", encoding="utf-8") as out:
    out.write(" ".join(sys.argv[2:]) + "|" + ",".join(seen) + "\\n")
if pathlib.Path("FAIL").exists():
    print("[gate] FAIL: a step failed")
    sys.exit(1)
line = pathlib.Path("LINE").read_text().strip() if pathlib.Path("LINE").exists() else ""
print("[gate] PASS")
print("[gate] gate line: " + (line or "mise run check passes."))
"""
TRAILER = "Co-Authored-By: Someone <someone@example.com>"
#: Whoever wrote and committed each commit, and when: none of it may change.
PEOPLE = {
    "GIT_AUTHOR_NAME": "Ada Author",
    "GIT_AUTHOR_EMAIL": "ada@example.invalid",
    "GIT_COMMITTER_NAME": "Cy Committer",
    "GIT_COMMITTER_EMAIL": "cy@example.invalid",
}


@pytest.fixture(autouse=True)
def _isolate_git(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        monkeypatch.delenv(name, raising=False)


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    done = subprocess.run(  # noqa: S603 - fixed test arguments
        [GIT, *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        env=env,
    )
    return done.stdout.strip()


def _commit(repo: Path, files: dict[str, str], message: str, when: int) -> str:
    for name, text in files.items():
        (repo / name).write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    stamp = f"{when} +0100"
    env = {
        **os.environ,
        **PEOPLE,
        "GIT_AUTHOR_DATE": stamp,
        "GIT_COMMITTER_DATE": f"{when + 7} -0300",
    }
    subprocess.run(  # noqa: S603 - fixed test arguments
        [GIT, "commit", "-q", "--no-verify", "-F", "-"],
        cwd=repo,
        input=message,
        text=True,
        encoding="utf-8",
        check=True,
        env=env,
    )
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A ``topic`` branch three commits past ``main``: an old gate line, none, and a bare subject."""
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.name", "test")
    _git(path, "config", "user.email", "test@example.invalid")
    _git(path, "config", "commit.gpgSign", "false")
    _commit(path, {"base.txt": "base\n"}, "feat: the base\n", 1_700_000_000)
    _git(path, "switch", "-q", "-c", "topic")
    _commit(
        path,
        {"one.txt": "1\n", "LINE": "mise run check-py passes; check-rust not run."},
        f"feat: one\n\nWhy one.\n\nmise run check passes.\n\n{TRAILER}\n",
        1_700_000_100,
    )
    _commit(path, {"two.txt": "2\n"}, f"fix: two\n\nWhy two.\n\n{TRAILER}\n", 1_700_000_200)
    _commit(path, {"three.txt": "3\n", "LINE": ""}, "docs: three\n", 1_700_000_300)
    return path


@pytest.fixture
def stub(tmp_path: Path) -> tuple[list[str], Path]:
    """The stub gate's command, and the log of each run's arguments and GIT_ variables."""
    script = tmp_path / "stub_gate.py"
    script.write_text(STUB, encoding="utf-8")
    log = tmp_path / "gate.log"
    return [sys.executable, str(script), str(log)], log


def _commits(repo: Path, revisions: str) -> list[dict[str, str]]:
    fields = ("tree", "an", "ae", "ad", "cn", "ce", "cd", "body")
    raw = _git(
        repo,
        "log",
        "--reverse",
        "--format=%T%x00%an%x00%ae%x00%ad%x00%cn%x00%ce%x00%cd%x00%B%x01",
        "--date=raw",
        revisions,
    )
    return [
        dict(zip(fields, entry.strip("\n").split("\0"), strict=True))
        for entry in raw.split("\x01")
        if entry.strip()
    ]


def test_all_passing_rewrites_each_gate_line_and_nothing_else(
    repo: Path, stub: tuple[list[str], Path]
) -> None:
    command, _ = stub
    old_tip = _git(repo, "rev-parse", "topic")
    before = _commits(repo, "main..topic")

    assert regate.regate("main", command, repo) == 0

    after = _commits(repo, "main..topic")
    assert _git(repo, "rev-parse", "refs/backup/regate/topic") == old_tip
    assert _git(repo, "rev-parse", "topic") != old_tip
    assert _git(repo, "rev-parse", "topic~3") == _git(repo, "rev-parse", "main")
    assert _git(repo, "symbolic-ref", "--short", "HEAD") == "topic"
    assert _git(repo, "status", "--porcelain") == ""
    for old, new in zip(before, after, strict=True):
        assert {k: v for k, v in old.items() if k != "body"} == {
            k: v for k, v in new.items() if k != "body"
        }
    raw = subprocess.run(  # noqa: S603 - fixed test arguments
        [GIT, "cat-file", "commit", "topic"], cwd=repo, capture_output=True, check=True
    ).stdout
    assert b"\r" not in raw
    assert after[0]["body"] == (
        "feat: one\n\nWhy one.\n\nmise run check-py passes; check-rust not run.\n\n" + TRAILER
    )


def test_a_missing_gate_line_is_added_before_the_trailers(
    repo: Path, stub: tuple[list[str], Path]
) -> None:
    command, _ = stub
    assert regate.regate("main", command, repo) == 0
    _, two, three = _commits(repo, "main..topic")
    assert two["body"] == (
        "fix: two\n\nWhy two.\n\nmise run check-py passes; check-rust not run.\n\n" + TRAILER
    )
    assert three["body"] == "docs: three\n\nmise run check passes."


def test_one_failing_commit_leaves_the_branch_untouched(
    repo: Path, stub: tuple[list[str], Path], capsys: pytest.CaptureFixture[str]
) -> None:
    command, log = stub
    _commit(repo, {"FAIL": "x"}, "fix: four\n", 1_700_000_400)
    _commit(repo, {"five.txt": "5"}, "fix: five\n", 1_700_000_500)
    old_tip = _git(repo, "rev-parse", "topic")
    failing = _git(repo, "rev-parse", "--short", "topic~1")

    assert regate.regate("main", command, repo) == 1

    assert _git(repo, "rev-parse", "topic") == old_tip
    assert _git(repo, "symbolic-ref", "--short", "HEAD") == "topic"
    assert _git(repo, "status", "--porcelain") == ""
    assert _git(repo, "for-each-ref", "refs/backup") == ""
    assert failing in capsys.readouterr().err
    assert len(log.read_text(encoding="utf-8").splitlines()) == 4  # nothing after the failure


def test_a_dirty_tree_is_refused_before_any_gate_runs(
    repo: Path, stub: tuple[list[str], Path]
) -> None:
    command, log = stub
    (repo / "untracked.txt").write_text("x", encoding="utf-8")
    old_tip = _git(repo, "rev-parse", "topic")

    assert regate.regate("main", command, repo) == 1

    assert _git(repo, "rev-parse", "topic") == old_tip
    assert not log.exists()


def test_the_gate_runs_without_the_variables_that_point_git_elsewhere(
    repo: Path, stub: tuple[list[str], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    command, log = stub
    monkeypatch.setenv("GIT_DIR", str(repo / ".git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(repo / ".git" / "index"))
    monkeypatch.setenv("GIT_PREFIX", "")

    assert regate.regate("main", command, repo) == 0

    for line in log.read_text(encoding="utf-8").splitlines():
        seen = line.partition("|")[2].split(",")
        assert not {"GIT_DIR", "GIT_INDEX_FILE", "GIT_PREFIX"} & set(seen)


def test_gate_arguments_pass_through() -> None:
    assert regate.parse(["main", "--", "--full"]) == ("main", ["--full"])
    assert regate.parse(["origin/main"]) == ("origin/main", [])
    assert regate.gate_command([]) == ["mise", "run", "check"]
    assert regate.gate_command(["--full"]) == ["mise", "run", "check", "--", "--full"]


def test_prose_before_a_gate_line_is_kept() -> None:
    message = "fix: x\n\nWhy. Then mise run check passes.\n"
    assert regate.with_gate_line(message, "mise run check-docs passes; check-rust not run.") == (
        "fix: x\n\nWhy. Then mise run check-docs passes; check-rust not run.\n"
    )
