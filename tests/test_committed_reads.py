"""Only a ``test_committed_*`` test reads the committed reference rows or manifests.

A test that reads ``research/parity/references.toml`` or ``manifests/`` through the checkout
breaks whenever those files are repinned, though what it tests did not change: moving the
reference films to Patch 3 (#300) failed six such tests. Every other test writes the rows it
needs into a stand-in (the ``rows`` fixture), so a repin breaks only the tests that check the
committed files themselves, and their names say so.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent
#: A test whose name starts with this may read the committed files.
COMMITTED = "test_committed_"
#: Names on the right of ``REPO_ROOT /`` that lead into the committed rows or manifests.
_COMMITTED_NAMES = frozenset({"REFERENCES_FILE", "manifest_path"})
_COMMITTED_DIRS = ("manifests",)


def _is_repo_root(node: ast.expr) -> bool:
    return (isinstance(node, ast.Name) and node.id == "REPO_ROOT") or (
        isinstance(node, ast.Attribute) and node.attr == "REPO_ROOT"
    )


def _leads_to_committed_data(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.replace("\\", "/").split("/")[0] in _COMMITTED_DIRS
    if isinstance(node, ast.Call):
        node = node.func
    return (isinstance(node, ast.Name) and node.id in _COMMITTED_NAMES) or (
        isinstance(node, ast.Attribute) and node.attr in _COMMITTED_NAMES
    )


def _is_references_call(node: ast.Call) -> bool:
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "references"
    )


def committed_reads(tree: ast.Module) -> list[int]:
    """Lines outside a ``test_committed_*`` function that read committed data via ``REPO_ROOT``.

    A read is ``REPO_ROOT / <REFERENCES_FILE, manifest_path(...), "manifests"...>``
    or ``REPO_ROOT`` passed to a ``references.<function>`` call.
    """
    allowed: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith(
            COMMITTED
        ):
            allowed.update(id(inner) for inner in ast.walk(node))
    found: list[int] = []
    for node in ast.walk(tree):
        if id(node) in allowed:
            continue
        if (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Div)
            and _is_repo_root(node.left)
            and _leads_to_committed_data(node.right)
        ) or (
            isinstance(node, ast.Call)
            and _is_references_call(node)
            and any(_is_repo_root(arg) for arg in [*node.args, *(kw.value for kw in node.keywords)])
        ):
            found.append(node.lineno)
    return sorted(found)


def test_no_test_reads_committed_rows_outside_a_committed_test() -> None:
    offenders = [
        f"{path.name}:{line}"
        for path in sorted(TESTS.glob("*.py"))
        for line in committed_reads(ast.parse(path.read_text(encoding="utf-8")))
    ]
    assert not offenders, (
        "read the committed rows only in a test_committed_* test; elsewhere write them into "
        f"the rows fixture's stand-in: {', '.join(offenders)}"
    )


def test_the_check_flags_each_form_and_allows_committed_tests() -> None:
    source = """
FILMS = references.reference_films(REPO_ROOT)
def test_a():
    (dataroot.REPO_ROOT / parity_layout.REFERENCES_FILE).read_text()
    REPO_ROOT / "manifests" / "all"
    REPO_ROOT / parity_layout.manifest_path("vault-ctry")
def test_b(tmp_path):
    tmp_path / parity_layout.REFERENCES_FILE
    REPO_ROOT / "research" / "MAP.md"
    references.reference_films(tmp_path)
    references.reference_films(root=tmp_path)
def test_committed_rows():
    references.read_reference(REPO_ROOT, "ctry")
def test_c():
    references.reference_films(root=REPO_ROOT)
"""
    assert committed_reads(ast.parse(source)) == [2, 4, 5, 6, 15]
