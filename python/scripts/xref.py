"""Find the instructions that reference a string or data offset in a DOS executable.

Usage: ``mise run xref -- <exe|img> (--string TEXT | --offset 0xN) [--ds 0xSEG] [--context N]``

The input is an MZ file, an LZEXE 0.91 one (unpacked first), or a bare load image (which needs
``--ds``). ``--string`` finds the text, case-insensitively, and turns its image offset into an
offset in each candidate data segment: the ``--ds`` given, else every segment the code loads
into ``DS`` (``mov ax,imm``/``mov ds,ax``) or the relocation table names, that the string lies
within. ``--offset`` names a data offset directly. Every 16-bit immediate or displacement equal
to that offset in the code before the data segment is printed with its surrounding
instructions. Addresses are load-image offsets, as in ``research/``.

Lives in ``python/scripts/`` beside ``build_pairing.py`` because it needs iced-x86 (ADR 0033).
"""

from __future__ import annotations

import argparse
import struct
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import unlzexe
from iced_x86 import Decoder, Formatter, FormatterSyntax, Instruction

from stunt_reel.dataroot import read_data_file_or_report

# How far back an instruction start is searched for, and how far back decodes vote on it.
MAX_OPERAND_OFFSET = 6
SYNC_WINDOW = 48


@dataclass
class Image:
    """A load image and the segment values its relocations name."""

    data: bytes
    header: int | None = None
    relocated: Counter[int] = field(default_factory=Counter)


@dataclass
class Reference:
    """One instruction whose 16-bit operand is the target offset, with its neighbours."""

    start: int
    before: list[Instruction]
    instruction: Instruction
    after: list[Instruction]


def load(raw: bytes) -> Image:
    """Return the load image of an MZ, LZEXE 0.91 or bare image file."""
    if raw[:2] != b"MZ":
        return Image(raw)
    if raw[0x1C:0x20] == b"LZ91":
        image, meta = unlzexe.unpack(raw)
        relocs = cast("list[int]", meta["relocs"])
        data, header = bytes(image), None
    else:
        last, pages, count, paragraphs = struct.unpack_from("<4H", raw, 2)
        table = struct.unpack_from("<H", raw, 0x18)[0]
        header = paragraphs * 16
        size = pages * 512 - ((512 - last) if last else 0) - header
        data = raw[header : header + size]
        relocs = []
        for i in range(count):
            off, seg = struct.unpack_from("<2H", raw, table + 4 * i)
            relocs.append(seg * 16 + off)
    relocated: Counter[int] = Counter(
        struct.unpack_from("<H", data, lin)[0] for lin in relocs if lin + 2 <= len(data)
    )
    return Image(data, header, relocated)


def ds_loads(data: bytes) -> Counter[int]:
    """Count the segment values loaded into DS through AX, DX or BX."""
    loads: Counter[int] = Counter()
    for opcode, mov in ((0xB8, b"\x8e\xd8"), (0xBA, b"\x8e\xda"), (0xBB, b"\x8e\xdb")):
        at = data.find(bytes([opcode]))
        while at != -1:
            if data[at + 3 : at + 5] == mov:
                loads[struct.unpack_from("<H", data, at + 1)[0]] += 1
            at = data.find(bytes([opcode]), at + 1)
    return loads


def _decode_one(data: bytes, start: int) -> tuple[Instruction, Decoder]:
    decoder = Decoder(16, data[start : start + 16], ip=start)
    return decoder.decode(), decoder


def _operand_at(data: bytes, start: int, at: int) -> Instruction | None:
    """The instruction at ``start`` if its 16-bit displacement or immediate sits at ``at``."""
    instruction, decoder = _decode_one(data, start)
    if instruction.is_invalid or start + instruction.len < at + 2:
        return None
    offsets = decoder.get_constant_offsets(instruction)
    in_displacement = (
        offsets.has_displacement
        and offsets.displacement_size == 2
        and start + offsets.displacement_offset == at
    )
    in_immediate = (
        offsets.has_immediate
        and offsets.immediate_size == 2
        and start + offsets.immediate_offset == at
    )
    return instruction if in_displacement or in_immediate else None


def _sync_starts(data: bytes, start: int) -> list[int]:
    """The earlier offsets whose straight-line decode lands exactly on ``start``."""
    hits = []
    for begin in range(max(0, start - SYNC_WINDOW), start):
        ip = begin
        for instruction in Decoder(16, data[begin:start], ip=begin):
            if instruction.is_invalid:
                break
            ip = instruction.next_ip
        if ip == start:
            hits.append(begin)
    return hits


def find_references(data: bytes, target: int, code_end: int, context: int) -> list[Reference]:
    """Every instruction before ``code_end`` whose 16-bit operand equals ``target``."""
    word = struct.pack("<H", target)
    refs: list[Reference] = []
    at = data.find(word, 0, code_end)
    while at != -1:
        candidates = [
            (start, instruction)
            for start in range(max(0, at - MAX_OPERAND_OFFSET), at)
            if (instruction := _operand_at(data, start, at)) is not None
        ]
        if candidates:
            votes = {start: _sync_starts(data, start) for start, _ in candidates}
            start, instruction = max(candidates, key=lambda c: (len(votes[c[0]]), -c[0]))
            begin = min(votes[start], default=start)
            before = list(Decoder(16, data[begin:start], ip=begin))[-context:] if context else []
            after: list[Instruction] = []
            for following in Decoder(16, data[instruction.next_ip :], ip=instruction.next_ip):
                if len(after) == context:
                    break
                after.append(following)
            if not refs or refs[-1].start != start:
                refs.append(Reference(start, before, instruction, after))
        at = data.find(word, at + 1, code_end)
    return refs


def candidate_segments(image: Image, linear: int, ds: int | None) -> list[tuple[int, str]]:
    """Data segments that could address ``linear``, most-loaded first, with why each is one."""
    if ds is not None:
        return [(ds, "--ds")]
    loads = ds_loads(image.data)
    found: list[tuple[int, str]] = []
    for seg in set(loads) | set(image.relocated):
        if 0 <= linear - seg * 16 < 0x10000:
            why = f"mov ds x{loads[seg]}, relocated x{image.relocated[seg]}"
            found.append((seg, why))
    found.sort(key=lambda s: (-loads[s[0]], -image.relocated[s[0]], s[0]))
    return found


def _format(formatter: Formatter, instruction: Instruction, mark: str) -> str:
    return f"  {mark} {instruction.ip:05X}  {formatter.format(instruction)}"


def report(
    image: Image,
    targets: list[tuple[str, int | None, int]],
    ds: int | None,
    context: int,
    code_end: int | None,
) -> list[str]:
    """Lines describing each target and the references to it."""
    formatter = Formatter(FormatterSyntax.NASM)
    lines: list[str] = []
    for label, linear, offset in targets:
        segments: list[tuple[int, str]]
        if linear is None:
            if ds is None:
                raise ValueError(f"{label} is a data offset, so it needs a data segment")
            segments = [(ds, "--ds")]
        else:
            file_at = f", file 0x{linear + image.header:X}" if image.header is not None else ""
            lines.append(f"{label} at image 0x{linear:X}{file_at}")
            segments = candidate_segments(image, linear, ds)
            if not segments:
                lines.append("  no segment addresses it; name one with --ds")
        for seg, why in segments:
            at = offset if linear is None else linear - seg * 16
            end = code_end if code_end is not None else seg * 16
            refs = find_references(image.data, at, end, context)
            lines.append(f"DS 0x{seg:04X} ({why}): offset 0x{at:04X}, {len(refs)} reference(s)")
            for ref in refs:
                lines.extend(_format(formatter, i, " ") for i in ref.before)
                lines.append(_format(formatter, ref.instruction, ">"))
                lines.extend(_format(formatter, i, " ") for i in ref.after)
                lines.append("")
    return lines


def _int(text: str) -> int:
    return int(text, 0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("file", type=Path, help="MZ, LZEXE 0.91 or load-image file")
    what = parser.add_mutually_exclusive_group(required=True)
    what.add_argument("--string", help="text to find, case-insensitively")
    what.add_argument("--offset", type=_int, help="data-segment offset (needs --ds)")
    parser.add_argument("--ds", type=_int, help="data segment, as a paragraph")
    parser.add_argument("--context", type=int, default=4, help="instructions shown each side")
    parser.add_argument("--code-end", type=_int, help="search code below this image offset")
    args = parser.parse_args(argv)

    raw = read_data_file_or_report("xref", args.file)
    if raw is None:
        return 2
    image = load(raw)
    targets: list[tuple[str, int | None, int]] = []
    if args.offset is not None:
        if args.ds is None:
            parser.error("--offset needs --ds")
        targets.append((f"DS:0x{args.offset:04X}", None, args.offset))
    else:
        needle = args.string.lower().encode("latin-1")
        haystack = image.data.lower()
        at = haystack.find(needle)
        while at != -1:
            targets.append((repr(args.string), at, 0))
            at = haystack.find(needle, at + 1)
        if not targets:
            print(f"{args.string!r} does not occur in the image")
            return 1
        if image.header is None and not image.relocated and args.ds is None:
            print("note: a bare image has no relocations; only mov-ds loads suggest segments")
    print("\n".join(report(image, targets, args.ds, args.context, args.code_end)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
