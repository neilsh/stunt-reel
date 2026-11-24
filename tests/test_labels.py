"""Validate the canonical label catalog in ``python/scripts/labels.py`` and its doc table."""

from __future__ import annotations

import colorsys
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "python" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import labels  # noqa: E402

_HEX_COLOR = re.compile(r"^[0-9A-F]{6}$")
_VALID_PREFIXES = ("status:", "priority:", "type:", "env:", "area:")
_PRIORITY_PREFIX = "priority:"
_GRAY_MAX_SATURATION = 0.20
_WARM_MAX_HUE_DEG = 60.0
_WARM_WRAP_MIN_HUE_DEG = 345.0
_WARM_MIN_SATURATION = 0.85
_COOL_MIN_HUE_DEG = 120.0
_COOL_MAX_HUE_DEG = 290.0
_COOL_MIN_SATURATION = 0.25
_COOL_MAX_SATURATION = 0.65


def _rgb(hex_color: str) -> tuple[float, float, float]:
    return (
        int(hex_color[0:2], 16) / 255.0,
        int(hex_color[2:4], 16) / 255.0,
        int(hex_color[4:6], 16) / 255.0,
    )


def _hsv_deg(hex_color: str) -> tuple[float, float]:
    r, g, b = _rgb(hex_color)
    h, s, _ = colorsys.rgb_to_hsv(r, g, b)
    return h * 360.0, s


def test_catalog_entries_have_valid_unique_names_colors_and_descriptions() -> None:
    names = [spec.name for spec in labels.CATALOG]
    assert len(names) == len(set(names))
    assert set(names) == set(labels.CATALOG_BY_NAME)
    for spec in labels.CATALOG:
        assert spec.name.startswith(_VALID_PREFIXES), spec.name
        assert _HEX_COLOR.fullmatch(spec.color), spec
        assert 1 <= len(spec.description) <= 100, spec


def test_priority_reserves_warm_vivid_and_gray_while_other_prefixes_stay_muted_cool() -> None:
    priority_specs = [spec for spec in labels.CATALOG if spec.name.startswith(_PRIORITY_PREFIX)]
    priority_colors = {spec.color for spec in priority_specs}
    assert len(priority_colors) == len(labels.PRIORITIES)
    for spec in priority_specs:
        hue, sat = _hsv_deg(spec.color)
        if spec.name == labels.PRIORITY_P3:
            assert sat <= _GRAY_MAX_SATURATION, (spec.name, sat)
        else:
            assert hue <= _WARM_MAX_HUE_DEG or hue >= _WARM_WRAP_MIN_HUE_DEG, (spec.name, hue)
            assert sat >= _WARM_MIN_SATURATION, (spec.name, sat)

    by_prefix: dict[str, set[str]] = {}
    for spec in labels.CATALOG:
        prefix = spec.name.split(":", 1)[0] + ":"
        if prefix != _PRIORITY_PREFIX:
            by_prefix.setdefault(prefix, set()).add(spec.color)
    assert set(by_prefix) == {"status:", "type:", "env:", "area:"}
    cool_colors: set[str] = set()
    for prefix, colors in by_prefix.items():
        assert len(colors) == 1, (prefix, colors)
        (color,) = colors
        hue, sat = _hsv_deg(color)
        assert _COOL_MIN_HUE_DEG <= hue <= _COOL_MAX_HUE_DEG, (prefix, color, hue)
        assert _COOL_MIN_SATURATION <= sat <= _COOL_MAX_SATURATION, (prefix, color, sat)
        assert color not in priority_colors
        cool_colors.add(color)
    assert len(cool_colors) == len(by_prefix)


def test_priority_rank_picks_highest_priority_and_none_when_unprioritized() -> None:
    assert labels.priority_rank([]) is None
    assert labels.priority_rank(["status:ready-for-agent", "area:core"]) is None
    assert labels.priority_rank(["priority:p0"]) == 0
    assert labels.priority_rank(["priority:p1"]) == 1
    assert labels.priority_rank(["priority:p2"]) == 2
    assert labels.priority_rank(["priority:p3"]) == 3
    assert labels.priority_rank(["priority:p3", "priority:p1"]) == 1


@pytest.mark.docs
def test_triage_labels_doc_lists_every_canonical_label_without_retired_tooling_row() -> None:
    text = (REPO_ROOT / "docs" / "agents" / "triage-labels.md").read_text(encoding="utf-8")
    for spec in labels.CATALOG:
        assert f"`{spec.name}`" in text, f"{spec.name} missing from docs/agents/triage-labels.md"
    table_lines = [line for line in text.splitlines() if line.lstrip().startswith("|")]
    assert not any("`type:tooling`" in line for line in table_lines)
