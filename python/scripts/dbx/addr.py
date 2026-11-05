"""Where an image offset runs, for either PLAYONE build, and how a plan offset maps to Patch #3.

Image offset `x` sits at linear `load * 16 + x`. Code runs with `CS = load + p`, where `p` is the
code segment holding it: the image's code paragraphs (the targets of its relocated far calls and
jumps, `LoadImage.code_paragraphs`) plus `vm`, the paragraph of the build's dispatch-slot run
(`research/playone-exe/world-scene.md` section 4), where the display-list handlers live.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from build_pairing import (
    ALIGNED,
    SLOT_BYTES,
    LoadImage,
    Pairing,
    dispatch_slots,
    map_code,
    map_data,
)

#: Fewer consecutive slots than this is not the VM's slot run (each build has 108).
MIN_SLOTS: int = 100

CodeSegment = Literal["auto", "module", "vm"]


class Unmappable(ValueError):  # noqa: N818 - reads as the condition
    """An unpatched offset has no trustworthy Patch #3 counterpart."""


class SiteMismatch(ValueError):  # noqa: N818
    """The live bytes at a probe site are not the image's bytes there."""


def vm_paragraph(image: LoadImage) -> int:
    """The paragraph where the dispatch-slot run starts."""
    for paragraph in range(len(image.data) // 16):
        at = paragraph * 16
        if image.data[at] != 0x26 or at + SLOT_BYTES * MIN_SLOTS > len(image.data):
            continue
        if len(dispatch_slots(image, paragraph)) >= MIN_SLOTS:
            return paragraph
    msg = f"no run of {MIN_SLOTS} dispatch slots in the image"
    raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class Runtime:
    """One build's image as loaded: its load paragraph, DGROUP and VM paragraphs."""

    image: LoadImage
    load: int
    dgroup_paragraph: int
    vm: int

    @property
    def ds(self) -> int:
        """The runtime `DS`."""
        return self.load + self.dgroup_paragraph

    @property
    def end(self) -> int:
        """The linear address just past the image."""
        return self.load * 16 + len(self.image.data)

    @property
    def slot_run(self) -> range:
        """Image offsets of the dispatch-slot run, whose writes patch the display list."""
        start = self.vm * 16
        return range(start, start + SLOT_BYTES * len(dispatch_slots(self.image, self.vm)))

    @property
    def code_paragraphs(self) -> list[int]:
        """The image paragraphs code segments start at, the VM's included."""
        return sorted({0, self.vm, *self.image.code_paragraphs()})

    def code_site(self, offset: int, cs: CodeSegment = "auto") -> tuple[int, int]:
        """The `seg:off` image *offset* runs at: `auto` takes the nearest code segment below it."""
        if not 0 <= offset < len(self.image.data):
            msg = f"image offset {offset:#x} is outside the {len(self.image.data):#x}-byte image"
            raise ValueError(msg)
        if cs == "auto":
            paragraph = max(p for p in self.code_paragraphs if p * 16 <= offset)
        else:
            paragraph = self.vm if cs == "vm" else 0
        seg = self.load + paragraph
        off = offset - paragraph * 16
        if not 0 <= off <= 0xFFFF:
            msg = f"image offset {offset:#x} is not addressable from CS={seg:04X}"
            raise ValueError(msg)
        return seg, off

    def to_image(self, seg: int, off: int) -> int | None:
        """The image offset of `seg:off`, or None outside the image."""
        offset = seg * 16 + off - self.load * 16
        return offset if 0 <= offset < len(self.image.data) else None


def site_matches(image: LoadImage, offset: int, live: bytes) -> bool:
    """Whether *live* equals the image at *offset*, ignoring relocated words (they hold segments)."""
    expected = image.data[offset : offset + len(live)]
    if len(expected) != len(live):
        return False
    masked = {
        at - offset for r in image.relocs for at in (r, r + 1) if offset <= at < offset + len(live)
    }
    return all(i in masked or a == b for i, (a, b) in enumerate(zip(live, expected, strict=True)))


def to_patch3(pairing: Pairing, offset: int) -> int:
    """The Patch #3 image offset of unpatched code *offset*, from an identical function only."""
    mapping = map_code(pairing, offset)
    pair = pairing.function_at(offset)
    ratio = pair[2] if pair is not None else None
    if mapping.how != ALIGNED or mapping.mapped is None or ratio != 1.0:
        msg = f"code {offset:#x} does not map to Patch #3: {mapping.how}, function ratio {ratio}"
        raise Unmappable(msg)
    return mapping.mapped


def to_patch3_data(pairing: Pairing, offset: int) -> int:
    """The Patch #3 DS offset of unpatched DS *offset*."""
    mapping = map_data(pairing, offset)
    if mapping.mapped is None:
        msg = f"DS:{offset:#06x} does not map to Patch #3: {mapping.how}"
        raise Unmappable(msg)
    return mapping.mapped
