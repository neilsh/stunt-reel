"""prek checks what is being committed, and CI runs its built-ins (ADR 0026).

`gate.py staged` once listed the staged paths and then checked the working tree, so an unstaged
edit could fail a clean commit or pass a broken one. prek sets unstaged edits aside before it runs
the hooks; the scratch-repository test below holds it to that both ways. It needs prek, so it
skips where prek is absent unless `STUNT_REQUIRE_PREK` is set, which the gate's `test-py` step
does, the way `STUNT_REQUIRE_KSC` guards the schema test.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path
from typing import IO

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

GIT = shutil.which("git")

#: `_run` kills a timed-out process tree differently on Windows.
pytestmark = pytest.mark.windows

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


#: Seconds any one git or prek call may take; these fixtures finish in a few.
_TIMEOUT = 60.0


def _run(repo: Path, *args: str, timeout: float = _TIMEOUT) -> subprocess.CompletedProcess[str]:
    """Run a command in `repo`; a hung one is killed and fails the test with its output.

    Without a timeout a hung prek held its pytest worker until the gate killed the worker,
    which orphaned prek with the scratch repository as its working directory (issue #220).
    Output goes to files, not pipes: a process prek started that outlives the kill can hold
    a pipe open and block its reader, and on Windows `subprocess.run` waits on it unbounded.
    """
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(  # noqa: S603 - fixed test arguments
            list(args),
            cwd=repo,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            start_new_session=True,  # one process group to kill on POSIX; ignored on Windows
        )
        try:
            proc.wait(timeout=timeout)
        except BaseException as exc:  # an interrupted wait must not orphan the tree either
            _kill_tree(proc)
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=10)
            if not isinstance(exc, subprocess.TimeoutExpired):
                raise
            pytest.fail(
                f"{' '.join(args)} timed out after {timeout} s\n"
                f"stdout:\n{_read(out)}\nstderr:\n{_read(err)}"
            )
        return subprocess.CompletedProcess(proc.args, proc.returncode, _read(out), _read(err))


def _kill_tree(proc: subprocess.Popen[bytes]) -> None:
    """Kill `proc` and every process it started that is still in its tree or group."""
    if sys.platform == "win32":
        _taskkill(proc.pid)
    else:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
    proc.kill()


def _taskkill(pid: int) -> None:
    """Kill the Windows process `pid` and its descendants, ignoring one already gone.

    A `taskkill` that cannot start or finish is ignored too: the caller still kills the direct
    child, and a timeout's failure must not be masked by the cleanup's.
    """
    with contextlib.suppress(OSError, subprocess.TimeoutExpired):
        subprocess.run(  # noqa: S603 - fixed arguments
            ["taskkill", "/F", "/T", "/PID", str(pid)],  # noqa: S607 - Windows built-in
            capture_output=True,
            timeout=10,
            check=False,
        )


def _read(file: IO[bytes]) -> str:
    """Return everything written to `file` as text, replacing bytes that do not decode."""
    file.seek(0)
    return file.read().decode(errors="replace").replace("\r\n", "\n")


#: A grandchild that appends a byte to the file named by its argument every 0.1 s for 60 s.
_GRANDCHILD = """\
import sys, time
for _ in range(600):
    with open(sys.argv[1], "ab") as beat:
        beat.write(b".")
    time.sleep(0.1)
"""

#: A child that starts the grandchild on its own stdout, records its pid, and hangs.
_CHILD = """\
import pathlib, subprocess, sys, time
here = pathlib.Path(__file__).parent
grand = subprocess.Popen(
    [sys.executable, str(here / "grand.py"), str(here / "beat")],
    stdout=sys.stdout,
    stderr=sys.stderr,
)
(here / "grand.pid").write_text(str(grand.pid))
while not (here / "beat").exists():
    time.sleep(0.05)
print("marker-220", flush=True)
time.sleep(60)
"""


def test_run_kills_a_timed_out_tree_and_keeps_its_output(tmp_path: Path) -> None:
    """A timed-out call fails within seconds with its output, and its grandchild is dead."""
    (tmp_path / "grand.py").write_text(_GRANDCHILD, encoding="utf-8")
    (tmp_path / "child.py").write_text(_CHILD, encoding="utf-8")
    beat = tmp_path / "beat"
    try:
        start = time.monotonic()
        with pytest.raises(pytest.fail.Exception, match="marker-220"):
            # Two interpreter starts must fit in the timeout on a loaded xdist worker.
            _run(tmp_path, sys.executable, str(tmp_path / "child.py"), timeout=5)
        # A call that waited on the grandchild's output would take its whole 60 s.
        assert time.monotonic() - start < 30
        time.sleep(1)
        size = beat.stat().st_size
        time.sleep(1)
        assert beat.stat().st_size == size, "the grandchild outlived the kill"
    finally:
        _kill_survivor(tmp_path / "grand.pid", beat)


def _kill_survivor(pid_file: Path, beat: Path) -> None:
    """Kill the grandchild if its heartbeat is still fresh, so a failing test leaks nothing.

    A stale heartbeat means it is dead and its pid may already belong to another process.
    """
    with contextlib.suppress(OSError, ValueError):
        if time.time() - beat.stat().st_mtime > 1:
            return
        pid = int(pid_file.read_text(encoding="utf-8"))
        if sys.platform == "win32":
            _taskkill(pid)
        else:
            os.kill(pid, signal.SIGKILL)


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
