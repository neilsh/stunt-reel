"""The package's module layers in `tach.toml` cover every module and fail a planted violation.

`mise run check-layers` runs `tach check` on the tree as it is; these tests check that the
configuration would catch a change. A planted import runs on a copy of `python/`, so the
checkout is never edited. The module carries the `windows` marker so the pull-request Windows
job runs tach there too: the gate runs on both platforms (ADR 0050).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.windows

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
    ],
    ids=["clean", "capture-to-parity", "tooling-to-capture", "package-to-script"],
)
def test_tach_fails_a_planted_violation(
    tmp_path: Path, module: str | None, planted: str, message: str
) -> None:
    shutil.copy2(ROOT / "tach.toml", tmp_path / "tach.toml")
    shutil.copytree(
        ROOT / "python", tmp_path / "python", ignore=shutil.ignore_patterns("__pycache__")
    )
    if module is not None:
        with (tmp_path / "python" / module).open("a", encoding="utf-8") as handle:
            handle.write(f"\n{planted}\n")
    result = _tach_check(tmp_path)
    output = result.stdout + result.stderr
    if module is None:
        assert result.returncode == 0, output
    else:
        assert result.returncode != 0, output
        assert message in output
