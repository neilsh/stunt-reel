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
import textwrap
import time
import tomllib
from pathlib import Path
from typing import IO

import pytest

from stunt_reel import process_tree
from stunt_reel.git_env import isolated_env

REPO_ROOT = Path(__file__).resolve().parent.parent

GIT = shutil.which("git")

#: `_run` kills a timed-out process tree differently on Windows.
pytestmark = pytest.mark.windows

#: Every git call carries its identity, and needs no key for a commit. ``core.longpaths``
#: because the fixtures sit under the checkout's per-run basetemp, whose paths run long.
_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_COUNT": "2",
    "GIT_CONFIG_KEY_0": "commit.gpgSign",
    "GIT_CONFIG_VALUE_0": "false",
    "GIT_CONFIG_KEY_1": "core.longpaths",
    "GIT_CONFIG_VALUE_1": "true",
}

#: A prek configuration of one built-in that parses the staged file.
_CONFIG = '[[repos]]\nrepo = "builtin"\n\n[[repos.hooks]]\nid = "check-toml"\n'


@pytest.fixture(autouse=True)
def _no_inherited_skip(monkeypatch: pytest.MonkeyPatch) -> None:
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
            # A hook's GIT_DIR would otherwise send git to the caller's repository (issue #520),
            # and the ceiling keeps a failed init from walking up into the test's checkout.
            env={
                **isolated_env(keep_index=False),
                "GIT_CEILING_DIRECTORIES": str(repo.parent),
                **_GIT_ENV,
            },
        )
        try:
            proc.wait(timeout=timeout)
        except BaseException as exc:  # an interrupted wait must not orphan the tree either
            process_tree.kill_tree(proc)
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=10)
            if not isinstance(exc, subprocess.TimeoutExpired):
                raise
            pytest.fail(
                f"{' '.join(args)} timed out after {timeout} s\n"
                f"stdout:\n{_read(out)}\nstderr:\n{_read(err)}"
            )
        return subprocess.CompletedProcess(proc.args, proc.returncode, _read(out), _read(err))


def _taskkill(pid: int) -> None:
    """Kill the Windows process `pid` and its descendants, ignoring one already gone."""
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


def _git_ok(path: Path, *args: str) -> None:
    """Run git in *path*, failing the test with its output unless it exits 0."""
    assert GIT is not None
    result = _run(path, GIT, *args)
    assert result.returncode == 0, f"git {' '.join(args)}: {result.stderr}"


def _repo(path: Path) -> Path:
    """A scratch repository at *path* with one commit; the identity rides in ``_GIT_ENV``."""
    assert GIT is not None
    _git_ok(path, "init", "-q")
    (path / "prek.toml").write_text(_CONFIG, encoding="utf-8", newline="\n")
    (path / "a.toml").write_text("x = 1\n", encoding="utf-8", newline="\n")
    _git_ok(path, "add", "prek.toml", "a.toml")
    _git_ok(path, "commit", "-q", "-m", "one")
    return path


def test_the_repo_fixture_leaves_the_callers_repository_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hook's GIT_DIR must not receive the fixture's identity (issue #520)."""
    assert GIT is not None
    caller = tmp_path / "caller"
    caller.mkdir()
    _run(caller, GIT, "init", "-q")
    config = caller / ".git" / "config"
    before = config.read_text(encoding="utf-8")
    monkeypatch.setenv("GIT_DIR", str(caller / ".git"))
    fixture = tmp_path / "fixture"
    fixture.mkdir()

    repo = _repo(fixture)

    assert config.read_text(encoding="utf-8") == before
    assert "[user]" not in (repo / ".git" / "config").read_text(encoding="utf-8")


def test_the_repo_fixture_raises_when_init_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A refused init must stop the fixture, not let git config walk up to a caller (issue #520)."""
    assert GIT is not None
    caller = tmp_path / "caller"
    caller.mkdir()
    _run(caller, GIT, "init", "-q")
    config = caller / ".git" / "config"
    before = config.read_text(encoding="utf-8")
    real_run = _run

    def refuse_init(repo: Path, *args: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        if args and args[0] == GIT and "init" in args:
            return subprocess.CompletedProcess(
                args=list(args), returncode=128, stdout="", stderr=""
            )
        return real_run(repo, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(sys.modules[__name__], "_run", refuse_init)
    fixture = caller / "fixture"
    fixture.mkdir()

    with pytest.raises(AssertionError):
        _repo(fixture)

    assert config.read_text(encoding="utf-8") == before


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
        ("notes.txt", "a \n"),
        ("notes.txt", "a"),
    ],
    ids=["conflict-markers", "large-file", "trailing-whitespace", "missing-final-newline"],
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


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("breaks.md", "a  \nb\n"),
        ("tests/fixtures/x.flm", "a"),
        (Path("work", "2026-01", "1_x", "journal.md").as_posix(), "a \n"),
    ],
    ids=["markdown-hard-break", "fixture", "work-folder"],
)
def test_ci_built_ins_pass_exempt_content(
    prek: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, content: str
) -> None:
    """A Markdown hard break, a fixture's bytes and a frozen work folder are not findings."""
    assert GIT is not None
    repo = _repo(tmp_path)
    shutil.copyfile(REPO_ROOT / "prek.toml", repo / "prek.toml")
    _run(repo, GIT, "add", "prek.toml")
    assert _run(repo, GIT, "commit", "-q", "-m", "config").returncode == 0
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_bytes(content.encode())
    _run(repo, GIT, "add", name)
    assert _run(repo, GIT, "commit", "-q", "--no-verify", "-m", "ok").returncode == 0
    monkeypatch.setenv("SKIP", _ci_skip())
    result = _run(
        repo, prek, "run", "--config", "prek.toml", "--from-ref", "HEAD~1", "--to-ref", "HEAD"
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_check_mode_leaves_the_file_alone(prek: str, tmp_path: Path) -> None:
    """The whitespace built-ins report; they never rewrite a staged file (ADR 0026)."""
    assert GIT is not None
    repo = _repo(tmp_path)
    shutil.copyfile(REPO_ROOT / "prek.toml", repo / "prek.toml")
    target = repo / "notes.txt"
    target.write_bytes(b"a \n")
    _run(repo, GIT, "add", "prek.toml", "notes.txt")
    result = _run(repo, prek, "run", "--config", "prek.toml")
    assert result.returncode != 0, result.stdout + result.stderr
    assert target.read_bytes() == b"a \n"


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
        env={**isolated_env(keep_index=False), "BASE_REF": "main"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode != 0) is fails, result.stdout + result.stderr
    assert ("changes no files" in result.stdout) is (change == "none"), result.stdout
