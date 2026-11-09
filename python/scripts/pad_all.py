"""Write a copy of a film's `.ALL` with chunks added, to test what `PLAYONE` does with a bigger archive.

`PLAYONE.EXE` draws some pages of a superset archive differently from the film's own archive
(``research/makeone-exe/linking.md`` section 7.2, issue 348). Two arms separate the superset's
extra shapes from its size:

- ``--add-from SOURCE.ALL`` adds every chunk of SOURCE whose id OWN lacks, such as a superset's
  extra shape chunks.
- ``--inert COUNT BYTES`` adds COUNT chunks of zero bytes, BYTES in all (sizes differ by at most
  one byte), with ids from ``--first-id`` (default ``0xF001``, a `res_index` no game file uses)
  upward, skipping item 0 of each index as `RES\\` files number items from 1.

Chunks are written in ascending id order, as every shipped archive is (``linking.md`` section 3).
Prints the SHA-256 of OWN and OUT and how many chunks and bytes were added. OUT must not exist.

Usage: ``mise run pad-all -- OWN.ALL -o OUT.ALL (--add-from SOURCE.ALL | --inert COUNT BYTES)
[--first-id 0xF001]``
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from stunt_reel.all_archive import ArchiveError, archive_chunks, pack_archive

#: The first id ``--inert`` uses by default: item 1 of `res_index` 0xF0, which no `RES\\` file has.
DEFAULT_FIRST_ID = 0xF001
#: An archive's chunk count is a `u16`.
MAX_CHUNKS = 0xFFFF


class PadError(ValueError):
    """The padding asked for cannot be written."""


def added_from(own: list[tuple[int, bytes]], source: bytes) -> list[tuple[int, bytes]]:
    """The chunks of *source* whose ids *own* lacks, in *source*'s order."""
    present = {chunk_id for chunk_id, _ in own}
    return [
        (chunk_id, payload)
        for chunk_id, payload in archive_chunks(source)
        if chunk_id not in present
    ]


def inert_ids(first: int, count: int, taken: set[int]) -> list[int]:
    """*count* ids from *first* upward, skipping item 0 of each index.

    Raises:
        PadError: an id would pass ``0xFFFF`` or is one of *taken*.
    """
    ids: list[int] = []
    chunk_id = first
    while len(ids) < count:
        if chunk_id > 0xFFFF:
            raise PadError(f"{count} inert ids from {first:#06x} pass 0xFFFF")
        if chunk_id & 0xFF:
            if chunk_id in taken:
                raise PadError(f"inert id {chunk_id:#06x} is already in the archive")
            ids.append(chunk_id)
        chunk_id += 1
    return ids


def inert(first: int, count: int, total: int, taken: set[int]) -> list[tuple[int, bytes]]:
    """*count* zero-filled chunks of *total* bytes in all, the first ``total % count`` a byte longer.

    Raises:
        PadError: *count* is under 1, *total* under *count*, or the ids do not fit.
    """
    if count < 1 or total < count:
        raise PadError(f"--inert needs at least one chunk and a byte each, not {count} and {total}")
    size, longer = divmod(total, count)
    ids = inert_ids(first, count, taken)
    return [(chunk_id, bytes(size + (n < longer))) for n, chunk_id in enumerate(ids)]


def pad(own: bytes, added: list[tuple[int, bytes]]) -> bytes:
    """*own* with *added* chunks, every chunk in ascending id order.

    Raises:
        PadError: the archive would hold more than ``0xFFFF`` chunks.
    """
    chunks = archive_chunks(own) + added
    if len(chunks) > MAX_CHUNKS:
        raise PadError(f"{len(chunks)} chunks; an archive holds at most {MAX_CHUNKS}")
    return pack_archive(sorted(chunks, key=lambda chunk: chunk[0]))


def _refuse(message: str) -> int:
    print(f"pad-all: {message}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    """Write the padded archive; 0 when written, 2 when refused."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("own", type=Path, metavar="OWN.ALL", help="the film's own archive")
    parser.add_argument("-o", "--output", type=Path, required=True, help="archive to write")
    arm = parser.add_mutually_exclusive_group(required=True)
    arm.add_argument(
        "--add-from", type=Path, metavar="SOURCE.ALL", help="add the chunks of SOURCE OWN lacks"
    )
    arm.add_argument(
        "--inert",
        type=int,
        nargs=2,
        metavar=("COUNT", "BYTES"),
        help="add COUNT zero-filled chunks of BYTES in all",
    )
    parser.add_argument(
        "--first-id",
        type=lambda text: int(text, 0),
        default=DEFAULT_FIRST_ID,
        help="the first inert chunk's id (default 0xF001)",
    )
    args = parser.parse_args(argv)
    out: Path = args.output
    if out.exists():
        return _refuse(f"{out} exists; pick a new output")
    if not out.parent.is_dir():
        return _refuse(f"{out.parent} is not a directory")
    try:
        own = args.own.read_bytes()
        chunks = archive_chunks(own)
        if args.add_from is not None:
            added = added_from(chunks, args.add_from.read_bytes())
        else:
            count, total = args.inert
            added = inert(args.first_id, count, total, {chunk_id for chunk_id, _ in chunks})
        padded = pad(own, added)
        with out.open("xb") as handle:
            handle.write(padded)
    except (ArchiveError, PadError, OSError) as exc:
        return _refuse(str(exc))
    print(f"in  {hashlib.sha256(own).hexdigest()}  {args.own}")
    print(f"out {hashlib.sha256(padded).hexdigest()}  {out}")
    print(f"added {len(added)} chunks, {sum(len(payload) for _, payload in added)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
