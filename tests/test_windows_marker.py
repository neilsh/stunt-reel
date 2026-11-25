"""Every test module that checks the platform, or imports a module that does, runs in the
pull-request Windows job.

``check-windows-smoke`` runs ``pytest -m windows``, so a module reaches the Windows job only
through its marker.  The job used to run a hand-kept list of files, and PR 124's target-seed
tests, which branch on ``sys.platform``, were left off it: no pull request ran them on Windows.
The marker sits on the module, as the list named whole files, so every test beside a platform
check runs where that check can go the other way.

A module can reach a platform branch without a check of its own: it imports a production module
that branches, such as ``capture_store``, whose swap lock is ``msvcrt`` on Windows.  Those
imports are checked too, so a test of Windows behaviour cannot skip the job by leaving the
branch one call away.
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

#: Production modules with a platform branch, keyed by dotted module, with the branch each owns.
#: A test module that imports one carries the marker, unless ``_JVM_SUITES`` gives its reason.
_WINDOWS_BRANCHES = {
    "stunt_reel.capture_store": "the msvcrt swap lock and its fcntl counterpart",
    "stunt_reel.link": "the .exe binary name and binary_locked",
    "stunt_reel.parity_pipeline": "physical_memory through ctypes or sysconf",
    "stunt_reel.kaitai": "the .bat launcher shim and its COMSPEC",
    "stunt_reel.tac.automation": "headless_env's SDL drivers",
    "stunt_reel.tac.timeout_evidence": "emulator_processes through tasklist",
    "scripts.ghidra_sod_dispatch": "_analyze_headless's .bat launcher",
}

#: Test modules that import a branch only to compile Kaitai schemas, which needs the JVM the
#: pull-request Windows job does not install.  Keyed by file name, with the reason: an entry
#: here is a promise, not a convenience.
_JVM_SUITES = {
    "test_formats_catalog.py": "compiles every research schema with the Kaitai JVM",
    "test_schema_contract.py": "compiles the schema contract with the Kaitai JVM",
    "test_set_schema.py": "compiles a .ksy schema with the Kaitai JVM",
    "test_sod_schema.py": "compiles a .ksy schema with the Kaitai JVM",
    "test_spr_schema.py": "compiles a .ksy schema with the Kaitai JVM",
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


def _branching_imports(tree: ast.Module) -> list[str]:
    """The Windows-branching production modules *tree* imports, sorted."""
    return sorted(_imported_modules(tree) & _WINDOWS_BRANCHES.keys())


def _production_module(module: str) -> Path:
    """The file the dotted production *module* lives in."""
    return PYTHON.joinpath(*module.split(".")).with_suffix(".py")


def _is_windows_mark(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "windows"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "mark"
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "pytest"
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


def test_the_detector_sees_a_branching_import() -> None:
    source = (
        "from stunt_reel import capture_store\n"
        "from stunt_reel.tac import automation\n"
        "import stunt_reel.link\n"
        "from stunt_reel.parity_pipeline import Run\n"
        "from stunt_reel import parity_layout\n"
        "from . import kaitai\n"
    )
    assert _branching_imports(ast.parse(source)) == [
        "stunt_reel.capture_store",
        "stunt_reel.link",
        "stunt_reel.parity_pipeline",
        "stunt_reel.tac.automation",
    ]


def test_only_a_module_level_mark_counts() -> None:
    assert _marked(ast.parse("import pytest\npytestmark = pytest.mark.windows\n"))
    assert _marked(
        ast.parse("import pytest\npytestmark = [pytest.mark.slow, pytest.mark.windows]\n")
    )
    assert not _marked(ast.parse("import pytest\n@pytest.mark.windows\ndef test_x(): pass\n"))


def test_every_test_that_reaches_a_platform_branch_carries_the_windows_marker() -> None:
    checked: list[str] = []
    unmarked: list[str] = []
    for path in sorted(TESTS.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        lines = _platform_checks(tree)
        imports = [] if path.name in _JVM_SUITES else _branching_imports(tree)
        if not lines and not imports:
            continue
        checked.append(path.name)
        if not _marked(tree):
            where = f"{path.name}:{lines[0]}" if lines else f"{path.name} imports {imports[0]}"
            unmarked.append(where)
    assert "test_target_seed.py" in checked, "the detector missed a known platform check"
    assert "test_link.py" in checked, "the detector missed a known branching import"
    assert not unmarked, (
        f"{unmarked} check the platform, or import a module that does, without "
        "`pytestmark = pytest.mark.windows`; the pull-request Windows job "
        "(check-windows-smoke) runs only marked modules"
    )


def test_every_branching_module_still_branches() -> None:
    """A registry entry whose branch is gone is rot: drop it or name the new branch."""
    for module, branch in _WINDOWS_BRANCHES.items():
        path = _production_module(module)
        assert path.is_file(), f"{module} is not at {path}"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert _platform_checks(tree), f"{module} no longer checks the platform: {branch}"


def test_every_jvm_suite_exists_and_is_still_unmarked() -> None:
    """An allow-list entry names a test that imports a branch and is not marked for it."""
    for name, reason in _JVM_SUITES.items():
        path = TESTS / name
        assert path.is_file(), f"{name} does not exist: {reason}"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert _branching_imports(tree), f"{name} no longer imports a branching module: {reason}"
        assert not _marked(tree), f"{name} is marked, so drop it from the JVM allow-list"


def test_every_indirectly_reached_branch_is_marked() -> None:
    for name, reason in _REACHED_INDIRECTLY.items():
        path = TESTS / name
        assert path.is_file(), f"{name} does not exist: {reason}"
        assert _marked(ast.parse(path.read_text(encoding="utf-8"))), (
            f"{name} reaches a platform branch without the marker: {reason}"
        )
