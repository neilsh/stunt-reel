"""Link Integrity: every relative Markdown link and anchor in the scan set resolves to committed data."""

from __future__ import annotations

import re
lazy from pathlib import Path

from formats_docs.catalog import VerificationResult, ignore_rules, link_scan_files
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


def _repo_relative(target: Path, root: Path) -> str | None:
    """*target*'s POSIX path inside *root*, or None when it lies outside."""
    try:
        return target.relative_to(root).as_posix()
    except ValueError:
        return None


def verify_link_integrity(repo_root: Path) -> VerificationResult:
    """Validate that every markdown link in the scanned document set resolves to committed data."""
    errors: list[str] = []
    details: list[str] = []
    links_checked = 0
    root = repo_root.resolve()

    scan_files = link_scan_files(repo_root)
    links: list[tuple[str, int, str, Path, str]] = []
    targets: set[str] = set()
    for rel_path in scan_files:
        source_file = (repo_root / rel_path).resolve()
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

                links_checked += 1
                file_part, _, anchor = url.partition("#")

                # Resolve target file path
                if file_part:
                    target_file = (source_file.parent / file_part).resolve()
                else:
                    target_file = source_file

                relative = _repo_relative(target_file, root)
                if relative is not None:
                    targets.add(relative)
                links.append((rel_path, line_num, url, target_file, anchor))

    ignored = ignore_rules(root, targets)
    for rel_path, line_num, url, target_file, anchor in links:
        if not target_file.exists():
            errors.append(
                f"Broken link in {rel_path}:{line_num} -> '{url}' (target does not exist: {target_file})"
            )
            continue

        # A gitignored target exists in the worktree that wrote it but not on main.
        relative = _repo_relative(target_file, root)
        rule = ignored.get(relative) if relative is not None else None
        if rule is not None:
            errors.append(
                f"Broken link in {rel_path}:{line_num} -> '{url}' "
                f"(target is gitignored by {rule}: {target_file})"
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
