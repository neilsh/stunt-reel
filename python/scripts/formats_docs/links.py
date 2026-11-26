"""Link Integrity: every relative Markdown link and anchor in the scan set resolves to committed data."""

from __future__ import annotations

lazy from pathlib import Path

from formats_docs.catalog import VerificationResult, link_scan_files
from stunt_reel.markdown_links import (
    ResolvedTarget,
    anchor_matches,
    anchors_of,
    extract_links,
    ignore_rules,
    resolve_target,
)


def verify_link_integrity(repo_root: Path) -> VerificationResult:
    """Validate that every markdown link in the scanned document set resolves to committed data."""
    errors: list[str] = []
    details: list[str] = []
    links_checked = 0
    root = repo_root.resolve()

    scan_files = link_scan_files(repo_root)
    pending: list[tuple[str, int, str, ResolvedTarget]] = []
    targets: set[str] = set()
    for rel_path in scan_files:
        source_file = (repo_root / rel_path).resolve()
        if not source_file.exists():
            continue
        for link in extract_links(source_file.read_text(encoding="utf-8")):
            resolved = resolve_target(source_file, link.target, root)
            if resolved is None:
                continue
            links_checked += 1
            if resolved.relative is not None:
                targets.add(resolved.relative)
            pending.append((rel_path, link.line, link.target, resolved))

    ignored = ignore_rules(root, targets)
    for rel_path, line, target, resolved in pending:
        if not resolved.file.exists():
            errors.append(
                f"Broken link in {rel_path}:{line} -> '{target}' "
                f"(target does not exist: {resolved.file})"
            )
            continue

        # A gitignored target exists in the worktree that wrote it but not on main. The lookup
        # is lexical, so a target under a data-root junction stays inside the repository.
        rule = ignored.get(resolved.relative) if resolved.relative is not None else None
        if rule is not None:
            errors.append(
                f"Broken link in {rel_path}:{line} -> '{target}' "
                f"(target is gitignored by {rule}: {resolved.file})"
            )
            continue

        # If anchor is present and target is a Markdown file, verify anchor target
        if (
            resolved.fragment
            and resolved.file.suffix == ".md"
            and not anchor_matches(resolved.fragment, anchors_of(resolved.file))
        ):
            errors.append(
                f"Broken anchor in {rel_path}:{line} -> '{target}' "
                f"(anchor '{resolved.fragment}' not found in {resolved.file.name})"
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
