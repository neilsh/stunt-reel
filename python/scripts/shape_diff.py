"""Show which stock shapes a ``DBG_*`` value changes, and how.

Usage::

    mise run shape-diff -- --var DBG_NAME=v1,v2 [--shapes IDS|FILE] [--archive X.ALL]
        [--views top,side,front] [--tile PX] [--no-build]

``stuntreel shape-views`` runs once per value, with that variable in the environment, into
``build/scratch/shape-diff/views_<n>_<value>`` (``n`` its position). A shape whose geometry
hash or decode failure differs from the first value's is listed, and
``build/scratch/shape-diff/sheet.png`` shows only those shapes, one row each: the first
value's views, then each later value's, split by a magenta divider, under a strip naming each
column's value. The archive defaults to
``target/linked/superset/SUPERSET.ALL``, every stock shape (``mise run superset-all``).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import parity_sweep
from PIL import Image, ImageDraw

from stunt_reel import parity_pipeline
from stunt_reel.dataroot import REPO_ROOT
from stunt_reel.link import binary_locked, binary_path

#: Where each value's views and the sheet go, relative to the checkout.
DIFF_DIR = Path("build") / "scratch" / "shape-diff"
#: The archive of every stock shape that ``mise run superset-all`` writes.
SUPERSET = Path("target") / "linked" / "superset" / "SUPERSET.ALL"
#: The divider between a row's panels and between rows.
DIVIDER = (255, 0, 255)
#: Divider width in pixels.
GAP = 2
#: Height in pixels of the strip naming each column's value.
HEADER = 14


@dataclass(frozen=True)
class Variant:
    """One value of the variable: its label, its environment entry, and its views directory."""

    label: str
    env: dict[str, str]
    out: Path


def variants(out: Path, var: str) -> list[Variant]:
    """One :class:`Variant` per value of ``DBG_NAME=v1,v2``, in the order given."""
    name, values = parity_sweep.parse_var(var)
    if len(values) < 2:
        raise ValueError(f"--var {name} needs two or more values to compare")
    if len(set(values)) != len(values):
        raise ValueError(f"--var {name} repeats a value")
    return [
        Variant(
            f"{name}={value}",
            {name: value},
            out / f"views_{i}_{re.sub(r'[^0-9A-Za-z.-]', '_', value)}",
        )
        for i, value in enumerate(values)
    ]


def views_argv(archive: Path, out: Path, args: argparse.Namespace) -> list[str]:
    """The ``stuntreel shape-views`` command line for one value."""
    argv = [str(binary_path()), "shape-views", "--archive", str(archive), "--out", str(out)]
    for flag, value in (("--shapes", args.shapes), ("--views", args.views), ("--tile", args.tile)):
        if value is not None:
            argv += [flag, str(value)]
    return argv


def read_manifest(out: Path) -> dict[str, dict[str, object]]:
    """``out/manifest.json``'s shapes, by hex id."""
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    return {str(shape["id"]): shape for shape in manifest["shapes"]}


def outcome(shape: dict[str, object] | None) -> tuple[object, object]:
    """What a run made of a shape: its geometry hash and its decode failure."""
    if shape is None:
        return ("absent", None)
    return (shape.get("geometry_hash"), shape.get("error"))


def changed_shapes(manifests: list[dict[str, dict[str, object]]]) -> list[str]:
    """Hex ids, ascending, whose outcome under a later value differs from the first value's."""
    ids = sorted(set().union(*manifests), key=lambda text: int(text, 16))
    first, *rest = manifests
    return [
        shape_id
        for shape_id in ids
        if any(outcome(later.get(shape_id)) != outcome(first.get(shape_id)) for later in rest)
    ]


def _load_rgb(png: Path) -> Image.Image:
    """``png`` read into memory as RGB, its file closed."""
    with Image.open(png) as image:
        return image.convert("RGB")


def draw_sheet(dirs: list[Path], labels: list[str], ids: list[str], out: Path) -> None:
    """Writes one row per id: each directory's ``<id>.png`` left to right, magenta between.

    A black strip ``HEADER`` pixels tall names each column by its entry in ``labels``. A
    run that drew no image of the shape (it failed to decode, or has no vertices) gets a
    black panel the size of the others in its row.
    """
    rows: list[list[Image.Image | None]] = []
    for shape_id in ids:
        panels = []
        for directory in dirs:
            png = directory / f"{shape_id}.png"
            panels.append(_load_rgb(png) if png.is_file() else None)
        rows.append(panels)
    sizes = [next((p.size for p in row if p is not None), (1, 1)) for row in rows]
    width = max(w for w, _ in sizes) * len(dirs) + GAP * (len(dirs) - 1)
    height = HEADER + sum(h for _, h in sizes) + GAP * (len(rows) - 1)
    sheet = Image.new("RGB", (width, height), DIVIDER)
    sheet.paste((0, 0, 0), (0, 0, width, HEADER))
    draw = ImageDraw.Draw(sheet)
    draw.fontmode = "1"
    for column, label in enumerate(labels):
        draw.text((column * (sizes[0][0] + GAP) + 2, 1), label, fill=(255, 255, 255))
    top = HEADER
    for row, (panel_width, panel_height) in zip(rows, sizes, strict=True):
        for column, panel in enumerate(row):
            left = column * (panel_width + GAP)
            sheet.paste(panel or Image.new("RGB", (panel_width, panel_height)), (left, top))
        top += panel_height + GAP
    sheet.save(out)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--var", required=True, help="DBG_NAME=v1,v2: one shape-views run each")
    parser.add_argument("--shapes", default=None, help="hex ids, A..=B ranges, or a file of them")
    parser.add_argument("--archive", type=Path, default=REPO_ROOT / SUPERSET)
    parser.add_argument("--views", default=None, help="top,side,front by default")
    parser.add_argument("--tile", type=int, default=None, help="view tile edge in pixels")
    parser.add_argument("--no-build", action="store_true", help="reuse the release binary")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out = REPO_ROOT / DIFF_DIR
    try:
        runs = variants(out, args.var)
    except ValueError as err:
        print(f"shape_diff: {err}", file=sys.stderr)
        return 2
    if not args.archive.is_file():
        print(f"shape_diff: no archive {args.archive} (run mise run superset-all)", file=sys.stderr)
        return 2
    if not args.no_build:
        if binary_locked(binary_path()):
            print("shape_diff: release binary is in use; rerun with --no-build", file=sys.stderr)
            return 2
        parity_pipeline.build_release()
    shutil.rmtree(out, ignore_errors=True)
    for run in runs:
        code, tail = parity_pipeline.run_command(
            views_argv(args.archive, run.out, args), {**os.environ, **run.env}
        )
        if code != 0:
            print(
                f"shape_diff: shape-views with {run.label} exited {code}:\n{tail}", file=sys.stderr
            )
            return 1
    manifests = [read_manifest(run.out) for run in runs]
    changed = changed_shapes(manifests)
    listed = f": {' '.join(changed)}" if changed else ""
    print(f"{len(changed)} of {len(set().union(*manifests))} shapes changed{listed}")
    if changed:
        sheet = out / "sheet.png"
        draw_sheet([run.out for run in runs], [run.label for run in runs], changed, sheet)
        print(sheet)
    print("panels: " + " | ".join(run.label for run in runs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
