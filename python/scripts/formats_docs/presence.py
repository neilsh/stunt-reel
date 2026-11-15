"""File Presence: every required catalog document exists and is non-empty."""

from __future__ import annotations

lazy from pathlib import Path

from formats_docs.catalog import REQUIRED_DOCS, VerificationResult


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
