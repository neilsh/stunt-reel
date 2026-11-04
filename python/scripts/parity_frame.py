"""Render a list of film ticks and show each beside its reference capture frame.

Usage::

    mise run frame -- --film intro --ticks 48,92,1009 [--crop x0,y0,x1,y1] [--scale N]
        [--no-build] [--var DBG_NAME=v1,v2]

One ``stuntreel --at-ticks`` process renders every tick (process startup is almost all of a
single frame's cost), into the render store ``build/scratch/frame/<film>/store``. For each tick
the capture holds, ``build/scratch/frame/<film>/<film>_<tick>.png`` is the capture frame left
of ours with a magenta divider; the path is printed. A tick the capture lacks is still
rendered and its nearest captured ticks are printed instead; one past the film's end is
named as not rendered. Each run replaces the store and the film's earlier PNGs.

With ``--var DBG_NAME=v1,v2`` the film is rendered once per value, with that variable in the
environment, into ``store_<n>_<value>`` (``n`` its position, so two values never share one); each PNG is then the capture followed by one panel per
value, in the order given (the before-and-after picture for a candidate change).
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

import parity_probe
import parity_sweep

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


def check_crop(box: tuple[int, int, int, int], scale: int, *, width: int, height: int) -> None:
    """Refuses a crop box outside the ``width`` x ``height`` raster, or a scale below 1."""
    x0, y0, x1, y1 = box
    if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height):
        raise ValueError(f"--crop {x0},{y0},{x1},{y1} is outside the {width}x{height} raster")
    if scale < 1:
        raise ValueError(f"--scale wants 1 or more, got {scale}")


def clear_previous(out: Path, film: str) -> None:
    """Deletes ``film``'s PNGs and render stores from an earlier run, so none outlives its store."""
    for png in out.glob(f"{film}_*.png"):
        png.unlink()
    for store in out.glob("store*"):
        shutil.rmtree(store, ignore_errors=True)


def variant_stores(out: Path, var: str | None) -> list[tuple[str, dict[str, str] | None, Path]]:
    """Label, environment and store directory of each render: one per ``--var`` value, or one."""
    if var is None:
        return [("ours", None, out / "store")]
    name, values = parity_sweep.parse_var(var)
    if len(set(values)) != len(values):
        raise ValueError(f"--var {name} repeats a value")
    return [
        (
            f"{name}={value}",
            {name: value},
            out / f"store_{i}_{re.sub(r'[^0-9A-Za-z.-]', '_', value)}",
        )
        for i, value in enumerate(values)
    ]


def describe_missing(tick: int, nearest: tuple[int | None, int | None], *, rendered: bool) -> str:
    """The line for a tick with no capture frame; one past the film's end was not rendered."""
    before, after = nearest
    if not rendered:
        last = "" if before is None else f" (last captured: {before})"
        return f"tick {tick}: past the film's end, not rendered{last}"
    return f"tick {tick}: not in the capture (nearest captured: {before}, {after})"


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--film", required=True, choices=references.reference_films(REPO_ROOT))
    parser.add_argument("--ticks", required=True, help="comma list of 0-based film ticks")
    parser.add_argument("--crop", default=None, help="x0,y0,x1,y1 (default: the whole viewport)")
    parser.add_argument("--scale", type=int, default=1)
    parser.add_argument("--no-build", action="store_true", help="reuse the release binary")
    parser.add_argument(
        "--var", default=None, help="DBG_NAME=v1,v2: one panel per value after the capture"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        ticks = parse_ticks(args.ticks)
        box = parse_box(args.crop) if args.crop else None
        variants = variant_stores(REPO_ROOT / FRAME_DIR / args.film, args.var)
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
    with parity_pipeline.reference_job(root, args.film) as job:
        return _draw(job, args, ticks, box, variants)


def _draw(
    job: parity_pipeline.FilmJob,
    args: argparse.Namespace,
    ticks: list[int],
    box: tuple[int, int, int, int] | None,
    variants: list[tuple[str, dict[str, str] | None, Path]],
) -> int:
    """Render the job's ticks once per variant and write each tick's sheet; the exit code."""
    root = job.root
    reference = job.capture
    found, missing = locate(read_capture(reference), ticks)

    out = root / FRAME_DIR / args.film
    clear_previous(out, args.film)
    for _, env, variant_dir in variants:
        parity_pipeline.render_film(job, variant_dir, env, ticks=ticks)
    store_dir = variants[0][2]
    stores = [variant_dir for _, _, variant_dir in variants]

    if not (store_dir / "render.json").exists():
        # Every tick was past the film's end, so the renderer wrote no store.
        for tick in ticks:
            print(describe_missing(tick, missing.get(tick, (None, None)), rendered=False))
        return 1
    store = RenderStore(store_dir)
    geometry = store.record.geometry
    box = box or (0, 0, geometry.width, geometry.viewport_rows or geometry.height)
    try:
        check_crop(box, args.scale, width=geometry.width, height=geometry.height)
    except ValueError as err:
        print(f"parity_frame: {err}", file=sys.stderr)
        return 2
    for tick, ordinal in found.items():
        if not store.holds(tick):
            print(describe_missing(tick, (None, None), rendered=False))
            continue
        png = out / f"{args.film}_{tick}.png"
        parity_probe.make_strip(reference, stores, ordinal, tick, box, args.scale, png)
        print(png)
    for tick, nearest in missing.items():
        print(describe_missing(tick, nearest, rendered=store.holds(tick)))
    print("panels: capture | " + " | ".join(label for label, _, _ in variants))
    print("render stores: " + ", ".join(str(path) for path in stores))
    return 0


if __name__ == "__main__":
    sys.exit(main())
