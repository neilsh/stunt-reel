"""Local corpus conformance sweep for the Kaitai schemas.

Compiles every ``research/formats/**/*.ksy`` schema and parses the matching
files under ``corpus/``. Local-only by design: ``corpus/`` is gitignored and
absent in CI, so this sweep is never part of ``mise run check``; run it with
``mise run verify-corpus``.

Exit codes:
    0: every schema candidate parsed; anomalies are reported but not fatal.
    1: missing compiler, compile/load failure, parse failure, or any anomaly
       when ``--strict`` is passed.
"""

from __future__ import annotations

import argparse
import importlib
import io
import itertools
import re
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stunt_reel.kaitai import (
    REQUIRED_KSC_VERSION,
    compile_schemas,
    compiler_version,
    load_generated_module,
)

SCHEMA_ROOT = Path("research") / "formats"
_KAITAISTRUCT: Any = importlib.import_module("kaitaistruct")
_ID_PATTERN = re.compile(r"^[ \t]*id:[ \t]*['\"]?([A-Za-z0-9_]+)['\"]?[ \t]*$", re.MULTILINE)
_EXT_PATTERN = re.compile(
    r"^[ \t]*file-extension:[ \t]*['\"]?([A-Za-z0-9_]+)['\"]?[ \t]*$", re.MULTILINE
)


@dataclass
class SchemaSpec:
    """One schema under test, with the corpus file extension it describes."""

    schema_id: str
    extension: str
    path: Path


@dataclass
class SweepResult:
    """Aggregated sweep outcome for one schema."""

    spec: SchemaSpec
    total: int = 0
    parsed: int = 0
    errors: list[str] = field(default_factory=list)
    anomalies: list[str] = field(default_factory=list)


def discover_schemas() -> list[SchemaSpec]:
    """Return every `.ksy` schema declaring both `meta/id` and `meta/file-extension`."""
    specs: list[SchemaSpec] = []
    for path in sorted(SCHEMA_ROOT.rglob("*.ksy")):
        text = path.read_text(encoding="utf-8")
        id_match = _ID_PATTERN.search(text)
        ext_match = _EXT_PATTERN.search(text)
        if id_match is None or ext_match is None:
            raise SystemExit(f"{path}: schema must declare meta id and file-extension")
        specs.append(SchemaSpec(id_match.group(1), ext_match.group(1), path))
    return specs


def _class_name(schema_id: str) -> str:
    """Return the generated Python class name for a schema id."""
    return "".join(part.capitalize() for part in schema_id.split("_"))


def _touch_public_fields(node: Any) -> None:
    """Access every public attribute, forcing lazy Kaitai instances to parse."""
    for name in dir(type(node)):
        if name.startswith("_"):
            continue
        value = getattr(node, name)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, _KAITAISTRUCT.KaitaiStruct):
                    _touch_public_fields(item)
        elif isinstance(value, _KAITAISTRUCT.KaitaiStruct):
            _touch_public_fields(value)


def _probe_res(root: Any, size: int) -> list[str]:
    offsets = [int(value) for value in root.offsets]
    problems: list[str] = []
    if any(later < earlier for earlier, later in itertools.pairwise(offsets)):
        problems.append("offset table is not monotonic")
    if any(offset > size for offset in offsets):
        problems.append("offset beyond end of file")
    if offsets[-1] != size:
        problems.append(f"last offset {offsets[-1]} != file size {size}")
    return problems


def _probe_all(root: Any, size: int) -> list[str]:
    offsets = [int(value) for value in root.offsets]
    problems: list[str] = []
    expected = int(root.num_chunk_ids) + 1
    if len(offsets) != expected:
        problems.append(f"{len(offsets)} offsets, expected {expected}")
    header_size = int(root.len_header)
    if offsets and offsets[0] != header_size:
        problems.append(f"offsets[0] {offsets[0]} != header size {header_size}")
    if any(later < earlier for earlier, later in itertools.pairwise(offsets)):
        problems.append("offset table is not monotonic")
    if any(offset > size for offset in offsets):
        problems.append("offset beyond end of file")
    if offsets and offsets[-1] != size:
        problems.append(f"last offset {offsets[-1]} != file size {size}")
    return problems


def _probe_spr(root: Any, size: int) -> list[str]:
    consumed = int(root._io.pos())
    return [] if consumed == size else [f"parsed {consumed} of {size} bytes"]


PROBES: dict[str, Callable[[Any, int], list[str]]] = {
    "res": _probe_res,
    "all": _probe_all,
    "spr": _probe_spr,
}


def sweep(spec: SchemaSpec, parser: Any, corpus_dir: Path, verbose: bool = False) -> SweepResult:
    """Parse every corpus file matching one schema and collect errors/anomalies."""
    result = SweepResult(spec)
    suffix = f".{spec.extension.lower()}"
    files = sorted(
        path for path in corpus_dir.rglob("*") if path.is_file() and path.suffix.lower() == suffix
    )
    result.total = len(files)
    probe = PROBES.get(spec.schema_id)
    for path in files:
        data = path.read_bytes()
        try:
            root = parser(_KAITAISTRUCT.KaitaiStream(io.BytesIO(data)))
            _touch_public_fields(root)
            if probe is not None:
                problems = probe(root, len(data))
                if problems:
                    result.anomalies.append(f"{path.name}: {'; '.join(problems)}")
            result.parsed += 1
            if verbose:
                print(f"  ok {path}")
        except Exception as exc:
            result.errors.append(f"{path}: {type(exc).__name__}: {exc}")
    return result


def _run(args: argparse.Namespace, specs: Sequence[SchemaSpec]) -> int:
    results: list[SweepResult] = []
    with tempfile.TemporaryDirectory(prefix="stunt-kaitai-corpus-") as tmp:
        compile_schemas([spec.path for spec in specs], tmp)
        print(f"corpus:   {args.corpus.resolve()}")
        print(f"schemas:  {len(specs)}")
        for spec in specs:
            module = load_generated_module(
                Path(tmp) / f"{spec.schema_id}.py", f"stunt_kaitai_{spec.schema_id}"
            )
            parser_cls: Any = getattr(module, _class_name(spec.schema_id))
            results.append(sweep(spec, parser_cls, args.corpus, args.verbose))

    errors = 0
    anomalies = 0
    print()
    for result in results:
        suffix = f", {len(result.anomalies)} anomalies" if result.anomalies else ""
        print(f"[{result.spec.schema_id}] {result.parsed}/{result.total} parsed{suffix}")
        for anomaly in result.anomalies:
            print(f"  anomaly: {anomaly}")
        for error in result.errors:
            print(f"  error: {error}")
        errors += len(result.errors)
        anomalies += len(result.anomalies)

    total = sum(result.total for result in results)
    parsed = sum(result.parsed for result in results)
    print(f"\nsummary: {parsed}/{total} files parsed, {anomalies} anomalies, {errors} errors")
    return 1 if errors or (args.strict and anomalies) else 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default=Path("corpus"), type=Path)
    parser.add_argument(
        "--schema", action="append", dest="schemas", help="limit the sweep to one schema id"
    )
    parser.add_argument("--strict", action="store_true", help="fail on corpus anomalies")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    corpus_dir: Path = args.corpus
    if not corpus_dir.is_dir():
        print(f"corpus directory not found: {corpus_dir} (local sweep skipped)")
        return 0

    version = compiler_version()
    if version is None:
        print("Kaitai Struct Compiler not found on PATH; run 'mise install'", file=sys.stderr)
        return 1
    if REQUIRED_KSC_VERSION not in version:
        print(
            f"expected Kaitai Struct Compiler {REQUIRED_KSC_VERSION}, got '{version}'",
            file=sys.stderr,
        )
        return 1

    specs = discover_schemas()
    if args.schemas:
        wanted = set(args.schemas)
        specs = [spec for spec in specs if spec.schema_id in wanted]
    if not specs:
        print("no schemas matched", file=sys.stderr)
        return 1

    print(f"compiler: {version}")
    try:
        return _run(args, specs)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
