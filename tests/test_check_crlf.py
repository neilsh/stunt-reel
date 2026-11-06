"""The CRLF pre-commit hook repairs, or else rejects, staged text files with CRLF in the working copy.

Each case builds a scratch repository with the repository's own ``.gitattributes``, stages
files and runs ``python/scripts/check_crlf.py`` in it, the way the hook runs. Staging a CRLF
file there stores LF in the index, so a file written with CRLF and then staged differs from
its index blob only in line endings, which the hook repairs; writing the working copy again
after staging makes the unstaged edits the hook must not touch.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "python" / "scripts" / "check_crlf.py"
GIT = shutil.which("git")

pytestmark = pytest.mark.skipif(GIT is None, reason="git is not on PATH")

#: Variables that point git at another repository. Git sets them while it runs a hook, so a
#: suite started from one would otherwise stage files in the outer repository.
_GIT_LOCATION_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")


@pytest.fixture(autouse=True)
def _isolate_git(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _GIT_LOCATION_ENV:
        monkeypatch.delenv(name, raising=False)


def _git(repo: Path, *args: str) -> None:
    assert GIT is not None
    done = subprocess.run(  # noqa: S603 - fixed test arguments
        [GIT, *args], cwd=repo, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr


def _repo(path: Path) -> Path:
    _git(path, "init", "-q")
    # The user's autocrlf would change what a staged CRLF file looks like to git.
    _git(path, "config", "core.autocrlf", "false")
    shutil.copyfile(REPO_ROOT / ".gitattributes", path / ".gitattributes")
    return path


def _run(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - the interpreter and the script under test
        [sys.executable, str(SCRIPT)],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _write(repo: Path, files: dict[str, bytes]) -> None:
    for name, data in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def _stage(repo: Path, files: dict[str, bytes]) -> None:
    _write(repo, files)
    _git(repo, "add", "-f", *files)


def _rejected(stderr: str) -> str:
    """The part of the hook's report that names the files it rejected."""
    return stderr.partition("not repaired:")[2]


def test_a_crlf_only_file_is_repaired_and_passes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _stage(repo, {"notes.md": b"one\r\ntwo\r\n", "pkg/mod.py": b"x = 1\r\n"})
    result = _run(repo)
    assert result.returncode == 0, result.stderr
    assert "notes.md" in result.stderr
    assert "pkg/mod.py" in result.stderr
    assert (repo / "notes.md").read_bytes() == b"one\ntwo\n"
    assert (repo / "pkg/mod.py").read_bytes() == b"x = 1\n"
    assert _run(repo).stderr == ""


def test_a_crlf_copy_of_a_staged_lf_file_is_repaired(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _stage(repo, {"a.py": b"x = 1\n"})
    _write(repo, {"a.py": b"x = 1\r\n"})
    result = _run(repo)
    assert result.returncode == 0, result.stderr
    assert "a.py" in result.stderr
    assert (repo / "a.py").read_bytes() == b"x = 1\n"


def test_mixed_line_endings_are_repaired(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _stage(repo, {"a.txt": b"one\ntwo\r\nthree"})
    assert _run(repo).returncode == 0
    assert (repo / "a.txt").read_bytes() == b"one\ntwo\nthree"


def test_a_crlf_file_with_unstaged_edits_fails_and_is_unchanged(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _stage(repo, {"a.py": b"x = 1\n"})
    edited = b"x = 2\r\ny = 3\r\n"
    _write(repo, {"a.py": edited})
    result = _run(repo)
    assert result.returncode == 1
    assert "a.py" in _rejected(result.stderr)
    assert (repo / "a.py").read_bytes() == edited


def test_only_the_files_with_edits_are_rejected(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _stage(repo, {"good.txt": b"one\n", "fixed.txt": b"one\r\n", "edited.txt": b"one\n"})
    _write(repo, {"edited.txt": b"two\r\n"})
    result = _run(repo)
    assert result.returncode == 1
    repaired, _, rejected = result.stderr.partition("not repaired:")
    assert "fixed.txt" in repaired
    assert "edited.txt" in rejected
    assert "fixed.txt" not in rejected
    assert "good.txt" not in result.stderr
    assert (repo / "fixed.txt").read_bytes() == b"one\n"
    assert (repo / "edited.txt").read_bytes() == b"two\r\n"


def test_a_blob_that_itself_holds_crlf_is_rejected_and_unchanged(tmp_path: Path) -> None:
    # Staged before the LF rule existed, so the index blob keeps its CRLF.
    repo = tmp_path
    _git(repo, "init", "-q")
    _git(repo, "config", "core.autocrlf", "false")
    _stage(repo, {"old.txt": b"a\r\nb\r\n"})
    shutil.copyfile(REPO_ROOT / ".gitattributes", repo / ".gitattributes")
    result = _run(repo)
    assert result.returncode == 1
    assert "old.txt" in _rejected(result.stderr)
    assert (repo / "old.txt").read_bytes() == b"a\r\nb\r\n"


def test_lf_files_pass(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _stage(repo, {"a.py": b"x = 1\n", "b.txt": b"no newline at end", "c.md": b""})
    result = _run(repo)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def test_windows_launchers_keep_crlf(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _stage(repo, {"run.bat": b"@echo off\r\n", "tools/go.cmd": b"@echo on\r\n"})
    result = _run(repo)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert (repo / "run.bat").read_bytes() == b"@echo off\r\n"


def test_binary_files_pass_untouched(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    files = {
        # Named binary by .gitattributes.
        "shot.png": b"\x89PNG\r\n\x1a\n\x00\x00",
        # Not named: only the NUL byte says it is binary.
        "blob.dat": b"\x00\x01\r\n\x02",
    }
    _stage(repo, files)
    result = _run(repo)
    assert result.returncode == 0, result.stderr
    for name, data in files.items():
        assert (repo / name).read_bytes() == data


def test_a_binary_attribute_exempts_a_file_without_a_nul_byte(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _stage(repo, {"table.idx": b"plain\r\nbytes\r\n"})
    assert _run(repo).returncode == 0
    assert (repo / "table.idx").read_bytes() == b"plain\r\nbytes\r\n"


def test_the_exemption_follows_gitattributes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / ".gitattributes").write_bytes(b"* text=auto eol=lf\n*.ps1 text eol=crlf\n")
    _stage(repo, {"x.ps1": b"a\r\n", "y.bat": b"b\r\n"})
    result = _run(repo)
    assert result.returncode == 0, result.stderr
    assert "y.bat" in result.stderr
    assert "x.ps1" not in result.stderr
    assert (repo / "y.bat").read_bytes() == b"b\n"
    assert (repo / "x.ps1").read_bytes() == b"a\r\n"


def test_an_unstaged_crlf_file_is_ignored(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _stage(repo, {"a.py": b"x = 1\n"})
    _write(repo, {"loose.py": b"y = 2\r\n"})
    assert _run(repo).returncode == 0
    assert (repo / "loose.py").read_bytes() == b"y = 2\r\n"


def test_a_deleted_staged_path_and_nothing_staged_pass(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert _run(repo).returncode == 0
    _stage(repo, {"gone.txt": b"x\n"})
    (repo / "gone.txt").unlink()
    assert _run(repo).returncode == 0


def test_names_with_spaces_and_non_ascii_are_found(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _stage(repo, {"a dir/naïve file.txt": b"x\r\n", "a dir/édité.txt": b"x\n"})
    _write(repo, {"a dir/édité.txt": b"y\r\n"})
    result = _run(repo)
    assert result.returncode == 1
    repaired, _, rejected = result.stderr.partition("not repaired:")
    assert "naïve file.txt" in repaired
    assert "édité.txt" in rejected
    assert (repo / "a dir/naïve file.txt").read_bytes() == b"x\n"


def test_a_directory_that_is_not_a_repository_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The scratch root is inside this checkout; the ceiling keeps git from finding it.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    result = _run(tmp_path)
    assert result.returncode == 2
    assert "crlf-check" in result.stderr
