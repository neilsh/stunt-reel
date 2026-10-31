"""The commit hooks run the gate's own tasks and nothing else (ADR 0026).

A hook configuration once drifted from the gate because it carried its own tool pins. These
checks keep `prek.toml` to the two shapes ADR 0026 allows: a local hook whose entry is exactly
`mise run <step>` for a step in `gate.STEPS`, or one of a fixed set of prek built-ins. Adding a
hook means adding a gate step first, or choosing a built-in, and updating the sets below with
the ADR.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import gate  # noqa: E402

#: The gate steps that run at commit, and the file types that trigger each.
GATE_HOOKS = {"fmt-check-rust": ["rust"], "fmt-check-py": ["python"], "lint-py": ["python"]}

#: Every key a local hook may set: anything else (`stages`, `files`, `exclude`, `always_run`) could
#: silence a hook or change when it fires.
LOCAL_HOOK_KEYS = {"id", "name", "entry", "language", "types", "pass_filenames"}

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


def _hooks(repo: str) -> list[dict[str, Any]]:
    """The hooks of every `[[repos]]` entry whose `repo` is *repo*."""
    return [
        hook
        for entry in _config()["repos"]
        if entry["repo"] == repo
        for hook in entry.get("hooks", [])
    ]


def test_local_hooks_run_a_gate_step() -> None:
    steps = {*gate.STEPS["rust"], *gate.STEPS["py"]}
    for hook in _hooks("local"):
        assert hook["id"] in steps, f"{hook['id']} is not a gate step"
        assert hook["entry"] == f"mise run {hook['id']}"
        assert hook["language"] == "system"


def test_local_hooks_take_no_arguments() -> None:
    for hook in _hooks("local"):
        assert hook["pass_filenames"] is False, f"{hook['id']} must not pass filenames"
        assert "args" not in hook, f"{hook['id']} must not add arguments to the gate step"
        assert set(hook) == LOCAL_HOOK_KEYS, (
            f"{hook['id']} sets {sorted(set(hook) ^ LOCAL_HOOK_KEYS)}"
        )


def test_local_hooks_are_the_adr_set() -> None:
    assert {hook["id"]: hook["types"] for hook in _hooks("local")} == GATE_HOOKS


def test_builtin_hooks_are_the_adr_set() -> None:
    assert {hook["id"] for hook in _hooks("builtin")} == BUILTINS


def test_only_local_and_builtin_repositories() -> None:
    repos = _config()["repos"]
    assert {entry["repo"] for entry in repos} == {"local", "builtin"}
    assert all("rev" not in entry for entry in repos), "a hook repository carries a pin"


def test_installs_only_the_pre_commit_shim() -> None:
    assert _config()["default_install_hook_types"] == ["pre-commit"]


def test_prek_is_pinned_and_installed_through_mise() -> None:
    with (REPO_ROOT / "mise.toml").open("rb") as handle:
        mise = tomllib.load(handle)
    assert re.fullmatch(r"\d+\.\d+\.\d+", mise["tools"]["prek"])
    # Git shares .git/hooks across worktrees, and prek fails a commit when the checkout has no
    # prek.toml unless the shim was installed to allow that: a worktree on an older branch, or
    # the primary checkout before this change merged, must still commit. The explicit --config
    # keeps such a checkout from running an old .pre-commit-config.yaml instead.
    assert (
        mise["tasks"]["hooks"]["run"] == "prek install --config ./prek.toml --allow-missing-config"
    )
