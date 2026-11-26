"""Flip `.SET` prop-record bytes, print each variant with the retail `TYPESET.EXE`, and diff.

Each variant changes one byte or bit of one prop record; the report lists, per variant, the dump
lines that differ from the unflipped set's dump, ignoring the `File Name` and `Printed at` lines.
``report.csv`` records which printed values changed, layout changes, and missing dumps.
All variants print in one ``dosbox-x -silent`` session, which returns once the guest exits.
Exits 1 when DOSBox-X fails or any dump is missing.
Reads a proprietary set and executable from the data root. The default output directory is the
worktree's gitignored ``build/typeset-flip/`` (``AGENTS.md``). Each run replaces ``<out>/stage``.
Keep the input set and executable outside that staging directory.

Usage: ``mise run typeset-flip -- [--set S] [--slots 1,3,10] [--offsets 0x18,0x22-0x27]
[--bits 0x02:0,0x03:1] [--out DIR]``.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from dbx.boot import dosbox_x_exe

from stunt_reel.dataroot import corpus_root, data_root

REPO = Path(__file__).resolve().parents[2]
HEADER = 0x54
EVENT_SIZE = 67
PROP_SIZE = 64
NUM_EVENTS_AT = 0x53

#: `[BK-SET-02]`'s unknown bytes and bits (`research/formats/auxiliary/set.md` § 3.1).
DEFAULT_OFFSETS = "0x18-0x19,0x22-0x27,0x2C-0x2F,0x31-0x33,0x35-0x3D"
DEFAULT_BITS = "0x02:0,0x03:1,0x03:3,0x03:4,0x34:7"
#: BOMBING.SET's Spot prop (slot 1), Free prop in a recording slot (3) and Free prop in slot 10.
DEFAULT_SLOTS = "1,3,10"


@dataclass(frozen=True)
class Variant:
    """One flipped copy of the set: *name* is its 8.3 stem."""

    name: str
    slot: int
    offset: int
    old: int
    new: int
    data: bytes


def prop_records(data: bytes) -> dict[int, int]:
    """Map each stored prop slot to its record's file offset."""
    start = HEADER + EVENT_SIZE * data[NUM_EVENTS_AT]
    return {
        data[at] | data[at + 1] << 8: at
        for at in range(start, len(data) - PROP_SIZE + 1, PROP_SIZE)
    }


def parse_offsets(spec: str) -> list[int]:
    """``0x18,0x22-0x24`` → ``[0x18, 0x22, 0x23, 0x24]``."""
    out: list[int] = []
    for part in filter(None, spec.split(",")):
        lo, _, hi = part.partition("-")
        out.extend(range(int(lo, 0), int(hi or lo, 0) + 1))
    return out


def parse_bits(spec: str) -> list[tuple[int, int]]:
    """``0x02:0,0x34:7`` → ``[(0x02, 0), (0x34, 7)]``."""
    return [
        (int(off, 0), int(bit, 0))
        for off, _, bit in (p.partition(":") for p in filter(None, spec.split(",")))
    ]


def variants(
    data: bytes, slots: list[int], offsets: list[int], bits: list[tuple[int, int]]
) -> list[Variant]:
    """Each single-bit flip and the 0x00 and 0xFF fills of *offsets*, plus each of *bits*."""
    records = prop_records(data)
    out: list[Variant] = []

    def add(slot: int, rel: int, new: int) -> None:
        at = records[slot] + rel
        old = data[at]
        if new == old or any(v.slot == slot and v.offset == rel and v.new == new for v in out):
            return
        flipped = bytearray(data)
        flipped[at] = new
        out.append(Variant(f"V{len(out):04d}", slot, rel, old, new, bytes(flipped)))

    for slot in slots:
        for rel in offsets:
            old = data[records[slot] + rel]
            for bit in range(8):
                add(slot, rel, old ^ 1 << bit)
            add(slot, rel, 0x00)
            add(slot, rel, 0xFF)
        for rel, bit in bits:
            add(slot, rel, data[records[slot] + rel] ^ 1 << bit)
    return out


def _lines(dump: str) -> list[str]:
    return [
        line.rstrip()
        for line in dump.splitlines()
        if not line.startswith(("Printed at", "File Name"))
    ]


def dump_diff(base: str, other: str) -> list[str]:
    """Changed lines of *other* against *base*, each prefixed by the base section it falls in."""
    a, b = _lines(base), _lines(other)
    section = ["(header)"] * len(a)
    current = "(header)"
    for i, line in enumerate(a):
        if line.startswith(("Prop #", "Event#")):
            current = line.split("\t")[0].strip()
        section[i] = current
    out: list[str] = []
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        where = section[min(i1, len(a) - 1)] if a else "(header)"
        out.extend(f"{where}: - {line}" for line in a[i1:i2])
        out.extend(f"{where}: + {line}" for line in b[j1:j2])
    return out


def _fields(line: str) -> dict[str, str]:
    """``Roll  :0\tRoll Anim :18`` → ``{"Roll": "0", "Roll Anim": "18"}``."""
    out: dict[str, str] = {}
    for part in filter(None, line.split("\t")):
        label, _, value = part.partition(":")
        out[label.strip()] = value.strip()
    return out


def summarize(diff: list[str]) -> str:
    """``Label: old->new`` per changed printed value, ``none``, or ``layout`` when lines differ."""
    if not diff:
        return "none"
    minus = [d.split(": - ", 1)[1] for d in diff if ": - " in d]
    plus = [d.split(": + ", 1)[1] for d in diff if ": + " in d]
    changes: list[str] = []
    for a, b in zip(minus, plus, strict=False):
        fa, fb = _fields(a), _fields(b)
        if len(minus) != len(plus) or fa.keys() != fb.keys():
            return "layout"
        changes.extend(f"{k}: {fa[k]}->{fb[k]}" for k in fa if fa[k] != fb[k])
    return "; ".join(changes) if changes else "layout"


def run_typeset(stage: Path, names: list[str], timeout: float) -> None:
    """Print each ``<name>.SET`` in *stage* to ``<name>.TXT`` in one silent DOSBox-X session."""
    bat = "@echo off\r\n" + "".join(f"typeset {n}.set > {n}.txt\r\n" for n in names)
    (stage / "RUN.BAT").write_bytes(bat.encode("ascii"))
    conf = (
        "[sdl]\noutput = surface\n[cpu]\ncore = dynamic\ncycles = max\n"
        f'[dosbox]\nmemsize = 16\n[autoexec]\n@echo off\nmount c "{stage.as_posix()}"\nc:\n'
    )
    (stage / "flip.conf").write_text(conf, encoding="ascii")
    subprocess.run(  # noqa: S603 - fixed argv
        [
            str(dosbox_x_exe()),
            "-silent",
            "-conf",
            str(stage / "flip.conf"),
            "-c",
            "run.bat",
            "-c",
            "exit",
        ],
        check=True,
        capture_output=True,
        timeout=timeout,
    )


def main(argv: list[str] | None = None) -> int:
    """Run the flip sweep; write ``report.json``, ``report.txt`` and ``report.csv`` under ``--out``."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--set", type=Path, default=corpus_root() / "siarchive/Misc/Sets/BOMBING.SET")
    ap.add_argument("--typeset", type=Path, default=data_root() / "builds/patch3/TYPESET.EXE")
    ap.add_argument("--slots", default=DEFAULT_SLOTS, help="0-based prop slots to flip")
    ap.add_argument("--offsets", default=DEFAULT_OFFSETS, help="record offsets, each byte flipped")
    ap.add_argument("--bits", default=DEFAULT_BITS, help="offset:bit pairs, each bit flipped")
    ap.add_argument("--out", type=Path, default=REPO / "build/typeset-flip")
    ap.add_argument("--timeout", type=float, default=600.0)
    args = ap.parse_args(argv)

    data = args.set.read_bytes()
    slots = [int(s, 0) for s in args.slots.split(",")]
    found = prop_records(data)
    missing = [s for s in slots if s not in found]
    if missing:
        print(f"slots {missing} are not stored; stored: {sorted(found)}", file=sys.stderr)
        return 2
    vs = variants(data, slots, parse_offsets(args.offsets), parse_bits(args.bits))
    stage = args.out / "stage"
    resolved_stage = stage.resolve()
    if resolved_stage != args.out.resolve() / "stage":
        print(f"stage must be a directory under --out: {stage}", file=sys.stderr)
        return 2
    for source in (args.set, args.typeset):
        if source.resolve().is_relative_to(resolved_stage):
            print(f"input is inside the staging directory: {source}", file=sys.stderr)
            return 2
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    (stage / "TYPESET.EXE").write_bytes(args.typeset.read_bytes())
    (stage / "BASE.SET").write_bytes(data)
    for v in vs:
        (stage / f"{v.name}.SET").write_bytes(v.data)
    try:
        run_typeset(stage, ["BASE", *(v.name for v in vs)], args.timeout)
    except subprocess.CalledProcessError as e:
        print(f"DOSBox-X exited {e.returncode}", file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        print(f"DOSBox-X did not exit within {args.timeout:g} s", file=sys.stderr)
        return 1

    def dump(name: str) -> str | None:
        path = stage / f"{name}.TXT"
        return path.read_text(encoding="latin-1") if path.is_file() else None

    base = dump("BASE")
    if base is None:
        print("TYPESET printed no base dump", file=sys.stderr)
        return 1
    diffs: list[tuple[Variant, list[str]]] = []
    for v in vs:
        text = dump(v.name)
        diffs.append((v, ["(no dump)"] if text is None else dump_diff(base, text)))
    rows = [
        {
            "variant": v.name,
            "slot": v.slot,
            "prop": v.slot + 1,
            "offset": f"0x{v.offset:02X}",
            "old": f"0x{v.old:02X}",
            "new": f"0x{v.new:02X}",
            "diff": diff,
        }
        for v, diff in diffs
    ]
    (args.out / "report.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    with (args.out / "report.txt").open("w", encoding="utf-8") as fh:
        for v, diff in diffs:
            change = "; ".join(diff) or "no printed change"
            fh.write(f"slot {v.slot} 0x{v.offset:02X} 0x{v.old:02X}->0x{v.new:02X}: {change}\n")
    with (args.out / "report.csv").open("w", encoding="utf-8", newline="") as fh:
        out = csv.writer(fh, lineterminator="\n")
        out.writerow(["slot", "offset", "old", "new", "printed_change"])
        for v, diff in diffs:
            change = "no dump" if diff == ["(no dump)"] else summarize(diff)
            out.writerow([v.slot, f"0x{v.offset:02X}", f"0x{v.old:02X}", f"0x{v.new:02X}", change])
    missing_dumps = sum(1 for _, diff in diffs if diff == ["(no dump)"])
    changed = sum(1 for _, diff in diffs if diff and diff != ["(no dump)"])
    print(
        f"{len(rows)} variants, {changed} with a printed change, {missing_dumps} with no dump: "
        f"{args.out / 'report.txt'}"
    )
    return 1 if missing_dumps else 0


if __name__ == "__main__":
    raise SystemExit(main())
