"""Write a copy of a `.ALL` with its sound samples stubbed, as captures play it (ADR 0043).

Every chunk in `0xC000`-`0xCFFF` gets the one-byte payload the demo's `CTRY.ALL` ships
(``stunt_reel.all_archive.stub_sound_samples``). ``--sound-ids-from`` also adds, as stubs, the
sound ids another archive has and IN lacks, so a superset archive carries a film's sound ids.
Prints the SHA-256 of IN and OUT. OUT must not exist and must not be IN.

Usage: ``mise run stub-sound-samples -- IN.ALL -o OUT.ALL [--sound-ids-from OWN.ALL]``
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from stunt_reel.all_archive import ArchiveError, stub_sound_samples


def _refuse(message: str) -> int:
    print(f"stub-sound-samples: {message}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    """Write the stubbed archive; 0 when written, 2 when refused."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, metavar="IN.ALL", help="archive to read")
    parser.add_argument("-o", "--output", type=Path, required=True, help="archive to write")
    parser.add_argument(
        "--sound-ids-from",
        type=Path,
        default=None,
        metavar="OWN.ALL",
        help="also add, as stubs, the sound ids this archive has and IN lacks",
    )
    args = parser.parse_args(argv)
    source: Path = args.source
    out: Path = args.output
    if out.exists():
        return _refuse(f"{out} exists; pick a new output")
    if out.resolve() == source.resolve():
        return _refuse("the output is the input")
    if not out.parent.is_dir():
        return _refuse(f"{out.parent} is not a directory")
    try:
        data = source.read_bytes()
        own = None if args.sound_ids_from is None else args.sound_ids_from.read_bytes()
        stubbed = stub_sound_samples(data, sound_ids_from=own)
        with out.open("xb") as handle:
            handle.write(stubbed)
    except (ArchiveError, OSError) as exc:
        return _refuse(str(exc))
    print(f"in  {hashlib.sha256(data).hexdigest()}  {source}")
    print(f"out {hashlib.sha256(stubbed).hexdigest()}  {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
