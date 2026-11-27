"""The object shift test finds an object drawn away from the capture's, and not a whole-frame shift."""

from __future__ import annotations

import numpy as np

from stunt_reel.bench.mismatch import object_shift, shift_gain

H, W = 60, 80
REACH = 24


def _plane(top: int, left: int) -> np.ndarray:
    plane = np.zeros((H, W), dtype=np.uint8)
    plane[top : top + 8, left : left + 10] = 7
    plane[top + 2 : top + 5, left + 3 : left + 6] = 9
    return plane


def _block(top: int, left: int) -> np.ndarray:
    block = np.zeros((H, W), dtype=bool)
    block[top : top + 8, left : left + 10] = True
    return block


def test_a_block_moved_by_five_and_minus_three_is_found() -> None:
    render = _plane(20, 30)
    capture = _plane(20 - 3, 30 + 5)
    dx, dy, gain = object_shift(capture, render, _block(20, 30), np.zeros((H, W), bool), REACH)
    assert (dx, dy) == (5, -3)
    assert gain > 0.7


def test_an_unmoved_block_gains_nothing() -> None:
    plane = _plane(20, 30)
    assert object_shift(plane, plane, _block(20, 30), np.zeros((H, W), bool), REACH) == (0, 0, 0.0)


def test_masked_and_empty_pixels_count_for_nothing() -> None:
    render, capture = _plane(20, 30), _plane(17, 35)
    assert object_shift(capture, render, np.zeros((H, W), bool), np.zeros((H, W), bool), REACH) == (
        0,
        0,
        0.0,
    )
    assert object_shift(capture, render, _block(20, 30), np.ones((H, W), bool), REACH) == (
        0,
        0,
        0.0,
    )


def test_a_whole_frame_shift_shows_in_the_terrain_at_the_blocks_shift() -> None:
    rng = np.random.default_rng(3)
    terrain = rng.integers(1, 6, size=(H + 20, W + 20), dtype=np.uint8)
    render = terrain[10 : 10 + H, 10 : 10 + W].copy()
    capture = terrain[10 + 3 : 10 + 3 + H, 10 - 5 : 10 - 5 + W].copy()  # render shifted by (5, -3)
    none = np.zeros((H, W), bool)
    dx, dy, gain = object_shift(capture, render, _block(20, 30), none, REACH)
    assert (dx, dy) == (5, -3)
    assert gain > 0.25
    assert shift_gain(capture, render, np.ones((H, W), bool), none, dx, dy) >= 0.10


def test_an_object_alone_moved_leaves_the_terrain_unmoved_at_its_shift() -> None:
    rng = np.random.default_rng(4)
    render = rng.integers(1, 6, size=(H, W), dtype=np.uint8)
    render[20:28, 30:40] = 9
    capture = render.copy()
    capture[17:25, 35:45] = 9
    capture[20:28, 30:35] = rng.integers(1, 6, size=(8, 5), dtype=np.uint8)
    none = np.zeros((H, W), bool)
    dx, dy, gain = object_shift(capture, render, render == 9, none, REACH)
    assert (dx, dy) == (5, -3)
    assert gain > 0.25
    terrain = np.ones((H, W), bool)
    terrain[17:28, 30:45] = False
    assert shift_gain(capture, render, terrain, none, dx, dy) < 0.10


def test_a_shift_that_leaves_most_of_the_object_out_of_frame_is_skipped() -> None:
    render = np.zeros((H, W), dtype=np.uint8)
    capture = np.zeros((H, W), dtype=np.uint8)
    render[:, W - 10 :] = 7  # an object at the right edge
    capture[:, W - 2 :] = 7  # only 2 of its 10 columns land in frame at d = (8, 0), all matching
    pixels = render == 7
    none = np.zeros((H, W), bool)
    assert shift_gain(capture, render, pixels, none, 8, 0) > 0.7
    assert object_shift(capture, render, pixels, none, 8)[2] < 0.7
