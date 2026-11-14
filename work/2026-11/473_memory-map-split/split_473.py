"""One-off for #473: split research/playone-exe/memory-map.md by segment and relink it.

Kept beside plan.md as the record of how the split was made (plan.md, Task 1). It writes the
four new memory-map files, trims memory-map.md to its index and section 1, and rewrites each
inbound link and the anchor registry; ``mise run fix`` then regenerates research/MAP.md.

Usage, once, from the repository root:
``mise exec -- uv run python work/2026-11/473_memory-map-split/split_473.py``.
Exits non-zero, having written nothing, when memory-map.md is not the blob the plan was cut
from or any expected text is missing or found a different number of times.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
DIR = "research/playone-exe"
SRC = ROOT / DIR / "memory-map.md"
EXPECTED_BLOB = "f60aa453e72dd8f6776c0a700fcf04cd610a912a"

D1 = "memory-map.md#1-dgroup-memory-reference-table"
P3 = "memory-map-patch3.md#11-patch-3-build"
RT2 = "memory-map-runtime.md#2-runtime-dynamic-capture-anchors"
VS = "memory-map-runtime.md#-mem-vsync-03da"
VM3 = "memory-map-vm.md#3-sod-display-list-vm-work-segment--mem-sod-vm"
PAL = "memory-map-main.md#-mem-palette"

PART_OF = (
    "Part of the `PLAYONE.EXE` memory map: [`memory-map.md`](memory-map.md) lists its files and "
    "states the conventions every table uses (target binary, image base, linear address). "
    "Section numbers run across the files.\n\n"
)


def fail(message: str) -> None:
    sys.exit(f"split_473: {message}; nothing written")


def sub(text: str, old: str, new: str, count: int, where: str) -> str:
    found = text.count(old)
    if found != count:
        fail(f"{where}: expected {count} of {old!r}, found {found}")
    return text.replace(old, new)


def header(summary: str, title: str) -> str:
    if len(summary) > 200:
        fail(f"summary over 200 characters: {summary!r}")
    return f'---\nsummary: "{summary}"\n---\n# {title}\n\n'


blob = subprocess.run(
    ["git", "hash-object", str(SRC)], capture_output=True, text=True, check=True
).stdout.strip()
if blob != EXPECTED_BLOB:
    fail(f"memory-map.md is blob {blob}, not {EXPECTED_BLOB}: it changed after the plan")
lines = SRC.read_text(encoding="utf-8").splitlines(keepends=True)
if len(lines) != 309:
    fail(f"memory-map.md has {len(lines)} lines, not 309")


def take(first: int, last: int) -> str:
    """Lines first..last of the original, 1-based and inclusive."""
    return "".join(lines[first - 1 : last])


# --- memory-map.md: index, conventions and section 1 (DGROUP) ---------------------------------
INDEX = (
    "**The memory map is split by segment; this file lists its files, states the conventions "
    "below, and holds the `DGROUP` table (§ 1).** Other notes keep subject tables of their own, "
    "such as the file-name strings in [`startup.md` § 4](startup.md#4-primary-asset-dependencies). "
    "The evidence behind a row (disassembly, live samples, provenance) lives in "
    "[`research/playone-exe/`](./) and is linked from the row; it is not restated here. Tier "
    "names come from the enum owned by "
    "[`python/scripts/verify_formats_docs.py`](../../python/scripts/verify_formats_docs.py) "
    "(`EVIDENTIARY_TIERS`) and defined in "
    "[`SPEC.md` § 2.4](../../docs/SPEC.md#24-evidentiary-tiers--contract-anchor-system).\n\n"
    "| File | Holds | Anchors defined |\n"
    "|---|---|---|\n"
    "| [`memory-map.md`](memory-map.md) | § 1: `DGROUP` (`DS`) offsets of the unpatched build | |\n"
    "| [`memory-map-patch3.md`](memory-map-patch3.md) | § 1.1: Patch #3 counterparts of the "
    "rows of the other files, with the unmapped ones marked | |\n"
    "| [`memory-map-runtime.md`](memory-map-runtime.md) | § 2: runtime capture anchors | "
    "`[MEM-VSYNC-03DA]`, `[MEM-FLM-TICK]`, `[MEM-CAMERA-RIG]`, `[MEM-ACTOR-TABLE]` |\n"
    "| [`memory-map-vm.md`](memory-map-vm.md) | § 3: the SOD display-list VM's work segment and "
    "its code anchors | `[MEM-SOD-VM]`, `[MEM-SOD-ANCHOR-TABLE]` |\n"
    "| [`memory-map-main.md`](memory-map-main.md) | `DS` data and code of the main program and "
    "the resident mixer: film "
    "state and variables, palette, view setup, light, matrix and draw routines | "
    "`[MEM-FLM-VARS]`, `[MEM-PALETTE]` |\n\n"
    "`[MEM-UNPACK-LOCKOUT]` is defined in "
    "[`memory.md` § 3.4](memory.md#34-lzexe-unpack-lockout--mem-unpack-lockout); "
    "[`doc_anchors.py`](../../python/stunt_reel/doc_anchors.py) names each anchor's home.\n\n"
)
dgroup = take(15, 57)
dgroup = sub(dgroup, "(see § 2)", f"(see [§ 2]({RT2}))", 3, "memory-map.md")
memory_map = (
    header(
        "Index of the `PLAYONE.EXE` memory-map files and the conventions they share, with the "
        "`DGROUP` offset table of the unpatched build: strings, flags, clocks, view and slot state.",
        "Runtime Memory Map & Real-Mode Offsets",
    )
    + INDEX
    + take(8, 14)
    + dgroup
)

# --- memory-map-patch3.md: section 1.1 ----------------------------------------------------------
patch3 = take(59, 148)
w = "memory-map-patch3.md"
patch3 = sub(patch3, "### 1.1 Patch #3 build\n", "## 1.1 Patch #3 build\n", 1, w)
patch3 = sub(
    patch3,
    "Every row in this file is for the unpatched",
    "Every row of the other memory-map files is for the unpatched",
    1,
    w,
)
patch3 = sub(
    patch3,
    "every row of § 1, § 3 and `[MEM-PALETTE]` on both builds",
    f"every row of [§ 1]({D1}), [§ 3]({VM3}) and [`[MEM-PALETTE]`]({PAL}) on both builds",
    1,
    w,
)
patch3 = sub(patch3, "(§ 2)", f"([§ 2]({RT2}))", 3, w)
patch3 = sub(patch3, "So the § 3 table holds", f"So the [§ 3]({VM3}) table holds", 1, w)
patch3 = sub(
    patch3,
    "trap conflict of § 2 is unaffected",
    f"trap conflict of [§ 2]({VS}) is unaffected",
    1,
    w,
)
patch3 = sub(patch3, "instructions cited in § 1 |", f"instructions cited in [§ 1]({D1}) |", 1, w)
patch3 = sub(patch3, "The relocation rule of § 1 (", f"The relocation rule of [§ 1]({D1}) (", 1, w)
patch3 = (
    header(
        "Patch #3 `PLAYONE.EXE` counterparts of the memory-map rows, unmapped ones marked: moved "
        "`DGROUP` offsets, the unchanged work segment, and code addresses, paired function by "
        "function.",
        "Memory Map: Patch #3 Build",
    )
    + PART_OF
    + patch3
)

# --- memory-map-runtime.md: section 2 -----------------------------------------------------------
runtime = take(152, 200)
runtime = sub(runtime, "; rows in § 1.", f"; rows in [§ 1]({D1}).", 1, "memory-map-runtime.md")
runtime = (
    header(
        "`PLAYONE.EXE` runtime capture anchors: the per-frame retrace trap, the 50 Hz tick and film "
        "clock, and the unverified camera-rig and actor-table layouts.",
        "Memory Map: Runtime Capture Anchors",
    )
    + PART_OF
    + runtime
)

# --- memory-map-vm.md: section 3 and 3.1 --------------------------------------------------------
vm = take(204, 259)
w = "memory-map-vm.md"
vm = sub(
    vm,
    "its code addresses are in [§ 1.1](#11-patch-3-build).",
    f"its code addresses are in [§ 1.1]({P3}).",
    1,
    w,
)
vm = sub(vm, "differs on Patch #3 (§ 1.1),", f"differs on Patch #3 ([§ 1.1]({P3})),", 1, w)
vm = (
    header(
        "Offsets in the work segment of `PLAYONE.EXE`'s SOD display-list VM: anchor table, sine "
        "table, vertex arena, view matrices, lens and bank words, shadow mode, and VM code anchors.",
        "Memory Map: SOD VM Work Segment",
    )
    + PART_OF
    + vm
)

# --- memory-map-main.md: [MEM-FLM-VARS] and [MEM-PALETTE] ---------------------------------------
main = take(261, 309)
w = "memory-map-main.md"
main = sub(main, "### # [MEM-FLM-VARS]\n", "## # [MEM-FLM-VARS]\n", 1, w)
main = sub(main, "### # [MEM-PALETTE]\n", "## # [MEM-PALETTE]\n", 1, w)
main = sub(
    main, "Patch #3 offsets: [§ 1.1](#11-patch-3-build).", f"Patch #3 offsets: [§ 1.1]({P3}).", 1, w
)
main = (
    header(
        "`DS` data and code offsets of `PLAYONE.EXE`'s main program and resident mixer: film "
        "variables and state, palette build and DAC upload, view setup, world light, matrix and "
        "draw routines.",
        "Memory Map: Main Program and Resident Mixer",
    )
    + PART_OF
    + main
)

# --- Inbound links and the anchor registry: (path, old, new, count), applied in order ----------
R = "../research/playone-exe/"
EDITS: list[tuple[str, str, str, int]] = [
    # docs/ARCHITECTURE.md
    (
        "docs/ARCHITECTURE.md",
        f"{R}memory-map.md#-mem-vsync-03da",
        f"{R}memory-map-runtime.md#-mem-vsync-03da",
        5,
    ),
    (
        "docs/ARCHITECTURE.md",
        f"{R}memory-map.md#-mem-flm-tick",
        f"{R}memory-map-runtime.md#-mem-flm-tick",
        5,
    ),
    (
        "docs/ARCHITECTURE.md",
        f"{R}memory-map.md#3-sod-display-list-vm-work-segment--mem-sod-vm",
        f"{R}memory-map-vm.md#3-sod-display-list-vm-work-segment--mem-sod-vm",
        3,
    ),
    (
        "docs/ARCHITECTURE.md",
        f"{R}memory-map.md#31-anchor-table-cache--mem-sod-anchor-table",
        f"{R}memory-map-vm.md#31-anchor-table-cache--mem-sod-anchor-table",
        2,
    ),
    (
        "docs/ARCHITECTURE.md",
        f"{R}memory-map.md#-mem-palette",
        f"{R}memory-map-main.md#-mem-palette",
        1,
    ),
    (
        "docs/ARCHITECTURE.md",
        f"[`memory-map.md` § 1.1]({R}memory-map.md#11-patch-3-build)",
        f"[`memory-map-patch3.md` § 1.1]({R}memory-map-patch3.md#11-patch-3-build)",
        1,
    ),
    # docs/SPEC.md
    (
        "docs/SPEC.md",
        "[`research/playone-exe/memory-map.md`](../research/playone-exe/memory-map.md) (evidence:",
        "[`research/playone-exe/memory-map.md`](../research/playone-exe/memory-map.md) and the "
        "segment files it lists (evidence:",
        1,
    ),
    # AGENTS.md
    (
        "AGENTS.md",
        "| `DGROUP` offsets and `[MEM-*]` anchors. |",
        "| `DGROUP` offsets, and the list of segment files that define the `[MEM-*]` anchors. |",
        1,
    ),
    # research/README.md
    (
        "research/README.md",
        "New offsets also update the tables in [`memory-map.md`](playone-exe/memory-map.md) "
        "(`# [MEM-*]` anchors);",
        "New offsets also update their segment's table in the memory-map files that "
        "[`memory-map.md`](playone-exe/memory-map.md) lists (`# [MEM-*]` anchors);",
        1,
    ),
    # Skills
    (
        ".agents/skills/distilling-notes/SKILL.md",
        "An offset registry (`research/playone-exe/memory-map.md`) is split by segment, not distilled.",
        "An offset registry (`research/playone-exe/memory-map*.md`) is split by segment, not distilled.",
        1,
    ),
    (
        ".agents/skills/distilling-notes/routine.md",
        "research/playone-exe/memory-map.md, which is split by segment, not distilled.",
        "research/playone-exe/memory-map*.md, which are split by segment, not distilled.",
        1,
    ),
    # research/formats/
    (
        "research/formats/auxiliary/anchorpt.md",
        "([`memory-map.md`](../../playone-exe/memory-map.md) `# [MEM-SOD-ANCHOR-TABLE]`)",
        "([`memory-map-vm.md`](../../playone-exe/memory-map-vm.md#31-anchor-table-cache--mem-sod-anchor-table)"
        " `# [MEM-SOD-ANCHOR-TABLE]`)",
        1,
    ),
    (
        "research/formats/concepts/timeline-and-ticks.md",
        "[`MEMORY_MAP.md` `# [MEM-FLM-TICK]`](../../playone-exe/memory-map.md#-mem-flm-tick)",
        "[`memory-map-runtime.md` `# [MEM-FLM-TICK]`](../../playone-exe/memory-map-runtime.md#-mem-flm-tick)",
        1,
    ),
    (
        "research/formats/memory/actor_record.ksy",
        "[MEM-ACTOR-TABLE] in research/playone-exe/memory-map.md.",
        "[MEM-ACTOR-TABLE] in research/playone-exe/memory-map-runtime.md.",
        1,
    ),
    (
        "research/formats/memory/actor_record.ksy",
        "`research/playone-exe/memory-map.md`.",
        "`research/playone-exe/memory-map-runtime.md`.",
        1,
    ),
    # research/playone-exe/
    (
        f"{DIR}/angle-bank.md",
        "[`memory-map.md`](memory-map.md#3-sod-display-list-vm-work-segment--mem-sod-vm) § 3",
        "[`memory-map-vm.md`](memory-map-vm.md#3-sod-display-list-vm-work-segment--mem-sod-vm) § 3",
        1,
    ),
    (
        f"{DIR}/angle-bank.md",
        "](memory-map.md#3-sod-display-list-vm-work-segment--mem-sod-vm)",
        "](memory-map-vm.md#3-sod-display-list-vm-work-segment--mem-sod-vm)",
        6,
    ),
    (
        f"{DIR}/capture.md",
        "[`MEMORY_MAP.md`](memory-map.md#-mem-vsync-03da)",
        "[`memory-map-runtime.md`](memory-map-runtime.md#-mem-vsync-03da)",
        1,
    ),
    (
        f"{DIR}/capture-dosbox-automation.md",
        "deserves a [`memory-map.md`](memory-map.md) entry",
        "deserves a [`memory-map-vm.md`](memory-map-vm.md) entry",
        1,
    ),
    (
        f"{DIR}/lod.md",
        "[`memory-map.md`](memory-map.md) section 1.1",
        "[`memory-map-patch3.md`](memory-map-patch3.md) section 1.1",
        1,
    ),
    (
        f"{DIR}/memory.md",
        "Every `DGROUP` offset, struct layout and `# [MEM-*]` anchor lives in "
        "[`research/playone-exe/memory-map.md`](memory-map.md);",
        "Every `DGROUP` offset and struct layout, and every `# [MEM-*]` anchor but "
        "`[MEM-UNPACK-LOCKOUT]` (§ 3.4), lives in the memory-map files that "
        "[`research/playone-exe/memory-map.md`](memory-map.md) lists;",
        1,
    ),
    (
        f"{DIR}/memory.md",
        "[`MEMORY_MAP.md` `# [MEM-VSYNC-03DA]`](memory-map.md#-mem-vsync-03da)",
        "[`memory-map-runtime.md` `# [MEM-VSYNC-03DA]`](memory-map-runtime.md#-mem-vsync-03da)",
        1,
    ),
    (
        f"{DIR}/memory.md",
        "[`MEMORY_MAP.md`](memory-map.md#-mem-flm-tick)",
        "[`memory-map-runtime.md`](memory-map-runtime.md#-mem-flm-tick)",
        1,
    ),
    (
        f"{DIR}/memory.md",
        "[`MEMORY_MAP.md`](memory-map.md#-mem-camera-rig)",
        "[`memory-map-runtime.md`](memory-map-runtime.md#-mem-camera-rig)",
        1,
    ),
    (
        f"{DIR}/patch3.md",
        "[`memory-map.md` § 1.1](memory-map.md#11-patch-3-build)",
        "[`memory-map-patch3.md` § 1.1](memory-map-patch3.md#11-patch-3-build)",
        2,
    ),
    (
        f"{DIR}/patch3.md",
        "([`memory-map.md`](memory-map.md) `[MEM-PALETTE]`)",
        "([`memory-map-main.md`](memory-map-main.md#-mem-palette) `[MEM-PALETTE]`)",
        1,
    ),
    (
        f"{DIR}/sod-vm.md",
        "[`memory-map.md`](memory-map.md) `0x808A`",
        "[`memory-map-vm.md`](memory-map-vm.md) `0x808A`",
        1,
    ),
    (
        f"{DIR}/sod-vm.md",
        "shifted right by `0x810C` ([`memory-map.md`](memory-map.md))",
        "shifted right by `0x810C` ([`memory-map-vm.md`](memory-map-vm.md))",
        1,
    ),
    (
        f"{DIR}/sod-vm.md",
        "[`memory-map.md`](memory-map.md) listed `0x806C`",
        "[`memory-map-vm.md`](memory-map-vm.md) listed `0x806C`",
        1,
    ),
    (
        f"{DIR}/sod-vm.md",
        "(roll, pitch, yaw, [`memory-map.md`](memory-map.md))",
        "(roll, pitch, yaw, [`memory-map-main.md`](memory-map-main.md))",
        1,
    ),
    (
        f"{DIR}/patch3.md",
        "It maps every row of [`memory-map.md`](memory-map.md), not only",
        "It maps every row of the [memory-map files](memory-map.md), not only",
        1,
    ),
    (
        f"{DIR}/memory.md",
        "The structures themselves are specified in [`MEMORY_MAP.md`](memory-map.md).",
        "The structures themselves are specified in "
        "[`memory-map-runtime.md`](memory-map-runtime.md).",
        1,
    ),
    (
        f"{DIR}/sod-vm.md",
        "[`memory-map.md`](memory-map.md) `0x8725`, `0x884A`",
        "[`memory-map-main.md`](memory-map-main.md) `0x8725`, `0x884A`",
        1,
    ),
    (
        f"{DIR}/static-tooling.md",
        "work segment to `0x14BF` ([`memory-map.md`](memory-map.md))",
        "work segment to `0x14BF` ([`memory-map-patch3.md`](memory-map-patch3.md))",
        1,
    ),
    (
        f"{DIR}/terrain-shade.md",
        "four direct references per word, [`memory-map.md`](memory-map.md),",
        "four direct references per word, [`memory-map-patch3.md`](memory-map-patch3.md),",
        1,
    ),
    (
        f"{DIR}/world-scene.md",
        "the anchor table in [`memory-map.md`](memory-map.md) section 3",
        "the anchor table in [`memory-map-vm.md`](memory-map-vm.md) section 3",
        1,
    ),
    # Code
    (
        "python/scripts/pair_builds.py",
        "``research/playone-exe/memory-map.md`` section 1.1",
        "``research/playone-exe/memory-map-patch3.md`` section 1.1",
        1,
    ),
    (
        "python/stunt_reel/doc_anchors.py",
        'MEMORY_MAP = "research/playone-exe/memory-map.md"\n',
        'MEMORY_MAP_RUNTIME = "research/playone-exe/memory-map-runtime.md"\n'
        'MEMORY_MAP_VM = "research/playone-exe/memory-map-vm.md"\n'
        'MEMORY_MAP_MAIN = "research/playone-exe/memory-map-main.md"\n',
        1,
    ),
    (
        "python/stunt_reel/doc_anchors.py",
        "# --- Runtime memory anchors: defined in the memory map (plus one evidence note) ---",
        "# --- Runtime memory anchors: defined in the memory-map files (plus one evidence note) ---",
        1,
    ),
    (
        "python/stunt_reel/doc_anchors.py",
        '"MEM-VSYNC-03DA", MEMORY_MAP,',
        '"MEM-VSYNC-03DA", MEMORY_MAP_RUNTIME,',
        1,
    ),
    (
        "python/stunt_reel/doc_anchors.py",
        '"MEM-FLM-TICK", MEMORY_MAP,',
        '"MEM-FLM-TICK", MEMORY_MAP_RUNTIME,',
        1,
    ),
    (
        "python/stunt_reel/doc_anchors.py",
        '"MEM-FLM-VARS", MEMORY_MAP,',
        '"MEM-FLM-VARS", MEMORY_MAP_MAIN,',
        1,
    ),
    (
        "python/stunt_reel/doc_anchors.py",
        '"MEM-PALETTE", MEMORY_MAP,',
        '"MEM-PALETTE", MEMORY_MAP_MAIN,',
        1,
    ),
    (
        "python/stunt_reel/doc_anchors.py",
        '"MEM-CAMERA-RIG", MEMORY_MAP,',
        '"MEM-CAMERA-RIG", MEMORY_MAP_RUNTIME,',
        1,
    ),
    (
        "python/stunt_reel/doc_anchors.py",
        '"MEM-ACTOR-TABLE", MEMORY_MAP,',
        '"MEM-ACTOR-TABLE", MEMORY_MAP_RUNTIME,',
        1,
    ),
    (
        "python/stunt_reel/doc_anchors.py",
        '"MEM-SOD-VM",\n        MEMORY_MAP,',
        '"MEM-SOD-VM",\n        MEMORY_MAP_VM,',
        1,
    ),
    (
        "python/stunt_reel/doc_anchors.py",
        '"MEM-SOD-ANCHOR-TABLE",\n        MEMORY_MAP,',
        '"MEM-SOD-ANCHOR-TABLE",\n        MEMORY_MAP_VM,',
        1,
    ),
]

# Compute every edit before writing anything, so a mismatch leaves the tree untouched.
edited: dict[str, str] = {}
for path, old, new, count in EDITS:
    text = edited.get(path)
    if text is None:
        text = (ROOT / path).read_text(encoding="utf-8")
    edited[path] = sub(text, old, new, count, path)

outputs = {
    f"{DIR}/memory-map.md": memory_map,
    f"{DIR}/memory-map-patch3.md": patch3,
    f"{DIR}/memory-map-runtime.md": runtime,
    f"{DIR}/memory-map-vm.md": vm,
    f"{DIR}/memory-map-main.md": main,
    **edited,
}
for path, text in outputs.items():
    (ROOT / path).write_bytes(text.encode("utf-8"))
for name in (
    "memory-map.md",
    "memory-map-patch3.md",
    "memory-map-runtime.md",
    "memory-map-vm.md",
    "memory-map-main.md",
):
    size = len((ROOT / DIR / name).read_bytes())
    print(f"{DIR}/{name}: {size} bytes{'  OVER 20480' if size > 20480 else ''}")
print(f"split_473: wrote {len(outputs)} files")
