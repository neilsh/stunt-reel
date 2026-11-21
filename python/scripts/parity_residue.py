"""Count the index-plane pixels two render-store trees differ on, film by film.

Usage::

    mise run parity-residue -- <render root A> <render root B> [--films f1,f2] [--ticks t1,t2]
    mise run parity-residue -- <render root A> --write-hashes FILE [--films f1,f2]
    mise run parity-residue -- <render root A> --against-hashes FILE [--films f1,f2]

Each root holds ``<film>_current`` render stores, as ``build/parity/ours`` does: one render of
each reference film, beside its ``render.json`` (ADR 0027). For every film in both roots the two
stores must hold the same ticks; each tick's index plane, the plane a fragment's palette index is
written to, is read from both and compared pixel by pixel. The table prints one row per film: the
ticks compared, the ticks differing at all, the mean differing pixels per tick, and the largest
difference with its tick. ``--ticks`` adds the count at each named tick, under the film that holds
it. Exits 1 when a film's tick sets differ or a film is missing from a root, so two trees that
render different ticks are never reported as a residue.

``--write-hashes`` writes one line per film tick of root A, ``<film> <tick> <sha256 of the index
plane>``, and ``--against-hashes`` compares root A with such a file in place of root B, printing
the ticks compared and the ticks differing per film: two machines compare their renders without
moving the stores.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

from stunt_reel.parity_artifacts import RenderStore

#: Suffix of a film's render store directory under a render root.
CURRENT_SUFFIX = "_current"
#: Maps a byte to 1 when it is not zero, so one ``translate`` counts the set bytes of a XOR.
_NONZERO = bytes(bool(value) for value in range(256))


@dataclass(frozen=True)
class Residue:
    """One film's differing-pixel count at each tick its two stores hold."""

    film: str
    ticks: list[int]
    counts: list[int]

    def differing(self) -> int:
        """How many ticks differ at all."""
        return sum(1 for count in self.counts if count)

    def mean(self) -> float:
        """The mean differing pixels per tick compared."""
        return sum(self.counts) / len(self.counts) if self.counts else 0.0

    def largest(self) -> tuple[int, int] | None:
        """The largest count and its tick, or ``None`` when no tick was compared."""
        if not self.counts:
            return None
        at = self.counts.index(max(self.counts))
        return max(self.counts), self.ticks[at]

    def at(self, tick: int) -> int | None:
        """The count at *tick*, or ``None`` when the stores do not hold it."""
        return self.counts[self.ticks.index(tick)] if tick in self.ticks else None


def differing_pixels(left: bytes, right: bytes) -> int:
    """How many pixels' index bytes differ between two planes of one raster."""
    if len(left) != len(right):
        raise ValueError(f"planes of {len(left)} and {len(right)} bytes")
    if left == right:
        return 0
    xor = int.from_bytes(left, "little") ^ int.from_bytes(right, "little")
    return xor.to_bytes(len(left), "little").translate(_NONZERO).count(1)


def film_stores(root: Path) -> dict[str, Path]:
    """Each ``<film>_current`` render store under *root*, keyed by film name."""
    return {
        child.name.removesuffix(CURRENT_SUFFIX): child
        for child in sorted(root.iterdir())
        if child.is_dir() and child.name.endswith(CURRENT_SUFFIX)
    }


def compare(left: RenderStore, right: RenderStore, ticks: list[int]) -> list[int]:
    """The differing-pixel count at each of *ticks*, read from both stores' index planes."""
    return [differing_pixels(left.frame(tick).indices, right.frame(tick).indices) for tick in ticks]


def describe_missing(name: str, left: list[int], right: list[int]) -> str:
    """Why two stores' tick sets are not comparable, naming the first few ticks either lacks."""
    only_left = sorted(set(left) - set(right))
    only_right = sorted(set(right) - set(left))
    return (
        f"{name}: tick sets differ ({len(left)} against {len(right)} ticks; "
        f"only the left: {only_left[:5]}, only the right: {only_right[:5]})"
    )


def parse_names(text: str) -> list[str]:
    """The comma-separated film names in *text*, in order, without repeats."""
    names = [part.strip() for part in text.split(",")]
    if any(not name for name in names):
        raise ValueError(f"--films wants comma-separated film names, got {text!r}")
    return list(dict.fromkeys(names))


def parse_ticks(text: str) -> list[int]:
    """Ascending distinct film ticks from ``145,227``."""
    try:
        ticks = [int(part) for part in text.split(",")]
    except ValueError:
        raise ValueError(f"--ticks wants comma-separated film ticks, got {text!r}") from None
    if any(tick < 0 for tick in ticks):
        raise ValueError(f"--ticks wants non-negative film ticks, got {text!r}")
    return sorted(set(ticks))


def tick_hashes(store: RenderStore, ticks: list[int]) -> dict[int, str]:
    """The SHA-256 of each of *ticks*' index plane in *store*."""
    return {tick: hashlib.sha256(store.frame(tick).indices).hexdigest() for tick in ticks}


def read_hashes(path: Path) -> dict[str, dict[int, str]]:
    """A ``--write-hashes`` file's digests, by film, then tick."""
    films: dict[str, dict[int, str]] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        parts = line.split()
        if len(parts) != 3 or not parts[1].isdigit():
            raise ValueError(f"{path}:{number}: want '<film> <tick> <sha256>', got {line!r}")
        films.setdefault(parts[0], {})[int(parts[1])] = parts[2]
    return films


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("left", type=Path, help="render root A, holding <film>_current stores")
    parser.add_argument(
        "right", type=Path, nargs="?", default=None, help="render root B, holding the same films"
    )
    parser.add_argument(
        "--write-hashes", type=Path, default=None, metavar="FILE", help="write root A's tick hashes"
    )
    parser.add_argument(
        "--against-hashes",
        type=Path,
        default=None,
        metavar="FILE",
        help="compare root A with a --write-hashes file in place of root B",
    )
    parser.add_argument("--films", default=None, metavar="F1,F2", help="compare only these films")
    parser.add_argument(
        "--ticks", default=None, metavar="T1,T2", help="also print the count at each of these ticks"
    )
    return parser.parse_args(argv)


def row(residue: Residue, width: int) -> str:
    """The table row for one film."""
    largest = residue.largest()
    shown = "-" if largest is None else str(largest[0])
    at = "-" if largest is None else str(largest[1])
    return (
        f"{residue.film:<{width}}  {len(residue.ticks):>6}  {residue.differing():>9}  "
        f"{residue.mean():>9.1f}  {shown:>7}  {at:>6}"
    )


def write_hashes(left: dict[str, Path], films: list[str], out: Path) -> int:
    """Writes *films*' tick hashes to *out*; 1 when a film has no store."""
    lines: list[str] = []
    failed = False
    for film in films:
        if film not in left:
            print(f"parity_residue: {film}: no {film}{CURRENT_SUFFIX} store", file=sys.stderr)
            failed = True
            continue
        store = RenderStore(left[film])
        lines += [
            f"{film} {tick} {digest}" for tick, digest in tick_hashes(store, store.ticks()).items()
        ]
    out.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8", newline="\n")
    return 1 if failed else 0


def against_hashes(
    left: dict[str, Path], films: list[str], hashes: dict[str, dict[int, str]]
) -> int:
    """Prints ticks compared and differing per film; 1 on a missing film or other tick sets."""
    failed = False
    table: list[tuple[str, int, int]] = []
    for film in films:
        if film not in left or film not in hashes:
            missing = "root A" if film not in left else "the hashes file"
            print(f"parity_residue: {film}: not in {missing}", file=sys.stderr)
            failed = True
            continue
        store = RenderStore(left[film])
        theirs = hashes[film]
        if store.ticks() != sorted(theirs):
            print(
                f"parity_residue: {describe_missing(film, store.ticks(), sorted(theirs))}",
                file=sys.stderr,
            )
            failed = True
            continue
        ours = tick_hashes(store, store.ticks())
        table.append((film, len(ours), sum(1 for tick in ours if ours[tick] != theirs[tick])))
    width = max((len(film) for film, _, _ in table), default=4)
    print(f"{'film':<{width}}  {'ticks':>6}  {'differing':>9}")
    for film, ticks, differing in table:
        print(f"{film:<{width}}  {ticks:>6}  {differing:>9}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    """Prints the residue table; 1 when a film's tick sets differ or a film is missing from a root, 2 on a refused invocation."""
    args = parse_args(argv)
    try:
        films = parse_names(args.films) if args.films is not None else None
        named_ticks = parse_ticks(args.ticks) if args.ticks is not None else []
    except ValueError as err:
        print(f"parity_residue: {err}", file=sys.stderr)
        return 2
    modes = [args.right is not None, args.write_hashes is not None, args.against_hashes is not None]
    if sum(modes) != 1:
        print(
            "parity_residue: give either root B, --write-hashes or --against-hashes",
            file=sys.stderr,
        )
        return 2
    if not args.left.is_dir():
        print(f"parity_residue: render root not found: {args.left}", file=sys.stderr)
        return 2
    if args.right is None:
        stores = film_stores(args.left)
        if args.write_hashes is not None:
            return write_hashes(stores, films or sorted(stores), args.write_hashes)
        try:
            hashes = read_hashes(args.against_hashes)
        except (OSError, ValueError) as err:
            print(f"parity_residue: {err}", file=sys.stderr)
            return 2
        return against_hashes(stores, films or sorted(set(stores) | set(hashes)), hashes)
    for root in (args.left, args.right):
        if not root.is_dir():
            print(f"parity_residue: render root not found: {root}", file=sys.stderr)
            return 2
    left, right = film_stores(args.left), film_stores(args.right)
    if films is None:
        films = sorted(set(left) | set(right))
    residues: list[Residue] = []
    failed = False
    for film in films:
        if film not in left or film not in right:
            missing = "the left" if film not in left else "the right"
            print(
                f"parity_residue: {film}: no {film}{CURRENT_SUFFIX} store in {missing}",
                file=sys.stderr,
            )
            failed = True
            continue
        first, second = RenderStore(left[film]), RenderStore(right[film])
        if first.ticks() != second.ticks():
            print(
                f"parity_residue: {describe_missing(film, first.ticks(), second.ticks())}",
                file=sys.stderr,
            )
            failed = True
            continue
        ticks = first.ticks()
        residues.append(Residue(film=film, ticks=ticks, counts=compare(first, second, ticks)))
    width = max((len(residue.film) for residue in residues), default=4)
    print(
        f"{'film':<{width}}  {'ticks':>6}  {'differing':>9}  {'mean/tick':>9}  {'max':>7}  {'at':>6}"
    )
    for residue in residues:
        print(row(residue, width))
        for tick in named_ticks:
            count = residue.at(tick)
            if count is not None:
                print(f"{'':<{width}}      tick {tick}: {count} differing pixels")
    held = {tick for residue in residues for tick in residue.ticks}
    for tick in named_ticks:
        if tick not in held:
            print(f"parity_residue: no store holds tick {tick}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
