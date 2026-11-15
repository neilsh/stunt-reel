"""Evidentiary Tier Vocabulary: every tier tag names a shared enum member."""

from __future__ import annotations

import re
lazy from pathlib import Path

from formats_docs.catalog import (
    EVIDENTIARY_TIERS,
    TIER_LIKE_REGEX,
    TIER_SCAN_GLOBS,
    VerificationResult,
)
from stunt_reel.markdown_links import prose


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
        rel = path.relative_to(repo_root).as_posix()
        text = path.read_text(encoding="utf-8")
        # Tiers inside inline code are still tags; only fenced blocks hold examples.
        for line_num, line in enumerate(prose(text, inline_code=False).splitlines(), start=1):
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
