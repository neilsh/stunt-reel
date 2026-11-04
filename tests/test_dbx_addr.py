"""Image offsets to runtime addresses and back, the live-byte site check, and patched mapping."""

from __future__ import annotations

import pytest
from dbx.addr import (
    Runtime,
    Unmappable,
    site_matches,
    to_patched,
    to_patched_data,
    vm_paragraph,
)

import dbx_stubs

IMG = dbx_stubs.put(dbx_stubs.image(relocs={0x9102}), 0x9100, bytes.fromhex("1ebfd4158edf"))
RT = Runtime(IMG, load=0x0824, dgroup_paragraph=0xD51, vm=0x824)


def test_vm_paragraph_finds_slot_run() -> None:
    assert vm_paragraph(IMG) == 0x824
    with pytest.raises(ValueError, match="slot"):
        vm_paragraph(dbx_stubs.image(slots=99))


def test_slot_run() -> None:
    assert RT.slot_run == range(0x8240, 0x8240 + 9 * 108)
    assert RT.slot_run.stop == 0x860C


def test_code_site_auto() -> None:
    assert RT.code_site(0x9100) == (0x1048, 0x0EC0)
    assert RT.code_site(0x2350) == (0x0824, 0x2350)
    assert RT.code_site(0x9100, "module") == (0x0824, 0x9100)


def test_to_image_round_trip() -> None:
    assert RT.to_image(0x1048, 0x0EC0) == 0x9100
    assert RT.to_image(0x0824, 0x2350) == 0x2350
    assert RT.to_image(0x2AAA, 0xEE94) is None


def test_ds() -> None:
    assert RT.ds == 0x1575
    assert RT.end == 0x8240 + 0xA000


def test_site_matches_masks_relocs() -> None:
    assert site_matches(IMG, 0x9100, bytes.fromhex("1ebff81d8edf"))
    assert not site_matches(IMG, 0x9100, bytes.fromhex("1ebff81d8ede"))


def test_to_patched_aligned() -> None:
    p = dbx_stubs.pairing(code={0x9100: 0x83F7}, functions=[(0x9100, 0x9120, 1.0)])
    assert to_patched(p, 0x9100) == 0x83F7


@pytest.mark.parametrize(
    ("pairing", "offset", "reason"),
    [
        (dbx_stubs.pairing(code={0x9100: 0x83F7}, functions=[(0x9100, 0x9120, 0.9)]), 0x9100, "0.9"),
        (dbx_stubs.pairing(code={0x9100: 0x83F7}, functions=[(0x9100, 0x9120, 1.0)]), 0x9104, "estimated"),
        (dbx_stubs.pairing(), 0x9100, "unmapped"),
    ],
)  # fmt: skip
def test_to_patched_refuses(pairing: object, offset: int, reason: str) -> None:
    with pytest.raises(Unmappable, match=reason):
        to_patched(pairing, offset)  # type: ignore[arg-type]


def test_to_patched_data() -> None:
    p = dbx_stubs.pairing(data={0x49EC: 0x4372})
    assert to_patched_data(p, 0x49EC) == 0x4372
    with pytest.raises(Unmappable, match="unmapped"):
        to_patched_data(p, 0x0100)
