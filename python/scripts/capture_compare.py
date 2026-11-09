"""Compare two frame captures of one film page by page, paired by `film_tick`.

Two captures of the same film and archive differ by recapture noise; a capture of another
archive (``capture-ref --archive``) is judged against that noise (issue 301). Pages pair only
on an exact `film_tick`: pairing by nearest tick measures the film's motion, not the capture.
Fewer than `MIN_PAIRS` shared ticks is reported as unpaired, with no statistics.

Prints each capture's archive hash and `PLAYONE` build, the shared ticks, how many paired
colour index pages are identical, the median and 90th percentile (nearest rank) of differing
pixels per paired page, and on how many paired ticks the two palettes are equal.

Usage: ``mise run capture-compare -- <capture A> <capture B>`` (directories holding meta.json)
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
class Comparison:
    """Two captures' pages paired by `film_tick`; the statistics are `None` when unpaired."""

    a: Side
    b: Side
    shared: int
    identical: int
    #: Differing pixels of every paired page, in tick order.
    differing: tuple[int, ...]
    palettes_equal: int

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


def compare(a: Path, b: Path) -> Comparison:
    """Pair *a*'s and *b*'s pages by `film_tick` and count what differs.

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
    )


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
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point; 0 compared, 3 unpaired, 1 an unreadable capture."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("a", type=Path, help="a capture directory holding meta.json")
    parser.add_argument("b", type=Path, help="the capture to compare it with")
    args = parser.parse_args(argv)
    try:
        result = compare(args.a, args.b)
    except (OSError, ValueError) as exc:
        print(f"capture-compare: {exc}", file=sys.stderr)
        return 1
    print(report(result))
    return 0 if result.paired else 3


if __name__ == "__main__":
    sys.exit(main())
