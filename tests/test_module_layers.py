"""The package's module layers in `tach.toml` cover every module and fail a planted violation.

`mise run check-layers` runs `tach check` on the tree as it is; these tests check that the
configuration would catch a change. The planted imports run on one module-scoped copy of
`python/`, restored after each case, so the checkout is never edited and every violation is
tested independently. The module carries the `windows` marker so the pull-request Windows job
runs tach there too, and an `xdist_group` so one worker serves all the cases with that one copy:
the gate runs on both platforms (ADR 0050).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

LAYERS_GROUP = "tach-layers"

pytestmark = [pytest.mark.windows, pytest.mark.xdist_group(LAYERS_GROUP)]

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "python" / "stunt_reel"


def _grouped() -> set[str]:
    config = tomllib.loads((ROOT / "tach.toml").read_text(encoding="utf-8"))
    paths: set[str] = set()
    for module in config["modules"]:
        paths.update(module.get("paths", [module.get("path")]))
    return paths


def test_every_package_module_is_in_a_group() -> None:
    found = {
        f"stunt_reel.{path.stem}"
        for path in PACKAGE.iterdir()
        if (path.suffix == ".py" and path.name != "__init__.py")
        or (path.is_dir() and (path / "__init__.py").is_file())
    }
    grouped = {path for path in _grouped() if path.startswith("stunt_reel.")}
    assert found - grouped == set(), "a module tach.toml puts in no group"
    assert grouped - found == set(), "a group names a module the package does not have"


def _tach_check(tree: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "tach", "check"],
        cwd=tree,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


@pytest.fixture(scope="module")
def layer_tree(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One disposable checkout for every planted violation in this module.

    The module's tests carry ``LAYERS_GROUP`` and the gate runs ``--dist loadgroup``, so one
    worker runs them in sequence and one copy of ``python/`` serves all six; a test appends its
    plant and restores the file in ``finally``, so the next case starts from the clean tree.
    """
    tree = tmp_path_factory.mktemp("tach-layers")
    shutil.copy2(ROOT / "tach.toml", tree / "tach.toml")
    shutil.copytree(ROOT / "python", tree / "python", ignore=shutil.ignore_patterns("__pycache__"))
    return tree


@pytest.mark.parametrize(
    ("module", "planted", "message"),
    [
        (None, "", ""),
        (
            "stunt_reel/capture_store.py",
            "from stunt_reel import parity_judge",
            "Layer 'capture' ('stunt_reel.capture_store') is lower than layer 'parity'",
        ),
        (
            "stunt_reel/work_items.py",
            "from stunt_reel import tac",
            "Module 'stunt_reel.work_items' cannot depend on 'stunt_reel.tac'",
        ),
        (
            "stunt_reel/dataroot.py",
            "import gate",
            "Layer 'shared' ('stunt_reel.dataroot') is lower than layer 'scripts'",
        ),
        (
            "stunt_reel/__init__.py",
            "import gate",
            "Layer 'capture' ('stunt_reel') is lower than layer 'scripts'",
        ),
        (
            "stunt_reel/capture_store.py",
            "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from stunt_reel import parity_judge",
            "Layer 'capture' ('stunt_reel.capture_store') is lower than layer 'parity'",
        ),
    ],
    ids=[
        "clean",
        "capture-to-parity",
        "tooling-to-capture",
        "package-to-script",
        "init-to-script",
        "type-only-import",
    ],
)
def test_tach_fails_a_planted_violation(
    layer_tree: Path, module: str | None, planted: str, message: str
) -> None:
    if module is None:
        result = _tach_check(layer_tree)
        assert result.returncode == 0, result.stdout + result.stderr
        return
    target = layer_tree / "python" / module
    original = (ROOT / "python" / module).read_bytes()
    assert target.read_bytes() == original, "the previous case left its plant behind"
    try:
        target.write_bytes(original + f"\n{planted}\n".encode())
        result = _tach_check(layer_tree)
        output = result.stdout + result.stderr
        assert result.returncode != 0, output
        assert message in output
    finally:
        target.write_bytes(original)
