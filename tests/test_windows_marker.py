"""Every test module that checks the platform runs in the pull-request Windows job.

``check-windows-smoke`` runs ``pytest -m windows``, so a module reaches the Windows job
only through its marker.  The job used to run a hand-kept list of files, and PR 124's
target-seed tests, which branch on ``sys.platform``, were left off it: no pull request ran
them on Windows.  The marker sits on the module, as the list named whole files, so every
test beside a platform check runs where that check can go the other way.
"""

from __future__ import annotations

import ast
from pathlib import Path

TESTS = Path(__file__).resolve().parent

#: ``module.attribute`` reads that tell one platform from another.
_PLATFORM_READS = frozenset({("sys", "platform"), ("os", "name"), ("platform", "system")})
#: Standard-library modules that exist only on Windows.
_WINDOWS_MODULES = frozenset({"msvcrt", "winreg", "_winapi"})


def _is_platform_check(node: ast.Attribute | ast.Import | ast.ImportFrom) -> bool:
    if isinstance(node, ast.Attribute):
        return isinstance(node.value, ast.Name) and (node.value.id, node.attr) in _PLATFORM_READS
    if isinstance(node, ast.Import):
        return any(alias.name in _WINDOWS_MODULES for alias in node.names)
    return node.module in _WINDOWS_MODULES


def _platform_checks(tree: ast.Module) -> list[int]:
    """Lines where *tree* reads the platform or imports a Windows-only module."""
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, (ast.Attribute, ast.Import, ast.ImportFrom))
        and _is_platform_check(node)
    )


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
        "A = sys.platform == 'win32'\n"
        "B = os.name == 'nt'\n"
        "C = platform.system()\n"
        "D = 'sys.platform in a string is not a check'\n"
    )
    assert _platform_checks(ast.parse(source)) == [1, 2, 4, 5, 6]


def test_only_a_module_level_mark_counts() -> None:
    assert _marked(ast.parse("import pytest\npytestmark = pytest.mark.windows\n"))
    assert _marked(
        ast.parse("import pytest\npytestmark = [pytest.mark.slow, pytest.mark.windows]\n")
    )
    assert not _marked(ast.parse("import pytest\n@pytest.mark.windows\ndef test_x(): pass\n"))


def test_every_module_that_checks_the_platform_carries_the_windows_marker() -> None:
    checked: list[str] = []
    unmarked: list[str] = []
    for path in sorted(TESTS.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        lines = _platform_checks(tree)
        if lines:
            checked.append(path.name)
            if not _marked(tree):
                unmarked.append(f"{path.name}:{lines[0]}")
    assert "test_target_seed.py" in checked, "the detector missed a known platform check"
    assert not unmarked, (
        f"{unmarked} check the platform without `pytestmark = pytest.mark.windows`; "
        "the pull-request Windows job (check-windows-smoke) runs only marked modules"
    )
