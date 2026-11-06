"""Guards the TAC Python palette copy against the shared golden fixture.

The Rust side asserts the same JSON file in stunt-core, so drift in either
language fails a test.
"""

from __future__ import annotations

import json
from pathlib import Path

from stunt_reel.tac.palette import MODE_13H_PALETTE

FIXTURES = Path(__file__).parent / "fixtures"


def test_palette_matches_golden() -> None:
    golden = json.loads((FIXTURES / "mode13h_palette.json").read_text(encoding="utf-8"))
    assert len(golden) == 256
    assert [list(c) for c in MODE_13H_PALETTE] == golden
