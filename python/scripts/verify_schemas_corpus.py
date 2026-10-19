"""Local corpus conformance sweep for the Kaitai schemas.

Compiles every ``research/formats/**/*.ksy`` schema and parses the matching
files under ``corpus/``. Corpus membership comes from one of three rules: a
dotted schema filename selects the fixed-name asset it names
(``anchorpt.dat.ksy`` matches only ``ANCHORPT.DAT``), ``CORPUS_SELECTORS``
resolves formats whose extension is shared with unrelated payloads (compiled
``.BIN`` SOD models next to ``MAP.BIN``), and everything else falls back to
``meta/file-extension``.

Local-only by design: ``corpus/`` is gitignored and absent in CI, so this
sweep is never part of ``mise run check``; run it with
``mise run verify-corpus``.

``flm_slice`` is driven by ``CASE_PROVIDERS``, which turns one film into one
parser invocation per slice and supplies the inter-slice slot masks as
constructor arguments, because those masks cannot cross a Kaitai ``repeat``.

``KNOWN_ANOMALIES`` pins the reviewed corpus defects, keyed by schema id,
corpus-relative path, and exact problem text. ``--strict`` therefore fails
only on anomalies missing from that table (a new defect) or on table entries
that no longer fire (a stale expectation, including changed field values,
because the text is compared verbatim).

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
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stunt_reel import flm_walk
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
    """One schema under test, with the corpus files it describes.

    ``filename`` is set when the schema file name carries a dot before the
    ``.ksy`` suffix, in which case it selects that single corpus asset by
    name; otherwise ``extension`` selects every corpus file with that suffix.
    """

    schema_id: str
    extension: str
    path: Path
    filename: str | None = None


@dataclass
class SweepResult:
    """Aggregated sweep outcome for one schema."""

    spec: SchemaSpec
    total: int = 0
    parsed: int = 0
    files_total: int = 0
    files_parsed: int = 0
    errors: list[str] = field(default_factory=list)
    anomalies: list[tuple[str, str]] = field(default_factory=list)


def discover_schemas() -> list[SchemaSpec]:
    """Return every `.ksy` schema declaring both `meta/id` and `meta/file-extension`."""
    specs: list[SchemaSpec] = []
    for path in sorted(SCHEMA_ROOT.rglob("*.ksy")):
        text = path.read_text(encoding="utf-8")
        id_match = _ID_PATTERN.search(text)
        ext_match = _EXT_PATTERN.search(text)
        if id_match is None or ext_match is None:
            raise SystemExit(f"{path}: schema must declare meta id and file-extension")
        stem = path.name.removesuffix(".ksy")
        filename = stem.upper() if "." in stem else None
        specs.append(SchemaSpec(id_match.group(1), ext_match.group(1), path, filename))
    return specs


def _is_compiled_sod(path: Path) -> bool:
    """Select `.BIN` files carrying the 0x000C SOD magic."""
    if path.suffix.lower() != ".bin":
        return False
    with path.open("rb") as handle:
        return handle.read(2) == b"\x0c\x00"


CORPUS_SELECTORS: dict[str, Callable[[Path], bool]] = {
    "sod": _is_compiled_sod,
}


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


def _probe_consumed(root: Any, size: int) -> list[str]:
    consumed = int(root._io.pos())
    return [] if consumed == size else [f"parsed {consumed} of {size} bytes"]


def _probe_map_area(root: Any, size: int) -> list[str]:
    problems = _probe_consumed(root, size)
    outliers = [
        f"patch {index} num_verts {int(patch.num_verts)}"
        for index, patch in enumerate(root.patches)
        if not 3 <= int(patch.num_verts) <= 7
    ]
    if outliers:
        problems.append("vertex count outside 3..7 at " + ", ".join(outliers))
    return problems


def _probe_scenery(root: Any, size: int) -> list[str]:
    problems = _probe_consumed(root, size)
    if len(root.words) < 2:
        problems.append("fewer than two words")
    elif int(root.words[1]) not in {0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22}:
        problems.append(f"root opcode {int(root.words[1])} is not a known SP type")
    return problems


PROBES: dict[str, Callable[[Any, int], list[str]]] = {
    "res": _probe_res,
    "all": _probe_all,
    "spr": _probe_consumed,
    "sio": _probe_consumed,
    "set": _probe_consumed,
    "anchorpt": _probe_consumed,
    "map_area": _probe_map_area,
    "sod": _probe_consumed,
    "scenery": _probe_scenery,
    "flm_slice": _probe_consumed,
}


# Reviewed corpus defects, keyed by ``(schema id, corpus-relative path,
# problem text)``. Every entry needs evidence for why the file, not the
# schema, is wrong:
#
# - ``map_area``: ``sisland.cpp`` declares ``short num_verts; short v[7];`` and
#   draws ``for (j = 0; j < num_verts; j++)``, so a count of 8 reads past
#   ``v[7]`` into the next record's ``num`` word (0). Patch 131 carries that
#   value in all six copies, and patch 22 of ``OBJECTS/Dean/MAP.BIN`` carries
#   2. The field is a count; the geometry data is malformed.
# - ``res``: the three ``SITools/GameReady/`` archives are community
#   ``MAKERES`` output whose item tables decode as ``[label, SOD, ...]`` with
#   ``item_count = N - 1``, matching retail archives, but whose files carry
#   undeclared bytes after the last declared item.
# - ``all``: ``BRIEFING.ALL`` declares a final chunk at 367223 in a 364544-byte
#   file; the trailing chunks are audio IDs 0xCA91..0xCA93, so the copy is
#   truncated by 2679 bytes.
# - ``flm_slice``: the walker reproduces ``FlmParser::parse_slice``, so a
#   rejection means the film breaks the opcode grammar that 561 other films
#   satisfy. ``CORSAIR``, ``JASON``, and ``PITTS`` carry class-3 tags (``0xF0``,
#   ``0xCC``, ``0xFD``) that no documented opcode defines; ``MOVIE``, ``ROD``,
#   ``SR71FLM``, and ``TUTORIAL`` run out of bytes inside an opcode payload.
KNOWN_ANOMALIES: dict[tuple[str, str, str], str] = {
    (
        "res",
        "si_archive/SITools/GameReady/F-14 Test-80.RES",
        "last offset 11404 != file size 11475",
    ): "MAKERES archive with 71 undeclared trailing bytes",
    (
        "res",
        "si_archive/SITools/GameReady/Tardis-82.RES",
        "last offset 10352 != file size 10359",
    ): "MAKERES archive with 7 undeclared trailing bytes",
    (
        "res",
        "si_archive/SITools/GameReady/Terrain Test-83.RES",
        "last offset 6218 != file size 6520",
    ): "MAKERES archive with 302 undeclared trailing bytes",
    (
        "all",
        "si_archive/Films/MultiFLM/UFOAct2/BRIEFING.ALL",
        "offset beyond end of file; last offset 367223 != file size 364544",
    ): "truncated copy, final audio chunks 0xCA91..0xCA93 missing",
    (
        "map_area",
        "si_archive/Developer/FreeFlight/SIDATA/MAP.BIN",
        "vertex count outside 3..7 at patch 131 num_verts 8",
    ): "patch 131 overruns v[7]; engine reads next record num 0",
    (
        "map_area",
        "si_archive/Developer/SIRes/SiData/MAP.BIN",
        "vertex count outside 3..7 at patch 131 num_verts 8",
    ): "patch 131 overruns v[7]; engine reads next record num 0",
    (
        "map_area",
        "si_archive/Developer/SODParse/MAP.BIN",
        "vertex count outside 3..7 at patch 131 num_verts 8",
    ): "patch 131 overruns v[7]; engine reads next record num 0",
    (
        "map_area",
        "si_archive/SITools/MAP.BIN",
        "vertex count outside 3..7 at patch 131 num_verts 8",
    ): "patch 131 overruns v[7]; engine reads next record num 0",
    (
        "map_area",
        "si_archive/SITools/OBJECTS/Dean/Egalloc/MAP.BIN",
        "vertex count outside 3..7 at patch 131 num_verts 8",
    ): "patch 131 overruns v[7]; engine reads next record num 0",
    (
        "map_area",
        "si_archive/SITools/OBJECTS/Dean/MAP.BIN",
        "vertex count outside 3..7 at patch 22 num_verts 2, patch 131 num_verts 8",
    ): "patch 22 underruns the 3-vertex minimum; patch 131 overruns v[7]",
    (
        "flm_slice",
        "si_archive/Films/FLMOnly/CORSAIR.FLM",
        "slice walk failed: unsupported opcode 0xf0 at 17119",
    ): "class-3 opcode outside the documented grammar",
    (
        "flm_slice",
        "si_archive/Films/FLMOnly/JASON.FLM",
        "slice walk failed: unsupported opcode 0xcc at 91738",
    ): "class-3 opcode outside the documented grammar",
    (
        "flm_slice",
        "si_archive/Films/FLMOnly/MOVIE.FLM",
        "slice walk failed: truncated opcode 0x1a at 15743",
    ): "stream truncated mid-opcode",
    (
        "flm_slice",
        "si_archive/Films/FLMOnly/PITTS.FLM",
        "slice walk failed: unsupported opcode 0xfd at 37540",
    ): "class-3 opcode outside the documented grammar",
    (
        "flm_slice",
        "si_archive/Films/FLMOnly/ROD.FLM",
        "slice walk failed: truncated opcode 0x1a at 12287",
    ): "stream truncated mid-opcode",
    (
        "flm_slice",
        "si_archive/Films/FLMOnly/SR71FLM.FLM",
        "slice walk failed: truncated opcode 0x41 at 79100",
    ): "stream truncated mid-opcode",
    (
        "flm_slice",
        "si_archive/Films/FLMOnly/TUTORIAL.FLM",
        "slice walk failed: truncated opcode 0x1a at 24063",
    ): "stream truncated mid-opcode",
}


@dataclass(frozen=True)
class ParseCase:
    """One parser invocation: constructor args plus the exact bytes to parse."""

    label: str
    args: tuple[Any, ...]
    data: bytes


def _flm_cases(data: bytes) -> Iterator[ParseCase]:
    """Turn one film into one case per slice, carrying the slot masks."""
    views = flm_walk.walk_film(data)
    return (
        ParseCase(
            f"slice {view.index} @ 0x{view.start:04X}",
            (view.moves, view.rotates, view.animates),
            data[view.start : view.end],
        )
        for view in views
    )


CASE_PROVIDERS: dict[str, Callable[[bytes], Iterator[ParseCase]]] = {
    "flm_slice": _flm_cases,
}


def _corpus_files(spec: SchemaSpec, corpus_dir: Path) -> list[Path]:
    """Return the corpus files one schema describes, sorted by path."""
    suffix = f".{spec.extension.lower()}"
    selector = CORPUS_SELECTORS.get(spec.schema_id)
    if spec.filename is not None:
        return sorted(
            path
            for path in corpus_dir.rglob("*")
            if path.is_file() and path.name.upper() == spec.filename
        )
    if selector is not None:
        return sorted(path for path in corpus_dir.rglob("*") if path.is_file() and selector(path))
    return sorted(
        path for path in corpus_dir.rglob("*") if path.is_file() and path.suffix.lower() == suffix
    )


def sweep(spec: SchemaSpec, parser: Any, corpus_dir: Path, verbose: bool = False) -> SweepResult:
    """Parse every corpus file matching one schema and collect errors/anomalies."""
    result = SweepResult(spec)
    files = _corpus_files(spec, corpus_dir)
    result.files_total = len(files)
    probe = PROBES.get(spec.schema_id)
    provider = CASE_PROVIDERS.get(spec.schema_id)
    for path in files:
        rel = path.relative_to(corpus_dir).as_posix()
        cases: Iterable[ParseCase]
        if provider is None:
            cases = (ParseCase(path.name, (), path.read_bytes()),)
        else:
            try:
                cases = provider(path.read_bytes())
            except flm_walk.FlmWalkError as exc:
                result.anomalies.append((rel, f"slice walk failed: {exc}"))
                continue
        result.files_parsed += 1
        for case in cases:
            result.total += 1
            try:
                root = parser(*case.args, _KAITAISTRUCT.KaitaiStream(io.BytesIO(case.data)))
                _touch_public_fields(root)
                if probe is not None:
                    problems = probe(root, len(case.data))
                    if problems:
                        result.anomalies.append((rel, "; ".join(problems)))
                result.parsed += 1
                if verbose:
                    print(f"  ok {rel} {case.label}")
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
            generated = Path(tmp) / f"{spec.path.stem}.py"
            if not generated.exists():
                generated = Path(tmp) / f"{spec.schema_id}.py"
            module = load_generated_module(generated, f"stunt_kaitai_{spec.schema_id}")
            parser_cls: Any = getattr(module, _class_name(spec.schema_id))
            results.append(sweep(spec, parser_cls, args.corpus, args.verbose))

    errors = 0
    anomalies = 0
    known = 0
    fired: set[tuple[str, str, str]] = set()
    print()
    for result in results:
        schema_id = result.spec.schema_id
        unknown = [item for item in result.anomalies if (schema_id, *item) not in KNOWN_ANOMALIES]
        pinned = len(result.anomalies) - len(unknown)
        suffix = ""
        if schema_id in CASE_PROVIDERS:
            suffix = f" in {result.files_parsed}/{result.files_total} files"
        if result.anomalies:
            suffix += f", {len(result.anomalies)} anomalies"
        suffix += f" ({pinned} known)" if pinned else ""
        print(f"[{schema_id}] {result.parsed}/{result.total} parsed{suffix}")
        for path, problem in result.anomalies:
            key = (schema_id, path, problem)
            if key in KNOWN_ANOMALIES:
                fired.add(key)
                print(f"  known: {path}: {problem} [{KNOWN_ANOMALIES[key]}]")
            else:
                print(f"  anomaly: {path}: {problem}")
        for error in result.errors:
            print(f"  error: {error}")
        errors += len(result.errors)
        anomalies += len(result.anomalies)
        known += pinned

    swept = {result.spec.schema_id for result in results}
    stale = sorted(key for key in KNOWN_ANOMALIES if key[0] in swept and key not in fired)
    for schema_id, path, problem in stale:
        print(f"  stale: {schema_id}: {path}: {problem}")

    total = sum(result.total for result in results)
    parsed = sum(result.parsed for result in results)
    print(
        f"\nsummary: {parsed}/{total} files parsed, {anomalies} anomalies "
        f"({known} known, {anomalies - known} unknown), {len(stale)} stale, {errors} errors"
    )
    return 1 if errors or (args.strict and (anomalies - known or stale)) else 0


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
