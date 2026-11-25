"""The `.SOD` schema reads the synthetic collision fixture's lists as the Rust decode does."""

from __future__ import annotations

import importlib
import io
from pathlib import Path
from typing import Any

import pytest

from conftest import COMPILED_SCHEMAS_GROUP, CompiledSchemas

pytestmark = [pytest.mark.docs, pytest.mark.xdist_group(COMPILED_SCHEMAS_GROUP)]

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "tests/fixtures/synthetic_collision.sod"
_KAITAISTRUCT: Any = importlib.import_module("kaitaistruct")


@pytest.fixture(scope="module")
def sod_parser(compiled_schemas: CompiledSchemas) -> Any:
    """Return the `.SOD` root type from the session's one catalog compilation."""
    return compiled_schemas.modules["sod"].Sod


def _kinds(collision_list: Any) -> list[int]:
    return [int(record.kind) for record in collision_list.records]


def test_collision_lists_follow_the_header_and_nested_pointers(sod_parser: Any) -> None:
    data = FIXTURE.read_bytes()
    root = sod_parser(_KAITAISTRUCT.KaitaiStream(io.BytesIO(data)))

    assert root._io.pos() == len(data)
    assert int(root.collision_meta) == 0x0E
    top = root.collision
    assert _kinds(top) == [0, 2, 2, 4, 0xFFFF]

    cube, top_box, bucket_box, plane = (record.body for record in top.records[:4])
    assert [int(v) for v in cube.centre] == [0, -8, 0]
    assert int(cube.half_size) == 16
    assert (int(top_box.y_min), int(top_box.y_max), int(top_box.code)) == (-10, -2, 8)
    assert int(bucket_box.code) == 3
    assert [int(v) for v in plane.normal] == [32767, 0, 0]
    assert int(plane.distance) == 4
    assert plane.nested_list is None

    nested = cube.nested_list
    assert _kinds(nested) == [2, 2, 0xFFFF]
    assert int(nested.records[0].body.code) == 0
    named = nested.records[1].body
    assert int(named.code) == 0x6A
    assert _kinds(named.nested_list) == [2, 0xFFFF]
    assert int(named.nested_list.records[0].body.code) == 1
