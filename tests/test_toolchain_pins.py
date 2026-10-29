"""One owner per tool pin: mise installs, rustup resolves, the floors stay policy.

`mise.toml` and `rust-toolchain.toml` name the Rust channel twice, and one Python
version appears as a pin (`mise.toml`), a floor (`requires-python`) and two targets
(`[tool.ruff]`, `[tool.mypy]`).  The "Dependency updates" section of
[docs/development.md](../docs/development.md) splits those into pins a bot may move, floors
it may not, and targets that follow the floor; this is what makes the split enforceable
instead of aspirational.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Rustup spells the component `llvm-tools-preview`; mise accepts `llvm-tools`.
_LLVM_TOOLS = frozenset({"llvm-tools", "llvm-tools-preview"})


def _toml(name: str) -> dict[str, Any]:
    with (REPO_ROOT / name).open("rb") as handle:
        return tomllib.load(handle)


def _numbers(text: str) -> tuple[int, int, int]:
    """The first three integers in *text*, zero-filled: `3.11` -> `(3, 11, 0)`."""
    parts = [int(part) for part in re.findall(r"\d+", text)[:3]]
    major, minor, patch = [*parts, 0, 0, 0][:3]
    return (major, minor, patch)


def _mise_tools() -> dict[str, Any]:
    tools: dict[str, Any] = _toml("mise.toml")["tools"]
    return tools


def _pin(tool: Any) -> str:
    """A mise pin is a version string or an inline table carrying `version`."""
    value: str = str(tool["version"]) if isinstance(tool, dict) else str(tool)
    return value


def _components(value: Any) -> set[str]:
    """Component names from mise's comma-separated string or rustup's list."""
    raw = value.split(",") if isinstance(value, str) else list(value)
    return {name.strip() for name in raw}


def _ruff_target(text: str) -> tuple[int, int]:
    """`py311` -> `(3, 11)`."""
    digits = text.removeprefix("py")
    return (int(digits[:-2]), int(digits[-2:]))


#: A JSONC string literal, a `//` comment, or a `/* */` comment: group 1 keeps strings.
_JSONC_TOKENS = re.compile(r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*.*?\*/', re.DOTALL)


def _jsonc_as_json(text: str) -> str:
    """*text* as JSON: comments dropped and trailing commas removed, strings left whole.

    A `//` inside a string must survive, which matters here: the schema URL contains one.
    """
    without_comments = _JSONC_TOKENS.sub(lambda match: match.group(1) or "", text)
    return re.sub(r",(\s*[}\]])", r"\1", without_comments)


def _renovate_config() -> dict[str, Any]:
    text = (REPO_ROOT / ".github" / "renovate.jsonc").read_text(encoding="utf-8")
    raw: dict[str, Any] = json.loads(_jsonc_as_json(text))
    return raw


def test_the_rust_compiler_is_declared_once_per_role() -> None:
    mise = _mise_tools()["rust"]
    toolchain: dict[str, Any] = _toml("rust-toolchain.toml")["toolchain"]
    assert _pin(mise) == toolchain["channel"], (
        "mise.toml installs one Rust and rust-toolchain.toml resolves another; "
        "rustup would download a second toolchain on the next cargo call"
    )


def test_both_rust_declarations_provide_the_llvm_tools() -> None:
    mise = _mise_tools()["rust"]
    toolchain: dict[str, Any] = _toml("rust-toolchain.toml")["toolchain"]
    assert _components(mise["components"]) & _LLVM_TOOLS, "mise.toml's rust lost the LLVM tools"
    assert _components(toolchain["components"]) & _LLVM_TOOLS, (
        "rustup resolves the toolchain from rust-toolchain.toml, so that file must name the "
        "LLVM tools or `mise run cov-rust` breaks on a machine mise did not install"
    )


def test_the_python_pin_satisfies_the_floor() -> None:
    pin = _numbers(_pin(_mise_tools()["python"]))[:2]
    floor = _numbers(_toml("pyproject.toml")["project"]["requires-python"])[:2]
    assert pin >= floor, f"mise.toml pins Python {pin} below the requires-python floor {floor}"


def test_the_python_targets_follow_the_pin() -> None:
    pin = _numbers(_pin(_mise_tools()["python"]))[:2]
    pyproject = _toml("pyproject.toml")
    assert _ruff_target(str(pyproject["tool"]["ruff"]["target-version"])) == pin, (
        "ruff's target-version no longer matches the interpreter mise installs; Renovate "
        "cannot move it, so the pin has outrun its target"
    )
    mypy_target = _numbers(str(pyproject["tool"]["mypy"]["python_version"]))[:2]
    assert mypy_target == pin, "mypy's python_version no longer matches the interpreter"


def test_there_is_no_second_python_pin() -> None:
    assert not (REPO_ROOT / ".python-version").exists(), (
        "a .python-version file is a second Python pin: mise ignores it and uv acts on it, "
        "so a bump can leave uv downloading an interpreter nobody runs"
    )


def test_the_jsonc_reader_keeps_strings_whole() -> None:
    text = '{ "url": "https://example.test/x", // a comment\n "count": 1 }'
    stripped = _jsonc_as_json(text)
    assert json.loads(stripped) == {"url": "https://example.test/x", "count": 1}


def test_every_renovate_rule_states_its_reason() -> None:
    rules: list[dict[str, Any]] = _renovate_config()["packageRules"]
    assert rules, "the config groups nothing, which is the behaviour the docs reject"
    for rule in rules:
        assert rule.get("description"), f"a packageRules entry states no reason: {rule}"


def test_nothing_auto_merges() -> None:
    assert '"automerge":' not in json.dumps(_renovate_config()), (
        "the repository leaves merging to a human; no rule may enable automerge"
    )
