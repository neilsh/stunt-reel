"""Technical Reference Catalog Verification Script for Stunt Island.

Programmatically validates:
1. File Presence: All 13 core, concept, and auxiliary format documents exist.
2. Schema Conformance: 5-section uniform structure across specs and concepts (invariants,
   Seam contracts and fixtures are linked from section 1, not restated), links to the .ksy
   schema that owns each byte layout,
   sequential header ordering, evidentiary tier tagging (see EVIDENTIARY_TIERS),
   and Mermaid asset graphs.
3. Provenance & Attribution: Direct citations to corpus/siarchive/, .agents/teamwork/,
   and explicit credit to community researchers.
4. Asset isolation: ZERO binary files in research/formats/, valid UTF-8 encoding,
   no null bytes, and offline synthetic test fixture alignment [I7].
5. Link Integrity: Zero broken relative markdown links or anchor targets across
   the catalog and docs/ARCHITECTURE.md.
6. Synthetic Fixture Consistency: Documented headers, offsets, and opcodes align
   byte-for-byte with synthetic test fixtures in tests/fixtures/.
"""

from __future__ import annotations

import argparse
import importlib
import io
import json
import math
import re
import struct
import sys
import tempfile
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

# -----------------------------------------------------------------------------
# Catalog Specification Constants
# -----------------------------------------------------------------------------

REQUIRED_DOCS: list[str] = [
    "research/formats/INDEX.md",
    "research/formats/res.md",
    "research/formats/all.md",
    "research/formats/sod.md",
    "research/formats/flm.md",
    "research/formats/concepts/coordinates-and-units.md",
    "research/formats/concepts/palette-and-shading.md",
    "research/formats/concepts/timeline-and-ticks.md",
    "research/formats/concepts/compression.md",
    "research/formats/auxiliary/set.md",
    "research/formats/auxiliary/spr.md",
    "research/formats/auxiliary/sio.md",
    "research/formats/auxiliary/map.md",
]

FORMAT_SPECS: list[str] = [
    "research/formats/res.md",
    "research/formats/all.md",
    "research/formats/sod.md",
    "research/formats/flm.md",
    "research/formats/auxiliary/set.md",
    "research/formats/auxiliary/spr.md",
    "research/formats/auxiliary/sio.md",
    "research/formats/auxiliary/map.md",
]

# Reference documents split out of a format specification. They are not held to the
# five-section template; each must exist and link back to its parent specification.
REFERENCE_DOCS: dict[str, str] = {
    "research/formats/sod-opcodes.md": "sod.md",
}

CONCEPT_DOCS: list[str] = [
    "research/formats/concepts/coordinates-and-units.md",
    "research/formats/concepts/palette-and-shading.md",
    "research/formats/concepts/timeline-and-ticks.md",
    "research/formats/concepts/compression.md",
]

INDEX_DOC: str = "research/formats/INDEX.md"

FORMAT_SPEC_SECTIONS: list[str] = [
    "## 1. Overview & File Identification",
    "## 2. Header & Memory Layout",
    "## 3. Data Structures & Opcode Table",
    "## 4. Open Questions & Analysis Backlog",
    "## 5. Attribution & Provenance",
]

CONCEPT_DOC_SECTIONS: list[str] = [
    "## 1. Overview & Mathematical / Hardware Principles",
    "## 2. Memory Layout & Bitfield Representations",
    "## 3. Data Structures, Tables & Conversion Algorithms",
    "## 4. Open Questions & Analysis Backlog",
    "## 5. Attribution & Provenance",
]

INDEX_SECTIONS: list[str] = [
    "## 1. Format Catalog",
    "## 2. Runtime Asset Graph",
    "## 3. Concepts and Auxiliary Notes",
    "## 4. Provenance",
]

# Invariants, Seam contracts and fixtures are NOT template sections: each document links to
# docs/SPEC.md (invariants), crates/stunt-core/src/contracts/ and tests/fixtures/README.md
# from section 1 instead of restating them. Byte layouts live in the .ksy schemas, so a
# specification must link every schema listed here.
KSY_SOURCES: dict[str, list[str]] = {
    "research/formats/res.md": ["res.ksy"],
    "research/formats/all.md": ["all.ksy"],
    "research/formats/sod.md": ["sod.ksy"],
    "research/formats/flm.md": ["flm_slice.ksy"],
    "research/formats/auxiliary/set.md": ["set.ksy"],
    "research/formats/auxiliary/spr.md": ["spr.ksy"],
    "research/formats/auxiliary/sio.md": ["sio.ksy"],
    "research/formats/auxiliary/map.md": [
        "anchorpt.dat.ksy",
        "map.bin.ksy",
        "scenery.scn.ksy",
    ],
}

# Single owner of the evidentiary tier vocabulary. Prose definitions live in
# docs/SPEC.md section 2.4, which must mention every tier below; every other
# document may only use these tags (verify_tier_vocabulary).
EVIDENTIARY_TIERS: list[str] = [
    "[Unknown]",  # unmapped or unencountered; parsers must fail loudly
    "[Hypothesis]",  # proposed, not observed in the binary or a corpus file
    "[Bounded Observation]",  # observed in one film or fixture
    "[Supported Inference]",  # cross-file alignment and passing parity gates
    "[Established]",  # disassembled or bit-exact runtime trap
    "[Superseded]",  # retired claim kept for history; not a confidence level
]

# Tags every format document set must collectively exercise. [Superseded] is a
# lifecycle marker, so the catalog does not need to contain one.
CATALOG_REQUIRED_TIERS: frozenset[str] = frozenset(EVIDENTIARY_TIERS) - {"[Superseded]"}

KEY_COMMUNITY_AUTHORS: list[str] = [
    "Adrian Stephens",
    "Chris Phillips",
    "Doug Armknecht",
    "Neil Halelamien",
    "Dave Palmowski",
]

ALLOWED_TEXT_SUFFIXES: frozenset[str] = frozenset({".md", ".ksy"})

LINK_SCAN_FILES: list[str] = [
    "README.md",
    "AGENTS.md",
    "docs/ARCHITECTURE.md",
    "docs/SPEC.md",
    "research/playone-exe/memory-map.md",
    "docs/process/TEAM_SHEET.md",
    "GLOSSARY.md",
    "tests/fixtures/README.md",
    "corpus/README.md",
    *REQUIRED_DOCS,
    *REFERENCE_DOCS,
]


# Directories whose Markdown is also link-checked (non-recursive globs).
LINK_SCAN_GLOBS: list[str] = [
    "research/playone-exe/*.md",
    "research/*.md",
    "docs/adr/*.md",
]

# Markdown scanned for evidentiary tier tags (recursive globs plus single files).
TIER_SCAN_GLOBS: list[str] = [
    "AGENTS.md",
    "README.md",
    "GLOSSARY.md",
    "docs/**/*.md",
    "research/**/*.md",
]

# A bracketed Title Case phrase that is not a link, footnote or checkbox looks
# like a tier tag; anything that looks like one but is not in EVIDENTIARY_TIERS
# is a vocabulary error.
TIER_LIKE_REGEX = re.compile(r"\[([A-Z][a-z]+(?: [A-Z][a-z]+)*)\](?![(\[:])")


def link_scan_files(repo_root: Path) -> list[str]:
    """Return the fixed link-scan list plus files matched by LINK_SCAN_GLOBS."""
    files = list(LINK_SCAN_FILES)
    for pattern in LINK_SCAN_GLOBS:
        for match in sorted(repo_root.glob(pattern)):
            rel = match.relative_to(repo_root).as_posix()
            if rel not in files:
                files.append(rel)
    return files


@dataclass
class VerificationResult:
    """Diagnostic outcome of catalog verification checks."""

    category: str
    passed: bool
    errors: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)


def slugify_heading(heading_text: str) -> str:
    """Generate GitHub-compatible markdown heading slug."""
    cleaned = re.sub(r"^#+\s*", "", heading_text).strip().lower()
    cleaned = re.sub(r"[^\w\s-]", "", cleaned)
    return cleaned.replace(" ", "-")


# -----------------------------------------------------------------------------
# Verification Category 1: File Presence
# -----------------------------------------------------------------------------


def verify_file_presence(repo_root: Path) -> VerificationResult:
    """Validate that all 13 required catalog documentation files exist."""
    errors: list[str] = []
    details: list[str] = []

    for rel_path in REQUIRED_DOCS:
        target = repo_root / rel_path
        if not target.exists():
            errors.append(f"Missing required documentation file: {rel_path}")
        elif not target.is_file():
            errors.append(f"Expected file but found directory: {rel_path}")
        else:
            size = target.stat().st_size
            if size == 0:
                errors.append(f"Documentation file is empty: {rel_path}")
            else:
                details.append(f"Present ({size:,} bytes): {rel_path}")

    return VerificationResult(
        category="File Presence",
        passed=(len(errors) == 0),
        errors=errors,
        details=details,
    )


# -----------------------------------------------------------------------------
# Verification Category 2: Schema Conformance
# -----------------------------------------------------------------------------


def verify_schema_conformance(repo_root: Path) -> VerificationResult:
    """Validate that specs and concept docs conform to uniform 5-section schemas."""
    errors: list[str] = []
    details: list[str] = []
    catalog_tiers_found: set[str] = set()

    # 1. Format Specifications (Core & Auxiliary)
    for rel_path in FORMAT_SPECS:
        file_path = repo_root / rel_path
        if not file_path.exists():
            continue

        content = file_path.read_text(encoding="utf-8")
        last_pos = -1

        for expected_sec in FORMAT_SPEC_SECTIONS:
            pos = content.find(expected_sec)
            if pos == -1:
                errors.append(f"Schema violation in {rel_path}: Missing section '{expected_sec}'")
            elif pos < last_pos:
                errors.append(
                    f"Section order violation in {rel_path}: '{expected_sec}' out of order"
                )
            else:
                last_pos = pos

        # Verify evidentiary tiers in Section 4
        sec4_match = re.search(
            r"## 4\. Open Questions & Analysis Backlog(.*?)(?:## 5\.|\Z)",
            content,
            re.DOTALL,
        )
        if sec4_match:
            sec4_content = sec4_match.group(1)
            found_in_doc = {tier for tier in EVIDENTIARY_TIERS if tier in sec4_content}
            catalog_tiers_found.update(found_in_doc)
            if not found_in_doc:
                errors.append(
                    f"Section 4 in {rel_path} lacks evidentiary tier tags ({', '.join(EVIDENTIARY_TIERS)})"
                )
        else:
            errors.append(f"Could not isolate Section 4 in {rel_path}")

        for ksy_name in KSY_SOURCES.get(rel_path, []):
            if not re.search(rf"\]\((?:[^)]*/)?{re.escape(ksy_name)}\)", content):
                errors.append(
                    f"{rel_path} must link its byte-layout schema {ksy_name} (.ksy is the source "
                    "of truth for layouts)"
                )

        details.append(f"Conforms to 5-section format schema: {rel_path}")

    # 2. Reference documents (no section template; must link their parent specification)
    for rel_path, parent_name in REFERENCE_DOCS.items():
        file_path = repo_root / rel_path
        if not file_path.exists():
            errors.append(f"Missing reference document: {rel_path}")
            continue

        content = file_path.read_text(encoding="utf-8")
        if not re.search(rf"\]\((?:[^)#]*/)?{re.escape(parent_name)}(?:#[^)]*)?\)", content):
            errors.append(f"{rel_path} must link its parent specification {parent_name}")
        details.append(f"Reference document links {parent_name}: {rel_path}")

    # 3. Concept Guides
    for rel_path in CONCEPT_DOCS:
        file_path = repo_root / rel_path
        if not file_path.exists():
            continue

        content = file_path.read_text(encoding="utf-8")
        last_pos = -1

        for expected_sec in CONCEPT_DOC_SECTIONS:
            pos = content.find(expected_sec)
            if pos == -1:
                errors.append(f"Schema violation in {rel_path}: Missing section '{expected_sec}'")
            elif pos < last_pos:
                errors.append(
                    f"Section order violation in {rel_path}: '{expected_sec}' out of order"
                )
            else:
                last_pos = pos

        sec4_match = re.search(
            r"## 4\. Open Questions & Analysis Backlog(.*?)(?:## 5\.|\Z)",
            content,
            re.DOTALL,
        )
        if sec4_match:
            sec4_content = sec4_match.group(1)
            found_in_doc = {tier for tier in EVIDENTIARY_TIERS if tier in sec4_content}
            catalog_tiers_found.update(found_in_doc)
            if not found_in_doc:
                errors.append(f"Section 4 in {rel_path} lacks evidentiary tier tags")
        else:
            errors.append(f"Could not isolate Section 4 in {rel_path}")

        details.append(f"Conforms to 5-section concept schema: {rel_path}")

    # 4. Master Index
    index_path = repo_root / INDEX_DOC
    if index_path.exists():
        index_content = index_path.read_text(encoding="utf-8")
        last_pos = -1
        for expected_sec in INDEX_SECTIONS:
            pos = index_content.find(expected_sec)
            if pos == -1:
                errors.append(f"Schema violation in {INDEX_DOC}: Missing section '{expected_sec}'")
            elif pos < last_pos:
                errors.append(
                    f"Section order violation in {INDEX_DOC}: '{expected_sec}' out of order"
                )
            else:
                last_pos = pos

        # Verify Mermaid diagram
        if "```mermaid" not in index_content:
            errors.append(f"{INDEX_DOC} missing Mermaid runtime asset dependency graph")
        else:
            details.append(f"{INDEX_DOC} includes Mermaid runtime asset dependency diagram")

        # Check section 5 evidentiary tiers in INDEX.md
        for tier in EVIDENTIARY_TIERS:
            if tier in index_content:
                catalog_tiers_found.add(tier)

    # 4. Global Evidentiary Tier Completeness across catalog
    missing_tiers = CATALOG_REQUIRED_TIERS - catalog_tiers_found
    if missing_tiers:
        errors.append(
            f"Catalog as a whole is missing evidentiary confidence tiers: {sorted(missing_tiers)}"
        )
    else:
        details.append(
            f"All {len(CATALOG_REQUIRED_TIERS)} catalog evidentiary tiers represented: {sorted(catalog_tiers_found)}"
        )

    return VerificationResult(
        category="Schema Conformance",
        passed=(len(errors) == 0),
        errors=errors,
        details=details,
    )


# -----------------------------------------------------------------------------
# Verification Category 2b: Evidentiary Tier Vocabulary
# -----------------------------------------------------------------------------


def verify_tier_vocabulary(repo_root: Path) -> VerificationResult:
    """Validate that tier tags are drawn from EVIDENTIARY_TIERS and SPEC defines each one."""
    errors: list[str] = []
    details: list[str] = []

    spec_path = repo_root / "docs" / "SPEC.md"
    spec_text = spec_path.read_text(encoding="utf-8") if spec_path.exists() else ""
    sec_match = re.search(r"### 2\.4 .*?(?=\n### |\n## |\Z)", spec_text, re.DOTALL)
    if not sec_match:
        errors.append("docs/SPEC.md has no section 2.4 defining the evidentiary tiers")
    else:
        for tier in EVIDENTIARY_TIERS:
            if tier not in sec_match.group(0):
                errors.append(f"docs/SPEC.md section 2.4 does not define tier {tier}")

    allowed = {tier.strip("[]") for tier in EVIDENTIARY_TIERS}
    files: set[Path] = set()
    for pattern in TIER_SCAN_GLOBS:
        files.update(path for path in repo_root.glob(pattern) if path.is_file())

    tags_seen = 0
    for path in sorted(files):
        in_code_block = False
        rel = path.relative_to(repo_root).as_posix()
        for line_num, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if line.strip().startswith("```"):
                in_code_block = not in_code_block
                continue
            if in_code_block:
                continue
            for match in TIER_LIKE_REGEX.finditer(line):
                name = match.group(1)
                if name in allowed:
                    tags_seen += 1
                else:
                    errors.append(
                        f"Unknown evidentiary tier [{name}] at {rel}:{line_num}; "
                        f"allowed: {', '.join(EVIDENTIARY_TIERS)}"
                    )

    details.append(f"{tags_seen} tier tags across {len(files)} Markdown files use the shared enum")
    return VerificationResult(
        category="Evidentiary Tier Vocabulary",
        passed=(len(errors) == 0),
        errors=errors,
        details=details,
    )


# -----------------------------------------------------------------------------
# Verification Category 3: Provenance & Attribution
# -----------------------------------------------------------------------------


def verify_provenance_and_attribution(repo_root: Path) -> VerificationResult:
    """Validate citations to corpus/siarchive/, .agents/teamwork/, and key community authors."""
    errors: list[str] = []
    details: list[str] = []

    # Check each documentation file for its provenance section
    for rel_path in REQUIRED_DOCS:
        file_path = repo_root / rel_path
        if not file_path.exists():
            continue

        content = file_path.read_text(encoding="utf-8")
        sec5_match = re.search(
            r"## \d+\. (?:Attribution & Provenance|Provenance)(.*?)(?:\n## \d+\.|\Z)",
            content,
            re.DOTALL,
        )
        if not sec5_match:
            errors.append(f"Missing Section 5 in {rel_path}")
            continue

        sec5_content = sec5_match.group(1)

        # Check for citation to corpus archive or teamwork lineage
        has_citation = (
            "corpus/siarchive" in sec5_content
            or ".agents/teamwork/" in sec5_content
            or "teamwork" in sec5_content.lower()
        )
        if not has_citation:
            errors.append(
                f"Missing citation to corpus/siarchive/ or .agents/teamwork/ in {rel_path}"
            )

        # Check that community authors are cited in Section 5
        authors_in_sec = [a for a in KEY_COMMUNITY_AUTHORS if a in sec5_content]
        if not authors_in_sec:
            errors.append(
                f"No recognized community researchers credited in Section 5 of {rel_path}"
            )
        else:
            details.append(
                f"Attribution verified in {rel_path} (credited: {', '.join(authors_in_sec)})"
            )

    # Master index author completeness check
    index_path = repo_root / INDEX_DOC
    if index_path.exists():
        index_content = index_path.read_text(encoding="utf-8")
        for author in KEY_COMMUNITY_AUTHORS:
            if author not in index_content:
                errors.append(
                    f"Master index {INDEX_DOC} missing historical pioneer citation: '{author}'"
                )

    return VerificationResult(
        category="Provenance & Attribution",
        passed=(len(errors) == 0),
        errors=errors,
        details=details,
    )


# -----------------------------------------------------------------------------
# Verification Category 4: Asset isolation
# -----------------------------------------------------------------------------


def verify_asset_isolation(repo_root: Path) -> VerificationResult:
    """Validate that ZERO binary files exist under research/formats/ and all are valid UTF-8 text."""
    errors: list[str] = []
    details: list[str] = []
    formats_dir = repo_root / "research" / "formats"

    if not formats_dir.exists():
        return VerificationResult(
            category="Asset isolation",
            passed=False,
            errors=[f"Directory does not exist: {formats_dir}"],
            details=[],
        )

    for item in sorted(formats_dir.rglob("*")):
        if item.is_dir():
            continue

        rel_item = item.relative_to(repo_root)

        # Invariant [I7]: Markdown prose and Kaitai YAML text only; no binaries
        if item.suffix not in ALLOWED_TEXT_SUFFIXES:
            errors.append(f"Prohibited non-text file in research/formats/: {rel_item}")
            continue

        # Check UTF-8 decoding
        try:
            raw_bytes = item.read_bytes()
            content = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            errors.append(f"File {rel_item} is not valid UTF-8: {exc}")
            continue

        # Check for null bytes or raw binary markers
        if b"\x00" in raw_bytes or "\x00" in content:
            errors.append(
                f"Prohibited null byte detected in text file {rel_item} (possible binary contamination)"
            )
            continue

        details.append(f"Clean UTF-8 text ({len(raw_bytes):,} bytes): {rel_item}")

    return VerificationResult(
        category="Asset isolation",
        passed=(len(errors) == 0),
        errors=errors,
        details=details,
    )


# -----------------------------------------------------------------------------
# Verification Category 5: Link Integrity
# -----------------------------------------------------------------------------


def verify_link_integrity(repo_root: Path) -> VerificationResult:
    """Validate that every markdown link in the scanned document set resolves on disk."""
    errors: list[str] = []
    details: list[str] = []
    link_regex = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    token_regex = re.compile(r"\[([A-Za-z0-9_-]+)\]")

    links_checked = 0

    scan_files = link_scan_files(repo_root)
    for rel_path in scan_files:
        source_file = repo_root / rel_path
        if not source_file.exists():
            continue

        content = source_file.read_text(encoding="utf-8")
        in_code_block = False

        for line_num, line in enumerate(content.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("```"):
                in_code_block = not in_code_block
                continue
            if in_code_block:
                continue

            for match in link_regex.finditer(line):
                url = match.group(2).strip()

                # Ignore external URLs
                if url.startswith(("http://", "https://", "mailto:")):
                    continue

                # Gitignored data trees exist only on developer machines
                if url.startswith(("corpus/", "target_bin/")):
                    continue

                links_checked += 1
                parts = url.split("#", 1)
                file_part = parts[0]
                anchor = parts[1] if len(parts) > 1 else None

                # Resolve target file path
                if file_part:
                    target_file = (source_file.parent / file_part).resolve()
                else:
                    target_file = source_file

                if not target_file.exists():
                    errors.append(
                        f"Broken link in {rel_path}:{line_num} -> '{url}' (target does not exist: {target_file})"
                    )
                    continue

                # If anchor is present and target is a Markdown file, verify anchor target
                if anchor and target_file.suffix == ".md":
                    target_content = target_file.read_text(encoding="utf-8")
                    target_slugs = {
                        slugify_heading(h_line)
                        for h_line in target_content.splitlines()
                        if h_line.startswith("#")
                    }
                    target_tokens = {t.lower() for t in token_regex.findall(target_content)}
                    slug_set = target_slugs | target_tokens

                    norm_anchor = anchor.lower()
                    if norm_anchor not in slug_set and slugify_heading(anchor) not in slug_set:
                        errors.append(
                            f"Broken anchor in {rel_path}:{line_num} -> '{url}' "
                            f"(anchor '{anchor}' not found in {target_file.name})"
                        )

    details.append(
        f"Successfully validated {links_checked} local markdown links across {len(scan_files)} files"
    )

    return VerificationResult(
        category="Link Integrity",
        passed=(len(errors) == 0),
        errors=errors,
        details=details,
    )


# -----------------------------------------------------------------------------
# Verification Category 6: Synthetic Fixture Consistency
# -----------------------------------------------------------------------------


def _validate_res_with_kaitai(repo_root: Path, res_bytes: bytes) -> tuple[list[str], list[str]]:
    """Validate the synthetic fixture with the parser generated from research/formats/res.ksy."""
    errors: list[str] = []
    details: list[str] = []

    version = compiler_version()
    if version is None:
        details.append(
            "Kaitai Struct Compiler not found on PATH; res.ksy fixture cross-check skipped"
        )
        return errors, details
    if REQUIRED_KSC_VERSION not in version:
        errors.append(
            "Kaitai Struct Compiler version mismatch: expected "
            f"{REQUIRED_KSC_VERSION}, got '{version}'"
        )
        return errors, details

    schema_path = repo_root / "research" / "formats" / "res.ksy"
    try:
        with tempfile.TemporaryDirectory(prefix="stunt-kaitai-") as tmp:
            compile_schemas([schema_path], tmp)
            res_module = load_generated_module(Path(tmp) / "res.py", "stunt_kaitai_res")
            res_cls: Any = res_module.Res

            kaitaistruct_mod: Any = importlib.import_module("kaitaistruct")
            kaitai_stream_cls: Any = kaitaistruct_mod.KaitaiStream

            parsed = res_cls(kaitai_stream_cls(io.BytesIO(res_bytes)))

            if parsed.magic != b"RS":
                errors.append(
                    f"Kaitai res.ksy magic mismatch: expected b'RS', got {bytes(parsed.magic)!r}"
                )
            if parsed.res_index != 1:
                errors.append(
                    f"Kaitai res.ksy res_index mismatch: expected 1, got {parsed.res_index}"
                )
            if parsed.item_count != 3:
                errors.append(
                    f"Kaitai res.ksy item_count mismatch: expected 3, got {parsed.item_count}"
                )
            if parsed.ofs_data != 20:
                errors.append(f"Kaitai res.ksy ofs[0] mismatch: expected 20, got {parsed.ofs_data}")
            if list(parsed.offsets) != [20, 40, 56, 72]:
                errors.append(
                    "Kaitai res.ksy offset table mismatch: expected [20, 40, 56, 72], "
                    f"got {list(parsed.offsets)}"
                )
            segments = [bytes(segment.body) for segment in parsed.segments]
            if [len(segment) for segment in segments] != [20, 16, 16]:
                errors.append(
                    "Kaitai res.ksy segment lengths mismatch: expected [20, 16, 16], "
                    f"got {[len(segment) for segment in segments]}"
                )
            if not segments or segments[0] != b"PLANE.SOD\x00PROP.SOD\x00\x00":
                errors.append(
                    "Kaitai res.ksy name-table segment mismatch: expected "
                    f"b'PLANE.SOD\\x00PROP.SOD\\x00\\x00', got {segments[0] if segments else None!r}"
                )
            if segments[1:3] != [res_bytes[40:56], res_bytes[56:72]]:
                errors.append("Kaitai res.ksy payload segments do not match fixture bytes 40..72")

            bad_magic = bytearray(res_bytes)
            bad_magic[0] = 0x58
            bad_align = bytearray(res_bytes)
            struct.pack_into("<I", bad_align, 4, 21)
            for label, mutated in (("bad magic", bad_magic), ("unaligned ofs[0]", bad_align)):
                try:
                    res_cls(kaitai_stream_cls(io.BytesIO(bytes(mutated))))
                except Exception:  # noqa: S112
                    continue
                errors.append(f"Kaitai res.ksy accepted malformed fixture copy: {label}")

            details.append(
                f"synthetic_minimal.res parsed by Kaitai res.ksy "
                f"({len(res_bytes)} bytes, offsets {list(parsed.offsets)})"
            )
    except Exception as exc:
        errors.append(f"Kaitai RES fixture validation failed: {exc}")
    return errors, details


def _validate_flm_with_kaitai(repo_root: Path, flm_bytes: bytes) -> tuple[list[str], list[str]]:
    """Parse every fixture slice with the walker's masks and the flm_slice.ksy parser."""
    errors: list[str] = []
    details: list[str] = []

    version = compiler_version()
    if version is None:
        details.append(
            "Kaitai Struct Compiler not found on PATH; flm_slice.ksy fixture cross-check skipped"
        )
        return errors, details

    try:
        views = flm_walk.walk_film(flm_bytes)
    except flm_walk.FlmWalkError as exc:
        errors.append(f"flm_walk rejected synthetic_minimal.flm: {exc}")
        return errors, details
    if [view.start for view in views] != [4, 13] or [view.end for view in views] != [13, 17]:
        errors.append(
            "flm_walk slice bounds mismatch: expected [4, 13]..[13, 17], "
            f"got {[(view.start, view.end) for view in views]}"
        )
        return errors, details

    schema_path = repo_root / "research" / "formats" / "flm_slice.ksy"
    try:
        with tempfile.TemporaryDirectory(prefix="stunt-kaitai-") as tmp:
            compile_schemas([schema_path], tmp)
            module = load_generated_module(Path(tmp) / "flm_slice.py", "stunt_kaitai_flm_slice")
            flm_cls: Any = module.FlmSlice
            kaitai_stream_cls: Any = importlib.import_module("kaitaistruct").KaitaiStream

            parsed_slices: list[Any] = []
            for view in views:
                chunk = flm_bytes[view.start : view.end]
                parsed = flm_cls(
                    view.moves, view.rotates, view.animates, kaitai_stream_cls(io.BytesIO(chunk))
                )
                parsed_slices.append(parsed)
                consumed = int(parsed._io.pos())
                if consumed != len(chunk):
                    errors.append(
                        f"flm_slice.ksy parsed {consumed} of {len(chunk)} bytes "
                        f"for slice {view.index}"
                    )
            first = parsed_slices[0]
            if int(first.first.tag) != 0x80 or int(first.first.body.body.value) != 0x9890:
                errors.append(
                    "flm_slice.ksy slice 0 var_set mismatch: expected tag 0x80 value 0x9890, "
                    f"got tag {int(first.first.tag)} value {int(first.first.body.body.value)}"
                )
            details.append(
                f"synthetic_minimal.flm parsed by Kaitai flm_slice.ksy "
                f"({len(flm_bytes)} bytes, {len(views)} slices)"
            )
    except Exception as exc:
        errors.append(f"Kaitai FLM fixture validation failed: {exc}")
    return errors, details


def verify_synthetic_fixtures_consistency(repo_root: Path) -> VerificationResult:
    """Validate documented offsets, signatures, and opcodes against synthetic fixtures in tests/fixtures/."""
    errors: list[str] = []
    details: list[str] = []
    fixtures_dir = repo_root / "tests" / "fixtures"

    # 1. synthetic_minimal.res
    res_path = fixtures_dir / "synthetic_minimal.res"
    if not res_path.exists():
        errors.append(f"Synthetic fixture missing: {res_path}")
    else:
        res_bytes = res_path.read_bytes()
        if len(res_bytes) != 72:
            errors.append(
                f"synthetic_minimal.res size mismatch: expected 72 bytes, got {len(res_bytes)}"
            )

        # Verify documentation in research/formats/res.md
        res_doc = (repo_root / "research" / "formats" / "res.md").read_text(encoding="utf-8")
        if 'b"RS"' not in res_doc and "0x52, 0x53" not in res_doc:
            errors.append("res.md does not document RS magic signature (0x52, 0x53)")
        if "synthetic_minimal.res" not in res_doc:
            errors.append("res.md does not cite tests/fixtures/synthetic_minimal.res in section 1")

        res_errors, res_details = _validate_res_with_kaitai(repo_root, res_bytes)
        errors.extend(res_errors)
        details.extend(res_details)

    # 2. synthetic_minimal.flm
    flm_path = fixtures_dir / "synthetic_minimal.flm"
    if not flm_path.exists():
        errors.append(f"Synthetic fixture missing: {flm_path}")
    else:
        flm_bytes = flm_path.read_bytes()
        if len(flm_bytes) != 17:
            errors.append(
                f"synthetic_minimal.flm size mismatch: expected 17 bytes, got {len(flm_bytes)}"
            )
        if flm_bytes[:4] != b"FILM":
            errors.append(
                f"synthetic_minimal.flm magic signature mismatch: expected b'FILM', got {flm_bytes[:4]!r}"
            )

        # Slice 0 header at 0x0004: prev_slice_len 0x0000, tick_duration 0x01.
        if struct.unpack_from("<H", flm_bytes, 4)[0] != 0 or flm_bytes[6] != 1:
            errors.append(
                "synthetic_minimal.flm slice 0 header mismatch: expected prev_slice_len 0, "
                f"tick_duration 1, got prev_slice_len "
                f"{struct.unpack_from('<H', flm_bytes, 4)[0]}, tick_duration {flm_bytes[6]}"
            )

        slice_0_bytecode = list(flm_bytes[7:13])
        if slice_0_bytecode != [0x80, 0x90, 0x98, 0x90, 0x98, 0xFF]:
            errors.append(f"synthetic_minimal.flm slice 0 bytecode mismatch: {slice_0_bytecode}")

        # Slice 1 header at 0x000D: 9-byte back-pointer to slice 0.
        if struct.unpack_from("<H", flm_bytes, 13)[0] != 9 or flm_bytes[15] != 1:
            errors.append(
                "synthetic_minimal.flm slice 1 header mismatch: expected prev_slice_len 9, "
                f"tick_duration 1, got prev_slice_len "
                f"{struct.unpack_from('<H', flm_bytes, 13)[0]}, tick_duration {flm_bytes[15]}"
            )
        if flm_bytes[16] != 0xFF:
            errors.append(
                f"synthetic_minimal.flm slice 1 terminator mismatch: expected 0xFF, got {flm_bytes[16]:#04x}"
            )

        # Verify documentation in research/formats/flm.md
        flm_doc = (repo_root / "research" / "formats" / "flm.md").read_text(encoding="utf-8")
        if 'b"FILM"' not in flm_doc and "FILM" not in flm_doc:
            errors.append("flm.md does not document FILM magic signature")
        if "synthetic_minimal.flm" not in flm_doc:
            errors.append("flm.md does not cite tests/fixtures/synthetic_minimal.flm in section 1")

        details.append(
            f"synthetic_minimal.flm validated against flm.md ({len(flm_bytes)} bytes, 2 slices)"
        )

        flm_errors, flm_details = _validate_flm_with_kaitai(repo_root, flm_bytes)
        errors.extend(flm_errors)
        details.extend(flm_details)

    # 3. synthetic_minimal.sod
    sod_path = fixtures_dir / "synthetic_minimal.sod"
    if not sod_path.exists():
        errors.append(f"Synthetic fixture missing: {sod_path}")
    else:
        sod_bytes = sod_path.read_bytes()
        if len(sod_bytes) != 76:
            errors.append(
                f"synthetic_minimal.sod size mismatch: expected 76 bytes, got {len(sod_bytes)}"
            )

        op_id = struct.unpack_from("<H", sod_bytes, 0)[0]
        if op_id != 0x000C:
            errors.append(
                f"synthetic_minimal.sod OP_ID mismatch: expected 0x000C, got 0x{op_id:04X}"
            )

        bounding_size = struct.unpack_from("<H", sod_bytes, 2)[0]
        scale = struct.unpack_from("<H", sod_bytes, 6)[0]
        if bounding_size != 100 or scale != 1:
            errors.append(
                f"synthetic_minimal.sod header fields mismatch: bounding_size={bounding_size}, scale={scale}"
            )

        # Check OP_VECTORS (0x0075) opcode at offset 10
        op_vectors = struct.unpack_from("<H", sod_bytes, 10)[0]
        if op_vectors != 0x0075:
            errors.append(f"synthetic_minimal.sod OP_VECTORS opcode mismatch: 0x{op_vectors:04X}")

        # Verify documentation in research/formats/sod.md
        sod_doc = (repo_root / "research" / "formats" / "sod.md").read_text(encoding="utf-8")
        if "0x000C" not in sod_doc and "0x000c" not in sod_doc:
            errors.append("sod.md does not document OP_ID 0x000C header")
        if "synthetic_minimal.sod" not in sod_doc:
            errors.append("sod.md does not cite tests/fixtures/synthetic_minimal.sod in section 1")

        details.append(
            f"synthetic_minimal.sod validated against sod.md ({len(sod_bytes)} bytes, OP_ID 0x000C)"
        )

    # 4. oracle_intro_trajectory.json
    traj_path = fixtures_dir / "oracle_intro_trajectory.json"
    if not traj_path.exists():
        errors.append(f"Synthetic fixture missing: {traj_path}")
    else:
        try:
            traj_data = json.loads(traj_path.read_text(encoding="utf-8"))
            if not isinstance(traj_data, list) or len(traj_data) != 2:
                errors.append(
                    f"oracle_intro_trajectory.json format error: expected 2 records list, got {len(traj_data)}"
                )
            else:
                for idx, record in enumerate(traj_data):
                    for req_key in ("tick", "camera", "actors", "audio_cues"):
                        if req_key not in record:
                            errors.append(
                                f"oracle_intro_trajectory.json record {idx} missing key '{req_key}'"
                            )

                    cam = record.get("camera", {})
                    for cam_key in ("eye", "target", "fov_degrees", "roll_radians"):
                        if cam_key not in cam:
                            errors.append(
                                f"oracle_intro_trajectory.json record {idx} camera missing '{cam_key}'"
                            )

                    actors = record.get("actors", [])
                    for actor_idx, actor in enumerate(actors):
                        q = actor.get("rotation_quat", [])
                        if len(q) == 4:
                            norm = math.sqrt(sum(c * c for c in q))
                            if abs(norm - 1.0) > 1e-4:
                                errors.append(
                                    f"Quaternion not normalized in tick {record.get('tick')} actor {actor_idx}: {norm}"
                                )

                details.append(
                    f"oracle_intro_trajectory.json validated ({len(traj_data)} discrete simulation ticks)"
                )
        except json.JSONDecodeError as exc:
            errors.append(f"Failed to parse oracle_intro_trajectory.json as JSON: {exc}")

    # 5. README.md in tests/fixtures
    readme_path = fixtures_dir / "README.md"
    if not readme_path.exists():
        errors.append("tests/fixtures/README.md is missing")
    else:
        readme_text = readme_path.read_text(encoding="utf-8")
        for fixture_name in (
            "synthetic_minimal.res",
            "synthetic_minimal.flm",
            "synthetic_minimal.sod",
        ):
            if fixture_name not in readme_text:
                errors.append(
                    f"tests/fixtures/README.md does not document fixture '{fixture_name}'"
                )
        details.append("tests/fixtures/README.md documentation verified")

    return VerificationResult(
        category="Synthetic Fixture Consistency",
        passed=(len(errors) == 0),
        errors=errors,
        details=details,
    )


# -----------------------------------------------------------------------------
# Main Test / Execution Runner
# -----------------------------------------------------------------------------


def run_all_verifications(
    repo_root: Path | None = None,
) -> tuple[bool, list[VerificationResult]]:
    """Execute all catalog verifications and return overall pass/fail status and results."""
    if repo_root is None:
        # Default to repository root (two directories up from python/scripts/)
        repo_root = Path(__file__).resolve().parent.parent.parent

    results: list[VerificationResult] = [
        verify_file_presence(repo_root),
        verify_schema_conformance(repo_root),
        verify_tier_vocabulary(repo_root),
        verify_provenance_and_attribution(repo_root),
        verify_asset_isolation(repo_root),
        verify_link_integrity(repo_root),
        verify_synthetic_fixtures_consistency(repo_root),
    ]

    all_passed = all(r.passed for r in results)
    return all_passed, results


def main() -> int:
    """CLI entry point for verification script."""
    parser = argparse.ArgumentParser(
        description="Verify Stunt Island Technical Reference Catalog & Format Specifications"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Path to repository root (defaults to parent of python/scripts/)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print detailed check output for passing items",
    )
    args = parser.parse_args()

    repo_root = args.root
    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent.parent

    print("=" * 80)
    print("STUNT ISLAND TECHNICAL REFERENCE CATALOG: PROGRAMMATIC VERIFICATION")
    print(f"Repository Root: {repo_root.resolve()}")
    print("=" * 80)

    all_passed, results = run_all_verifications(repo_root=repo_root)

    for result in results:
        status_tag = "[PASS]" if result.passed else "[FAIL]"
        print(f"\n{status_tag} {result.category}")

        if args.verbose:
            for detail in result.details:
                print(f"  + {detail}")

        if result.errors:
            for err in result.errors:
                print(f"  ! ERROR: {err}")

    print("\n" + "=" * 80)
    if all_passed:
        print("RESULT: ALL 7 VERIFICATION SUITES PASSED (100% SPEC & ASSET-ISOLATED)")
        print("=" * 80)
        return 0

    print("RESULT: VERIFICATION SUITE FAILED — REVIEW DIAGNOSTIC ERRORS ABOVE")
    print("=" * 80)
    return 1


if __name__ == "__main__":
    sys.exit(main())
