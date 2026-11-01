"""Render faults are planted in memory, from the planes of a source."""

from __future__ import annotations

import numpy as np

from pytest_helpers import MemorySource
from stunt_reel.bench.faults import ALL_FAULTS, Fault, plant
from stunt_reel.bench.planes import RenderPlanes

H, W = 200, 320


def planes(value: int = 0, *, idx_value: int | None = 0, layer_value: int = 2) -> RenderPlanes:
    rgb = np.full((H, W, 3), value, dtype=np.uint8)
    idx = None if idx_value is None else np.full((H, W), idx_value, dtype=np.uint8)
    layer = np.full((H, W), layer_value, dtype=np.uint16)
    return RenderPlanes(rgb=rgb, idx=idx, layer=layer)


def test_fault_keys_and_order() -> None:
    keys = [fault.key for fault in ALL_FAULTS]
    assert keys == [
        "none",
        "actors_removed",
        "shift_x:1",
        "shift_x:2",
        "shift_x:4",
        "shift_x:8",
        "shift_y:1",
        "shift_y:2",
        "shift_y:4",
        "advance:1",
        "advance:3",
        "advance:5",
        "flat_terrain",
        "flicker:3",
        "flicker:10",
        "wrong_tick",
        "grey",
    ]


def test_none_returns_the_source_planes() -> None:
    base = planes(5)
    assert plant(Fault("none", None), 0, MemorySource({0: base}), 1) is base


def test_actor_pixels_take_their_left_neighbour() -> None:
    base = planes()
    base.idx[0, :4] = [5, 7, 7, 9]  # type: ignore[index]
    base.layer[0, :4] = [2, 16, 20, 2]
    base.layer[1, :4] = [16, 2, 2, 2]
    base.idx[1, :4] = [7, 1, 1, 1]  # type: ignore[index]
    base.rgb[0, :4, 0] = [5, 7, 7, 9]
    out = plant(Fault("actors_removed", None), 0, MemorySource({0: base}), 1)
    assert out is not None
    assert out.idx is not None
    assert out.idx[0, :4].tolist() == [5, 5, 5, 9]
    assert out.rgb[0, :4, 0].tolist() == [5, 5, 5, 9]
    assert out.layer[0, :4].tolist() == [2, 2, 2, 2]
    assert out.idx[1, 0] == 7
    assert out.layer[1, 0] == 16
    assert base.layer[0, 1] == 16  # the source is not mutated


def test_shift_x_repeats_the_first_column() -> None:
    base = planes()
    base.idx[0, :5] = [1, 2, 3, 4, 5]  # type: ignore[index]
    out = plant(Fault("shift_x", 2), 0, MemorySource({0: base}), 1)
    assert out is not None
    assert out.idx is not None
    assert out.idx[0, :5].tolist() == [1, 1, 1, 2, 3]
    assert out.layer.shape == (H, W)


def test_shift_y_repeats_the_first_row() -> None:
    base = planes()
    for row in range(3):
        base.rgb[row, :, 0] = row + 1
    out = plant(Fault("shift_y", 1), 0, MemorySource({0: base}), 1)
    assert out is not None
    assert out.rgb[:3, 0, 0].tolist() == [1, 1, 2]


def test_advance_takes_a_later_tick() -> None:
    source = MemorySource({0: planes(1), 2: planes(9)})
    out = plant(Fault("advance", 2), 0, source, 1)
    assert out is not None
    assert out.rgb[0, 0, 0] == 9


def test_advance_past_the_end_is_none() -> None:
    source = MemorySource({0: planes(1), 2: planes(9)})
    assert plant(Fault("advance", 1), 0, source, 1) is None
    assert plant(Fault("advance", 3), 2, source, 1) is None


def test_flat_terrain_flattens_layer_two() -> None:
    base = planes(0)
    base.rgb[0, 0] = [10, 20, 30]
    base.rgb[0, 1] = [11, 20, 30]
    base.idx[0, 0] = 4  # type: ignore[index]
    base.idx[0, 1] = 4  # type: ignore[index]
    base.layer[1:, :] = 3
    base.rgb[1:, :] = 99
    base.layer[0, 2:] = 3
    base.rgb[0, 2:] = 99
    out = plant(Fault("flat_terrain", None), 0, MemorySource({0: base}), 1)
    assert out is not None
    assert out.idx is not None
    assert out.rgb[0, 0].tolist() == [10, 20, 30] or out.rgb[0, 0].tolist() == [11, 20, 30]
    assert out.rgb[0, 0].tolist() == out.rgb[0, 1].tolist()
    assert out.rgb[5, 5, 0] == 99
    assert out.idx[0, 0] == 4


def test_flat_terrain_keeps_an_index_shared_with_another_layer_one_colour() -> None:
    # Terrain's most common index (0) is also the sky's, so flattening it in place would give
    # index 0 two colours; the flat terrain moves to an index only terrain uses instead.
    base = planes(50, idx_value=0, layer_value=2)
    base.layer[:10, :] = 0
    base.rgb[:10, :] = 200
    base.idx[100, :5] = 7  # type: ignore[index]
    base.rgb[100, :5] = 60
    out = plant(Fault("flat_terrain", None), 0, MemorySource({0: base}), 1)
    assert out is not None
    assert out.idx is not None
    terrain = out.layer == 2
    assert set(np.unique(out.idx[terrain]).tolist()) == {7}
    assert set(np.unique(out.idx[~terrain]).tolist()) == {0}
    for index in (0, 7):
        assert len(np.unique(out.rgb[out.idx == index], axis=0)) == 1


def test_flat_terrain_takes_a_free_index_when_every_terrain_index_is_shared() -> None:
    base = planes(50, idx_value=0, layer_value=2)
    base.layer[:10, :] = 0
    base.rgb[:10, :] = 200
    base.rgb[100, :5] = 60
    out = plant(Fault("flat_terrain", None), 0, MemorySource({0: base}), 1)
    assert out is not None
    assert out.idx is not None
    assert set(np.unique(out.idx[out.layer == 2]).tolist()) == {1}


def test_flat_terrain_reuses_an_index_already_showing_the_flat_colour() -> None:
    # Every index appears outside terrain, so none is terrain-only or free; index 5's other
    # pixels already show the flat colour (5, 5, 5), so terrain can share it.
    base = planes(5, idx_value=0, layer_value=2)
    base.layer[0, :] = 0
    base.idx[0, :] = np.arange(W) % 256  # type: ignore[index]
    base.rgb[0, :] = (np.arange(W) % 256)[:, None]
    out = plant(Fault("flat_terrain", None), 0, MemorySource({0: base}), 1)
    assert out is not None
    assert out.idx is not None
    assert set(np.unique(out.idx[out.layer == 2]).tolist()) == {5}


def test_flicker_alternates_and_clips() -> None:
    source = MemorySource({4: planes(250), 5: planes(250)})
    even = plant(Fault("flicker", 10), 4, source, 1)
    odd = plant(Fault("flicker", 10), 5, source, 1)
    assert even is not None
    assert odd is not None
    assert even.rgb[0, 0, 0] == 255
    assert odd.rgb[0, 0, 0] == 240
    assert even.idx is not None
    assert even.idx[0, 0] == 0


def _wrong_tick_source() -> MemorySource:
    ticks = {t: planes(t % 256, idx_value=t % 7) for t in range(0, 400, 10)}
    return MemorySource(ticks)


def test_wrong_tick_is_far_and_different_and_repeatable() -> None:
    source = _wrong_tick_source()
    fault = Fault("wrong_tick", None)
    first = plant(fault, 200, source, 7)
    again = plant(fault, 200, source, 7)
    assert first is not None
    assert again is not None
    assert first.idx is not None
    assert first.rgb[0, 0, 0] == again.rgb[0, 0, 0]
    chosen = int(first.rgb[0, 0, 0])
    far = [t for t in source.ticks() if abs(t - 200) >= 100 and t % 256 == chosen]
    assert far
    own = source.load(200).idx
    assert own is not None
    assert (first.idx != own).mean() >= 0.10


def test_wrong_tick_none_without_a_qualifying_tick() -> None:
    source = MemorySource({t: planes(0, idx_value=3) for t in (0, 50, 300)})
    assert plant(Fault("wrong_tick", None), 0, source, 1) is None
    only_near = MemorySource({0: planes(0), 50: planes(0, idx_value=9)})
    assert plant(Fault("wrong_tick", None), 0, only_near, 1) is None
    no_idx = MemorySource({0: planes(0, idx_value=None), 300: planes(0, idx_value=9)})
    assert plant(Fault("wrong_tick", None), 0, no_idx, 1) is None


def test_grey_has_no_index_plane() -> None:
    base = planes(0)
    base.rgb[:, :100] = 255
    out = plant(Fault("grey", None), 0, MemorySource({0: base}), 1)
    assert out is not None
    assert out.idx is None
    assert len(np.unique(out.rgb)) == 1
    assert out.rgb[0, 0, 0] == round(255 * 100 / 320)
