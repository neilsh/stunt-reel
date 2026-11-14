"""Create and name PLAYONE.EXE's .SOD display-list handlers in Ghidra headless.

The display-list VM dispatches an opcode through a 9-byte slot at image `0x8240` in the
unpatched build, or `0x7540` in Patch #3: `26 C7 44 FE imm16` followed by `E9 rel16`, where
`imm16` plus the slot run's image offset is the handler (`research/playone-exe/sod-vm.md`
section 1). This driver unpacks the executable, reads that run, writes the slot list, and runs
Ghidra's `analyzeHeadless` on `tools/ghidra/SodDispatchTable.java`, which creates a function at
each handler and names it from `research/formats/sod-opcodes.md`. Ghidra saves the project under
`build/re/ghidra/` when the session ends.

The slot count comes from the run itself, never a constant: 108 in the unpatched executable and
107 in Patch #3 (issue #480). Above opcode `0x0333` the two builds' opcode words dispatch
different handlers (`research/playone-exe/patch3.md` section 4.1), so a handler is named for the
slot index it pairs with in the 107-name table; the unpatched build's slot 92, which Patch #3
drops, is named `OP_033C_UNPATCHED_ONLY`.

Usage::

    mise run ghidra-sod-table
    mise run ghidra-sod-table -- --build patch3
    mise run ghidra-sod-table -- --parse-only
    mise run ghidra-sod-table -- --exe PATH/PLAYONE.EXE [--ghidra-install-dir DIR]

`--build patch3` reads `<data root>/builds/patch3/PLAYONE.EXE`, which `mise run game-builds`
writes. `--parse-only` reads and prints the table without Ghidra. Exit status: 0 on success;
1 when the Ghidra run fails; 2 when the executable, the slot run or `analyzeHeadless` cannot be
read or found.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path

import unlzexe

from stunt_reel import dataroot, game_builds

REPO = Path(__file__).resolve().parents[2]
#: The opcode table the handlers are named from.
OPCODE_TABLE = REPO / "research" / "formats" / "sod-opcodes.md"
#: The Ghidra post-script, and the directory `analyzeHeadless -scriptPath` finds it in.
POST_SCRIPT = "SodDispatchTable.java"
SCRIPT_DIR = REPO / "tools" / "ghidra"
#: The default project location; `build/` is gitignored.
PROJECT_DIR = REPO / "build" / "re" / "ghidra"

#: One dispatch slot: the six-byte self-patch and the near jump after it.
SLOT_BYTES = 9
SLOT_PREFIX = bytes.fromhex("26c744fe")
#: Fewer consecutive slots than this is not the VM's run (`python/scripts/dbx/addr.py`).
MIN_SLOTS = 100
#: The slot Patch #3 drops, so the unpatched build has one more than the name table has rows.
UNPATCHED_ONLY_INDEX = 92
UNPATCHED_ONLY_NAME = "OP_033C_UNPATCHED_ONLY"
#: A name table row: `| **N** | 0xNNNN | N*9 | OP_NAME | ...`.
NAME_ROW = re.compile(r"^\| \*\*(\d+)\*\* \| `(0x[0-9A-F]{4})` \| \d+ \| `(OP_[A-Z0-9]+)`")


@dataclass(frozen=True, slots=True)
class Slot:
    """One dispatch slot and the handler its self-patch word names."""

    index: int
    image: int
    opcode: int
    imm16: int
    handler: int
    name: str | None


@dataclass(frozen=True, slots=True)
class SlotTable:
    """A build's dispatch-slot run, in opcode order, with the function names to give it."""

    image: int
    slots: tuple[Slot, ...]


def read_names(path: Path = OPCODE_TABLE) -> tuple[str, ...]:
    """The opcode mnemonics in table order; raise ValueError if they are not `9 * index`."""
    rows = [
        (int(match.group(1)), int(match.group(2), 16), match.group(3))
        for line in path.read_text(encoding="utf-8").splitlines()
        if (match := NAME_ROW.match(line)) is not None
    ]
    if [index for index, _, _ in rows] != list(range(len(rows))):
        raise ValueError(f"{path}: the opcode table's Index column is not 0..N-1")
    for index, opcode, _ in rows:
        if opcode != SLOT_BYTES * index:
            raise ValueError(f"{path}: opcode {opcode:#06x} is not {SLOT_BYTES} x index {index}")
    return tuple(name for _, _, name in rows)


def handler_name(index: int, count: int, names: tuple[str, ...]) -> str | None:
    """The function name for slot *index* of a *count*-slot build, or None past the table.

    The build with one slot more than the table is the unpatched executable: Patch #3 drops
    slot 92, and every later slot names the handler it pairs with
    (`research/playone-exe/patch3.md` section 4.1, issue #480).
    """
    if len(names) == 107 and count == 108:
        if index == UNPATCHED_ONLY_INDEX:
            return UNPATCHED_ONLY_NAME
        return names[index] if index < UNPATCHED_ONLY_INDEX else names[index - 1]
    return names[index] if 0 <= index < len(names) else None


def _slot_run(data: bytes, table: int) -> int:
    """How many whole slots follow *table* before the pattern breaks."""
    count = 0
    while True:
        at = table + count * SLOT_BYTES
        if at + SLOT_BYTES > len(data) or data[at : at + 4] != SLOT_PREFIX:
            return count
        if data[at + 6] != 0xE9:
            return count
        count += 1


def find_slot_table(data: bytes) -> int:
    """The image offset of the first run of at least MIN_SLOTS dispatch slots."""
    for at in range(len(data) - MIN_SLOTS * SLOT_BYTES + 1):
        if (
            data[at : at + 4] == SLOT_PREFIX
            and data[at + 6] == 0xE9
            and _slot_run(data, at) >= MIN_SLOTS
        ):
            return at
    raise ValueError(f"no run of {MIN_SLOTS} display-list dispatch slots")


def _parse_slots(data: bytes, table: int) -> tuple[Slot, ...]:
    """The run at *table*, checking each self-patch word against its near jump."""
    slots: list[Slot] = []
    at = table
    while (
        at + SLOT_BYTES <= len(data) and data[at : at + 4] == SLOT_PREFIX and data[at + 6] == 0xE9
    ):
        imm16 = int.from_bytes(data[at + 4 : at + 6], "little")
        rel16 = int.from_bytes(data[at + 7 : at + 9], "little", signed=True)
        handler = table + imm16
        jumped = table + ((at - table + SLOT_BYTES + rel16) & 0xFFFF)
        if jumped != handler:
            raise ValueError(
                f"slot {len(slots)} at image {at:#06x}: the self-patch word names "
                f"{handler:#06x}, the jump names {jumped:#06x}"
            )
        slots.append(Slot(len(slots), at, SLOT_BYTES * len(slots), imm16, handler, None))
        at += SLOT_BYTES
    return tuple(slots)


def parse_slot_table(data: bytes, names: tuple[str, ...] | None = None) -> SlotTable:
    """The dispatch-slot run in *data*, each handler named from *names* (default: the table)."""
    table = find_slot_table(data)
    slots = _parse_slots(data, table)
    source = read_names() if names is None else names
    return SlotTable(
        table,
        tuple(replace(slot, name=handler_name(slot.index, len(slots), source)) for slot in slots),
    )


def slot_lines(table: SlotTable, build: str) -> list[str]:
    """The slot file the post-script reads: a header naming the build, table and count, then rows."""
    lines = [
        f"# ghidra-sod-dispatch build={build} table=0x{table.image:X} slots={len(table.slots)}",
        "# index\topcode\thandler\tname",
    ]
    lines.extend(
        f"{slot.index}\t0x{slot.opcode:04X}\t0x{slot.handler:04X}\t{slot.name or ''}"
        for slot in table.slots
    )
    return lines


def _build_exe(build: str, explicit: Path | None) -> Path:
    """The PLAYONE.EXE for *build*, or *explicit* when given."""
    if explicit is not None:
        return explicit
    if build == "patch3":
        builds = dataroot.data_root() / game_builds.BUILDS_DIR
        return game_builds.build_tree(builds, "patch3") / "PLAYONE.EXE"
    return unlzexe.default_exe()


def _analyze_headless(install_dir: Path | None) -> Path | None:
    """`analyzeHeadless` from *install_dir*, `GHIDRA_INSTALL_DIR` or PATH, if it is there."""
    names = (
        ("analyzeHeadless.bat", "analyzeHeadless")
        if sys.platform == "win32"
        else ("analyzeHeadless",)
    )
    roots = [install_dir] if install_dir is not None else []
    env = os.environ.get("GHIDRA_INSTALL_DIR")
    if env:
        roots.append(Path(env))
    for root in roots:
        for name in names:
            candidate = root / "support" / name
            if candidate.is_file():
                return candidate
    for name in names:
        found = shutil.which(name)
        if found is not None:
            return Path(found)
    return None


def _command(
    launcher: Path, project_dir: Path, project_name: str, mz: Path, slots: Path
) -> list[str]:
    """The `analyzeHeadless` argv; headless saves the project because neither -readOnly nor
    -deleteProject is passed."""
    command = [
        str(launcher),
        str(project_dir),
        project_name,
        "-import",
        str(mz),
        "-overwrite",
        "-scriptPath",
        str(SCRIPT_DIR),
        "-postScript",
        POST_SCRIPT,
        str(slots),
        "-log",
        str(project_dir / "analyze.log"),
        "-scriptlog",
        str(project_dir / "script.log"),
    ]
    if launcher.suffix.lower() in {".bat", ".cmd"}:
        return [os.environ.get("COMSPEC", "cmd.exe"), "/c", *command]
    return command


def _run_ghidra(launcher: Path, project_dir: Path, project_name: str, mz: Path, slots: Path) -> int:
    """Import *mz*, run the post-script and report what it named; 0 on success."""
    project_dir.mkdir(parents=True, exist_ok=True)
    command = _command(launcher, project_dir, project_name, mz, slots)
    print(f"[ghidra-sod-table] {' '.join(command)}")
    try:
        done = subprocess.run(command, check=False)  # noqa: S603 - resolved launcher, fixed argv
    except OSError as error:
        print(f"[ghidra-sod-table] could not start analyzeHeadless: {error}", file=sys.stderr)
        return 1
    if done.returncode != 0:
        print(
            f"[ghidra-sod-table] analyzeHeadless failed with {done.returncode}; "
            f"see {project_dir / 'analyze.log'}",
            file=sys.stderr,
        )
        return 1
    script_log = project_dir / "script.log"
    if script_log.is_file():
        for line in script_log.read_text(encoding="utf-8", errors="replace").splitlines():
            if "ghidra-sod-table:" in line:
                print(line)
    print(f"[ghidra-sod-table] project {project_name} at {project_dir}, saved by Ghidra")
    return 0


def _summary(table: SlotTable, build: str) -> list[str]:
    """The lines printed before the Ghidra run: the table, its count and what is not named."""
    last = table.slots[-1]
    named = sum(1 for slot in table.slots if slot.name is not None)
    lines = [
        (
            f"[ghidra-sod-table] {build}: {len(table.slots)} slots at image 0x{table.image:X} "
            f"(opcodes 0x0000..0x{last.opcode:04X}), {named} named"
        ),
    ]
    for slot in table.slots:
        if slot.name == UNPATCHED_ONLY_NAME:
            lines.append(
                f"[ghidra-sod-table]   slot {slot.index} (opcode 0x{slot.opcode:04X}) is the one "
                f"Patch #3 drops: {UNPATCHED_ONLY_NAME}"
            )
    unnamed = sum(1 for slot in table.slots if slot.name is None)
    if unnamed:
        lines.append(f"[ghidra-sod-table]   {unnamed} slot(s) past the opcode table stay unnamed")
    return lines


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse the command line."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--build", choices=game_builds.BUILD_NAMES, default="unpatched")
    parser.add_argument("--exe", type=Path, help="PLAYONE.EXE to read (default: the build's)")
    parser.add_argument(
        "--parse-only",
        action="store_true",
        help="read and print the slot table, then stop before Ghidra",
    )
    parser.add_argument(
        "--ghidra-install-dir",
        type=Path,
        help="Ghidra installation with support/analyzeHeadless (default: PATH or GHIDRA_INSTALL_DIR)",
    )
    parser.add_argument(
        "--project-dir", type=Path, default=PROJECT_DIR, help=f"default {PROJECT_DIR}"
    )
    parser.add_argument(
        "--project-name", help="default PLAYONE, or PLAYONE_patch3 for --build patch3"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Read the build's table and run the post-script; see the module docstring for exit codes."""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    exe = _build_exe(args.build, args.exe)
    try:
        image, meta = unlzexe.unpack(exe.read_bytes())
    except (OSError, ValueError) as error:
        print(f"[ghidra-sod-table] {exe}: {error}", file=sys.stderr)
        return 2
    payload = bytes(image)
    try:
        table = parse_slot_table(payload)
    except (OSError, ValueError) as error:
        print(f"[ghidra-sod-table] {error}", file=sys.stderr)
        return 2
    for line in _summary(table, args.build):
        print(line)
    project_dir: Path = args.project_dir
    inputs = project_dir / "input"
    try:
        inputs.mkdir(parents=True, exist_ok=True)
        mz = inputs / f"playone-{args.build}-unpacked.exe"
        mz.write_bytes(unlzexe.to_mz(payload, meta))
        slots = inputs / f"playone-{args.build}-slots.tsv"
        slots.write_text("\n".join(slot_lines(table, args.build)) + "\n", encoding="utf-8")
    except OSError as error:
        print(f"[ghidra-sod-table] {project_dir}: {error}", file=sys.stderr)
        return 2
    print(f"[ghidra-sod-table] wrote {mz} and {slots}")
    if args.parse_only:
        return 0
    launcher = _analyze_headless(args.ghidra_install_dir)
    if launcher is None:
        print(
            "[ghidra-sod-table] analyzeHeadless is not on PATH or in GHIDRA_INSTALL_DIR; "
            "the table parsed but no project was written",
            file=sys.stderr,
        )
        print(
            "[ghidra-sod-table] set GHIDRA_INSTALL_DIR to a Ghidra 12.1.x install "
            "(research/playone-exe/static-tooling.md section 4), or pass --ghidra-install-dir",
            file=sys.stderr,
        )
        return 2
    project_name = args.project_name or (
        "PLAYONE" if args.build == "unpatched" else f"PLAYONE_{args.build}"
    )
    return _run_ghidra(launcher, project_dir, project_name, mz, slots)


if __name__ == "__main__":
    raise SystemExit(main())
