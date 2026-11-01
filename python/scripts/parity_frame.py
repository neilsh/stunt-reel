"""Render a list of film ticks and show each beside its reference capture frame.

Usage::

    mise run frame -- --film intro --ticks 48,92,1009 [--crop x0,y0,x1,y1] [--scale N]
        [--no-build]

One ``stuntreel --at-ticks`` process renders every tick (process startup is almost all of a
single frame's cost), into the render store ``build/scratch/frame/<film>/store``. For each tick
the capture holds, ``build/scratch/frame/<film>/<film>_<tick>.png`` is the capture frame left
of ours with a magenta divider; the path is printed. A tick the capture lacks is still
rendered and its nearest captured ticks are printed instead; one past the film's end is
named as not rendered.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import parity_probe

from stunt_reel import parity_pipeline, references
from stunt_reel.dataroot import REPO_ROOT, ensure_links_or_report
from stunt_reel.parity_artifacts import CaptureSet, RenderStore, read_capture

#: Where renders and their side-by-side PNGs go, relative to the checkout.
FRAME_DIR = Path("build") / "scratch" / "frame"


def parse_ticks(text: str) -> list[int]:
    """Ascending distinct film ticks from ``48,92,1009``."""
    try:
        ticks = [int(part) for part in text.split(",")]
    except ValueError:
        raise ValueError(f"--ticks wants comma-separated film ticks, got {text!r}") from None
    if any(tick < 0 for tick in ticks):
        raise ValueError(f"--ticks wants non-negative film ticks, got {text!r}")
    return sorted(set(ticks))


def parse_box(text: str) -> tuple[int, int, int, int]:
    """A crop box from ``x0,y0,x1,y1``."""
    try:
        x0, y0, x1, y1 = (int(part) for part in text.split(","))
    except ValueError:
        raise ValueError(f"--crop wants x0,y0,x1,y1, got {text!r}") from None
    return x0, y0, x1, y1


def locate(
    capture: CaptureSet, ticks: list[int]
) -> tuple[dict[int, int], dict[int, tuple[int | None, int | None]]]:
    """Split ``ticks`` into capture ordinals and, for the rest, the neighbouring captured ticks."""
    held = {frame.film_tick: frame.ordinal for frame in capture.frames}
    found = {tick: held[tick] for tick in ticks if tick in held}
    missing: dict[int, tuple[int | None, int | None]] = {}
    for tick in ticks:
        if tick not in held:
            before = [t for t in held if t < tick]
            after = [t for t in held if t > tick]
            missing[tick] = (max(before, default=None), min(after, default=None))
    return found, missing


def describe_missing(tick: int, nearest: tuple[int | None, int | None], *, rendered: bool) -> str:
    """The line for a tick with no capture frame; one past the film's end was not rendered."""
    before, after = nearest
    if not rendered:
        return f"tick {tick}: past the film's end, not rendered (last captured: {before})"
    return f"tick {tick}: not in the capture (nearest captured: {before}, {after})"


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--film", required=True, choices=list(parity_pipeline.FILMS))
    parser.add_argument("--ticks", required=True, help="comma list of 0-based film ticks")
    parser.add_argument("--crop", default=None, help="x0,y0,x1,y1 (default: the whole viewport)")
    parser.add_argument("--scale", type=int, default=1)
    parser.add_argument("--no-build", action="store_true", help="reuse the release binary")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        ticks = parse_ticks(args.ticks)
        box = parse_box(args.crop) if args.crop else None
    except ValueError as err:
        print(f"parity_frame: {err}", file=sys.stderr)
        return 2
    root = REPO_ROOT
    if not ensure_links_or_report("parity_frame"):
        return 2
    problems = parity_pipeline.preflight(root, [args.film], build_required=not args.no_build)
    if problems:
        print("parity_frame: " + "\n  ".join(problems), file=sys.stderr)
        return 2
    if not args.no_build:
        parity_pipeline.build_release()
    reference = references.reference_dir(root, args.film)
    found, missing = locate(read_capture(reference), ticks)

    out = root / FRAME_DIR / args.film
    store_dir = out / "store"
    shutil.rmtree(store_dir, ignore_errors=True)
    parity_pipeline.render_film(args.film, root, store_dir, ticks=ticks)

    store = RenderStore(store_dir)
    geometry = store.record.geometry
    box = box or (0, 0, geometry.width, geometry.viewport_rows or geometry.height)
    for tick, ordinal in found.items():
        png = out / f"{args.film}_{tick}.png"
        parity_probe.make_side_by_side(reference, store_dir, ordinal, tick, box, args.scale, png)
        print(png)
    for tick, nearest in missing.items():
        print(describe_missing(tick, nearest, rendered=store.holds(tick)))
    print(f"render store: {store_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
