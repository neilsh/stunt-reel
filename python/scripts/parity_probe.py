"""Diagnostic probes for parity work (see research/parity/probes.md).

Four subcommands read a capture directory (``tick_%04d.idx`` by ordinal plus
``palettes_%04d.json``) and a render directory (``tick_%05d.idx`` and
``.layer`` by film tick), both written by the parity loop:

* ``crop``   - capture over ours, one frame region, as a PNG.
* ``shift``  - best (dx, dy) that slides our actor silhouette onto the
  capture's object pixels, per scored frame.
* ``iou``    - mean IoU of our actor pixels against the capture's object
  pixels inside the actor's padded bounding box.
* ``retime`` - relabel an existing render by N ticks (negative allowed) and
  rebuild its palette sidecar, so a timing hypothesis costs no rebuild.

Object pixels are capture pixels that are not sky, ground ramp, button bar or
cursor; the index ranges default to ``CTRY.FLM`` and are per film.
"""

from __future__ import annotations

import argparse
import json
import shutil
import struct
import sys
import zlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from parity_inputs import capture_ticks, load_palette, load_sidecar, scored_frames

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


#: Files `--headless` writes per rendered tick, beside the frame PNG.
RENDER_SUFFIXES = (".png", ".idx", ".layer")
#: Sidecar `stunt-cli --headless` writes beside its frames (`PALETTE_SIDECAR_NAME`).
RENDER_SIDECAR = "palette_controls.json"


class RetimeError(RuntimeError):
    """A retime request that cannot be served: a busy output directory or missing ticks."""


@dataclass(frozen=True)
class RetimeResult:
    """What a retime wrote: target frames copied, targets with no source, a rebuilt sidecar."""

    copied: int
    missing: list[int]
    palette_written: bool


def plan_retime(ticks: Iterable[int], by: int) -> list[tuple[int, int]]:
    """`(target, source)` per distinct captured tick: target `t` shows source `t + by`."""
    return [(tick, tick + by) for tick in sorted(set(ticks))]


def rebuild_palette(sidecar: dict[str, Any], pairs: Iterable[tuple[int, int]]) -> dict[str, Any]:
    """Copies each source tick's palette entry onto its target tick; invents no entry."""
    by_tick = {int(entry["tick"]): entry for entry in sidecar.get("ticks", [])}
    ticks: list[dict[str, Any]] = []
    for target, source in pairs:
        entry = by_tick.get(source)
        if entry is None:
            continue
        shifted = dict(entry)
        shifted["tick"] = target
        ticks.append(shifted)
    rebuilt = {key: value for key, value in sidecar.items() if key != "ticks"}
    rebuilt["ticks"] = ticks
    return rebuilt


def retime_render(
    ours: Path,
    reference: Path,
    out: Path,
    by: int,
    *,
    force: bool = False,
    allow_missing: bool = False,
) -> RetimeResult:
    """Writes `out` as the render in `ours` re-labelled by `by` ticks.

    Target `t` gets the frame, index and layer planes of source `t + by`, and the
    sidecar's palette entry is copied from the source tick and relabelled. Ticks whose
    source is absent are reported and, with `allow_missing`, skipped; otherwise they
    are an error. A non-empty `out` is refused unless `force`.
    """
    pairs = plan_retime(capture_ticks(reference), by)
    if out.exists() and any(out.iterdir()) and not force:
        raise RetimeError(f"{out} is not empty; pass --force to replace its frames")
    missing = [
        target
        for target, source in pairs
        if not all((ours / f"tick_{source:05d}{ext}").is_file() for ext in RENDER_SUFFIXES)
    ]
    if missing and not allow_missing:
        raise RetimeError(
            f"missing render for {len(missing)} tick(s), first {missing[0]}; "
            "pass --allow-missing to skip them"
        )
    skipped = set(missing)
    out.mkdir(parents=True, exist_ok=True)
    copied = 0
    for target, source in pairs:
        if target in skipped:
            continue
        for ext in RENDER_SUFFIXES:
            shutil.copyfile(ours / f"tick_{source:05d}{ext}", out / f"tick_{target:05d}{ext}")
        copied += 1
    palette_written = False
    sidecar_path = ours / RENDER_SIDECAR
    if sidecar_path.is_file():
        sidecar = load_sidecar(sidecar_path)
        rebuilt = rebuild_palette(sidecar, [p for p in pairs if p[0] not in skipped])
        (out / RENDER_SIDECAR).write_text(json.dumps(rebuilt, indent=2) + "\n", encoding="utf-8")
        palette_written = True
    return RetimeResult(copied, missing, palette_written)


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
    if not result.palette_written:
        print(
            f"retime: {args.ours} has no {RENDER_SIDECAR}; {args.out} has none",
            file=sys.stderr,
        )
    print(f"copied {result.copied} frames; missing {len(result.missing)} ticks")
    return 0


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


def make_crop(
    reference: Path,
    ours: Path,
    ordinal: int,
    tick: int,
    box: tuple[int, int, int, int],
    scale: int,
    out: Path,
) -> None:
    """Writes capture ordinal ``ordinal`` over our film tick ``tick`` for ``box`` as a PNG."""
    palette = load_palette(reference / f"palettes_{ordinal:04d}.json")
    capture = (reference / f"tick_{ordinal:04d}.idx").read_bytes()
    render = (ours / f"tick_{tick:05d}.idx").read_bytes()
    top = render_region(capture, palette, box, scale)
    bottom = render_region(render, palette, box, scale)
    width = (box[2] - box[0]) * scale
    divider = [[255, 0, 255] * width] * 2
    write_png(out, width, top + divider + bottom)


def cmd_crop(args: argparse.Namespace) -> None:
    box = (args.x0, args.y0, args.x1, args.y1)
    make_crop(args.reference, args.ours, args.ordinal, args.tick, box, args.scale, args.out)


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


def actor_iou(
    report: Path,
    reference: Path,
    ours: Path,
    every: int = 2,
    pad: int = 25,
    min_pixels: int = 100,
) -> tuple[float, int]:
    """Mean actor-window IoU over every ``every``-th scored frame, and the frames used."""
    total = 0.0
    count = 0
    for frame in scored_frames(report)[::every]:
        layer = (ours / f"tick_{frame['film_tick']:05d}.layer").read_bytes()
        pixels = set(actor_pixels(layer))
        if len(pixels) < min_pixels:
            continue
        xs = [i % WIDTH for i in pixels]
        ys = [i // WIDTH for i in pixels]
        capture = (reference / f"tick_{frame['ordinal']:04d}.idx").read_bytes()
        seen = {
            y * WIDTH + x
            for y in range(max(0, min(ys) - pad), min(ROWS, max(ys) + pad))
            for x in range(max(0, min(xs) - pad), min(WIDTH, max(xs) + pad))
            if is_object(capture[y * WIDTH + x], CTRY_BACKGROUND)
        }
        total += len(pixels & seen) / len(pixels | seen)
        count += 1
    return total / max(count, 1), count


def cmd_iou(args: argparse.Namespace) -> None:
    value, count = actor_iou(
        args.report, args.reference, args.ours, args.every, args.pad, args.min_pixels
    )
    print(f"{value:.4f} {count}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(required=True)
    commands = (("crop", cmd_crop), ("shift", cmd_shift), ("iou", cmd_iou), ("retime", cmd_retime))
    for name, fn in commands:
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
        elif name == "retime":
            p.add_argument("--out", type=Path, required=True, help="output render directory")
            p.add_argument("--by", type=int, required=True, help="ticks to shift; may be negative")
            p.add_argument("--force", action="store_true", help="replace a non-empty --out")
            p.add_argument("--allow-missing", action="store_true", help="skip absent sources")
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
    result = args.func(args)
    return 0 if result is None else int(result)


if __name__ == "__main__":
    sys.exit(main())
