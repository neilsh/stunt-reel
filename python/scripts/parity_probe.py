"""Diagnostic probes for parity work (see research/parity/probes.md).

Four subcommands read a capture directory through the artifact adapter (its
``meta.json`` names each frame's planes and palettes) and a render directory
(its ``render.json`` and render store), and a fifth reads one ``report.json``
through the same adapter:

* ``crop``   - capture over ours, one frame region, as a PNG.
* ``shift``  - best (dx, dy) that slides our actor silhouette onto the
  capture's object pixels, per scored frame.
* ``iou``    - mean IoU of our actor pixels against the capture's object
  pixels inside the actor's padded bounding box.
* ``retime`` - relabel an existing render by N ticks (negative allowed),
  rewriting its store and ``render.json``, so a timing hypothesis costs no
  rebuild.
* ``summary`` - the scored headline, the loss by class, the worst scored
  frames and the ``research/parity/log.md`` row for one report, so the numbers
  are never retyped by hand.

Object pixels are capture pixels that are not sky, ground ramp, button bar or
cursor; the index ranges default to ``CTRY.FLM`` and are per film.
"""

from __future__ import annotations

import argparse
import contextlib
import statistics
import struct
import sys
import zlib
from pathlib import Path
lazy from collections.abc import Sequence

import numpy as np

from stunt_reel import parity_layout, references
from stunt_reel.dataroot import REPO_ROOT
from stunt_reel.parity_artifacts import (
    CapturedFrame,
    CaptureSet,
    RenderStore,
    read_capture,
    read_capture_palette,
    read_page,
    read_report,
)
from stunt_reel.parity_pipeline import RetimeError, retime_render

#: Inclusive index ranges that are not "object": ground ramp, sky, shade greens.
CTRY_BACKGROUND = ((192, 199), (228, 238), (161, 165))
#: Cursor (255) and shadow/black (0) are never object pixels.
NEVER_OBJECT = (0, 255)


def write_png(path: Path, width: int, rows: list[list[int]]) -> None:
    """Writes an 8-bit RGB PNG; ``rows`` hold flat R, G, B triples."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    raw = b"".join(b"\x00" + bytes(r) for r in rows)
    header = struct.pack(">IIBBBBB", width, len(rows), 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def is_object(index: int, background: tuple[tuple[int, int], ...]) -> bool:
    """True when a capture index belongs to a model rather than backdrop or UI."""
    if index in NEVER_OBJECT:
        return False
    return not any(lo <= index <= hi for lo, hi in background)


def _capture_frame(capture: CaptureSet, ordinal: int) -> CapturedFrame:
    for frame in capture.frames:
        if frame.ordinal == ordinal:
            return frame
    raise ValueError(f"the capture has no ordinal {ordinal}")


def cmd_retime(args: argparse.Namespace) -> int:
    try:
        result = retime_render(
            args.ours,
            args.reference,
            args.out,
            args.by,
            force=args.force,
            allow_missing=args.allow_missing,
        )
    except RetimeError as err:
        print(f"retime: {err}", file=sys.stderr)
        return 2
    print(f"copied {result.copied} frames; missing {len(result.missing)} ticks")
    return 0


def render_region(
    index: bytes,
    palette: tuple[tuple[int, int, int], ...],
    box: tuple[int, int, int, int],
    scale: int,
    width: int,
) -> list[list[int]]:
    x0, y0, x1, y1 = box
    rows: list[list[int]] = []
    for y in range(y0, y1):
        row: list[int] = []
        for x in range(x0, x1):
            row += [min(255, int(v)) for v in palette[index[y * width + x]][:3]] * scale
        rows += [row] * scale
    return rows


def _regions(
    reference: Path,
    ours: Path,
    ordinal: int,
    tick: int,
    box: tuple[int, int, int, int],
    scale: int,
) -> tuple[list[list[int]], list[list[int]]]:
    """Capture ordinal `ordinal` and our film tick `tick` over `box`, both in the capture's palette."""
    capture = read_capture(reference)
    store = RenderStore(ours)
    width = store.record.geometry.width
    frame = _capture_frame(capture, ordinal)
    palette = read_capture_palette(reference / frame.palette_file)
    theirs = render_region((reference / frame.frame_file).read_bytes(), palette, box, scale, width)
    mine = render_region(read_page(store, tick).indices, palette, box, scale, width)
    return theirs, mine


def make_crop(
    reference: Path,
    ours: Path,
    ordinal: int,
    tick: int,
    box: tuple[int, int, int, int],
    scale: int,
    out: Path,
) -> None:
    """Writes capture ordinal `ordinal` over our film tick `tick` for `box` as a PNG."""
    top, bottom = _regions(reference, ours, ordinal, tick, box, scale)
    width = (box[2] - box[0]) * scale
    divider = [[255, 0, 255] * width] * 2
    write_png(out, width, top + divider + bottom)


#: The report `mise run parity` writes for ctry, so a probe reads the render it just scored.
DEFAULT_REPORT = REPO_ROOT / parity_layout.report_dir("ctry") / "report.json"


def make_side_by_side(
    reference: Path,
    ours: Path,
    ordinal: int,
    tick: int,
    box: tuple[int, int, int, int],
    scale: int,
    out: Path,
) -> None:
    """Writes capture ordinal `ordinal` left of our film tick `tick` for `box`, magenta between."""
    make_strip(reference, [ours], ordinal, tick, box, scale, out)


def make_strip(
    reference: Path,
    stores: Sequence[Path],
    ordinal: int,
    tick: int,
    box: tuple[int, int, int, int],
    scale: int,
    out: Path,
) -> None:
    """Writes capture ordinal `ordinal`, then film tick `tick` of each store, left to right.

    Panels show `box` at `scale` in the capture's palette, with a magenta divider between them.
    """
    panels: list[list[list[int]]] = []
    for store in stores:
        theirs, mine = _regions(reference, store, ordinal, tick, box, scale)
        if not panels:
            panels.append(theirs)
        panels.append(mine)
    divider = [255, 0, 255] * 2
    rows = []
    for parts in zip(*panels, strict=True):
        row: list[int] = []
        for i, part in enumerate(parts):
            row += (divider if i else []) + part
        rows.append(row)
    write_png(out, ((box[2] - box[0]) * scale + 2) * len(panels) - 2, rows)


def cmd_crop(args: argparse.Namespace) -> None:
    box = (args.x0, args.y0, args.x1, args.y1)
    make_crop(args.reference, args.ours, args.ordinal, args.tick, box, args.scale, args.out)


def shifted_pixels(pixels: list[int], dx: int, dy: int, width: int, rows: int) -> list[int]:
    """``pixels`` moved by ``(dx, dy)``, dropping any that leave the ``width`` x ``rows`` frame."""
    return [
        (p // width + dy) * width + p % width + dx
        for p in pixels
        if 0 <= p % width + dx < width and 0 <= p // width + dy < rows
    ]


def capture_actor_pixels(
    capture: bytes, silhouette: list[int], width: int, rows: int, pad: int = 8
) -> list[int]:
    """The capture's object pixels near ``silhouette``, so the capture's aircraft is left out whole.

    The capture's aircraft can be larger than our silhouette moved onto it, so every capture
    object pixel within ``pad`` pixels (in x and in y) of a silhouette pixel is taken as aircraft.
    Scenery away from every silhouette pixel stays in, even between two separated actors.
    """
    near = np.zeros(width * rows, dtype=bool)
    near[silhouette] = True
    grown = near.reshape(rows, width)
    for axis, size in ((0, rows), (1, width)):
        spread = grown.copy()
        for step in range(1, pad + 1):
            if step >= size:
                break
            if axis == 0:
                spread[step:, :] |= grown[:-step, :]
                spread[:-step, :] |= grown[step:, :]
            else:
                spread[:, step:] |= grown[:, :-step]
                spread[:, :-step] |= grown[:, step:]
        grown = spread
    return [
        int(p) for p in np.flatnonzero(grown.reshape(-1)) if is_object(capture[p], CTRY_BACKGROUND)
    ]


def world_shift(
    ours: bytes,
    capture: bytes,
    actor: list[int],
    width: int,
    rows: int,
    reach: int,
    capture_actor: list[int] | None = None,
) -> tuple[int, int, float]:
    """The ``(dx, dy)`` that best lands our non-actor pixels on equal capture indices.

    Same sign as the actor shift: our pixel at ``(x, y)`` is compared with the capture's at
    ``(x + dx, y + dy)``. Every even offset from -``reach`` to ``reach`` is tried, zero
    included; a tie goes to the smaller displacement. ``actor`` (our pixels) and
    ``capture_actor`` (capture pixels) are left out, so the aircraft does not pull the world.
    Returns the shift and the fraction of compared pixels whose indices agreed.
    """
    mine = np.frombuffer(ours, dtype=np.uint8)[: width * rows].reshape(rows, width)
    theirs = np.frombuffer(capture, dtype=np.uint8)[: width * rows].reshape(rows, width)
    flat = np.ones(width * rows, dtype=bool)
    flat[actor] = False
    keep = flat.reshape(rows, width)
    flat_theirs = np.ones(width * rows, dtype=bool)
    flat_theirs[capture_actor or []] = False
    keep_theirs = flat_theirs.reshape(rows, width)
    offsets = [2 * k for k in range(-(reach // 2), reach // 2 + 1)]
    best = (0, 0, -1.0)
    for dy in (d for d in offsets if abs(d) < rows):
        for dx in (d for d in offsets if abs(d) < width):
            ys, yt = slice(max(0, -dy), rows - max(0, dy)), slice(max(0, dy), rows - max(0, -dy))
            xs, xt = slice(max(0, -dx), width - max(0, dx)), slice(max(0, dx), width - max(0, -dx))
            mask = keep[ys, xs] & keep_theirs[yt, xt]
            agree = float(np.count_nonzero((mine[ys, xs] == theirs[yt, xt]) & mask))
            fraction = agree / max(1, int(np.count_nonzero(mask)))
            closer = abs(dx) + abs(dy) < abs(best[0]) + abs(best[1])
            if fraction > best[2] or (fraction == best[2] and closer):
                best = (dx, dy, fraction)
    return best


def cmd_shift(args: argparse.Namespace) -> None:
    capture = read_capture(args.reference)
    store = RenderStore(args.ours)
    geometry = store.record.geometry
    width, rows = geometry.width, geometry.plane_rows()
    print("film_tick actor_px dx dy hit world_dx world_dy world_agree")
    shifts: list[tuple[int, int, int, int]] = []
    for frame in read_report(args.report).per_frame:
        if frame.scored is not True:
            continue
        page = read_page(store, frame.film_tick)
        pixels = page.actor_pixels()
        if len(pixels) < args.min_pixels:
            continue
        capture_index = (
            args.reference / _capture_frame(capture, frame.ordinal).frame_file
        ).read_bytes()
        sample = pixels[::3]
        best = (-1, 0, 0)
        for dy in range(-args.reach, args.reach + 1, 2):
            for dx in range(-args.reach, args.reach + 1, 2):
                hit = 0
                for p in sample:
                    x, y = p % width + dx, p // width + dy
                    if (
                        0 <= x < width
                        and 0 <= y < rows
                        and is_object(capture_index[y * width + x], CTRY_BACKGROUND)
                    ):
                        hit += 1
                if hit > best[0]:
                    best = (hit, dx, dy)
        capture_actor = capture_actor_pixels(
            capture_index, shifted_pixels(pixels, best[1], best[2], width, rows), width, rows
        )
        world = world_shift(
            page.indices, capture_index, pixels, width, rows, args.world_reach, capture_actor
        )
        shifts.append((best[1], best[2], world[0], world[1]))
        print(
            frame.film_tick,
            len(pixels),
            best[1],
            best[2],
            round(best[0] / len(sample), 2),
            world[0],
            world[1],
            round(world[2], 2),
        )
    print(shift_summary(shifts))


def shift_summary(shifts: list[tuple[int, int, int, int]]) -> str:
    """Median actor, world and actor-minus-world shifts over ``(dx, dy, world_dx, world_dy)``."""
    if not shifts:
        return "no frame had enough actor pixels"
    adx, ady, wdx, wdy = (list(column) for column in zip(*shifts, strict=True))
    rdx = [a - w for a, w in zip(adx, wdx, strict=True)]
    rdy = [a - w for a, w in zip(ady, wdy, strict=True)]
    med = statistics.median
    return (
        f"frames {len(shifts)}: median actor dx {med(adx):g} dy {med(ady):g}; "
        f"world dx {med(wdx):g} dy {med(wdy):g}; "
        f"actor minus world dx {med(rdx):g} dy {med(rdy):g}"
    )


def actor_iou(
    report: Path,
    reference: Path,
    ours: Path,
    every: int = 2,
    pad: int = 25,
    min_pixels: int = 100,
) -> tuple[float, int]:
    """Mean actor-window IoU over every `every`-th scored frame, and the frames used."""
    capture = read_capture(reference)
    store = RenderStore(ours)
    geometry = store.record.geometry
    width, rows = geometry.width, geometry.plane_rows()
    total = 0.0
    count = 0
    scored = [frame for frame in read_report(report).per_frame if frame.scored is True]
    for frame in scored[::every]:
        page = read_page(store, frame.film_tick)
        pixels = set(page.actor_pixels())
        if len(pixels) < min_pixels:
            continue
        xs = [i % width for i in pixels]
        ys = [i // width for i in pixels]
        captured = _capture_frame(capture, frame.ordinal)
        capture_index = (reference / captured.frame_file).read_bytes()
        seen = {
            y * width + x
            for y in range(max(0, min(ys) - pad), min(rows, max(ys) + pad))
            for x in range(max(0, min(xs) - pad), min(width, max(xs) + pad))
            if is_object(capture_index[y * width + x], CTRY_BACKGROUND)
        }
        total += len(pixels & seen) / len(pixels | seen)
        count += 1
    return total / max(count, 1), count


def cmd_iou(args: argparse.Namespace) -> None:
    value, count = actor_iou(
        args.report, args.reference, args.ours, args.every, args.pad, args.min_pixels
    )
    print(f"{value:.4f} {count}")


def summary(report_path: Path, *, worst: int = 5) -> list[str]:
    """Summarise one ``report.json``: headline, class loss, worst frames and a log row."""
    report = read_report(report_path)
    ssim, iou = report.headline()
    matched = f"{report.scored_frames}/{report.frames}"
    headline = f"ssim {ssim:.4f}  iou {iou:.4f}"
    if report.mean_index_agreement_scored is not None:
        headline += f"  idx {report.mean_index_agreement_scored:.3f}"
    lines = [f"[summary] {report_path.parent.name}  {headline}  scored {matched}"]
    if report.mean_loss_by_class_scored:
        by_class = "  ".join(
            f"{name} {loss:.4f}" for name, loss in sorted(report.mean_loss_by_class_scored.items())
        )
        lines.append(f"[summary] loss by class: {by_class}")
    scored = [frame for frame in report.per_frame if frame.scored is True]
    if scored:
        lowest = sorted(scored, key=lambda frame: frame.ssim)[:worst]
        listed = ", ".join(f"tick {frame.film_tick} {frame.ssim:.3f}" for frame in lowest)
        lines.append(f"[summary] worst scored frames: {listed}")
    lines.append(
        f"[summary] log row: | <date> | `<commit>` | {matched} | {ssim:.3f} | {iou:.3f} "
        f"| <what moved and why> |"
    )
    return lines


def cmd_summary(args: argparse.Namespace) -> None:
    for line in summary(args.report, worst=args.worst):
        print(line)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(required=True)
    commands = (
        ("crop", cmd_crop),
        ("shift", cmd_shift),
        ("iou", cmd_iou),
        ("retime", cmd_retime),
        ("summary", cmd_summary),
    )
    for name, fn in commands:
        p = sub.add_parser(name)
        p.set_defaults(func=fn)
        p.add_argument(
            "--reference",
            type=Path,
            default=None,
            help="a capture directory (default: ctry's reference from references.toml)",
        )
        if name == "summary":
            p.add_argument(
                "--report",
                type=Path,
                default=DEFAULT_REPORT,
                help="report.json (default: the one mise run parity last wrote for ctry)",
            )
            p.add_argument("--worst", type=int, default=5, help="low-scoring frames to list")
            continue
        p.add_argument("--ours", type=Path, required=True, help="render directory")
        if name == "crop":
            p.add_argument("ordinal", type=int)
            p.add_argument("tick", type=int)
            for edge in ("x0", "y0", "x1", "y1"):
                p.add_argument(edge, type=int)
            p.add_argument("--scale", type=int, default=3)
            p.add_argument("--out", type=Path, required=True)
        elif name == "retime":
            p.add_argument("--out", type=Path, required=True, help="output render directory")
            p.add_argument("--by", type=int, required=True, help="ticks to shift; may be negative")
            p.add_argument("--force", action="store_true", help="replace a non-empty --out")
            p.add_argument("--allow-missing", action="store_true", help="skip absent sources")
        else:
            p.add_argument(
                "--report",
                type=Path,
                default=DEFAULT_REPORT,
                help="report.json (default: the one mise run parity last wrote for ctry)",
            )
            p.add_argument("--min-pixels", type=int, default=100)
        if name == "shift":
            p.add_argument("--reach", type=int, default=40)
            p.add_argument(
                "--world-reach", type=int, default=12, help="largest whole-frame shift tried"
            )
        if name == "iou":
            p.add_argument("--every", type=int, default=2, help="use every Nth scored frame")
            p.add_argument("--pad", type=int, default=25)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    with contextlib.ExitStack() as stack:
        if args.reference is None and args.func is not cmd_summary:
            try:
                args.reference = stack.enter_context(references.open_reference(REPO_ROOT, "ctry"))
            except references.ReferenceCaptureError as err:
                print(f"parity_probe: {err}", file=sys.stderr)
                return 1
        result = args.func(args)
    return 0 if result is None else int(result)


if __name__ == "__main__":
    sys.exit(main())
