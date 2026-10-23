"""Diagnostic probes for parity work (see research/parity/probes.md).

Three subcommands read a capture directory (``tick_%04d.idx`` by ordinal plus
``palettes_%04d.json``) and a render directory (``tick_%05d.idx`` and
``.layer`` by film tick), both written by the parity loop:

* ``crop``   - capture over ours, one frame region, as a PNG.
* ``shift``  - best (dx, dy) that slides our actor silhouette onto the
  capture's object pixels, per scored frame.
* ``iou``    - mean IoU of our actor pixels against the capture's object
  pixels inside the actor's padded bounding box.

Object pixels are capture pixels that are not sky, ground ramp, button bar or
cursor; the index ranges default to ``CTRY.FLM`` and are per film.
"""

from __future__ import annotations

import argparse
import json
import struct
import zlib
from pathlib import Path

WIDTH = 320
ROWS = 185
ACTOR_LAYER_MIN = 16
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


def actor_pixels(layer: bytes) -> list[int]:
    """Pixel offsets (within the viewport) drawn by an actor (layer id >= 16)."""
    return [i for i in range(ROWS * WIDTH) if layer[2 * i] >= ACTOR_LAYER_MIN]


def scored_frames(report: Path) -> list[dict[str, int]]:
    """``film_tick`` and ``ordinal`` of every scored frame in ``report.json``."""
    data = json.loads(report.read_text(encoding="utf-8"))
    return [f for f in data["per_frame"] if f["scored"]]


def render_region(
    index: bytes, palette: list[list[int]], box: tuple[int, int, int, int], scale: int
) -> list[list[int]]:
    x0, y0, x1, y1 = box
    rows: list[list[int]] = []
    for y in range(y0, y1):
        row: list[int] = []
        for x in range(x0, x1):
            row += [min(255, int(v)) for v in palette[index[y * WIDTH + x]][:3]] * scale
        rows += [row] * scale
    return rows


def cmd_crop(args: argparse.Namespace) -> None:
    palette = json.loads(
        (args.reference / f"palettes_{args.ordinal:04d}.json").read_text(encoding="utf-8")
    )
    capture = (args.reference / f"tick_{args.ordinal:04d}.idx").read_bytes()
    ours = (args.ours / f"tick_{args.tick:05d}.idx").read_bytes()
    box = (args.x0, args.y0, args.x1, args.y1)
    top = render_region(capture, palette, box, args.scale)
    bottom = render_region(ours, palette, box, args.scale)
    width = (args.x1 - args.x0) * args.scale
    divider = [[255, 0, 255] * width] * 2
    write_png(args.out, width, top + divider + bottom)


def cmd_shift(args: argparse.Namespace) -> None:
    for frame in scored_frames(args.report):
        layer = (args.ours / f"tick_{frame['film_tick']:05d}.layer").read_bytes()
        pixels = actor_pixels(layer)
        if len(pixels) < args.min_pixels:
            continue
        capture = (args.reference / f"tick_{frame['ordinal']:04d}.idx").read_bytes()
        sample = pixels[::3]
        best = (-1, 0, 0)
        for dy in range(-args.reach, args.reach + 1, 2):
            for dx in range(-args.reach, args.reach + 1, 2):
                hit = 0
                for p in sample:
                    x, y = p % WIDTH + dx, p // WIDTH + dy
                    if (
                        0 <= x < WIDTH
                        and 0 <= y < ROWS
                        and is_object(capture[y * WIDTH + x], CTRY_BACKGROUND)
                    ):
                        hit += 1
                if hit > best[0]:
                    best = (hit, dx, dy)
        print(frame["film_tick"], len(pixels), best[1], best[2], round(best[0] / len(sample), 2))


def cmd_iou(args: argparse.Namespace) -> None:
    total = 0.0
    count = 0
    for frame in scored_frames(args.report)[:: args.every]:
        layer = (args.ours / f"tick_{frame['film_tick']:05d}.layer").read_bytes()
        ours = set(actor_pixels(layer))
        if len(ours) < args.min_pixels:
            continue
        xs = [i % WIDTH for i in ours]
        ys = [i // WIDTH for i in ours]
        pad = args.pad
        capture = (args.reference / f"tick_{frame['ordinal']:04d}.idx").read_bytes()
        seen = {
            y * WIDTH + x
            for y in range(max(0, min(ys) - pad), min(ROWS, max(ys) + pad))
            for x in range(max(0, min(xs) - pad), min(WIDTH, max(xs) + pad))
            if is_object(capture[y * WIDTH + x], CTRY_BACKGROUND)
        }
        total += len(ours & seen) / len(ours | seen)
        count += 1
    print(f"{total / max(count, 1):.4f} {count}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(required=True)
    for name, fn in (("crop", cmd_crop), ("shift", cmd_shift), ("iou", cmd_iou)):
        p = sub.add_parser(name)
        p.set_defaults(func=fn)
        p.add_argument("--reference", type=Path, default=Path("build/parity/reference/ctry"))
        p.add_argument("--ours", type=Path, required=True, help="render directory")
        if name == "crop":
            p.add_argument("ordinal", type=int)
            p.add_argument("tick", type=int)
            for edge in ("x0", "y0", "x1", "y1"):
                p.add_argument(edge, type=int)
            p.add_argument("--scale", type=int, default=3)
            p.add_argument("--out", type=Path, required=True)
        else:
            p.add_argument(
                "--report", type=Path, default=Path("build/parity/report/ctry/report.json")
            )
            p.add_argument("--min-pixels", type=int, default=100)
        if name == "shift":
            p.add_argument("--reach", type=int, default=40)
        if name == "iou":
            p.add_argument("--every", type=int, default=2, help="use every Nth scored frame")
            p.add_argument("--pad", type=int, default=25)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
