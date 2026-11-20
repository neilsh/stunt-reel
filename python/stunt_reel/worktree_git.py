"""The git settings and calls the worktree commands share.

``init`` and ``ensure`` set ``core.hooksPath`` and ``blame.ignoreRevsFile`` here (ADR 0036) and
register the ``expected-pins`` merge driver (ADR 0053), and the :class:`Line` a caller prints is the
same report line ``init`` shows. ``_worktrees`` reads what git knows.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, override

from stunt_reel.dataroot import SharedDataError


@dataclass(frozen=True)
class Line:
    """One line of ``init``'s report, printed as ``  <mark> <text>``.

    *mark* is ``+`` (changed), ``-`` (skipped), ``=`` (already so) or ``!`` (a problem).
    *news* marks a line ``ensure`` prints even when quiet: a change this run made, or one it
    failed to make. A standing warning, such as a hooks path someone else chose, is not news.
    """

    mark: Literal["+", "-", "=", "!"]
    text: str
    news: bool = False

    @override
    def __str__(self) -> str:
        return f"  {self.mark} {self.text}"


#: The committed hooks directory ``init`` points ``core.hooksPath`` at, relative to the worktree.
HOOKS_DIR = ".githooks"


def ensure_hooks_path(repo: Path) -> list[Line]:
    """Point *repo*'s ``core.hooksPath`` at the committed hooks; the lines ``init`` prints.

    The setting is in the shared repository config, so one ``init`` covers every worktree,
    and the relative value resolves against whichever worktree runs the hook. A different
    value someone chose is left alone and reported. Setting it turns off the untracked hooks in
    the git directory, so any that the committed ones do not chain to are named.
    """
    current = _git(repo, "config", "--get", "core.hooksPath").stdout.strip()
    if current and current != HOOKS_DIR:
        return [
            Line("!", f"core.hooksPath is {current!r}; left alone, so {HOOKS_DIR}/ does not run")
        ]
    lines = [Line("=", f"core.hooksPath {HOOKS_DIR}")]
    if not current:
        result = _git(repo, "config", "core.hooksPath", HOOKS_DIR)
        if result.returncode != 0:
            return [Line("!", f"could not set core.hooksPath: {result.stderr.strip()}", news=True)]
        lines = [Line("+", f"core.hooksPath -> {HOOKS_DIR}", news=True)]
    common = _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    local = Path(common) / "hooks"
    if not common or not local.is_dir():
        return lines
    hooks = repo / HOOKS_DIR
    committed = {path.name for path in hooks.iterdir()} if hooks.is_dir() else set()
    for hook in sorted(local.iterdir()):
        if hook.suffix != ".sample" and hook.is_file() and hook.name not in committed:
            lines.append(
                Line("!", f"{hook} no longer runs: core.hooksPath replaces the hooks there")
            )
    return lines


#: The committed list of revisions ``git blame`` skips, relative to the worktree.
BLAME_IGNORE_FILE = ".git-blame-ignore-revs"

#: ``blame.ignoreRevsFile``'s value. The setting is shared by every worktree, and ``git blame``
#: fails outright on a missing file unless it is marked optional, as in one checked out at a
#: commit older than the file.
BLAME_IGNORE_VALUE = f":(optional){BLAME_IGNORE_FILE}"


def git_marks_paths_optional(repo: Path) -> bool:
    """Whether *repo*'s git skips a missing config path marked ``:(optional)``."""
    probe = _git(
        repo,
        "-c",
        "stunt-reel.probe=:(optional)no-such-file",
        "config",
        "--type=path",
        "--get",
        "stunt-reel.probe",
    )
    # 1 is `--get` finding no value; an older git that rejects `--type=path` exits otherwise.
    return probe.returncode == 1 and not probe.stdout.strip()


def ensure_blame_ignore(repo: Path) -> list[Line]:
    """Point *repo*'s ``blame.ignoreRevsFile`` at the committed list; the lines ``init`` prints.

    Shared like ``core.hooksPath``, so set only when this checkout has the file and this git can
    mark it optional. The plain file name is made optional; another value is left alone.
    """
    if not (repo / BLAME_IGNORE_FILE).is_file():
        return []
    current = _git(repo, "config", "--get", "blame.ignoreRevsFile").stdout.strip()
    if current == BLAME_IGNORE_VALUE:
        return [Line("=", f"blame.ignoreRevsFile {BLAME_IGNORE_VALUE}")]
    if current not in ("", BLAME_IGNORE_FILE):
        return [Line("!", f"blame.ignoreRevsFile is {current!r}; left alone")]
    if not git_marks_paths_optional(repo):
        return [Line("!", "this git cannot mark a path :(optional); blame.ignoreRevsFile not set")]
    result = _git(repo, "config", "blame.ignoreRevsFile", BLAME_IGNORE_VALUE)
    if result.returncode != 0:
        return [
            Line("!", f"could not set blame.ignoreRevsFile: {result.stderr.strip()}", news=True)
        ]
    return [Line("+", f"blame.ignoreRevsFile -> {BLAME_IGNORE_VALUE}", news=True)]


#: The merge driver ``.gitattributes`` attaches to the generated expected-scores files.
MERGE_DRIVER = "expected-pins"

#: ``merge.expected-pins.driver``'s value: absolute through the shell, so the driver's working
#: directory does not matter.
MERGE_DRIVER_COMMAND = 'sh "$(git rev-parse --show-toplevel)/.githooks/merge-take-main.sh" %O %A %B'

#: ``merge.expected-pins.name``'s value.
MERGE_DRIVER_NAME = "take main's side of a generated expected-scores file"


def ensure_merge_driver(repo: Path) -> list[Line]:
    """Register the ``expected-pins`` merge driver in *repo*'s shared config; the lines ``init`` prints.

    Shared like ``core.hooksPath``. A different driver value someone chose is left alone and
    reported; a clone without the driver gets git's plain conflict.
    """
    key = f"merge.{MERGE_DRIVER}.driver"
    current = _git(repo, "config", "--get", key).stdout.strip()
    if current == MERGE_DRIVER_COMMAND:
        return [Line("=", f"{key} set")]
    if current:
        return [Line("!", f"{key} is {current!r}; left alone, so conflicts in expected/ stay")]
    for name, value in (
        (key, MERGE_DRIVER_COMMAND),
        (f"merge.{MERGE_DRIVER}.name", MERGE_DRIVER_NAME),
    ):
        result = _git(repo, "config", name, value)
        if result.returncode != 0:
            return [Line("!", f"could not set {name}: {result.stderr.strip()}", news=True)]
    return [Line("+", f"{key} set", news=True)]


@dataclass(frozen=True)
class _Worktree:
    """One entry of ``git worktree list --porcelain``."""

    path: Path
    head: str
    branch: str | None


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one git command in *repo*; the caller decides what a failure means."""
    git = shutil.which("git")
    if git is None:
        raise SharedDataError("git is not on PATH")
    return subprocess.run(  # noqa: S603
        [git, *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def _parse_worktrees(text: str) -> list[_Worktree]:
    """Parse ``git worktree list --porcelain``; the primary checkout comes first."""
    found: list[_Worktree] = []
    path: Path | None = None
    head = ""
    branch: str | None = None
    for line in [*text.splitlines(), ""]:
        if not line:
            if path is not None:
                found.append(_Worktree(path=path, head=head, branch=branch))
            path, head, branch = None, "", None
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            path = Path(value)
        elif key == "HEAD":
            head = value
        elif key == "branch":
            branch = value.removeprefix("refs/heads/")
    return found


def _worktrees(repo: Path) -> list[_Worktree]:
    """Every worktree git knows in *repo*, primary first."""
    result = _git(repo, "worktree", "list", "--porcelain")
    if result.returncode != 0:
        raise SharedDataError(f"cannot list worktrees: {result.stderr.strip()}")
    return _parse_worktrees(result.stdout)
