"""Compare two frame captures of one film page by page, paired by `film_tick`.

Two captures of the same film and archive differ by recapture noise; a capture of another
archive (``capture-ref --archive``) is judged against that noise (issue 301). Pages pair only
on an exact `film_tick`: pairing by nearest tick measures the film's motion, not the capture.
Fewer than `MIN_PAIRS` shared ticks is reported as unpaired, with no statistics.

Prints each capture's archive hash and `PLAYONE` build, the shared ticks, how many paired
colour index pages are identical, the median and 90th percentile (nearest rank) of differing
pixels per paired page, and on how many paired ticks the two palettes are equal.

With ``--shift N``, each page of A with no identical page of B at its tick is looked for among
B's pages at ticks ``t-N``..``t+N``: an exact pixel match there is a page drawn at another tick.
It prints how many match, at which offsets, the ticks only one capture holds, and each page left
unmatched with its differing pixels and their bounding box.

Usage: ``mise run capture-compare -- <capture A> <capture B> [--shift N]`` (directories holding
meta.json)
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
lazy from collections.abc import Sequence

from stunt_reel.parity_artifacts.capture import CaptureSet, read_capture, read_capture_palette

#: Fewer shared ticks than this cannot bracket noise (the bench's threshold, issue 299).
MIN_PAIRS = 20


@dataclass(frozen=True)
class Side:
    """What one capture says about itself."""

    path: Path
    all_sha256: str | None
    playone_build: str | None
    pages: int


@dataclass(frozen=True)
class Unmatched:
    """A page of A that no B page within the shift matches."""

    tick: int
    #: Pixels differing from B's page at the same tick; `None` when B has no page there.
    differing: int | None
    #: First and last differing column, then row; `None` when B has no page there.
    box: tuple[int, int, int, int] | None


@dataclass(frozen=True)
class Shift:
    """A's pages with no identical B page at their tick, looked for at nearby ticks of B."""

    n: int
    #: How many of the paired pages differ, and how many of those a nearby B page matches.
    differing: int
    differing_matched: int
    #: Ticks only A holds, and how many of their pages a nearby B page matches.
    only_a: tuple[int, ...]
    only_a_matched: int
    only_b: tuple[int, ...]
    #: Matches per offset, B's tick minus A's.
    offsets: dict[int, int]
    unmatched: tuple[Unmatched, ...]


@dataclass(frozen=True)
class Comparison:
    """Two captures' pages paired by `film_tick`; the statistics are `None` when unpaired."""

    a: Side
    b: Side
    shared: int
    identical: int
    #: Differing pixels of every paired page, in tick order.
    differing: tuple[int, ...]
    palettes_equal: int
    #: Set when compared with a shift of at least 1.
    shift: Shift | None = None

    @property
    def paired(self) -> bool:
        """Whether enough ticks are shared to judge."""
        return self.shared >= MIN_PAIRS


def nearest_rank(values: Sequence[int], q: float) -> int:
    """The *q* quantile of *values* by nearest rank (the smallest value with at least *q* below)."""
    if not values:
        raise ValueError("no values")
    ordered = sorted(values)
    return ordered[max(math.ceil(q * len(ordered)), 1) - 1]


def _side(path: Path, capture: CaptureSet) -> Side:
    raw: dict[str, Any] = json.loads((path / "meta.json").read_text(encoding="utf-8"))
    build = raw.get("playone_build")
    return Side(
        path=path,
        all_sha256=capture.film.all_sha256,
        playone_build=build if isinstance(build, str) else None,
        pages=len(capture.frames),
    )


def _by_tick(capture: CaptureSet) -> dict[int, tuple[str, str]]:
    """Each tick's frame and palette file; a tick captured twice keeps its first page."""
    pages: dict[int, tuple[str, str]] = {}
    for frame in capture.frames:
        pages.setdefault(frame.film_tick, (frame.frame_file, frame.palette_file))
    return pages


def _box(raster_a: bytes, raster_b: bytes, width: int) -> tuple[int, int, int, int]:
    """First and last column, then row, where two differing pages differ."""
    where = [i for i, (x, y) in enumerate(zip(raster_a, raster_b, strict=True)) if x != y]
    columns = [i % width for i in where]
    return min(columns), max(columns), where[0] // width, where[-1] // width


def _shift(
    n: int,
    a: Path,
    b: Path,
    pages_a: dict[int, tuple[str, str]],
    pages_b: dict[int, tuple[str, str]],
    width: int,
) -> Shift:
    """Look for each of A's pages that B does not draw identically at its tick within *n* ticks."""
    shared = pages_a.keys() & pages_b.keys()
    rasters_b = {tick: (b / frame).read_bytes() for tick, (frame, _) in pages_b.items()}
    offsets: dict[int, int] = {}
    unmatched: list[Unmatched] = []
    differing = differing_matched = only_a_matched = 0
    for tick in sorted(pages_a):
        raster_a = (a / pages_a[tick][0]).read_bytes()
        if tick in shared and rasters_b[tick] == raster_a:
            continue
        nearby = sorted((d for d in range(-n, n + 1) if d), key=lambda d: (abs(d), d))
        found = next((d for d in nearby if rasters_b.get(tick + d) == raster_a), None)
        if tick in shared:
            differing += 1
        if found is not None:
            offsets[found] = offsets.get(found, 0) + 1
            if tick in shared:
                differing_matched += 1
            else:
                only_a_matched += 1
        elif tick in shared:
            raster_b = rasters_b[tick]
            pixels = sum(x != y for x, y in zip(raster_a, raster_b, strict=True))
            unmatched.append(Unmatched(tick, pixels, _box(raster_a, raster_b, width)))
        else:
            unmatched.append(Unmatched(tick, None, None))
    return Shift(
        n=n,
        differing=differing,
        differing_matched=differing_matched,
        only_a=tuple(sorted(pages_a.keys() - shared)),
        only_a_matched=only_a_matched,
        only_b=tuple(sorted(pages_b.keys() - shared)),
        offsets=dict(sorted(offsets.items())),
        unmatched=tuple(unmatched),
    )


def compare(a: Path, b: Path, *, shift: int = 0) -> Comparison:
    """Pair *a*'s and *b*'s pages by `film_tick` and count what differs; *shift* as `Shift`.

    Raises:
        ValueError: a page of one pair differs in size from the other.
        OSError: a capture's file is missing.
    """
    capture_a, capture_b = read_capture(a), read_capture(b)
    pages_a, pages_b = _by_tick(capture_a), _by_tick(capture_b)
    shared = sorted(pages_a.keys() & pages_b.keys())
    differing: list[int] = []
    palettes_equal = 0
    for tick in shared:
        (frame_a, palette_a), (frame_b, palette_b) = pages_a[tick], pages_b[tick]
        raster_a, raster_b = (a / frame_a).read_bytes(), (b / frame_b).read_bytes()
        if len(raster_a) != len(raster_b):
            raise ValueError(
                f"film tick {tick}: pages of {len(raster_a)} and {len(raster_b)} bytes"
            )
        differing.append(sum(x != y for x, y in zip(raster_a, raster_b, strict=True)))
        if read_capture_palette(a / palette_a) == read_capture_palette(b / palette_b):
            palettes_equal += 1
    return Comparison(
        a=_side(a, capture_a),
        b=_side(b, capture_b),
        shared=len(shared),
        identical=differing.count(0),
        differing=tuple(differing),
        palettes_equal=palettes_equal,
        shift=(
            _shift(shift, a, b, pages_a, pages_b, capture_a.geometry.width) if shift > 0 else None
        ),
    )


def _ticks(ticks: Sequence[int]) -> str:
    return ", ".join(map(str, ticks)) or "none"


def _shift_lines(shift: Shift) -> list[str]:
    looked = shift.differing + len(shift.only_a)
    matched = shift.differing_matched + shift.only_a_matched
    lines = [
        (
            f"shift ±{shift.n}: {matched} of {looked} A pages with no identical B page at their "
            f"tick match a B page within {shift.n} ticks (differing pages "
            f"{shift.differing_matched} of {shift.differing}, ticks only in A "
            f"{shift.only_a_matched} of {len(shift.only_a)})"
        ),
        "offsets (B tick minus A tick): "
        + (", ".join(f"{d:+d}: {count}" for d, count in shift.offsets.items()) or "none"),
        f"film ticks only in A: {_ticks(shift.only_a)}; only in B: {_ticks(shift.only_b)}",
    ]
    for page in shift.unmatched:
        if page.box is None:
            lines.append(f"no match: tick {page.tick} (no B page)")
        else:
            x0, x1, y0, y1 = page.box
            lines.append(
                f"no match: tick {page.tick} ({page.differing} differing pixels, "
                f"columns {x0}-{x1}, rows {y0}-{y1})"
            )
    return lines


def report(result: Comparison) -> str:
    """The comparison as the lines the command prints."""
    lines = [
        f"{label}: {side.path} ({side.pages} pages, archive {(side.all_sha256 or '?')[:12]}, "
        f"PLAYONE {side.playone_build or '?'})"
        for label, side in (("A", result.a), ("B", result.b))
    ]
    if not result.paired:
        lines.append(f"unpaired: {result.shared} shared film ticks, fewer than {MIN_PAIRS}")
        return "\n".join(lines)
    lines += [
        f"shared film ticks: {result.shared}",
        f"identical pages: {result.identical} of {result.shared}",
        (
            f"differing pixels: median {nearest_rank(result.differing, 0.5)}, "
            f"90th percentile {nearest_rank(result.differing, 0.9)}"
        ),
        f"palettes equal: {result.palettes_equal} of {result.shared}",
    ]
    if result.shift is not None:
        lines += _shift_lines(result.shift)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point; 0 compared, 3 unpaired, 1 an unreadable capture."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("a", type=Path, help="a capture directory holding meta.json")
    parser.add_argument("b", type=Path, help="the capture to compare it with")
    parser.add_argument(
        "--shift",
        type=int,
        default=0,
        metavar="N",
        help="look for each of A's pages B does not draw identically at its tick within N ticks",
    )
    args = parser.parse_args(argv)
    if args.shift < 0:
        parser.error("--shift must be 0 or more")
    try:
        result = compare(args.a, args.b, shift=args.shift)
    except (OSError, ValueError) as exc:
        print(f"capture-compare: {exc}", file=sys.stderr)
        return 1
    print(report(result))
    return 0 if result.paired else 3


if __name__ == "__main__":
    sys.exit(main())
