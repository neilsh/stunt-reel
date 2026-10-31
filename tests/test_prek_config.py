"""The commit hooks run the repository's own tasks and nothing else (ADR 0026).

A hook configuration once drifted from the gate because it carried its own tool pins. These
checks keep `prek.toml` to the two shapes ADR 0026 allows: a local hook whose entry is exactly
`mise run <task>` for a leaf task of `mise.toml`, or one of a fixed set of prek built-ins.
Adding a hook means adding a leaf task first, or choosing a built-in, and updating the sets
below with the ADR.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The local hooks in `prek.toml` order, and the trigger keys each sets. `diff-check` and
#: `test-docs` fire on every commit: prek passes no deleted files to hooks, so a commit that only
#: deletes a linked page would otherwise skip the doc invariants.
LOCAL_HOOKS: dict[str, dict[str, Any]] = {
    "diff-check": {"always_run": True},
    "fmt-check-rust": {"types": ["rust"]},
    "fmt-check-py": {"types": ["python"]},
    "lint-py": {"types": ["python"]},
    "test-docs": {"always_run": True},
}

#: Every key a local hook must set.
REQUIRED_KEYS = {"id", "name", "entry", "language", "pass_filenames"}

#: The only keys that choose when a local hook fires: anything else (`stages`, `files`,
#: `exclude`, `args`) could silence a hook or change what it runs.
TRIGGER_KEYS = {"types", "always_run"}

#: The prek built-ins ADR 0026 adopts; none of them rewrites a file.
BUILTINS = {
    "check-added-large-files",
    "check-illegal-windows-names",
    "check-case-conflict",
    "check-merge-conflict",
    "check-toml",
    "check-yaml",
    "detect-private-key",
}


def _config() -> dict[str, Any]:
    with (REPO_ROOT / "prek.toml").open("rb") as handle:
        return tomllib.load(handle)


def _mise() -> dict[str, Any]:
    with (REPO_ROOT / "mise.toml").open("rb") as handle:
        return tomllib.load(handle)


def _hooks(repo: str) -> list[dict[str, Any]]:
    """The hooks of every `[[repos]]` entry whose `repo` is *repo*."""
    return [
        hook
        for entry in _config()["repos"]
        if entry["repo"] == repo
        for hook in entry.get("hooks", [])
    ]


def test_local_hooks_run_a_leaf_mise_task() -> None:
    tasks = _mise()["tasks"]
    for hook in _hooks("local"):
        assert hook["entry"] == f"mise run {hook['id']}"
        assert hook["language"] == "system"
        task = tasks[hook["id"]]
        assert "run" in task, f"{hook['id']} is not a leaf task"
        assert "depends" not in task, f"{hook['id']} is not a leaf task"


def test_local_hooks_take_no_arguments() -> None:
    for hook in _hooks("local"):
        assert hook["pass_filenames"] is False, f"{hook['id']} must not pass filenames"
        assert REQUIRED_KEYS <= set(hook) <= REQUIRED_KEYS | TRIGGER_KEYS, (
            f"{hook['id']} sets {sorted(set(hook) ^ REQUIRED_KEYS)}"
        )


def test_local_hooks_fire_as_the_adr_says() -> None:
    assert [hook["id"] for hook in _hooks("local")] == list(LOCAL_HOOKS)
    for hook in _hooks("local"):
        assert {key: hook[key] for key in TRIGGER_KEYS & set(hook)} == LOCAL_HOOKS[hook["id"]]


def test_builtin_hooks_are_the_adr_set() -> None:
    assert {hook["id"] for hook in _hooks("builtin")} == BUILTINS


def test_only_local_and_builtin_repositories() -> None:
    repos = _config()["repos"]
    assert {entry["repo"] for entry in repos} == {"local", "builtin"}
    assert all("rev" not in entry for entry in repos), "a hook repository carries a pin"


def test_pre_commit_task_runs_prek() -> None:
    mise = _mise()
    tasks = mise["tasks"]
    assert tasks["pre-commit"]["run"] == "prek run --config prek.toml"
    assert tasks["diff-check"]["run"] == "git diff --cached --check"
    assert "hooks" not in tasks, "nothing installs prek's own shim (ADR 0026)"
    assert re.fullmatch(r"\d+\.\d+\.\d+", mise["tools"]["prek"])


def test_prek_installs_nothing() -> None:
    assert "default_install_hook_types" not in _config()
