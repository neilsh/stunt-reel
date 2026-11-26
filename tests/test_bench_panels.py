"""Offline tests for the readout's difference panels and mismatch helpers (synthetic arrays)."""

from __future__ import annotations

import numpy as np

from stunt_reel.bench.mismatch import (
    TIMECODE_BOX,
    colour_mismatch,
    index_mismatch,
    mismatch_fraction,
    readout_mask,
)
from stunt_reel.bench.panels import LAYER_KEY, MASKED, composite, index_map
from stunt_reel.parity_artifacts import LAYER_FIRST_ACTOR, LAYER_PROP, LAYER_TERRAIN

MAGENTA = (255, 0, 255)
GREEN = (0, 255, 0)


def _square(left: int) -> np.ndarray:
    """A white 4x4 square at column *left* on black, 8x12."""
    rgb = np.zeros((8, 12, 3), dtype=np.uint8)
    rgb[2:6, left : left + 4] = 255
    return rgb


def test_a_shifted_square_fringes_magenta_on_one_side_and_green_on_the_other() -> None:
    capture, render = _square(2), _square(4)  # the render draws it 2 px to the right
    out = composite(capture, render, np.zeros((8, 12), dtype=bool))
    assert tuple(out[3, 2]) == MAGENTA  # only the capture is white here
    assert tuple(out[3, 7]) == GREEN  # only the render is white here
    assert tuple(out[3, 4]) == (255, 255, 255)  # both
    assert tuple(out[0, 0]) == (0, 0, 0)  # neither


def test_composite_greys_masked_pixels() -> None:
    mask = np.zeros((8, 12), dtype=bool)
    mask[3, 2] = True
    out = composite(_square(2), _square(4), mask)
    assert tuple(out[3, 2]) == (MASKED,) * 3


def test_index_map_paints_mismatches_by_render_layer_and_counts_them() -> None:
    capture = np.full((2, 4, 3), 200, dtype=np.uint8)
    mismatch = np.array([[True, True, True, False], [True, False, False, False]])
    layer = np.array(
        [[LAYER_TERRAIN, LAYER_PROP, LAYER_FIRST_ACTOR + 3, LAYER_PROP], [7, 0, 0, 0]],
        dtype=np.uint16,
    )
    mask = np.zeros((2, 4), dtype=bool)
    mask[1, 0] = True  # masked, so the unknown layer 7 is neither painted nor counted
    out, counts = index_map(capture, mismatch, layer, mask)
    colours = {entry.name: entry.colour for entry in LAYER_KEY}
    assert tuple(out[0, 0]) == colours["terrain"]
    assert tuple(out[0, 1]) == colours["prop"]
    assert tuple(out[0, 2]) == colours["actor or its shadow"]
    assert tuple(out[0, 3]) == (110, 110, 110)  # matched: the capture dimmed to 55%
    assert tuple(out[1, 0]) == (MASKED,) * 3
    assert counts == {
        "uncovered": 0,
        "ocean": 0,
        "terrain": 1,
        "prop": 1,
        "credits": 0,
        "actor or its shadow": 1,
        "unknown layer": 0,
    }


def test_the_key_covers_every_layer_once_and_avoids_the_composite_colours() -> None:
    covered = [layer for entry in LAYER_KEY for layer in range(entry.lo, entry.hi + 1)]
    assert sorted(covered) == list(range(0x10000))
    assert not {MAGENTA, GREEN} & {entry.colour for entry in LAYER_KEY}


def test_readout_mask_adds_the_timer_to_the_overlay_mask() -> None:
    idx = np.zeros((200, 320), dtype=np.uint8)
    idx[10, 10] = 255  # the cursor's index
    mask = readout_mask(idx)
    row0, row1, col0, col1 = TIMECODE_BOX
    assert mask[row0:row1, col0:col1].all()
    assert mask[185:].all()
    assert mask[10, 10]
    assert not mask[row0 - 1, col0]
    assert not mask[row0, col1]
    assert not readout_mask(idx, credits_drawn=True)[10, 10]


def test_readout_mask_fits_a_small_raster() -> None:
    assert not readout_mask(np.zeros((2, 4), dtype=np.uint8)).any()


def test_mismatch_by_index_or_colour_and_its_unmasked_share() -> None:
    a = np.array([[1, 2], [3, 4]], dtype=np.uint8)
    b = np.array([[1, 9], [3, 9]], dtype=np.uint8)
    found = index_mismatch(a, b)
    assert found.tolist() == [[False, True], [False, True]]
    rgb = np.zeros((2, 2, 3), dtype=np.uint8)
    other = rgb.copy()
    other[0, 1, 2] = 1
    assert colour_mismatch(rgb, other).tolist() == [[False, True], [False, False]]
    mask = np.array([[False, False], [False, True]])
    assert mismatch_fraction(found, mask) == 1 / 3
    assert mismatch_fraction(found, np.ones((2, 2), dtype=bool)) == 0.0
