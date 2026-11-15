"""Technical Reference Catalog Verification Script for Stunt Island.

Programmatically validates:
1. File Presence: All 13 core, concept, and auxiliary format documents exist.
2. Schema Conformance: 5-section uniform structure across specs and concepts (invariants,
   Seam contracts and fixtures are linked from section 1, not restated), links to the .ksy
   schema that owns each byte layout,
   sequential header ordering, evidentiary tier tagging (see EVIDENTIARY_TIERS in
   formats_docs/catalog.py),
   and Mermaid asset graphs.
3. Provenance & Attribution: Direct citations to corpus/siarchive/, .agents/teamwork/,
   and explicit credit to community researchers.
4. Asset isolation: ZERO binary files in research/formats/, valid UTF-8 encoding,
   no null bytes, and offline synthetic test fixture alignment [I7].
5. Link Integrity: Zero broken relative markdown links or anchor targets across
   the catalog and docs/ARCHITECTURE.md.
6. Synthetic Fixture Consistency: Documented headers, offsets, and opcodes align
   byte-for-byte with synthetic test fixtures in tests/fixtures/.

Each pass lives in ``formats_docs/`` beside this script; they are re-exported here so the
catalog tests can keep calling them from this module.
"""

from __future__ import annotations

import sys

from formats_docs.catalog import TIER_LIKE_REGEX, VerificationResult
from formats_docs.fixtures import verify_synthetic_fixtures_consistency
from formats_docs.isolation import verify_asset_isolation
from formats_docs.links import verify_link_integrity
from formats_docs.presence import verify_file_presence
from formats_docs.provenance import verify_provenance_and_attribution
from formats_docs.runner import main, run_all_verifications
from formats_docs.schema import verify_schema_conformance
from formats_docs.tiers import verify_tier_vocabulary

__all__ = [
    "TIER_LIKE_REGEX",
    "VerificationResult",
    "run_all_verifications",
    "verify_asset_isolation",
    "verify_file_presence",
    "verify_link_integrity",
    "verify_provenance_and_attribution",
    "verify_schema_conformance",
    "verify_synthetic_fixtures_consistency",
    "verify_tier_vocabulary",
]


if __name__ == "__main__":
    sys.exit(main())
