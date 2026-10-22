"""Guards the TAC Python math/palette copies against the shared golden fixtures.

The Rust side asserts the same JSON files in stunt-core, so drift in either
language fails a test.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from stunt_reel.tac import dos_math
from stunt_reel.tac.palette import MODE_13H_PALETTE

FIXTURES = Path(__file__).parent / "fixtures"
TOL = 1e-5

GOLDENS = json.loads((FIXTURES / "dos_math_goldens.json").read_text(encoding="utf-8"))


def _assert_close(actual: list[float], expected: list[float]) -> None:
    assert len(actual) == len(expected)
    for a, e in zip(actual, expected, strict=True):
        assert abs(a - e) <= TOL, (a, e)


def test_palette_matches_golden() -> None:
    golden = json.loads((FIXTURES / "mode13h_palette.json").read_text(encoding="utf-8"))
    assert len(golden) == 256
    assert [list(c) for c in MODE_13H_PALETTE] == golden


@pytest.mark.parametrize("case", GOLDENS["bam_to_radians"])
def test_bam_to_radians_golden(case: dict[str, Any]) -> None:
    _assert_close([dos_math.bam_to_radians(case["input"])], [case["expected"]])


@pytest.mark.parametrize("case", GOLDENS["focal_to_fov_y"])
def test_focal_to_fov_y_golden(case: dict[str, Any]) -> None:
    _assert_close([dos_math.focal_to_fov_y(case["input"])], [case["expected"]])


@pytest.mark.parametrize("case", GOLDENS["quat_from_euler"])
def test_quat_from_euler_golden(case: dict[str, Any]) -> None:
    _assert_close(dos_math.quat_from_euler(*case["input"]), case["expected"])


@pytest.mark.parametrize("case", GOLDENS["world_matrix"])
def test_world_matrix_golden(case: dict[str, Any]) -> None:
    _assert_close(dos_math.compute_world_matrix(case["position"], case["quat"]), case["expected"])
