"""Run every catalog verification pass and print the verdict."""

from __future__ import annotations

import argparse
from pathlib import Path

from formats_docs.fixtures import verify_synthetic_fixtures_consistency
from formats_docs.isolation import verify_asset_isolation
from formats_docs.links import verify_link_integrity
from formats_docs.presence import verify_file_presence
from formats_docs.provenance import verify_provenance_and_attribution
from formats_docs.schema import verify_schema_conformance
from formats_docs.tiers import verify_tier_vocabulary
lazy from formats_docs.catalog import VerificationResult


def _default_repo_root() -> Path:
    """The checkout, four directories above this module (``python/scripts/formats_docs/``)."""
    return Path(__file__).resolve().parents[3]


def run_all_verifications(
    repo_root: Path | None = None,
) -> tuple[bool, list[VerificationResult]]:
    """Execute all catalog verifications and return overall pass/fail status and results."""
    if repo_root is None:
        repo_root = _default_repo_root()

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
        repo_root = _default_repo_root()

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
