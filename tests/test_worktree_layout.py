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
from typing import Any

import pytest

pytestmark = pytest.mark.windows

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "python" / "scripts"

#: The doc checker matches ``corpus/`` in the text of other pages; it reads no corpus file.
_NOT_READERS = frozenset({"verify_formats_docs.py"})
#: Calls whose arguments are read against the data root rather than the working directory.
_RESOLVERS = frozenset({"resolve_data_path", "data_path_arg", "corpus_root", "corpus_of"})

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


def _call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    return node.attr if isinstance(node, ast.Attribute) else ""


def _names_corpus(value: object) -> bool:
    return isinstance(value, str) and (value == "corpus" or value.startswith("corpus/"))


def _docstrings(tree: ast.Module) -> set[ast.AST]:
    found: set[ast.AST] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                found.add(first.value)
    return found


def _resolved(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """True when the ``corpus`` literal *node* is read against the data root, or not read."""
    parent = parents.get(node)
    while parent is not None and not isinstance(parent, ast.stmt):
        if isinstance(parent, ast.Call) and _call_name(parent.func) in _RESOLVERS:
            return True
        if isinstance(parent, ast.keyword) and parent.arg == "help":
            return True
        if isinstance(parent, ast.keyword) and parent.arg == "default":
            call = parents[parent]
            assert isinstance(call, ast.Call)
            return any(
                k.arg == "type" and _call_name(k.value) == "data_path_arg" for k in call.keywords
            )
        parent = parents.get(parent)
    return False


def _unresolved_corpus_literals(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    docstrings = _docstrings(tree)
    return [
        f"{path.relative_to(REPO_ROOT).as_posix()}:{node.lineno}: {node.value!r}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and _names_corpus(node.value)
        and node not in docstrings
        and not _resolved(node, parents)
    ]


PYTHON_FILES = sorted(
    path
    for path in (*SCRIPTS.glob("*.py"), *(REPO_ROOT / "python" / "stunt_reel").rglob("*.py"))
    if path.name != "dataroot.py" and path.name not in _NOT_READERS
)


def test_no_module_reads_a_data_path_relative_to_the_working_directory() -> None:
    """A ``corpus`` literal outside a resolver reads the checkout, which holds no corpus (ADR 0036)."""
    offenders = [line for path in PYTHON_FILES for line in _unresolved_corpus_literals(path)]
    assert offenders == [], "read it through dataroot.resolve_data_path or corpus_root"


def test_nothing_calls_the_retired_link_repair() -> None:
    assert not any("ensure_links_or_report" in p.read_text(encoding="utf-8") for p in PYTHON_FILES)


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
    assert "--git-common-dir" in config["vars"]["primary"]
    assert config["vars"]["cargo_home"].startswith("{{vars.primary}}/")
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
    missing = [
        name
        for name in _tasks_that_build(config)
        if config["tasks"][name].get("env", {}).get("CARGO_HOME") != "{{vars.cargo_home}}"
    ]
    assert not missing, missing


#: What a script names when it runs cargo: itself, through the parity pipeline, or by building
#: the release binary that ``stuntreel link`` needs before it rebuilds a film's ``.ALL``.
_BUILDS = ('"cargo"', "parity_pipeline", "ensure_binary", "resolve_all")


def _tasks_that_build(config: dict[str, Any]) -> list[str]:
    """The tasks that run cargo, directly or through a script that does."""
    scripts = {
        path.name
        for path in SCRIPTS.glob("*.py")
        if path.name != "worktree_init.py"
        and any(needle in path.read_text(encoding="utf-8") for needle in _BUILDS)
    }
    return [
        name
        for name, task in config["tasks"].items()
        if "CARGO_HOME" in task.get("env", {})
        or any(script in str(task.get("run", "")) for script in scripts)
    ]


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


def test_every_task_that_builds_depends_on_ensure() -> None:
    """A new worktree's first cargo task seeds target/ first, with no init (ADR 0036)."""
    config = tomllib.loads((REPO_ROOT / "mise.toml").read_text(encoding="utf-8"))
    # Formatting and the advisory check build nothing; check-rust runs tasks that do; init
    # and seed call ensure's code themselves.
    exempt = {"fmt-rust", "fmt-check-rust", "deny", "check-rust", "init", "seed"}
    missing = [
        name
        for name in _tasks_that_build(config)
        if name not in exempt and "ensure" not in config["tasks"][name].get("depends", [])
    ]
    assert missing == []
    assert config["tasks"]["ensure"]["hide"] is True
    assert config["tasks"]["ensure"]["env"] == config["tasks"]["init"]["env"]


def test_the_uv_cache_is_the_primarys_by_absolute_path() -> None:
    """No .cache link: every checkout names the primary's uv cache directly (ADR 0036)."""
    config = tomllib.loads((REPO_ROOT / "mise.toml").read_text(encoding="utf-8"))
    assert config["env"]["UV_CACHE_DIR"] == "{{vars.primary}}/.cache/uv"


def test_tasks_use_the_os_temp_directory() -> None:
    """The temp override existed only for DSH's sandbox (ADR 0036)."""
    config = tomllib.loads((REPO_ROOT / "mise.toml").read_text(encoding="utf-8"))
    assert "TMP" not in config["env"]
    assert "TEMP" not in config["env"]


@pytest.mark.parametrize("name", ["sod-census", "test-corpus"])
def test_rust_corpus_readers_take_the_corpus_python_resolves(name: str) -> None:
    """dataroot is the one place that finds the corpus; Rust is handed it (ADR 0036).

    The path travels in ``STUNT_CORPUS``, never a shell command line, where a ``$(...)``, a
    quote or an ``&`` in it would run, and no template in mise.toml repeats the rule.
    """
    config = tomllib.loads((REPO_ROOT / "mise.toml").read_text(encoding="utf-8"))
    task = config["tasks"][name]
    assert task["run"].startswith("uv run python python/scripts/run_with_corpus.py cargo ")
    assert "--corpus" not in task["run"]
    assert "{%" not in str(task["env"])
    assert "ensure" in task["depends"]


def test_the_data_root_var_sits_beside_the_primary() -> None:
    config = tomllib.loads((REPO_ROOT / "mise.toml").read_text(encoding="utf-8"))
    assert config["vars"]["data_root"] == "{{vars.primary}}.data"
    assert config["vars"]["cargo_home"] == "{{vars.primary}}/.cache/cargo"


@pytest.mark.parametrize("with_git", [True, False])
def test_cargo_home_renders_in_a_checkout_whose_path_has_an_ampersand(
    tmp_path: Path, *, with_git: bool
) -> None:
    """The shell runs a `&` in a path it is handed, so the checkout path never reaches it."""
    mise = shutil.which("mise")
    git = shutil.which("git")
    if mise is None or git is None:
        pytest.skip("mise or git is not on PATH")
    checkout = tmp_path / "r&d"
    checkout.mkdir()
    config = tomllib.loads((REPO_ROOT / "mise.toml").read_text(encoding="utf-8"))
    lines = ["[vars]"]
    for name in ("primary", "cargo_home"):
        template = config["vars"][name].replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'{name} = "{template}"')
    (checkout / "mise.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    env = {**os.environ, "MISE_TRUSTED_CONFIG_PATHS": str(checkout)}
    if with_git:
        subprocess.run([git, "init", "-q", str(checkout)], check=True)  # noqa: S603 - fixed argv
    else:
        env["GIT_DIR"] = str(checkout / "no-such-git-dir")
    result = subprocess.run(  # noqa: S603 - fixed argv, mise resolved from PATH
        [mise, "vars"], cwd=checkout, env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    rendered = {
        line.split(None, 1)[0]: Path(line.split(None, 1)[1].rsplit(None, 1)[0])
        for line in result.stdout.splitlines()
        if line.startswith(("primary", "cargo_home"))
    }
    assert rendered == {"primary": checkout, "cargo_home": checkout / ".cache" / "cargo"}, (
        result.stdout
    )


def test_no_reference_capture_is_opened_under_the_checkout() -> None:
    """A capture is in the data root; ``open_reference(REPO_ROOT, ...)`` reads a path no checkout has."""
    readers = {"open_reference", "reference_job", "read_reference"}
    offenders = [
        f"{path.relative_to(REPO_ROOT).as_posix()}:{node.lineno}"
        for path in PYTHON_FILES
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and _call_name(node.func) in readers
        and node.args
        and _call_name(node.args[0]) == "REPO_ROOT"
    ]
    assert offenders == []
