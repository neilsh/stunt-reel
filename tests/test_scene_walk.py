"""``mise run scene-walk``: extents from shape headers, the frame listing and the walk's report."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest
import scene_walk

from stunt_reel import scene_tree
from stunt_reel.all_archive import pack_archive

TREE = (Path(__file__).parent / "fixtures" / "synthetic_walk_tree.bin").read_bytes()


def _sod(bounding: int, scale: int) -> bytes:
    """A shape header: ``OP_ID``, ``bounding_size``, a ground offset, ``scale_index``, flags."""
    return struct.pack("<HHhBB", 0x000C, bounding, 0, scale, 0) + b"\x00" * 4


FRAME = json.dumps(
    {
        "tick": 871,
        "eye": [0.0, 0.0, 0.0],
        "target": [0.0, 0.0, 100.0],
        "slots": [
            {
                "slot": 4,
                "shape": 0x0107,
                "position": [150.0, 0.0, 0.0],
                "view": False,
                "shadow": False,
            },
            {"slot": 5, "shape": 0x0000, "position": [0.0, 0.0, 0.0], "view": True, "shadow": True},
        ],
    }
)


def _sample(_flm: Path, tick: float) -> str:
    assert tick == 871
    return FRAME


def test_extent_is_the_bounding_size_shifted_down_plus_one() -> None:
    assert scene_walk.sod_extent(_sod(0x4000, 0x0A)) == 17
    assert scene_walk.sod_extent(_sod(0x0010, 0x12)) == 1  # a shift of 16 or more clears it
    with pytest.raises(ValueError, match="no header"):
        scene_walk.sod_extent(b"\x0c\x00")


def test_an_earlier_archive_wins_a_shared_shape_and_non_shapes_are_skipped() -> None:
    own = pack_archive([(0x0107, _sod(0x4000, 0x0A)), (0xC000, b"\x04")])
    stock = pack_archive([(0x0107, _sod(0x0010, 0x00)), (0x0262, _sod(0x0040, 0x02))])
    assert scene_walk.shape_extents([own, stock]) == {0x0107: 17, 0x0262: 17}


def test_the_listing_shows_each_slot_with_its_extent() -> None:
    frame = scene_walk.parse_frame(FRAME, {0x0107: 17})
    assert scene_walk.frame_lines(frame) == [
        "tick 871",
        "eye (0.00, 0.00, 0.00)  target (0.00, 0.00, 100.00)",
        "slot  4 shape 0x0107 at (150.00, 0.00, 0.00) extent 17",
        "slot  5 shape 0x0000 at (0.00, 0.00, 0.00) extent ? view shadow",
    ]


def test_run_walks_the_chosen_slot_through_the_tree(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    image = tmp_path / "playone.img"
    image.write_bytes(bytes(scene_tree.TREE_IMAGE_OFFSET) + TREE)
    archive = tmp_path / "S.ALL"
    archive.write_bytes(pack_archive([(0x0107, _sod(0x4000, 0x0A))]))
    args = scene_walk.parse_args(
        [
            *(str(tmp_path / "X.FLM"), "--tick", "871", "--slot", "4"),
            *("--image", str(image), "--archive", str(archive), "--context", "1"),
        ]
    )
    assert scene_walk.run(args, sample=_sample) == 0
    out = capsys.readouterr().out
    assert "slot  4 shape 0x0107 at (150.00, 0.00, 0.00) extent 17" in out
    assert "the entry reaches leaf 0x005C" in out
    assert "SP_XPLANE 0x000A at 100: greater side (whole)" in out
    assert "SP_1NODE 0x0040: object 0x0D00 at (10, 0, 20), taken as near" in out
    assert "draw order, 5 steps; the slot is step 2:" in out
    assert "    2> slot at (150, 0, 0), leaf 0x005C" in out


def test_run_without_a_slot_lists_the_frame_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "S.ALL"
    archive.write_bytes(pack_archive([(0x0262, _sod(0x0040, 0x02))]))
    args = scene_walk.parse_args(
        [str(tmp_path / "X.FLM"), "--tick", "871", "--archive", str(archive)]
    )
    assert scene_walk.run(args, sample=_sample) == 0
    assert "reaches" not in capsys.readouterr().out


def test_run_reports_a_slot_that_is_not_drawn_and_a_shape_no_archive_holds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    archive = tmp_path / "S.ALL"
    archive.write_bytes(pack_archive([(0x0262, _sod(0x0040, 0x02))]))
    base = [str(tmp_path / "X.FLM"), "--tick", "871", "--archive", str(archive)]
    assert scene_walk.run(scene_walk.parse_args([*base, "--slot", "9"]), _sample) == 1
    assert "slot 9 is not drawn" in capsys.readouterr().err
    assert scene_walk.run(scene_walk.parse_args([*base, "--slot", "4"]), _sample) == 1
    assert "no archive holds shape 0x0107" in capsys.readouterr().err
