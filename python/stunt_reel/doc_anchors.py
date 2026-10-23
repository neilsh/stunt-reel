"""Registry of documentation anchors and the single heading that defines each one.

An anchor is a permanent citation token written ``[FMT-RES-HEADER]``, ``[MEM-FLM-TICK]`` or
``[I4]``. Code, tests and documents cite it; exactly one Markdown heading defines it. This
module is the only place that says which heading, so a rename edits one line here and
``tests/test_doc_invariants.py`` proves every definition and every citation still resolves.

``heading`` is the heading text exactly as it appears in ``file``, without the leading ``#``
marks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Anchor:
    """One citation token and its single home heading."""

    id: str
    file: str
    heading: str

    @property
    def token(self) -> str:
        """The bracketed form used in citations."""
        return f"[{self.id}]"

    @property
    def slug(self) -> str:
        """GitHub-style fragment for linking to the home heading."""
        cleaned = re.sub(r"[^\w\s-]", "", self.heading.strip().lower())
        return cleaned.replace(" ", "-")


SPEC = "docs/SPEC.md"
MEMORY_MAP = "docs/MEMORY_MAP.md"
MEMORY_NOTES = "research/playone-exe/memory.md"

ANCHORS: tuple[Anchor, ...] = (
    # --- System invariants: defined in the specification ---
    Anchor(
        "I1",
        SPEC,
        "[I1] Metric Right-Handed Coordinates, Attribute-Preserving Vertex Welding"
        " & Angle/FOV Normalization",
    ),
    Anchor("I2", SPEC, "[I2] Flat Arena Allocation (No Recursive Pointers)"),
    Anchor("I3", SPEC, "[I3] Authentic VGA Mode 13h Palette Indexing & Flat Shading"),
    Anchor("I4", SPEC, "[I4] Discrete Simulation Ticks & Cut-Aware Sub-Tick Interpolation"),
    Anchor("I5", SPEC, "[I5] Coplanar Decal Resolution"),
    Anchor(
        "I6", SPEC, "[I6] Visual Parity Acceptance Thresholds & VGA 1:1.2 Aspect Ratio Correction"
    ),
    Anchor("I7", SPEC, "[I7] Cleanroom Asset Isolation & Small Pure-Rust Core Dependencies"),
    Anchor("I8", SPEC, "[I8] DOS 8.3 Uppercase Path Normalization"),
    # --- Format anchors: defined in the format document that owns the layout ---
    Anchor(
        "FMT-RES-HEADER",
        "research/formats/res.md",
        "2.1 On-Disk Physical Header & Offset Table Layout (`# [FMT-RES-HEADER]`)",
    ),
    Anchor(
        "FMT-ALL-CHUNKS",
        "research/formats/all.md",
        "2.1 On-Disk Directory Layout (`# [FMT-ALL-CHUNKS]`)",
    ),
    Anchor(
        "FMT-SOD-HEADER",
        "research/formats/sod.md",
        "2.1 10-Byte Header Binary Layout (`# [FMT-SOD-HEADER]`)",
    ),
    Anchor(
        "FMT-SOD-OPCODES",
        "research/formats/sod.md",
        "3.2 The Authoritative 107-Opcode Reference Table (`# [FMT-SOD-OPCODES]`)",
    ),
    Anchor(
        "FMT-SOD-IFVIS",
        "research/formats/sod.md",
        "3.1.6 BSP Sorting & Two-Sided Visibility Logic (`# [FMT-SOD-IFVIS]`)",
    ),
    Anchor(
        "FMT-SOD-TAP",
        "research/formats/sod.md",
        "3.1.4a Terrain Anchor Load (`OP_TAP`, `0x022E`) (`# [FMT-SOD-TAP]`)",
    ),
    Anchor(
        "FMT-SOD-ANIMATE",
        "research/formats/sod.md",
        "3.1.4b Animation Resource Draw (`OP_ANIMATE`, `0x01F8`) (`# [FMT-SOD-ANIMATE]`)",
    ),
    Anchor(
        "FMT-FLM-OPCODES",
        "research/formats/flm.md",
        "3.3 Master Opcode Dispatch Table (`# [FMT-FLM-OPCODES]`)",
    ),
    Anchor(
        "FMT-SET-HEADER",
        "research/formats/auxiliary/set.md",
        "2.1 Global Environment Header (`0x0000`–`0x005F`) (`# [FMT-SET-HEADER]`)",  # noqa: RUF001
    ),
    Anchor(
        "FMT-SPR-HEADER",
        "research/formats/auxiliary/spr.md",
        "2.2 Field Definitions (`# [FMT-SPR-HEADER]`)",
    ),
    Anchor(
        "FMT-SIO-RECORDS",
        "research/formats/auxiliary/sio.md",
        "3.2 Opcode Definitions (`# [FMT-SIO-RECORDS]`)",
    ),
    Anchor(
        "FMT-MAP-ANCHORPT",
        "research/formats/auxiliary/map.md",
        "2.2 `ANCHORPT.DAT` Memory Layout (`# [FMT-MAP-ANCHORPT]`)",
    ),
    Anchor(
        "FMT-MAP-AREA",
        "research/formats/auxiliary/map.md",
        "2.3 `MAP.BIN` Memory Layout (`# [FMT-MAP-AREA]`)",
    ),
    Anchor(
        "FMT-MAP-SCENERY",
        "research/formats/auxiliary/map.md",
        "3.2 `SCENERY.scn` Node Opcode Table (`# [FMT-MAP-SCENERY]`)",
    ),
    # --- Runtime memory anchors: defined in the memory map (plus one evidence note) ---
    Anchor("MEM-VSYNC-03DA", MEMORY_MAP, "# [MEM-VSYNC-03DA]"),
    Anchor("MEM-FLM-TICK", MEMORY_MAP, "# [MEM-FLM-TICK]"),
    Anchor("MEM-FLM-VARS", MEMORY_MAP, "# [MEM-FLM-VARS]"),
    Anchor("MEM-PALETTE", MEMORY_MAP, "# [MEM-PALETTE]"),
    Anchor("MEM-CAMERA-RIG", MEMORY_MAP, "# [MEM-CAMERA-RIG]"),
    Anchor("MEM-ACTOR-TABLE", MEMORY_MAP, "# [MEM-ACTOR-TABLE]"),
    Anchor(
        "MEM-SOD-VM",
        MEMORY_MAP,
        "3. SOD Display-List VM Work Segment (`# [MEM-SOD-VM]`)",
    ),
    Anchor(
        "MEM-SOD-ANCHOR-TABLE",
        MEMORY_MAP,
        "3.1 Anchor Table Cache (`# [MEM-SOD-ANCHOR-TABLE]`)",
    ),
    Anchor(
        "MEM-UNPACK-LOCKOUT",
        MEMORY_NOTES,
        "3.4 LZEXE Unpack Lockout (`# [MEM-UNPACK-LOCKOUT]`)",
    ),
)

BY_ID: dict[str, Anchor] = {anchor.id: anchor for anchor in ANCHORS}

#: Matches a citation of any anchor-shaped token, registered or not.
CITATION_REGEX = re.compile(r"\[((?:FMT|MEM)-[A-Z0-9]+(?:-[A-Z0-9]+)*|I\d+)\]")
