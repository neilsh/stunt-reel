"""Asset isolation: research/formats/ holds only UTF-8 Markdown and Kaitai YAML."""

from __future__ import annotations

lazy from pathlib import Path

from formats_docs.catalog import ALLOWED_TEXT_SUFFIXES, VerificationResult


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
