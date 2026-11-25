"""The ``expected-pins`` merge driver: main's side on a merge or rebase.

``.githooks/merge-take-main.sh`` resolves the generated ``research/parity/expected/*.toml`` files
(ADR 0053). Each test runs real git in a scratch repository holding copies of the script and
``.gitattributes``, so the driver's own shell, Git for Windows' ``sh`` on local-windows, is the one
under test.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from stunt_reel import worktree_git
from stunt_reel.git_env import isolated_env

REPO_ROOT = Path(__file__).resolve().parent.parent
GIT = shutil.which("git")
pytestmark = [
    pytest.mark.windows,
    pytest.mark.skipif(GIT is None, reason="git is not on PATH"),
]

EXPECTED = "research/parity/expected/gpu.toml"
REFERENCES = "research/parity/references.toml"


def _lines(ssim: str) -> str:
    """A class file with one value to differ on, and a line each side leaves alone."""
    return f"[ctry]\nssim = {ssim}\niou = 0.9\n\n[intro]\nssim = 0.7\n"


class Scratch:
    """A scratch repository: ``main`` and ``br`` branch from one commit and each edit one line."""

    def __init__(self, root: Path) -> None:
        self.root = root
        root.mkdir()
        self.env = {
            **isolated_env(keep_index=False),
            "GIT_CEILING_DIRECTORIES": str(root.parent),
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
        self.git("init", "-q", "-b", "main")
        hooks = root / ".githooks"
        hooks.mkdir()
        shutil.copyfile(
            REPO_ROOT / ".githooks" / "merge-take-main.sh", hooks / "merge-take-main.sh"
        )
        shutil.copyfile(REPO_ROOT / ".gitattributes", root / ".gitattributes")
        self.write(EXPECTED, _lines("0.5"))
        self.write(REFERENCES, "[ctry]\nfilm = 'a'\nsha256 = 'x'\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "base")
        self.git("branch", "br")

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        assert GIT is not None
        return subprocess.run(  # noqa: S603 - fixed test arguments
            [GIT, *args],
            cwd=self.root,
            env=self.env,
            capture_output=True,
            text=True,
            check=check,
        )

    def write(self, name: str, text: str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    def read(self, name: str = EXPECTED) -> str:
        return (self.root / name).read_text(encoding="utf-8")

    def commit_on(self, branch: str, name: str, text: str) -> None:
        self.git("checkout", "-q", branch)
        self.write(name, text)
        self.git("commit", "-qam", f"{branch} edits {name}")

    def register(self) -> None:
        assert not any(line.mark == "!" for line in worktree_git.ensure_merge_driver(self.root))

    def diverge(self) -> None:
        """``br`` and ``main`` each set ``ctry``'s ``ssim`` to another value; ``br`` is checked out."""
        self.commit_on("main", EXPECTED, _lines("0.8"))
        self.commit_on("br", EXPECTED, _lines("0.6"))


@pytest.fixture
def scratch(tmp_path: Path) -> Scratch:
    return Scratch(tmp_path / "scratch")


def test_a_merge_of_main_takes_mains_side(scratch: Scratch) -> None:
    scratch.register()
    scratch.diverge()

    done = scratch.git("merge", "main", "-m", "merge main", check=False)

    assert done.returncode == 0, done.stdout + done.stderr
    assert scratch.read() == _lines("0.8")


def test_a_rebase_onto_main_takes_mains_side(scratch: Scratch) -> None:
    scratch.register()
    scratch.diverge()

    done = scratch.git("rebase", "main", check=False)

    assert done.returncode == 0, done.stdout + done.stderr
    assert scratch.read() == _lines("0.8")


def test_a_cherry_pick_takes_the_picked_side(scratch: Scratch) -> None:
    """Git runs a pick through the driver as a merge, so it cannot leave a conflict (ADR 0053)."""
    scratch.register()
    scratch.diverge()
    scratch.git("checkout", "-q", "main")

    done = scratch.git("cherry-pick", "br", check=False)

    assert done.returncode == 0, done.stdout + done.stderr
    assert scratch.read() == _lines("0.6")


def test_without_the_driver_a_merge_conflicts(scratch: Scratch) -> None:
    scratch.diverge()

    done = scratch.git("merge", "main", "-m", "merge main", check=False)

    assert done.returncode != 0
    assert "<<<<<<<" in scratch.read()


def test_a_change_to_references_toml_still_conflicts(scratch: Scratch) -> None:
    scratch.register()
    scratch.commit_on("main", EXPECTED, _lines("0.8"))
    scratch.write(REFERENCES, "[ctry]\nfilm = 'a'\nsha256 = 'main'\n")
    scratch.git("commit", "-qam", "main edits references")
    scratch.commit_on("br", EXPECTED, _lines("0.6"))
    scratch.write(REFERENCES, "[ctry]\nfilm = 'a'\nsha256 = 'br'\n")
    scratch.git("commit", "-qam", "br edits references")

    done = scratch.git("merge", "main", "-m", "merge main", check=False)

    assert done.returncode != 0
    assert "<<<<<<<" in scratch.read(REFERENCES)
    assert "<<<<<<<" not in scratch.read(), "the expected file resolved"
    assert scratch.read() == _lines("0.8")
