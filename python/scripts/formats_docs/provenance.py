"""Provenance & Attribution: every catalog document cites and credits its sources."""

from __future__ import annotations

import re
lazy from pathlib import Path

from formats_docs.catalog import INDEX_DOC, KEY_COMMUNITY_AUTHORS, REQUIRED_DOCS, VerificationResult


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
