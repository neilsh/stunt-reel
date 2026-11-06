"""The CRLF pre-commit hook repairs, or else rejects, staged text files with CRLF in the working copy.

Each case builds a scratch repository with the repository's own ``.gitattributes``, stages
files and runs ``python/scripts/check_crlf.py`` in it, the way the hook runs. Staging a CRLF
file there stores LF in the index, so a file written with CRLF and then staged differs from
its index blob only in line endings, which the hook repairs; writing the working copy again
after staging makes the unstaged edits the hook must not touch.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "python" / "scripts" / "check_crlf.py"
GIT = shutil.which("git")

pytestmark = [pytest.mark.windows, pytest.mark.skipif(GIT is None, reason="git is not on PATH")]

#: Variables that point git at another repository. Git sets them while it runs a hook, so a
#: suite started from one would otherwise stage files in the outer repository.
_GIT_LOCATION_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")


@pytest.fixture(autouse=True)
def _isolate_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset git's location variables, so each test sees only its scratch repository."""
    for name in _GIT_LOCATION_ENV:
        monkeypatch.delenv(name, raising=False)


def _git(repo: Path, *args: str) -> None:
    """Run git in *repo* and fail the test if it fails."""
    assert GIT is not None
    done = subprocess.run(  # noqa: S603 - fixed test arguments
        [GIT, *args], cwd=repo, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr


def _repo(path: Path) -> Path:
    """Make *path* a repository with this checkout's ``.gitattributes`` and no autocrlf."""
    _git(path, "init", "-q")
    # The user's autocrlf would change what a staged CRLF file looks like to git.
    _git(path, "config", "core.autocrlf", "false")
    shutil.copyfile(REPO_ROOT / ".gitattributes", path / ".gitattributes")
    return path


def _run(repo: Path) -> subprocess.CompletedProcess[str]:
    """Run the hook in *repo* as a commit would."""
    return subprocess.run(  # noqa: S603 - the interpreter and the script under test
        [sys.executable, str(SCRIPT)],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _write(repo: Path, files: dict[str, bytes]) -> None:
    """Write each file's bytes under *repo*, making parent directories."""
    for name, data in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def _stage(repo: Path, files: dict[str, bytes]) -> None:
    """Write each file under *repo* and stage it."""
    _write(repo, files)
    _git(repo, "add", "-f", *files)


def _rejected(stderr: str) -> str:
    """The part of the hook's report that names the files it rejected."""
    return stderr.partition("not repaired:")[2]


def test_a_crlf_only_file_is_repaired_and_passes(tmp_path: Path) -> None:
    """A file staged with CRLF is rewritten as LF, named, and the hook passes."""
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
    """A CRLF working copy of a staged LF file is rewritten as LF."""
    repo = _repo(tmp_path)
    _stage(repo, {"a.py": b"x = 1\n"})
    _write(repo, {"a.py": b"x = 1\r\n"})
    result = _run(repo)
    assert result.returncode == 0, result.stderr
    assert "a.py" in result.stderr
    assert (repo / "a.py").read_bytes() == b"x = 1\n"


def test_mixed_line_endings_are_repaired(tmp_path: Path) -> None:
    """A working copy with both LF and CRLF endings is rewritten as LF."""
    repo = _repo(tmp_path)
    _stage(repo, {"a.txt": b"one\ntwo\r\nthree"})
    assert _run(repo).returncode == 0
    assert (repo / "a.txt").read_bytes() == b"one\ntwo\nthree"


def test_a_crlf_file_with_unstaged_edits_fails_and_is_unchanged(tmp_path: Path) -> None:
    """CRLF plus unstaged edits fails the commit and leaves the file byte for byte."""
    repo = _repo(tmp_path)
    _stage(repo, {"a.py": b"x = 1\n"})
    edited = b"x = 2\r\ny = 3\r\n"
    _write(repo, {"a.py": edited})
    result = _run(repo)
    assert result.returncode == 1
    assert "a.py" in _rejected(result.stderr)
    assert (repo / "a.py").read_bytes() == edited


def test_only_the_files_with_edits_are_rejected(tmp_path: Path) -> None:
    """Repaired and rejected files are reported apart, and only edited ones fail."""
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


def _load_script() -> Any:
    """Import ``check_crlf.py`` by path, without putting python/scripts on sys.path."""
    spec = importlib.util.spec_from_file_location("check_crlf", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_failed_checkout_puts_every_file_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A checkout that fails partway restores every removed file's bytes."""
    repo = _repo(tmp_path)
    files = {"a.txt": b"one\r\n", "b.txt": b"two\r\n", "c.txt": b"three\r\n"}
    _stage(repo, files)
    script = _load_script()
    real_git = script._git

    def failing_git(root: Path, *args: str, stdin: bytes | None = None) -> bytes:
        """Run git, except that checkout-index fails."""
        if args[0] != "checkout-index":
            output: bytes = real_git(root, *args, stdin=stdin)
            return output
        # Git rewrote the first path, then a filter failed on a later one.
        (root / "a.txt").write_bytes(b"one\n")
        raise script.GitError("git checkout-index failed: smudge filter failed")

    monkeypatch.setattr(script, "_git", failing_git)
    with pytest.raises(script.GitError):
        script.repair(repo, list(files))
    for name, data in files.items():
        assert (repo / name).read_bytes() == data


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows has no executable bit to lose or restore"
)
def test_a_failed_checkout_puts_back_the_executable_bit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A checkout that fails restores a removed file's permission bits with its bytes."""
    repo = _repo(tmp_path)
    _stage(repo, {"run.sh": b"echo hi\r\n"})
    (repo / "run.sh").chmod(0o755)
    _git(repo, "add", "run.sh")
    script = _load_script()
    real_git = script._git

    def failing_git(root: Path, *args: str, stdin: bytes | None = None) -> bytes:
        """Run git, except that checkout-index fails."""
        if args[0] != "checkout-index":
            output: bytes = real_git(root, *args, stdin=stdin)
            return output
        raise script.GitError("git checkout-index failed")

    monkeypatch.setattr(script, "_git", failing_git)
    with pytest.raises(script.GitError):
        script.repair(repo, ["run.sh"])
    assert (repo / "run.sh").read_bytes() == b"echo hi\r\n"
    assert (repo / "run.sh").stat().st_mode & 0o777 == 0o755


def test_a_checkout_that_leaves_crlf_puts_the_file_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file still holding CRLF after checkout gets its bytes back and is rejected."""
    repo = _repo(tmp_path)
    _stage(repo, {"a.txt": b"one\ntwo\n"})
    _write(repo, {"a.txt": b"one\r\ntwo\n"})
    script = _load_script()
    real_git = script._git

    def crlf_git(root: Path, *args: str, stdin: bytes | None = None) -> bytes:
        """Run git, except that checkout-index writes CRLF."""
        if args[0] != "checkout-index":
            output: bytes = real_git(root, *args, stdin=stdin)
            return output
        # As git configured to write CRLF on checkout would.
        (root / "a.txt").write_bytes(b"one\r\ntwo\r\n")
        return b""

    monkeypatch.setattr(script, "_git", crlf_git)
    assert script.repair(repo, ["a.txt"]) == ([], ["a.txt"])
    assert (repo / "a.txt").read_bytes() == b"one\r\ntwo\n"


def test_a_file_written_after_its_comparison_is_not_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file another process writes between the comparison and the removal is kept."""
    repo = _repo(tmp_path)
    _stage(repo, {"a.txt": b"one\r\n"})
    script = _load_script()
    real_compare = script.crlf_copy_of_index

    def compare_then_edit(root: Path, path: str) -> bytes | None:
        """Compare, then let an editor save new text, as it could at any moment."""
        data: bytes | None = real_compare(root, path)
        (root / path).write_bytes(b"edited\r\n")
        return data

    monkeypatch.setattr(script, "crlf_copy_of_index", compare_then_edit)
    assert script.repair(repo, ["a.txt"]) == ([], ["a.txt"])
    assert (repo / "a.txt").read_bytes() == b"edited\r\n"


def test_a_file_written_after_its_removal_is_not_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file another process writes after the hook removed it keeps that process's bytes."""
    repo = _repo(tmp_path)
    _stage(repo, {"a.txt": b"one\r\n", "b.txt": b"two\r\n"})
    script = _load_script()
    real_git = script._git

    def save_then_git(root: Path, *args: str, stdin: bytes | None = None) -> bytes:
        """Let an editor save ``a.txt`` just before git checks the files out."""
        if args[0] == "checkout-index":
            (root / "a.txt").write_bytes(b"edited\r\n")
        output: bytes = real_git(root, *args, stdin=stdin)
        return output

    monkeypatch.setattr(script, "_git", save_then_git)
    with pytest.raises(script.GitError, match="already exists"):
        script.repair(repo, ["a.txt", "b.txt"])
    assert (repo / "a.txt").read_bytes() == b"edited\r\n"
    assert (repo / "b.txt").read_bytes() == b"two\r\n"


@pytest.mark.skipif(sys.platform == "win32", reason="a colon in a Windows name opens a stream")
def test_a_name_that_reads_as_a_stage_is_compared_with_its_own_blob(tmp_path: Path) -> None:
    """``0:x`` is compared with its own blob, not with stage 0 of ``x``."""
    repo = _repo(tmp_path)
    _stage(repo, {"x": b"a\n", "0:x": b"b\n"})
    _write(repo, {"0:x": b"a\r\n"})
    result = _run(repo)
    assert result.returncode == 1
    assert "0:x" in _rejected(result.stderr)
    assert (repo / "0:x").read_bytes() == b"a\r\n"


def test_a_file_reached_through_a_linked_directory_is_not_touched(tmp_path: Path) -> None:
    """A staged path whose directory is now a link to elsewhere is rejected, not rewritten.

    Git reports a path beyond a link as deleted, so the hook's mode check excludes it.
    """
    (tmp_path / "repo").mkdir()
    repo = _repo(tmp_path / "repo")
    _stage(repo, {"d/f.txt": b"a\n"})
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "f.txt").write_bytes(b"a\r\n")
    (repo / "d" / "f.txt").unlink()
    (repo / "d").rmdir()
    try:
        (repo / "d").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("this account cannot make symbolic links")
    result = _run(repo)
    assert result.returncode == 1
    assert "d/f.txt" in _rejected(result.stderr)
    assert (outside / "f.txt").read_bytes() == b"a\r\n"


def test_a_reported_mode_change_is_rejected_and_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A path git reports with a mode change is rejected, not rewritten."""
    repo = _repo(tmp_path)
    _stage(repo, {"a.txt": b"one\r\n"})
    script = _load_script()
    real_git = script._git
    zeros = "0" * 40

    def mode_git(root: Path, *args: str, stdin: bytes | None = None) -> bytes:
        """Run git, except that diff-files reports a mode change on ``a.txt``."""
        if args[0] == "diff-files":
            return f":100644 100755 {zeros} {zeros} M\0a.txt\0".encode()
        output: bytes = real_git(root, *args, stdin=stdin)
        return output

    monkeypatch.setattr(script, "_git", mode_git)
    assert script.repair(repo, ["a.txt"]) == ([], ["a.txt"])
    assert (repo / "a.txt").read_bytes() == b"one\r\n"


@pytest.mark.skipif(
    sys.platform == "win32", reason="git on Windows sets core.filemode=false and ignores the bit"
)
def test_an_unstaged_executable_bit_is_rejected_and_unchanged(tmp_path: Path) -> None:
    """An unstaged executable bit is rejected, and the bytes and the bit are kept."""
    repo = _repo(tmp_path)
    _stage(repo, {"run.sh": b"echo hi\n"})
    _write(repo, {"run.sh": b"echo hi\r\n"})
    (repo / "run.sh").chmod(0o755)
    result = _run(repo)
    assert result.returncode == 1
    assert "run.sh" in _rejected(result.stderr)
    assert (repo / "run.sh").read_bytes() == b"echo hi\r\n"
    assert (repo / "run.sh").stat().st_mode & 0o111


def test_an_extra_cr_before_a_crlf_in_the_blob_is_rejected_and_unchanged(tmp_path: Path) -> None:
    """A working copy adding a CR to a CRLF blob is rejected and left as it is."""
    # The blob keeps its CRLF (staged before the LF rule), and the working copy adds a CR.
    repo = tmp_path
    _git(repo, "init", "-q")
    _git(repo, "config", "core.autocrlf", "false")
    _stage(repo, {"old.txt": b"a\r\n"})
    shutil.copyfile(REPO_ROOT / ".gitattributes", repo / ".gitattributes")
    _write(repo, {"old.txt": b"a\r\r\n"})
    result = _run(repo)
    assert result.returncode == 1
    assert "old.txt" in _rejected(result.stderr)
    assert (repo / "old.txt").read_bytes() == b"a\r\r\n"


def test_a_blob_that_itself_holds_crlf_is_rejected_and_unchanged(tmp_path: Path) -> None:
    """A CRLF working copy of a CRLF blob is rejected and left as it is."""
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
    """LF files, empty or without a final newline, pass silently."""
    repo = _repo(tmp_path)
    _stage(repo, {"a.py": b"x = 1\n", "b.txt": b"no newline at end", "c.md": b""})
    result = _run(repo)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""


def test_windows_launchers_keep_crlf(tmp_path: Path) -> None:
    """``*.bat`` and ``*.cmd`` keep CRLF and are neither repaired nor rejected."""
    repo = _repo(tmp_path)
    _stage(repo, {"run.bat": b"@echo off\r\n", "tools/go.cmd": b"@echo on\r\n"})
    result = _run(repo)
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert (repo / "run.bat").read_bytes() == b"@echo off\r\n"


def test_binary_files_pass_untouched(tmp_path: Path) -> None:
    """Binary files, named by attribute or by a NUL byte, pass untouched."""
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
    """A binary attribute alone exempts a file from the check."""
    repo = _repo(tmp_path)
    _stage(repo, {"table.idx": b"plain\r\nbytes\r\n"})
    assert _run(repo).returncode == 0
    assert (repo / "table.idx").read_bytes() == b"plain\r\nbytes\r\n"


def test_the_exemption_follows_gitattributes(tmp_path: Path) -> None:
    """The ``eol=crlf`` exemption is read from ``.gitattributes``, not a list."""
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
    """A CRLF file that is not staged is neither checked nor touched."""
    repo = _repo(tmp_path)
    _stage(repo, {"a.py": b"x = 1\n"})
    _write(repo, {"loose.py": b"y = 2\r\n"})
    assert _run(repo).returncode == 0
    assert (repo / "loose.py").read_bytes() == b"y = 2\r\n"


def test_a_deleted_staged_path_and_nothing_staged_pass(tmp_path: Path) -> None:
    """An empty index and a staged path deleted from disk both pass."""
    repo = _repo(tmp_path)
    assert _run(repo).returncode == 0
    _stage(repo, {"gone.txt": b"x\n"})
    (repo / "gone.txt").unlink()
    assert _run(repo).returncode == 0


def test_names_with_spaces_and_non_ascii_are_found(tmp_path: Path) -> None:
    """Paths with spaces and non-ASCII letters are repaired and rejected by name."""
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
    """Outside a repository the hook exits 2 and says why."""
    # The scratch root is inside this checkout; the ceiling keeps git from finding it.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    result = _run(tmp_path)
    assert result.returncode == 2
    assert "crlf-check" in result.stderr
