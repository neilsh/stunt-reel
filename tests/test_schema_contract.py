"""Contract tests for the Kaitai schema catalog.

``mise run check``` used to compile only the schemas a test happened to name, so a schema that
no longer compiled could ship green. These tests pin the catalog's shape and compile every
schema, including the compile-only ones under ``memory/`` that describe runtime memory rather
than a corpus file.

``STUNT_REQUIRE_KSC=1`` — set by ``python/scripts/gate.py`` for the ``test-py`` step — turns a
missing Kaitai compiler into a failure. Without it the compile test skips, so a plain
``pytest`` on a machine without the pinned toolchain still works.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path
from types import ModuleType

import pytest

from stunt_reel.kaitai import compile_schemas, ksc_command

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_ROOT = REPO_ROOT / "research" / "formats"
VERIFIER = REPO_ROOT / "python" / "scripts" / "verify_schemas_corpus.py"
REQUIRE_KSC = os.environ.get("STUNT_REQUIRE_KSC") == "1"


def _verifier() -> ModuleType:
    """Import ``verify_schemas_corpus`` by path so its private helpers can be asserted on."""
    spec = importlib.util.spec_from_file_location("verify_schemas_corpus", VERIFIER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before executing: the module defines dataclasses, and dataclasses
    # resolves string annotations through sys.modules[cls.__module__].
    sys.modules[spec.name or "verify_schemas_corpus"] = module
    spec.loader.exec_module(module)
    return module


def _schema_files() -> list[Path]:
    """Every committed schema, including the compile-only memory ones."""
    return sorted(SCHEMA_ROOT.rglob("*.ksy"))


def test_every_schema_declares_a_unique_id() -> None:
    """A schema without ``meta/id`` has no parser class and no stable name."""
    verifier = _verifier()
    ids: list[str] = []
    for path in _schema_files():
        match = verifier._ID_PATTERN.search(path.read_text(encoding="utf-8"))
        assert match is not None, f"{path}: schema must declare meta id"
        ids.append(match.group(1))
    assert len(ids) == len(set(ids)), f"duplicate schema ids: {sorted(ids)}"


def test_discovery_compiles_memory_schemas_without_sweeping_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A memory schema describes a runtime record: discovered, but with no corpus file.

    ``discover_schemas`` resolves ``research/formats`` from the working directory, so the test
    runs from the repository root rather than requiring a root argument.
    """
    monkeypatch.chdir(REPO_ROOT)
    specs = _verifier().discover_schemas()
    assert specs, "discover_schemas returned nothing"
    memory = {path.resolve() for path in (SCHEMA_ROOT / "memory").rglob("*.ksy")}
    assert memory, "expected at least one schema under memory/"
    by_path = {spec.path.resolve(): spec for spec in specs}
    assert memory <= set(by_path), "memory schemas must still be discovered, so they compile"
    for path in sorted(memory):
        spec = by_path[path]
        assert spec.extension is None, f"{path}: a memory schema sweeps no corpus file"
        assert spec.filename is None, f"{path}: a memory schema selects no corpus filename"
    for spec in specs:
        if spec.path.resolve() in memory:
            continue
        assert spec.extension is not None or spec.filename is not None, (
            f"{spec.path}: a non-memory schema must select the corpus files it describes"
        )


@pytest.mark.skipif(
    ksc_command() is None and not REQUIRE_KSC,
    reason="Kaitai compiler not on PATH (export STUNT_REQUIRE_KSC=1 to require it)",
)
def test_every_schema_compiles() -> None:
    """Every schema in the catalog must compile, not just the ones a test names."""
    if ksc_command() is None:
        pytest.fail("STUNT_REQUIRE_KSC=1 but the Kaitai compiler is not on PATH")
    schema_files = _schema_files()
    assert schema_files
    with tempfile.TemporaryDirectory(prefix="stunt-kaitai-catalog-") as tmp:
        compile_schemas(schema_files, tmp)
        generated = sorted(Path(tmp).glob("*.py"))
    assert len(generated) == len(schema_files), (
        f"{len(schema_files)} schemas compiled to {len(generated)} modules: "
        f"{[path.name for path in generated]}"
    )
