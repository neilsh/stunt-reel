"""Schema Conformance: every spec, concept guide and the index follow its sections."""

from __future__ import annotations

import re
lazy from pathlib import Path

from formats_docs.catalog import (
    CATALOG_REQUIRED_TIERS,
    CONCEPT_DOC_SECTIONS,
    CONCEPT_DOCS,
    EVIDENTIARY_TIERS,
    FORMAT_SPEC_SECTIONS,
    FORMAT_SPECS,
    INDEX_DOC,
    INDEX_SECTIONS,
    KSY_SOURCES,
    REFERENCE_DOCS,
    VerificationResult,
)


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
