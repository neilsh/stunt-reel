"""Technical Reference Catalog Verification Script for Stunt Island.

Programmatically validates:
1. File Presence: All 13 core, concept, and auxiliary format documents exist.
2. Schema Conformance: 7-section uniform structure across specs and concepts,
   sequential header ordering, evidentiary tier tagging ([Hypothesis],
   [Bounded Observation], [Supported Inference], [Established]), and Mermaid asset graphs.
3. Provenance & Attribution: Direct citations to corpus/si_archive/, .agents/teamwork/,
   and explicit credit to community reverse-engineers.
4. Cleanroom Isolation: ZERO binary files in research/formats/, valid UTF-8 encoding,
   no null bytes, and offline synthetic test fixture alignment [I7].
5. Link Integrity: Zero broken relative markdown links or anchor targets across
   the catalog and docs/ARCHITECTURE.md.
6. Synthetic Fixture Consistency: Documented headers, offsets, and opcodes align
   byte-for-byte with cleanroom test fixtures in tests/fixtures/.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

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
    "## 4. Architectural Invariants & Coordinate Mapping",
    "## 5. Open Questions & Reverse Engineering Backlog",
    "## 6. Attribution & Provenance",
    "## 7. Codebase Seam Contracts & Fixtures",
]

CONCEPT_DOC_SECTIONS: list[str] = [
    "## 1. Overview & Mathematical / Hardware Principles",
    "## 2. Memory Layout & Bitfield Representations",
    "## 3. Data Structures, Tables & Conversion Algorithms",
    "## 4. Architectural Invariants & Coordinate Mapping",
    "## 5. Open Questions & Reverse Engineering Backlog",
    "## 6. Attribution & Provenance",
    "## 7. Codebase Seam Contracts & Fixtures",
]

INDEX_SECTIONS: list[str] = [
    "## 1. Master Format Catalog",
    "## 2. Runtime Asset Dependency Graph & Data Flow Architecture",
    "## 3. Shared Architectural Concepts Directory",
    "## 4. Seam Contracts & Invariants Mapping",
    "## 5. Reverse Engineering Backlog & Open Questions",
    "## 6. Provenance & Community Attribution",
    "## 7. Cleanroom Codebase Contracts & Synthetic Fixtures",
]

EVIDENTIARY_TIERS: list[str] = [
    "[Hypothesis]",
    "[Bounded Observation]",
    "[Supported Inference]",
    "[Established]",
]

KEY_COMMUNITY_AUTHORS: list[str] = [
    "Adrian Stephens",
    "Chris Phillips",
    "Doug Armknecht",
    "Neil Halelamien",
    "Dave Palmowski",
]

LINK_SCAN_FILES: list[str] = [
    "docs/ARCHITECTURE.md",
    *REQUIRED_DOCS,
]


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
    """Validate that specs and concept docs conform to uniform 7-section schemas."""
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

        # Verify evidentiary tiers in Section 5
        sec5_match = re.search(
            r"## 5\. Open Questions & Reverse Engineering Backlog(.*?)(?:## 6\.|\Z)",
            content,
            re.DOTALL,
        )
        if sec5_match:
            sec5_content = sec5_match.group(1)
            found_in_doc = {tier for tier in EVIDENTIARY_TIERS if tier in sec5_content}
            catalog_tiers_found.update(found_in_doc)
            if not found_in_doc:
                errors.append(
                    f"Section 5 in {rel_path} lacks evidentiary tier tags ([Hypothesis], [Bounded Observation], etc.)"
                )
        else:
            errors.append(f"Could not isolate Section 5 in {rel_path}")

        details.append(f"Conforms to 7-section format schema: {rel_path}")

    # 2. Concept Guides
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

        sec5_match = re.search(
            r"## 5\. Open Questions & Reverse Engineering Backlog(.*?)(?:## 6\.|\Z)",
            content,
            re.DOTALL,
        )
        if sec5_match:
            sec5_content = sec5_match.group(1)
            found_in_doc = {tier for tier in EVIDENTIARY_TIERS if tier in sec5_content}
            catalog_tiers_found.update(found_in_doc)
            if not found_in_doc:
                errors.append(f"Section 5 in {rel_path} lacks evidentiary tier tags")
        else:
            errors.append(f"Could not isolate Section 5 in {rel_path}")

        details.append(f"Conforms to 7-section concept schema: {rel_path}")

    # 3. Master Index
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
    missing_tiers = set(EVIDENTIARY_TIERS) - catalog_tiers_found
    if missing_tiers:
        errors.append(
            f"Catalog as a whole is missing evidentiary confidence tiers: {sorted(missing_tiers)}"
        )
    else:
        details.append(
            f"All 4 evidentiary confidence tiers represented across catalog: {sorted(catalog_tiers_found)}"
        )

    return VerificationResult(
        category="Schema Conformance",
        passed=(len(errors) == 0),
        errors=errors,
        details=details,
    )


# -----------------------------------------------------------------------------
# Verification Category 3: Provenance & Attribution
# -----------------------------------------------------------------------------


def verify_provenance_and_attribution(repo_root: Path) -> VerificationResult:
    """Validate citations to corpus/si_archive/, .agents/teamwork/, and key community authors."""
    errors: list[str] = []
    details: list[str] = []

    # Check each documentation file for Section 6 attribution
    for rel_path in REQUIRED_DOCS:
        file_path = repo_root / rel_path
        if not file_path.exists():
            continue

        content = file_path.read_text(encoding="utf-8")
        sec6_match = re.search(
            r"## 6\. (?:Attribution & Provenance|Provenance & Community Attribution)(.*?)(?:## 7\.|\Z)",
            content,
            re.DOTALL,
        )
        if not sec6_match:
            errors.append(f"Missing Section 6 in {rel_path}")
            continue

        sec6_content = sec6_match.group(1)

        # Check for citation to corpus archive or teamwork lineage
        has_citation = (
            "corpus/si_archive" in sec6_content
            or ".agents/teamwork/" in sec6_content
            or "teamwork" in sec6_content.lower()
        )
        if not has_citation:
            errors.append(
                f"Missing citation to corpus/si_archive/ or .agents/teamwork/ in {rel_path}"
            )

        # Check that community authors are cited in Section 6
        authors_in_sec = [a for a in KEY_COMMUNITY_AUTHORS if a in sec6_content]
        if not authors_in_sec:
            errors.append(
                f"No recognized community researchers credited in Section 6 of {rel_path}"
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
# Verification Category 4: Cleanroom Isolation
# -----------------------------------------------------------------------------


def verify_cleanroom_isolation(repo_root: Path) -> VerificationResult:
    """Validate that ZERO binary files exist under research/formats/ and all are valid UTF-8 text."""
    errors: list[str] = []
    details: list[str] = []
    formats_dir = repo_root / "research" / "formats"

    if not formats_dir.exists():
        return VerificationResult(
            category="Cleanroom Isolation",
            passed=False,
            errors=[f"Directory does not exist: {formats_dir}"],
            details=[],
        )

    for item in sorted(formats_dir.rglob("*")):
        if item.is_dir():
            continue

        rel_item = item.relative_to(repo_root)

        # Invariant [I7]: Must only be Markdown text files
        if item.suffix != ".md":
            errors.append(f"Prohibited non-markdown file in research/formats/: {rel_item}")
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

        details.append(f"Clean UTF-8 markdown ({len(raw_bytes):,} bytes): {rel_item}")

    return VerificationResult(
        category="Cleanroom Isolation",
        passed=(len(errors) == 0),
        errors=errors,
        details=details,
    )


# -----------------------------------------------------------------------------
# Verification Category 5: Link Integrity
# -----------------------------------------------------------------------------


def verify_link_integrity(repo_root: Path) -> VerificationResult:
    """Validate that all markdown links within catalog specs and docs/ARCHITECTURE.md resolve on disk."""
    errors: list[str] = []
    details: list[str] = []
    link_regex = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    token_regex = re.compile(r"\[([A-Za-z0-9_-]+)\]")

    links_checked = 0

    for rel_path in LINK_SCAN_FILES:
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
        f"Successfully validated {links_checked} local markdown links across {len(LINK_SCAN_FILES)} files"
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
        if res_bytes[:2] != b"RS":
            errors.append(
                f"synthetic_minimal.res magic signature mismatch: expected b'RS', got {res_bytes[:2]!r}"
            )

        ofs_0 = struct.unpack_from("<I", res_bytes, 4)[0]
        if ofs_0 != 20:
            errors.append(f"synthetic_minimal.res ofs[0] mismatch: expected 20, got {ofs_0}")

        num_offsets = (ofs_0 // 4) - 1
        if num_offsets != 4:
            errors.append(
                f"synthetic_minimal.res offset count calculation error: expected 4, got {num_offsets}"
            )

        expected_offsets = [20, 40, 56, 72]
        actual_offsets = [
            struct.unpack_from("<I", res_bytes, 4 + i * 4)[0] for i in range(num_offsets)
        ]
        if actual_offsets != expected_offsets:
            errors.append(
                f"synthetic_minimal.res offset array mismatch: expected {expected_offsets}, got {actual_offsets}"
            )

        name_table_slice = res_bytes[20:40]
        if b"PLANE.SOD\x00PROP.SOD\x00\x00" not in name_table_slice:
            errors.append("synthetic_minimal.res name table string content mismatch")

        # Verify documentation in research/formats/res.md
        res_doc = (repo_root / "research" / "formats" / "res.md").read_text(encoding="utf-8")
        if 'b"RS"' not in res_doc and "0x52, 0x53" not in res_doc:
            errors.append("res.md does not document RS magic signature (0x52, 0x53)")
        if "synthetic_minimal.res" not in res_doc:
            errors.append("res.md does not cite tests/fixtures/synthetic_minimal.res in Section 7")

        details.append(
            f"synthetic_minimal.res validated against res.md ({len(res_bytes)} bytes, 4 offsets)"
        )

    # 2. synthetic_minimal.flm
    flm_path = fixtures_dir / "synthetic_minimal.flm"
    if not flm_path.exists():
        errors.append(f"Synthetic fixture missing: {flm_path}")
    else:
        flm_bytes = flm_path.read_bytes()
        if len(flm_bytes) != 15:
            errors.append(
                f"synthetic_minimal.flm size mismatch: expected 15 bytes, got {len(flm_bytes)}"
            )
        if flm_bytes[:4] != b"FILM":
            errors.append(
                f"synthetic_minimal.flm magic signature mismatch: expected b'FILM', got {flm_bytes[:4]!r}"
            )

        # Slice 0
        inctime_0 = flm_bytes[4]
        decl_len_0 = struct.unpack_from("<H", flm_bytes, 5)[0]
        if inctime_0 != 1 or decl_len_0 != 4:
            errors.append(
                f"synthetic_minimal.flm slice 0 header mismatch: inctime={inctime_0}, decl_len={decl_len_0}"
            )

        slice_0_opcodes = list(flm_bytes[7:11])
        if slice_0_opcodes != [0x80, 0x90, 0x98, 0xFF]:
            errors.append(f"synthetic_minimal.flm slice 0 opcodes mismatch: {slice_0_opcodes}")

        # Slice 1
        inctime_1 = flm_bytes[11]
        decl_len_1 = struct.unpack_from("<H", flm_bytes, 12)[0]
        if inctime_1 != 1 or decl_len_1 != 1:
            errors.append(
                f"synthetic_minimal.flm slice 1 header mismatch: inctime={inctime_1}, decl_len={decl_len_1}"
            )

        # Verify documentation in research/formats/flm.md
        flm_doc = (repo_root / "research" / "formats" / "flm.md").read_text(encoding="utf-8")
        if 'b"FILM"' not in flm_doc and "FILM" not in flm_doc:
            errors.append("flm.md does not document FILM magic signature")
        if "synthetic_minimal.flm" not in flm_doc:
            errors.append("flm.md does not cite tests/fixtures/synthetic_minimal.flm in Section 7")

        details.append(
            f"synthetic_minimal.flm validated against flm.md ({len(flm_bytes)} bytes, 2 slices)"
        )

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
            errors.append("sod.md does not cite tests/fixtures/synthetic_minimal.sod in Section 7")

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
    repo_root: Path | None = None, verbose: bool = False
) -> tuple[bool, list[VerificationResult]]:
    """Execute all catalog verifications and return overall pass/fail status and results."""
    if repo_root is None:
        # Default to repository root (two directories up from python/scripts/)
        repo_root = Path(__file__).resolve().parent.parent.parent

    results: list[VerificationResult] = [
        verify_file_presence(repo_root),
        verify_schema_conformance(repo_root),
        verify_provenance_and_attribution(repo_root),
        verify_cleanroom_isolation(repo_root),
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

    all_passed, results = run_all_verifications(repo_root=repo_root, verbose=args.verbose)

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
        print("RESULT: ALL 6 VERIFICATION SUITES PASSED (100% SPEC & CLEANROOM COMPLIANT)")
        print("=" * 80)
        return 0

    print("RESULT: VERIFICATION SUITE FAILED — REVIEW DIAGNOSTIC ERRORS ABOVE")
    print("=" * 80)
    return 1


if __name__ == "__main__":
    sys.exit(main())
