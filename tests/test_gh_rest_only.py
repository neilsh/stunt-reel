"""No code under ``python/`` runs a ``gh`` command that needs GraphQL, outside its allow-list.

A cloud session's proxy refuses GitHub's GraphQL API, which ``gh issue``, ``gh pr``,
``gh repo view`` and ``gh api graphql`` use, so a script that runs there reaches GitHub through
``gh api`` REST (``docs/cloud-sessions.md``, "What a cloud session cannot do"). The check reads
each file's syntax tree for a ``gh`` argv: a list or tuple whose first item is ``"gh"`` or a
name ``gh``, or the string arguments of a call to a function named ``gh`` or ``_gh``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PYTHON = Path(__file__).resolve().parent.parent / "python"
#: Subcommand prefixes that reach GitHub through GraphQL.
GRAPHQL = (("issue",), ("pr",), ("repo", "view"), ("api", "graphql"))
_RUNNERS = frozenset(("gh", "_gh"))
#: Files that may use GraphQL because no cloud session runs them, each with why it needs to.
LOCAL_ONLY = {
    # GitHub's REST API neither lists a pull request's review threads nor resolves one.
    "scripts/pr_threads.py",
    # Only CI runs `--range`, which asks GraphQL for the merged PRs that hold a commit.
    "scripts/check_commit_msg.py",
    # Only `reap`, run from the owner's primary checkout, lists merged PRs with `gh pr list`.
    "scripts/worktree_init.py",
}


def _words(items: list[ast.expr]) -> tuple[str, ...]:
    """The string constants *items* starts with, up to two."""
    words: list[str] = []
    for item in items[:2]:
        if not (isinstance(item, ast.Constant) and isinstance(item.value, str)):
            break
        words.append(item.value)
    return tuple(words)


def _is_gh(node: ast.expr) -> bool:
    return (isinstance(node, ast.Constant) and node.value == "gh") or (
        isinstance(node, ast.Name) and node.id == "gh"
    )


def _subcommands(tree: ast.AST) -> list[tuple[int, tuple[str, ...]]]:
    """Each ``gh`` argv in *tree*: its line and the words of its subcommand."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.List | ast.Tuple) and node.elts and _is_gh(node.elts[0]):
            found.append((node.lineno, _words(node.elts[1:])))
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name in _RUNNERS:
                args = list(node.args)
                # A runner may take a working directory before the argv, as worktree_init's does.
                while args and not isinstance(args[0], ast.Constant | ast.Starred):
                    args.pop(0)
                found.append((node.lineno, _words(args)))
    return found


def graphql_calls(source: str) -> list[str]:
    """``<line>: gh <subcommand>`` for each ``gh`` argv in *source* that needs GraphQL."""
    return [
        f"{line}: gh {' '.join(words)}"
        for line, words in sorted(_subcommands(ast.parse(source)))
        if any(words[: len(prefix)] == prefix for prefix in GRAPHQL)
    ]


@pytest.mark.parametrize(
    ("source", "words"),
    [
        ('run(["gh", "issue", "view", "7"])', "issue view"),
        ('cmd = ("gh", "pr", "list")', "pr list"),
        ('run(["gh", "repo", "view", "--json", "nameWithOwner"])', "repo view"),
        ('run([gh, "api", "graphql", "-f", "query=q"])', "api graphql"),
        ('_gh("pr", "list")', "pr list"),
        ('self._gh(self._repo, "pr", "list")', "pr list"),
        ('_gh("api", "graphql", "-f", "query=q")', "api graphql"),
    ],
)
def test_a_graphql_gh_argv_is_found(source: str, words: str) -> None:
    assert graphql_calls(source) == [f"1: gh {words}"]


@pytest.mark.parametrize(
    "source",
    [
        'run(["gh", "api", "repos/{owner}/{repo}/issues/7", "--jq", "{title}"])',
        'run(["gh", "api", "-X", "POST", "repos/o/r/issues"])',
        'run(["gh", "repo", "set-default", "o/r"])',
        'run(["git", "issue"])',
        'x = ("title", "issue")',
        '_gh("api", "repos/o/r/pulls")',
    ],
)
def test_a_rest_or_local_argv_is_not(source: str) -> None:
    assert graphql_calls(source) == []


def test_python_reaches_github_through_rest() -> None:
    found = [
        f"python/{relative}:{call}"
        for path in sorted(PYTHON.rglob("*.py"))
        if (relative := path.relative_to(PYTHON).as_posix()) not in LOCAL_ONLY
        for call in graphql_calls(path.read_text(encoding="utf-8"))
    ]
    assert not found, (
        "these gh commands use GraphQL, which a cloud session's proxy refuses; reach GitHub "
        "through `gh api` REST instead (docs/cloud-sessions.md, 'What a cloud session cannot "
        "do'), or add a file no cloud session runs to LOCAL_ONLY, saying why:\n" + "\n".join(found)
    )


def test_every_local_only_file_exists() -> None:
    assert sorted(p for p in LOCAL_ONLY if not (PYTHON / p).is_file()) == []
