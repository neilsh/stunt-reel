"""Link Integrity: every relative Markdown link and anchor in the scan set resolves."""

from __future__ import annotations

import re
lazy from pathlib import Path

from formats_docs.catalog import VerificationResult, link_scan_files
from stunt_reel.markdown_links import (
    HEADING_REGEX,
    MARKDOWN_LINK_REGEX,
    URL_SCHEME_REGEX,
    prose,
    slug,
)

#: A bracketed anchor token, ``[MEM-SOD-VM]``, which a fragment may name.
_TOKEN_REGEX = re.compile(r"\[([A-Za-z0-9_-]+)\]")


def _heading_slugs(text: str) -> set[str]:
    """Anchor slugs of *text*'s ATX headings outside fenced code."""
    return {
        slug(heading.group(2))
        for blanked, line in zip(prose(text).splitlines(), text.splitlines(), strict=True)
        if HEADING_REGEX.match(blanked) and (heading := HEADING_REGEX.match(line))
    }


def verify_link_integrity(repo_root: Path) -> VerificationResult:
    """Validate that every markdown link in the scanned document set resolves on disk."""
    errors: list[str] = []
    details: list[str] = []
    links_checked = 0

    scan_files = link_scan_files(repo_root)
    for rel_path in scan_files:
        source_file = repo_root / rel_path
        if not source_file.exists():
            continue

        # The catalog has always read links inside inline code, so only fenced blocks are blanked.
        content = prose(source_file.read_text(encoding="utf-8"), inline_code=False)

        for line_num, line in enumerate(content.splitlines(), start=1):
            for match in MARKDOWN_LINK_REGEX.finditer(line):
                url = match.group(1).strip()

                # Ignore external URLs
                if URL_SCHEME_REGEX.match(url):
                    continue

                # Gitignored data trees exist only on developer machines
                if url.startswith("corpus/"):
                    continue

                links_checked += 1
                file_part, _, anchor = url.partition("#")

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
                    slug_set = _heading_slugs(target_content) | {
                        token.lower() for token in _TOKEN_REGEX.findall(target_content)
                    }

                    norm_anchor = anchor.lower()
                    if norm_anchor not in slug_set and slug(norm_anchor) not in slug_set:
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
