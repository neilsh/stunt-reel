"""The test session's git children get ``core.longpaths`` on Windows (issue #852).

A repository under the per-run basetemp can pass ``MAX_PATH``, and Windows git refuses to
write one past it unless ``core.longpaths`` is on.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.windows

GIT = shutil.which("git")


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    assert GIT is not None
    return subprocess.run(  # noqa: S603 - fixed git arguments, git resolved from PATH
        [GIT, *args], cwd=cwd, capture_output=True, text=True, check=False
    )


@pytest.mark.skipif(sys.platform != "win32", reason="core.longpaths is a Windows setting")
@pytest.mark.skipif(GIT is None, reason="git is not on PATH")
def test_a_git_child_spawned_under_the_session_sees_core_longpaths(tmp_path: Path) -> None:
    done = _git("config", "--get", "core.longpaths", cwd=tmp_path)
    assert (done.returncode, done.stdout.strip()) == (0, "true"), done.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="core.longpaths is a Windows setting")
@pytest.mark.skipif(GIT is None, reason="git is not on PATH")
def test_the_upload_pack_child_of_a_local_transport_sees_core_longpaths(tmp_path: Path) -> None:
    """git drops ``GIT_CONFIG_*`` from this child (connect.c local_repo_env), not the global file."""
    assert GIT is not None
    source = tmp_path / "source"
    source.mkdir()
    assert _git("init", "-q", "-b", "main", cwd=source).returncode == 0
    report = tmp_path / "child-longpaths.txt"
    probe = tmp_path / "probe.sh"
    probe.write_text(
        f'#!/bin/sh\n"{Path(GIT).as_posix()}" config --get core.longpaths > "{report.as_posix()}"\n'
        "exit 1\n",
        encoding="utf-8",
        newline="\n",
    )
    done = _git("ls-remote", f"--upload-pack={probe.as_posix()}", str(source), cwd=tmp_path)
    assert done.returncode != 0
    assert report.is_file(), done.stderr
    assert report.read_text(encoding="utf-8").strip() == "true"
