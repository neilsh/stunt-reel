"""Kaitai Struct schema compilation helpers for verification only.

Schemas under ``research/formats/`` are executable layout descriptions. They
are compiled to Python in a temporary directory and executed against committed
cleanroom fixtures or the local (gitignored) reference corpus. Kaitai is not a
production dependency: the pinned compiler and its JVM come from ``mise``.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType

REQUIRED_KSC_VERSION = "0.11"


def ksc_command() -> list[str] | None:
    """Resolve the pinned Kaitai Struct Compiler launcher, unwrapping Windows shims."""
    if os.name == "nt":
        launcher = shutil.which("kaitai-struct-compiler.bat") or shutil.which(
            "kaitai-struct-compiler"
        )
    else:
        launcher = shutil.which("kaitai-struct-compiler")
    if launcher is None:
        return None
    if launcher.lower().endswith(".bat"):
        return [os.environ.get("COMSPEC", "cmd.exe"), "/c", launcher]
    return [launcher]


def compiler_version() -> str | None:
    """Return the compiler version banner, or None when the compiler is unavailable."""
    ksc = ksc_command()
    if ksc is None:
        return None
    proc = subprocess.run(  # noqa: S603
        [*ksc, "--version"], capture_output=True, text=True, check=False
    )
    banner = f"{proc.stdout}{proc.stderr}".strip()
    return banner or None


def compile_schemas(schema_paths: Sequence[Path], outdir: str | Path) -> None:
    """Compile `.ksy` schemas to Python under ``outdir``.

    Raises:
        RuntimeError: if the compiler is missing or any schema fails to compile.
    """
    ksc = ksc_command()
    if ksc is None:
        raise RuntimeError("Kaitai Struct Compiler not found on PATH; run 'mise install'")
    proc = subprocess.run(  # noqa: S603
        [*ksc, "-t", "python", "--outdir", str(outdir), *[str(p) for p in schema_paths]],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip()
        raise RuntimeError(f"Kaitai schema compilation failed (exit {proc.returncode}): {detail}")


def load_generated_module(python_file: Path, module_name: str) -> ModuleType:
    """Import a generated parser module from an explicit file path."""
    spec = importlib.util.spec_from_file_location(module_name, python_file)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load generated Kaitai parser at {python_file}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
