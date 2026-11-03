"""Repo shape: a worktree inside the checkout must stay out of every walker's way.

``.agents/worktrees/`` and ``.claude/worktrees/`` hold live worktrees, each with its
own ``target/``.  A directory there that is neither git-ignored nor ruff-excluded is
read by every recursive tool in the repo: ``tests/test_doc_invariants.py`` lost 61
seconds to exactly that before it learned to prune.  The rule lives in SOP 6; this
is what enforces it.
"""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "python" / "scripts"

#: Scripts that name corpus paths without reading the corpus: the linker itself,
#: and the doc checker, which only asserts that other pages cite the archive.
_NOT_READERS = frozenset({"worktree_init.py", "verify_formats_docs.py"})

#: Never walked: build output, caches, and the git directory itself.
_PRUNED = frozenset(
    {
        ".cache",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "node_modules",
        "target",
    }
)
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def _is_link(path: Path) -> bool:
    """True for a symlink or a Windows junction, which ``walk`` would descend."""
    if path.is_symlink():
        return True
    try:
        return bool(getattr(path.lstat(), "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT)
    except OSError:
        return False


def _nested_worktrees(root: Path) -> list[Path]:
    """Every linked worktree inside *root*, without descending into one it finds."""
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        here = Path(dirpath)
        if here != root and ".git" in filenames:
            found.append(here)
            dirnames[:] = []
            continue
        dirnames[:] = [name for name in dirnames if name not in _PRUNED]
        dirnames[:] = [name for name in dirnames if not _is_link(here / name)]
    return found


def _ruff_excludes() -> list[str]:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        config = tomllib.load(handle)
    return [str(entry) for entry in config["tool"]["ruff"]["exclude"]]


def _excluded(relative: str, excludes: list[str]) -> bool:
    parts = relative.split("/")
    for entry in excludes:
        cleaned = entry.rstrip("/")
        if cleaned and (relative == cleaned or relative.startswith(cleaned + "/")):
            return True
        if Path(relative).match(cleaned):
            return True
        if parts[0] == cleaned:
            return True
    return False


def _ignored(relative: str, git: str) -> bool:
    result = subprocess.run(  # noqa: S603
        [git, "check-ignore", "-q", "--", relative],
        cwd=REPO_ROOT,
        check=False,
    )
    return result.returncode == 0


def test_the_detector_finds_a_linked_worktree(tmp_path: Path) -> None:
    # A worktree is a directory whose .git is a file naming its git directory.
    (tmp_path / ".git").mkdir()
    worktree = tmp_path / ".agents" / "worktrees" / "slug"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    assert _nested_worktrees(tmp_path) == [worktree]


def _corpus_scripts() -> set[str]:
    """Scripts holding a ``corpus/`` path literal, docstring usage examples included."""
    found: set[str] = set()
    for path in sorted(SCRIPTS.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and ("corpus/" in node.value or node.value == "corpus")
            ):
                found.add(path.name)
                break
    return found


def test_every_script_that_reads_the_corpus_links_it() -> None:
    readers = _corpus_scripts() - _NOT_READERS
    assert "capture_playone_reference.py" in readers, "the detector missed a known corpus reader"
    for name in sorted(readers):
        text = (SCRIPTS / name).read_text(encoding="utf-8")
        assert "ensure_links_or_report(" in text, (
            f"{name} names corpus paths but never links the data root; in a worktree that "
            "skipped mise run init it reads an empty corpus"
        )


def test_a_worktree_inside_the_checkout_is_ignored_and_excluded() -> None:
    git = shutil.which("git")
    assert git, "git must be on PATH: check-ignore is the only authority on .gitignore"
    excludes = _ruff_excludes()
    for worktree in _nested_worktrees(REPO_ROOT):
        relative = worktree.relative_to(REPO_ROOT).as_posix()
        assert _ignored(relative, git), (
            f"{relative} is a worktree inside the checkout; .gitignore must cover it"
        )
        assert _excluded(relative, excludes), (
            f"{relative} is a worktree inside the checkout; ruff's exclude must cover it"
        )


def test_the_shared_tool_cache_is_ignored_and_excluded() -> None:
    # ADR 0013's cache holds every downloaded crate and uv artifact; an unpruned
    # walk of it is the same mistake test_doc_invariants.py lost 61 seconds to.
    git = shutil.which("git")
    assert git, "git must be on PATH: check-ignore is the only authority on .gitignore"
    assert _ignored(".cache", git), ".cache is a shared tool cache; .gitignore must cover it"
    assert _excluded(".cache", _ruff_excludes()), (
        ".cache is a shared tool cache; ruff's exclude must cover it"
    )


def test_cargo_home_is_one_absolute_path() -> None:
    """Every cargo task names the shared cache alike, so a cloned target/ stays fresh (ADR 0030)."""
    config = tomllib.loads((REPO_ROOT / "mise.toml").read_text(encoding="utf-8"))
    assert "--git-common-dir" in config["vars"]["cargo_home"]
    homes = {
        name: task["env"]["CARGO_HOME"]
        for name, task in config["tasks"].items()
        if "CARGO_HOME" in task.get("env", {})
    }
    assert homes, "no task sets CARGO_HOME"
    assert set(homes.values()) == {"{{vars.cargo_home}}"}, homes


def test_seeding_tasks_pass_the_cargo_home() -> None:
    """init and seed judge donors by the CARGO_HOME every cargo task uses (ADR 0030)."""
    config = tomllib.loads((REPO_ROOT / "mise.toml").read_text(encoding="utf-8"))
    for name in ("init", "seed"):
        assert config["tasks"][name]["env"]["STUNT_CARGO_HOME"] == "{{vars.cargo_home}}", name


def test_every_task_that_builds_names_the_shared_cargo_home() -> None:
    """A script that runs cargo, itself or through parity_pipeline, gets the shared cache.

    Without it cargo falls back to the user's CARGO_HOME and builds a second copy of every
    dependency (ADR 0030).
    """
    config = tomllib.loads((REPO_ROOT / "mise.toml").read_text(encoding="utf-8"))
    builds = {
        path.name
        for path in SCRIPTS.glob("*.py")
        if path.name != "worktree_init.py"
        and any(
            needle in path.read_text(encoding="utf-8") for needle in ('"cargo"', "parity_pipeline")
        )
    }
    missing = [
        name
        for name, task in config["tasks"].items()
        if any(script in str(task.get("run", "")) for script in builds)
        and task.get("env", {}).get("CARGO_HOME") != "{{vars.cargo_home}}"
    ]
    assert not missing, missing


def test_build_at_sets_cargo_home() -> None:
    """build-at builds into its own target dir but must still name the shared cache."""
    config = tomllib.loads((REPO_ROOT / "mise.toml").read_text(encoding="utf-8"))
    assert config["tasks"]["build-at"]["env"]["CARGO_HOME"] == "{{vars.cargo_home}}"


def test_mise_config_renders_outside_a_git_checkout() -> None:
    """A checkout without git (a source archive, git's dubious-ownership refusal) still runs mise."""
    mise = shutil.which("mise")
    if mise is None:
        pytest.skip("mise is not on PATH")
    env = {**os.environ, "GIT_DIR": str(REPO_ROOT / "no-such-git-dir")}
    result = subprocess.run(  # noqa: S603 - fixed argv, mise resolved from PATH
        [mise, "vars"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    homes = [
        line.split()[1] for line in result.stdout.splitlines() if line.startswith("cargo_home")
    ]
    assert homes == [f"{REPO_ROOT}/.cache/cargo"], result.stdout
