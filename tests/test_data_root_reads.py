"""Every library function that reads the configured data root on its own is listed with a reason.

A function handed a root must use it. On 2026-11-06 ``all_archive.resolve_all`` took a ``data``
root while its helpers read ``dataroot.data_root()`` themselves, and review found the gap one
helper at a time (the corpus copy, the stored archive, the manifest's game tree). A new read of
``data_root()`` or ``corpus_root()`` in ``python/stunt_reel/`` fails here until it is listed below
with its reason, or replaced by a root the caller passes.
"""

from __future__ import annotations

import ast
from pathlib import Path

LIBRARY = Path(__file__).resolve().parent.parent / "python" / "stunt_reel"

#: The implicit reads of the configured data root: ``data_root()`` and ``corpus_root()``.
READS = frozenset({"data_root", "corpus_root"})

#: (module path under ``stunt_reel``, enclosing function) -> why that function may read the configured root itself.
ALLOWED: dict[tuple[str, str], str] = {
    ("all_archive", "resolve_all"): "the default when the caller passes no data root",
    ("batch_stages", "_capture_problem"): "the batch survey runs on the configured root",
    (
        "batch_stages",
        "run_render",
    ): "the batch survey runs on the configured root; root is the checkout",
    (
        "batch_stages",
        "run_score",
    ): "the batch survey runs on the configured root; root is the checkout",
    ("capture_run", "_store_path"): "capture-ref writes into the configured store",
    ("capture_run", "build_root"): "capture-ref reads the game builds from the configured store",
    ("capture_run", "execute"): "capture-ref writes into the configured store",
    ("references", "archive_makeone_build"): (
        "callers pass the checkout, not a data root; the shipped trees are the configured corpus's"
    ),
    (
        "tac.staging",
        "_engine_root",
    ): "a film outside a game tree takes the configured demo's engine",
    ("tac.staging", "_stage"): "a capture stages its DOSBox mount under the configured store",
}


def _reads(path: Path) -> set[tuple[str, str]]:
    """The (module path, enclosing function) of every call to a READS function in *path*."""
    module = ".".join(path.relative_to(LIBRARY).with_suffix("").parts)
    found: set[tuple[str, str]] = set()

    def visit(node: ast.AST, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            inner = scope
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                inner = f"{scope}.{child.name}" if scope else child.name
            if isinstance(child, ast.Call):
                func = child.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if name in READS:
                    found.add((module, scope or "<module>"))
            visit(child, inner)

    visit(ast.parse(path.read_text(encoding="utf-8")), "")
    return found


def test_every_implicit_data_root_read_is_listed() -> None:
    found: set[tuple[str, str]] = set()
    for path in sorted(LIBRARY.rglob("*.py")):
        if path != LIBRARY / "dataroot.py":
            found |= _reads(path)
    unlisted = sorted(found - ALLOWED.keys())
    stale = sorted(ALLOWED.keys() - found)
    assert not unlisted, f"pass the root in, or list these with a reason: {unlisted}"
    assert not stale, f"no longer read the configured root; drop them from ALLOWED: {stale}"
