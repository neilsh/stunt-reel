"""Every test module that checks the platform, or imports a module that does, runs in the
pull-request Windows job.

``check-windows-smoke`` runs ``pytest -m windows``, so a module reaches the Windows job only
through its marker.  The job used to run a hand-kept list of files, and PR 124's target-seed
tests, which branch on ``sys.platform``, were left off it: no pull request ran them on Windows.
The marker sits on the module, as the list named whole files, so every test beside a platform
check runs where that check can go the other way.

A module can reach a platform branch without a check of its own: it imports a production module
that branches, such as ``capture_store``, whose swap lock is ``msvcrt`` on Windows.  The
branching production modules are discovered by scanning ``python/``, not listed by hand, so a
new branch cannot be left out of the job by forgetting an entry here.  Two promises soften the
rule, each with its reason and each checked: an allow-list for the JVM-backed schema suites the
pull-request job cannot run, and ``_COVERED_ELSEWHERE`` for a branching module whose importers
only use its platform-free surface.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent
PYTHON = TESTS.parent / "python"

#: ``module.attribute`` reads that tell one platform from another.
_PLATFORM_READS = frozenset({("sys", "platform"), ("os", "name"), ("platform", "system")})
#: Standard-library modules that exist only on Windows.
_WINDOWS_MODULES = frozenset({"msvcrt", "winreg", "_winapi"})

#: The packages under ``python/`` whose tests are part of the gate.
_PRODUCTION_PACKAGES = ("stunt_reel", "scripts")

#: Test modules that compile Kaitai schemas, which needs the JVM the pull-request Windows job
#: does not install: they import the branching compiler helper, or request the shared schema
#: fixture that does.  Keyed by file name, with the reason: an entry here is a promise, not a
#: convenience.
_JVM_SUITES = {
    "test_formats_catalog.py": "compiles every research schema with the Kaitai JVM",
    "test_schema_contract.py": "compiles the schema contract with the Kaitai JVM",
    "test_set_schema.py": "compiles a .ksy schema with the Kaitai JVM",
    "test_sod_schema.py": "compiles a .ksy schema with the Kaitai JVM",
    "test_spr_schema.py": "compiles a .ksy schema with the Kaitai JVM",
}

#: Branching modules whose importers need no marker because a marked suite runs the branch on
#: Windows; the rest import only the module's platform-free surface.  The guard checks that a
#: marked test still imports the module, so an entry cannot outlive its coverage.
_COVERED_ELSEWHERE = {
    "stunt_reel.dataroot": (
        "create_link and remove_link branch on os.name; test_dataroot, test_worktree_reap and "
        "test_worktree_seed run them on Windows, while the other suites read only REPO_ROOT, "
        "data_root() and corpus_root()"
    ),
}

#: Test modules that reach a platform branch without importing its module, so no import check
#: sees them: the driver is loaded from a path, or the branch sits behind another call.
_REACHED_INDIRECTLY = {
    "test_capture_run.py": "publishes through capture_store's swap lock via capture_run",
    "test_ghidra_sod_dispatch.py": "loads the dispatch driver by file path",
    "test_merge_driver.py": "runs Git for Windows' sh, the merge driver under test",
    "test_worktree_seed.py": "seeds target/ through the reparse-point checks",
}


def _platform_checks(tree: ast.Module) -> list[int]:
    """Lines where *tree* reads the platform or imports a Windows-only module.

    A read goes through whatever name the module was imported as, so ``import sys as
    system`` makes ``system.platform`` a check, and ``from os import name`` is one itself.
    A name keeps every module any scope binds it to: over-matching costs only a marker.
    """
    modules: dict[str, set[str]] = {}
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in _WINDOWS_MODULES:
                    lines.append(node.lineno)
                root = alias.name.split(".")[0]
                modules.setdefault(alias.asname or root, set()).add(
                    alias.name if alias.asname else root
                )
        elif isinstance(node, ast.ImportFrom) and (
            node.module in _WINDOWS_MODULES
            or any((node.module, alias.name) in _PLATFORM_READS for alias in node.names)
        ):
            lines.append(node.lineno)
    lines.extend(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and any((module, node.attr) in _PLATFORM_READS for module in modules.get(node.value.id, ()))
    )
    return sorted(lines)


def _discover_branching_modules(root: Path = PYTHON) -> dict[str, Path]:
    """The production modules under *root* that read the platform, by each import name.

    ``python/scripts`` is on ``pytest``'s ``pythonpath`` and has no ``__init__.py``, so a script
    is imported both as ``scripts.<stem>`` and by its bare name; a test may import either.
    """
    found: dict[str, Path] = {}
    for package in _PRODUCTION_PACKAGES:
        for path in sorted((root / package).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            if not _platform_checks(tree):
                continue
            parts = list(path.relative_to(root).with_suffix("").parts)
            if parts[-1] == "__init__":
                parts.pop()
            module = ".".join(parts)
            names = {module}
            if module.startswith("scripts."):
                names.add(module.removeprefix("scripts."))
            found.update(dict.fromkeys(names, path))
    return found


def _imported_modules(tree: ast.Module) -> set[str]:
    """Every dotted module name *tree* imports, including each name of a ``from`` import.

    A ``from stunt_reel import link`` names the module ``stunt_reel.link``, and a relative
    import names no module this checkout's production tree holds, so it is left out.
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names if alias.name != "*")
    return found


def _branching_imports(tree: ast.Module, modules: dict[str, Path]) -> list[str]:
    """The Windows-branching production modules *tree* imports, by import name, sorted."""
    return sorted(_imported_modules(tree) & set(modules))


def _is_windows_mark(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "windows"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "mark"
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "pytest"
    )


def _requests_compiled_schemas(tree: ast.Module) -> bool:
    """True when a test or fixture in *tree* takes the shared compiled-schema fixture."""
    return any(
        isinstance(node, ast.arg) and node.arg == "compiled_schemas" for node in ast.walk(tree)
    )


def _marked(tree: ast.Module) -> bool:
    """True when a module-level ``pytestmark`` carries ``pytest.mark.windows``."""
    return any(
        isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets
        )
        and any(_is_windows_mark(part) for part in ast.walk(node.value))
        for node in tree.body
    )


def _test_trees() -> dict[str, ast.Module]:
    """Every test module's parsed tree, keyed by file name."""
    return {
        path.name: ast.parse(path.read_text(encoding="utf-8"))
        for path in sorted(TESTS.glob("test_*.py"))
    }


def test_the_detector_sees_each_kind_of_platform_check() -> None:
    source = (
        "import msvcrt\n"
        "from winreg import HKEY_CURRENT_USER\n"
        "import os, platform, sys\n"
        "import sys as system\n"
        "from os import name as os_name\n"
        "A = sys.platform == 'win32'\n"
        "B = os.name == 'nt'\n"
        "C = platform.system()\n"
        "D = system.platform\n"
        "E = 'sys.platform in a string is not a check'\n"
        "F = system.path\n"
    )
    assert _platform_checks(ast.parse(source)) == [1, 2, 5, 6, 7, 8, 9]
    rebound = (
        "def a():\n"
        "    import sys as p\n"
        "    return p.platform\n"
        "def b():\n"
        "    import platform as p\n"
        "    return p.node()\n"
    )
    assert _platform_checks(ast.parse(rebound)) == [3]


def test_the_discovery_finds_every_branching_module(tmp_path: Path) -> None:
    """A new branch anywhere under ``python/`` is discovered, with no list to update."""
    for package in _PRODUCTION_PACKAGES:
        (tmp_path / package).mkdir()
    (tmp_path / "stunt_reel" / "windows.py").write_text(
        "import sys\nFLAG = sys.platform == 'win32'\n", encoding="utf-8"
    )
    (tmp_path / "stunt_reel" / "plain.py").write_text("FLAG = True\n", encoding="utf-8")
    (tmp_path / "scripts" / "tool.py").write_text("import msvcrt\n", encoding="utf-8")

    assert set(_discover_branching_modules(tmp_path)) == {
        "stunt_reel.windows",
        "scripts.tool",
        "tool",
    }


def test_the_discovery_finds_the_modules_issue_1044_names() -> None:
    modules = _discover_branching_modules()
    assert {
        "stunt_reel.ab_timing",
        "stunt_reel.capture_store",
        "stunt_reel.kaitai",
        "stunt_reel.link",
        "stunt_reel.parity_pipeline",
        "stunt_reel.process_tree",
        "stunt_reel.tac.automation",
        "stunt_reel.tac.timeout_evidence",
        "ghidra_sod_dispatch",
        "scripts.ghidra_sod_dispatch",
    } <= set(modules)


def test_the_detector_sees_a_branching_import() -> None:
    source = (
        "from stunt_reel import capture_store\n"
        "from stunt_reel.tac import automation\n"
        "import stunt_reel.link\n"
        "from stunt_reel.parity_pipeline import Run\n"
        "from stunt_reel import parity_layout\n"
        "from . import kaitai\n"
    )
    assert _branching_imports(ast.parse(source), _discover_branching_modules()) == [
        "stunt_reel.capture_store",
        "stunt_reel.link",
        "stunt_reel.parity_pipeline",
        "stunt_reel.tac.automation",
    ]


def test_the_detector_sees_the_compiled_schema_fixture() -> None:
    assert _requests_compiled_schemas(ast.parse("def test_x(compiled_schemas): pass\n"))
    assert not _requests_compiled_schemas(ast.parse("def test_x(tmp_path): pass\n"))


def test_the_detector_sees_a_bare_script_import() -> None:
    """``python/scripts`` has no ``__init__.py``, so a script is imported by its bare name."""
    modules = _discover_branching_modules()
    for source in (
        "import ghidra_sod_dispatch\n",
        "from ghidra_sod_dispatch import _analyze_headless\n",
    ):
        assert _branching_imports(ast.parse(source), modules) == ["ghidra_sod_dispatch"]


def test_only_a_module_level_mark_counts() -> None:
    assert _marked(ast.parse("import pytest\npytestmark = pytest.mark.windows\n"))
    assert _marked(
        ast.parse("import pytest\npytestmark = [pytest.mark.slow, pytest.mark.windows]\n")
    )
    assert not _marked(ast.parse("import pytest\n@pytest.mark.windows\ndef test_x(): pass\n"))


def test_every_test_that_reaches_a_platform_branch_carries_the_windows_marker() -> None:
    modules = _discover_branching_modules()
    checked: list[str] = []
    unmarked: list[str] = []
    for name, tree in _test_trees().items():
        lines = _platform_checks(tree)
        imports = (
            []
            if name in _JVM_SUITES
            else [
                module
                for module in _branching_imports(tree, modules)
                if module not in _COVERED_ELSEWHERE
            ]
        )
        if not lines and not imports:
            continue
        checked.append(name)
        if not _marked(tree):
            where = f"{name}:{lines[0]}" if lines else f"{name} imports {imports[0]}"
            unmarked.append(where)
    assert "test_target_seed.py" in checked, "the detector missed a known platform check"
    assert "test_link.py" in checked, "the detector missed a known branching import"
    assert "test_ab_timing.py" in checked, "the detector missed a branching import"
    assert not unmarked, (
        f"{unmarked} check the platform, or import a module that does, without "
        "`pytestmark = pytest.mark.windows`; the pull-request Windows job "
        "(check-windows-smoke) runs only marked modules"
    )


def test_every_jvm_suite_exists_and_is_still_unmarked() -> None:
    """An allow-list entry names a test that reaches the compiler and is not marked for it."""
    modules = _discover_branching_modules()
    trees = _test_trees()
    for name, reason in _JVM_SUITES.items():
        assert name in trees, f"{name} does not exist: {reason}"
        reaches_compiler = _branching_imports(trees[name], modules) or _requests_compiled_schemas(
            trees[name]
        )
        assert reaches_compiler, (
            f"{name} no longer imports a branching module or requests compiled_schemas: {reason}"
        )
        assert not _marked(trees[name]), f"{name} is marked, so drop it from the JVM allow-list"


def test_every_indirectly_reached_branch_is_marked() -> None:
    trees = _test_trees()
    for name, reason in _REACHED_INDIRECTLY.items():
        assert name in trees, f"{name} does not exist: {reason}"
        assert _marked(trees[name]), (
            f"{name} reaches a platform branch without the marker: {reason}"
        )


def test_every_excepted_module_is_branching_and_has_a_marked_importer() -> None:
    """An exception without a marked suite running the branch is a gap, not a reason."""
    modules = _discover_branching_modules()
    trees = _test_trees()
    for module, reason in _COVERED_ELSEWHERE.items():
        assert module in modules, f"{module} no longer reads the platform: {reason}"
        covered = [
            name
            for name, tree in trees.items()
            if _marked(tree) and module in _branching_imports(tree, modules)
        ]
        assert covered, f"no marked test imports {module}, whose branch it must cover: {reason}"
