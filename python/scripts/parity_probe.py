"""Diagnostic probes for parity work (see research/parity/probes.md).

Four subcommands read a capture directory through the artifact adapter (its
``meta.json`` names each frame's planes and palettes) and a render directory
(``render.json``, or the legacy ``palette_controls.json`, plus ``tick_%05d``
planes), and a fifth reads one ``report.json`` through the same adapter:

* ``crop``   - capture over ours, one frame region, as a PNG.
* ``shift``  - best (dx, dy) that slides our actor silhouette onto the
  capture's object pixels, per scored frame.
* ``iou``    - mean IoU of our actor pixels against the capture's object
  pixels inside the actor's padded bounding box.
* ``retime`` - relabel an existing render by N ticks (negative allowed),
  rewriting its ``render.json`` and legacy palette sidecar, so a timing
  hypothesis costs no rebuild.
* ``summary`` - the scored headline, the loss by class, the worst scored
  frames and the ``research/parity/log.md`` row for one report, so the numbers
  are never retyped by hand.

Object pixels are capture pixels that are not sky, ground ramp, button bar or
cursor; the index ranges default to ``CTRY.FLM`` and are per film.
"""

from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path

from stunt_reel import parity_layout
from stunt_reel.parity_artifacts import (
    LAYER_FIRST_ACTOR,
    LEGACY_SIDECAR,
    CapturedFrame,
    CaptureSet,
    Geometry,
    RenderControls,
    open_render,
    read_capture,
    read_capture_palette,
    read_report,
    render_plane_paths,
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


def actor_pixels(layer: bytes, geometry: Geometry) -> list[int]:
    """Pixel offsets (within the viewport) drawn by an actor (layer id >= first actor)."""
    width, rows = geometry.width, geometry.plane_rows()
    return [pixel for pixel in range(width * rows) if layer[2 * pixel] >= LAYER_FIRST_ACTOR]


def _geometry(capture: CaptureSet, controls: RenderControls) -> Geometry:
    """The render's geometry, falling back to the capture's for a legacy directory."""
    return controls.geometry if controls.geometry is not None else capture.geometry


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
    if not result.palette_written:
        print(
            f"retime: {args.ours} has no {LEGACY_SIDECAR}; {args.out} has none",
            file=sys.stderr,
        )
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
    capture = read_capture(reference)
    geometry = _geometry(capture, open_render(ours))
    frame = _capture_frame(capture, ordinal)
    palette = read_capture_palette(reference / frame.palette_file)
    capture_index = (reference / frame.frame_file).read_bytes()
    render_index = render_plane_paths(ours, tick)[0].read_bytes()
    top = render_region(capture_index, palette, box, scale, geometry.width)
    bottom = render_region(render_index, palette, box, scale, geometry.width)
    width = (box[2] - box[0]) * scale
    divider = [[255, 0, 255] * width] * 2
    write_png(out, width, top + divider + bottom)


def cmd_crop(args: argparse.Namespace) -> None:
    box = (args.x0, args.y0, args.x1, args.y1)
    make_crop(args.reference, args.ours, args.ordinal, args.tick, box, args.scale, args.out)


def cmd_shift(args: argparse.Namespace) -> None:
    capture = read_capture(args.reference)
    geometry = _geometry(capture, open_render(args.ours))
    width, rows = geometry.width, geometry.plane_rows()
    for frame in read_report(args.report).per_frame:
        if frame.scored is not True:
            continue
        layer = render_plane_paths(args.ours, frame.film_tick)[1].read_bytes()
        pixels = actor_pixels(layer, geometry)
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
        print(frame.film_tick, len(pixels), best[1], best[2], round(best[0] / len(sample), 2))


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
    geometry = _geometry(capture, open_render(ours))
    width, rows = geometry.width, geometry.plane_rows()
    total = 0.0
    count = 0
    scored = [frame for frame in read_report(report).per_frame if frame.scored is True]
    for frame in scored[::every]:
        layer = render_plane_paths(ours, frame.film_tick)[1].read_bytes()
        pixels = set(actor_pixels(layer, geometry))
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


def main() -> int:
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
        p.add_argument("--reference", type=Path, default=parity_layout.capture_dir("ctry"))
        if name == "summary":
            p.add_argument(
                "--report",
                type=Path,
                default=parity_layout.manual_report_dir("ctry") / "report.json",
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
                default=parity_layout.manual_report_dir("ctry") / "report.json",
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
