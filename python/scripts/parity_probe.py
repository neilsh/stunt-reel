"""Diagnostic probes for parity work (see research/parity/probes.md).

Six subcommands read a capture directory through the artifact adapter (its
``meta.json`` names each frame's planes and palettes) and a render directory
(its ``render.json`` and render store), and a seventh reads one ``report.json``
through the same adapter:

* ``index``  - where one palette index (or a range) lands in the capture and in our
  render at the same film ticks: pixel count, bounding box and centroid in each, and the
  centroid offset. ``--film`` renders the ticks once, as ``mise run frame`` does; ``--ours``
  reads an existing render store instead.
* ``crop``   - capture over ours, one frame region, as a PNG.
* ``shift``  - best (dx, dy) that slides our actor silhouette onto the
  capture's object pixels, per scored frame.
* ``iou``    - mean IoU of our actor pixels against the capture's object
  pixels inside the actor's padded bounding box.
* ``register`` - per captured tick, the render-tick offset and the whole-page shift that best
  match the capture's backdrop edges (horizon, hills, road edges, sky bands; away from props
  and actors).
* ``retime`` - relabel an existing render by N ticks (negative allowed),
  rewriting its store and ``render.json``, so a timing hypothesis costs no
  rebuild.
* ``summary`` - the scored headline, the loss by class and the worst scored
  frames of one report: the scores a journal entry quotes, so the numbers are
  never retyped by hand.

Object pixels are capture pixels outside the film's ``background`` bands and not
index 0 or 255, within the render's viewport rows (``viewport_rows`` of 185 or less leaves out
the button bar). ``shift`` and ``iou`` take the backdrop index bands from the ``background``
field of the ``references.toml`` row of the film the capture's ``meta.json`` names, and refuse a
film whose row has none.
"""

from __future__ import annotations

import argparse
import contextlib
import re
import shutil
import statistics
import struct
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path
lazy from collections.abc import Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont
lazy from numpy.typing import NDArray

from stunt_reel import dataroot, parity_layout, parity_pipeline, references
from stunt_reel.bench import panels
from stunt_reel.bench.mismatch import index_mismatch, mismatch_fraction, readout_mask
from stunt_reel.dataroot import REPO_ROOT
from stunt_reel.matched_frames import Reference
from stunt_reel.parity_artifacts import (
    LAYER_NONE,
    LAYER_OCEAN,
    LAYER_PROP,
    LAYER_TERRAIN,
    ArtifactError,
    CaptureSet,
    RenderStore,
    read_capture,
    read_page,
    read_report,
)
from stunt_reel.parity_pipeline import RetimeError, retime_render

#: Cursor (255) and shadow/black (0) are never object pixels.
NEVER_OBJECT = (0, 255)


def write_png(path: Path, width: int, rows: Sequence[bytes | Sequence[int]]) -> None:
    """Writes an 8-bit RGB PNG; ``rows`` hold flat R, G, B bytes or triples."""

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


def background_for(reference: Path, root: Path | None = None) -> tuple[tuple[int, int], ...]:
    """The backdrop index bands of the film the capture in *reference* shows.

    They are the ``background`` field of that film's ``references.toml`` row, found by the
    ``.FLM`` stem in the capture's ``meta.json`` and read under *root* (default: the data root).
    Raises ``ReferenceCaptureError`` when the capture names no film, the film has no row, or its
    row has no ``background``: a guessed band would score another film's sky and ground as
    aircraft.
    """
    name = read_capture(reference).film.name
    if not name:
        raise references.ReferenceCaptureError(f"{reference / 'meta.json'} names no film")
    film = Path(name).stem.lower()
    try:
        row = references.read_reference(dataroot.data_root() if root is None else root, film)
    except references.ReferenceCaptureError as err:
        raise references.ReferenceCaptureError(
            f"{name}: cannot read the [{film}] row in "
            f"{parity_layout.REFERENCES_FILE.as_posix()} for its backdrop ({err})"
        ) from err
    if row.background is None:
        raise references.ReferenceCaptureError(
            f"{name}: the [{film}] row of {parity_layout.REFERENCES_FILE.as_posix()} has no "
            "`background` (inclusive [lo, hi] palette-index bands of sky and ground); record it"
        )
    return row.background


#: Where ``index`` puts the render it makes, relative to the checkout (``mise run frame``'s tree).
INDEX_DIR = Path("build") / "scratch" / "index"


@dataclass(frozen=True)
class IndexStats:
    """Where an index range lies in one plane: pixel ``count``, inclusive ``box``, ``centroid``.

    ``box`` is ``(x0, y0, x1, y1)`` and ``centroid`` is ``(x, y)`` in pixels; both are ``None``
    when ``count`` is 0.
    """

    count: int
    box: tuple[int, int, int, int] | None
    centroid: tuple[float, float] | None


def index_stats(plane: bytes, width: int, rows: int, lo: int, hi: int) -> IndexStats:
    """The pixels of the first ``rows`` rows of *plane* whose index is in ``lo..hi`` inclusive."""
    pixels = np.frombuffer(plane, dtype=np.uint8)[: width * rows].reshape(rows, width)
    ys, xs = np.nonzero((pixels >= lo) & (pixels <= hi))
    if not len(xs):
        return IndexStats(0, None, None)
    box = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
    return IndexStats(len(xs), box, (float(xs.mean()), float(ys.mean())))


def centroid_offset(ours: IndexStats, theirs: IndexStats) -> tuple[float, float] | None:
    """Our centroid minus the capture's, or ``None`` when either side has no pixel."""
    if ours.centroid is None or theirs.centroid is None:
        return None
    return ours.centroid[0] - theirs.centroid[0], ours.centroid[1] - theirs.centroid[1]


def parse_index_range(text: str) -> tuple[int, int]:
    """The inclusive ``(lo, hi)`` palette indices of ``239`` or ``236-239``."""
    match = re.fullmatch(r"(\d+)(?:-(\d+))?", text.strip())
    if match is None:
        raise ValueError(f"--index wants an index or a range such as 236-239, got {text!r}")
    lo = int(match[1])
    hi = int(match[2]) if match[2] is not None else lo
    if not 0 <= lo <= hi <= 255:
        raise ValueError(f"--index wants 0 <= lo <= hi <= 255, got {text!r}")
    return lo, hi


def parse_ticks(text: str) -> list[int]:
    """Ascending distinct film ticks from ``48,92,1009``."""
    try:
        ticks = [int(part) for part in text.split(",")]
    except ValueError:
        raise ValueError(f"--ticks wants comma-separated film ticks, got {text!r}") from None
    if any(tick < 0 for tick in ticks):
        raise ValueError(f"--ticks wants non-negative film ticks, got {text!r}")
    return sorted(set(ticks))


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


def paired_ticks(capture: CaptureSet, ticks: list[int]) -> dict[int, int]:
    """Each captured tag of *ticks* with the render tick the scorer pairs it with."""
    held = {frame.film_tick: frame.render_tick for frame in capture.frames}
    return {tick: held[tick] for tick in ticks if tick in held}


def _describe(stats: IndexStats) -> str:
    if stats.box is None or stats.centroid is None:
        return f"{stats.count} - -"
    x0, y0, x1, y1 = stats.box
    return f"{stats.count} {x0},{y0},{x1},{y1} {stats.centroid[0]:.2f},{stats.centroid[1]:.2f}"


def index_rows(reference: Path, ours: Path, ticks: list[int], lo: int, hi: int) -> list[str]:
    """One line per tick: the index range in the capture and in our render, and the offset.

    Each line reads ``tick`` then, for the capture and for ours, ``count box centroid`` (``-``
    for the box and centroid of an empty side), then ``dx dy``, our centroid minus the capture's
    (``-`` when either side is empty). A tick the capture lacks, or the render holds no page
    for, gets a line saying so.
    """
    store = RenderStore(ours)
    geometry = store.record.geometry
    width, rows = geometry.width, geometry.plane_rows()
    held = Reference(reference, store)
    found, missing = locate(held.capture, ticks)
    lines = ["tick capture(count box centroid) ours(count box centroid) dx dy"]
    for tick in ticks:
        if tick not in found:
            before, after = missing[tick]
            lines.append(f"{tick} not in the capture (nearest captured: {before}, {after})")
        elif not store.holds(paired_ticks(held.capture, [tick])[tick]):
            lines.append(f"{tick} not in the render")
        else:
            matched = held.match(found[tick])
            theirs = index_stats(matched.capture_indices(), width, rows, lo, hi)
            mine = index_stats(matched.page.indices, width, rows, lo, hi)
            offset = centroid_offset(mine, theirs)
            shown = "- -" if offset is None else f"{offset[0]:+.2f} {offset[1]:+.2f}"
            lines.append(f"{tick} {_describe(theirs)} {_describe(mine)} {shown}")
    return lines


def cmd_index(args: argparse.Namespace) -> int:
    """Print where an index range lies in the capture and in our render, per film tick."""
    try:
        ticks = parse_ticks(args.ticks)
        lo, hi = parse_index_range(args.index)
    except ValueError as err:
        print(f"parity_probe: {err}", file=sys.stderr)
        return 2
    root = dataroot.data_root()
    if args.ours is not None:
        try:
            with references.open_reference(root, args.film) as reference:
                lines = index_rows(reference, args.ours, ticks, lo, hi)
        except ArtifactError as err:
            print(f"parity_probe: {err}", file=sys.stderr)
            return 2
    else:
        problems = parity_pipeline.preflight(root, [args.film], build_required=not args.no_build)
        if problems:
            print("parity_probe: " + "\n  ".join(problems), file=sys.stderr)
            return 2
        if not args.no_build:
            parity_pipeline.build_release()
        out = REPO_ROOT / INDEX_DIR / args.film
        with parity_pipeline.reference_job(root, args.film) as job:
            shutil.rmtree(out, ignore_errors=True)
            wanted = sorted({*paired_ticks(read_capture(job.capture), ticks).values(), *ticks})
            parity_pipeline.render_film(job, out, ticks=wanted, software_only=args.software_only)
            if not (out / "render.json").exists():
                print("parity_probe: every tick is past the film's end, nothing rendered")
                return 1
            lines = index_rows(job.capture, out, ticks, lo, hi)
    print(f"[index] {args.film} index {lo if lo == hi else f'{lo}-{hi}'}")
    for line in lines:
        print(line)
    return 0


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
    store = RenderStore(ours)
    width = store.record.geometry.width
    matched = Reference(reference, store).match(ordinal, tick)
    palette = matched.capture_palette()
    theirs = render_region(matched.capture_indices(), palette, box, scale, width)
    mine = render_region(matched.page.indices, palette, box, scale, width)
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


def _strip_planes(
    reference: Path, store: Path, ordinal: int, tick: int
) -> tuple[NDArray[np.uint8], NDArray[np.uint8], NDArray[np.uint8], NDArray[np.uint16]]:
    """Capture ordinal `ordinal` and our film tick `tick` over the full raster.

    Returns the capture's palette (256 x 3), its index plane, our index plane and our layer plane.
    """
    render = RenderStore(store)
    width = render.record.geometry.width
    matched = Reference(reference, render).match(ordinal, tick)
    palette = np.array(matched.capture_palette(), dtype=np.int64)[:, :3].clip(0, 255)
    capture_idx = np.frombuffer(matched.capture_indices(), dtype=np.uint8).reshape(-1, width)
    ours = matched.page
    render_idx = np.frombuffer(ours.indices, dtype=np.uint8).reshape(-1, width)
    layer = np.array(ours.layers, dtype=np.uint16).reshape(-1, width)
    return palette.astype(np.uint8), capture_idx, render_idx, layer


#: Height of one line of a strip's key, and its font.
STRIP_KEY_LINE = 16


def _strip_key(
    columns: list[dict[str, int]], fractions: list[float], width: int
) -> NDArray[np.uint8]:
    """The strip's key band: what the two rows show, and each store's figures.

    It is *width* wide, or wider when its captions need it.
    """
    font = ImageFont.load_default(size=12)
    unknown = any(column[panels.LAYER_KEY[-1].name] for column in columns)
    lines = 2 + len(panels.LAYER_KEY) - 1 + unknown
    mismatch = " | ".join(f"{100 * f:.1f}%" for f in fractions)
    captions = (panels.COMPOSITE_TITLE, f"{panels.INDEX_MAP_TITLE}: {mismatch}")
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    needed = 4 + max(int(probe.textlength(text, font=font)) for text in captions)
    image = Image.new("RGB", (max(width, needed), lines * STRIP_KEY_LINE + 4), "white")
    draw = ImageDraw.Draw(image)
    for i, text in enumerate(captions):
        draw.text((2, i * STRIP_KEY_LINE), text, fill="black", font=font)
    panels.draw_key(draw, (2, 2 * STRIP_KEY_LINE), columns, font, STRIP_KEY_LINE)
    return np.asarray(image, dtype=np.uint8)


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
    Under each store's panel are its composite against the capture, then its index map
    (:mod:`stunt_reel.bench.panels`); a key with each store's mismatch share and per-layer counts
    closes the strip.
    """
    x0, y0, x1, y1 = box
    top: list[NDArray[np.uint8]] = []
    overlays: list[NDArray[np.uint8]] = []
    maps: list[NDArray[np.uint8]] = []
    columns: list[dict[str, int]] = []
    fractions: list[float] = []
    for store in stores:
        palette, capture_idx, render_idx, layer = _strip_planes(reference, store, ordinal, tick)
        capture_rgb, render_rgb = palette[capture_idx], palette[render_idx]
        mask = readout_mask(capture_idx)
        mismatch = index_mismatch(capture_idx, render_idx)
        crop = (slice(y0, y1), slice(x0, x1))
        if not top:
            top.append(capture_rgb[crop])
        top.append(render_rgb[crop])
        overlays.append(panels.composite(capture_rgb[crop], render_rgb[crop], mask[crop]))
        picture, counts = panels.index_map(
            capture_rgb[crop], mismatch[crop], layer[crop], mask[crop]
        )
        maps.append(picture)
        columns.append(counts)
        fractions.append(mismatch_fraction(mismatch[crop], mask[crop]))
    blank = np.full_like(top[0], 255)
    grid = [top, [blank, *overlays], [blank, *maps]]
    enlarged = [
        [np.repeat(np.repeat(p, scale, axis=0), scale, axis=1) for p in row] for row in grid
    ]
    height = enlarged[0][0].shape[0]
    divider = np.full((height, 2, 3), (255, 0, 255), dtype=np.uint8)
    bands = []
    for row in enlarged:
        parts: list[NDArray[np.uint8]] = []
        for i, part in enumerate(row):
            parts += [divider, part] if i else [part]
        bands.append(np.concatenate(parts, axis=1))
    rule = np.full((2, bands[0].shape[1], 3), (255, 0, 255), dtype=np.uint8)
    grid_rows = np.concatenate([bands[0], rule, bands[1], rule, bands[2]], axis=0)
    key = _strip_key(columns, fractions, grid_rows.shape[1])
    pad = key.shape[1] - grid_rows.shape[1]  # a key wider than a narrow crop pads it white
    grid_rows = np.pad(grid_rows, ((0, 0), (0, pad), (0, 0)), constant_values=255)
    picture = np.concatenate([grid_rows, key], axis=0)
    write_png(out, picture.shape[1], [row.tobytes() for row in picture])


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
    capture: bytes,
    silhouette: list[int],
    width: int,
    rows: int,
    background: tuple[tuple[int, int], ...],
    pad: int = 8,
) -> list[int]:
    """The capture's object pixels near ``silhouette``, so the capture's aircraft is left out whole.

    A capture pixel is an object pixel as :func:`is_object` says: not cursor or shadow
    (``NEVER_OBJECT``) and not in a ``background`` band.

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
    return [int(p) for p in np.flatnonzero(grown.reshape(-1)) if is_object(capture[p], background)]


def world_shift(
    ours: bytes,
    capture: bytes,
    actor: list[int],
    width: int,
    rows: int,
    reach: int,
    capture_actor: list[int] | None = None,
) -> tuple[int, int, float]:
    """The ``(dx, dy, agreement)`` that best lands our non-actor pixels on equal capture indices.

    Our pixel at ``(x, y)`` is compared with the capture's at ``(x + dx, y + dy)``, as for the
    actor shift. Every even offset in ±``reach`` is tried; a tie goes to the smaller displacement.
    ``actor`` (our pixels) and ``capture_actor`` (capture pixels) are excluded. *agreement* is the
    fraction of compared pixels whose indices matched.
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


#: Our layers that are backdrop (``LAYER_NONE`` sky, ocean, terrain): what ``register`` compares.
BACKDROP_LAYERS = (LAYER_NONE, LAYER_OCEAN, LAYER_TERRAIN)


def backdrop_mask(
    layers: tuple[int, ...],
    width: int,
    rows: int,
    pad: int = 8,
    kept: tuple[int, ...] = BACKDROP_LAYERS,
) -> np.ndarray:
    """Our pixels of a ``kept`` layer (default sky, ocean, terrain) farther than ``pad`` px from
    any other layer's (props, actors, credits).

    The pad leaves out the capture's props and aircraft where they sit a few pixels off ours.
    """
    plane = np.asarray(layers[: width * rows], dtype=np.uint16).reshape(rows, width)
    solid = ~np.isin(plane, kept)
    grown = solid.copy()
    for step in range(1, pad + 1):
        grown[step:, :] |= solid[:-step, :]
        grown[:-step, :] |= solid[step:, :]
    solid, grown = grown, grown.copy()
    for step in range(1, pad + 1):
        grown[:, step:] |= solid[:, :-step]
        grown[:, :-step] |= solid[:, step:]
    return ~grown


def edge_band(indices: bytes, width: int, rows: int, reach: int = 1) -> np.ndarray:
    """Pixels within ``reach`` px (in x and in y) of an index change in ``indices``.

    Flat sky and flat ground agree under any small move, so ``register`` compares only these.
    """
    plane = np.frombuffer(indices, dtype=np.uint8)[: width * rows].reshape(rows, width)
    edge = np.zeros((rows, width), dtype=bool)
    edge[:, :-1] |= plane[:, :-1] != plane[:, 1:]
    edge[:-1, :] |= plane[:-1, :] != plane[1:, :]
    grown = edge.copy()
    for step in range(1, reach + 1):
        grown[step:, :] |= edge[:-step, :]
        grown[:-step, :] |= edge[step:, :]
    edge, grown = grown, grown.copy()
    for step in range(1, reach + 1):
        grown[:, step:] |= edge[:, :-step]
        grown[:, :-step] |= edge[:, step:]
    return grown


def backdrop_agreement(
    ours: bytes, keep: np.ndarray, capture: bytes, width: int, rows: int, dx: int, dy: int
) -> float:
    """Fraction of ``keep`` pixels whose index equals the capture's at ``(x + dx, y + dy)``."""
    mine = np.frombuffer(ours, dtype=np.uint8)[: width * rows].reshape(rows, width)
    theirs = np.frombuffer(capture, dtype=np.uint8)[: width * rows].reshape(rows, width)
    ys, yt = slice(max(0, -dy), rows - max(0, dy)), slice(max(0, dy), rows - max(0, -dy))
    xs, xt = slice(max(0, -dx), width - max(0, dx)), slice(max(0, dx), width - max(0, -dx))
    mask = keep[ys, xs]
    total = int(np.count_nonzero(mask))
    return float(np.count_nonzero((mine[ys, xs] == theirs[yt, xt]) & mask)) / max(1, total)


@dataclass(frozen=True)
class Registration:
    """How well one captured tick's backdrop matches ours: as rendered, and at the best moves.

    Each best is ``(ticks, dx, dy, agreement)``: ``time`` moves only the render tick, ``page``
    only the page, ``joint`` both. Ties go to the smaller move.
    """

    tick: int
    pixels: int
    base: float
    time: tuple[int, int, int, float]
    page: tuple[int, int, int, float]
    joint: tuple[int, int, int, float]


def register(
    pages: dict[int, tuple[bytes, np.ndarray]],
    capture: bytes,
    tick: int,
    width: int,
    rows: int,
    shift_reach: int,
) -> Registration:
    """Searches render ticks ``tick + k`` (every key of ``pages``) and page shifts in ±reach.

    ``pixels`` in the result counts the compared pixels at ``k = 0`` with no shift.

    ``pages`` maps the offset ``k`` to our indices and backdrop mask at ``tick + k``; it must
    hold ``k = 0``.
    """
    grid: dict[tuple[int, int, int], float] = {}
    for k, (indices, keep) in pages.items():
        for dy in range(-shift_reach, shift_reach + 1):
            for dx in range(-shift_reach, shift_reach + 1):
                grid[k, dx, dy] = backdrop_agreement(indices, keep, capture, width, rows, dx, dy)

    def best(cells: list[tuple[int, int, int]]) -> tuple[int, int, int, float]:
        k, dx, dy = max(cells, key=lambda c: (grid[c], -(abs(c[0]) + abs(c[1]) + abs(c[2]))))
        return (k, dx, dy, grid[k, dx, dy])

    return Registration(
        tick=tick,
        pixels=int(np.count_nonzero(pages[0][1])),
        base=grid[0, 0, 0],
        time=best([c for c in grid if c[1] == 0 and c[2] == 0]),
        page=best([c for c in grid if c[0] == 0]),
        joint=best(list(grid)),
    )


def registration_row(r: Registration) -> str:
    """One ``register`` output line: base agreement, then each best move and its gain."""

    def cell(best: tuple[int, int, int, float]) -> str:
        k, dx, dy, agree = best
        return f"{k:+d} {dx:+d} {dy:+d} {agree:.3f} {agree - r.base:+.3f}"

    return f"{r.tick} {r.pixels} {r.base:.3f} | {cell(r.time)} | {cell(r.page)} | {cell(r.joint)}"


def cmd_register(args: argparse.Namespace) -> None:
    """Per captured tick: does a render-tick offset or a whole-page shift best match the backdrop?

    Compares our backdrop pixels next to an index edge (:func:`edge_band`) with the capture's.
    """
    store = RenderStore(args.ours)
    geometry = store.record.geometry
    width, rows = geometry.width, geometry.plane_rows()
    reference = Reference(args.reference, store)
    by_tick = {frame.film_tick: frame for frame in reference.capture.frames}
    print(
        "tick pixels base | time: k dx dy agree gain | page: k dx dy agree gain | joint: k dx dy agree gain"
    )
    for tick in parse_ticks(args.ticks):
        frame = by_tick.get(tick)
        if frame is None:
            print(f"{tick} not captured")
            continue
        pages: dict[int, tuple[bytes, np.ndarray]] = {}
        for k in range(-args.time_reach, args.time_reach + 1):
            try:
                page = read_page(store, frame.render_tick + k)
            except ArtifactError:
                continue
            kept = BACKDROP_LAYERS + ((LAYER_PROP,) if args.with_props else ())
            keep = backdrop_mask(page.layers, width, rows, args.pad, kept)
            pages[k] = (page.indices, keep & edge_band(page.indices, width, rows))
        if 0 not in pages or not pages[0][1].any():
            print(f"{tick} not rendered" if 0 not in pages else f"{tick} 0 no backdrop edges")
            continue
        capture = reference.matched_frame(frame, frame.render_tick).capture_indices()
        print(registration_row(register(pages, capture, tick, width, rows, args.shift_reach)))


def cmd_shift(args: argparse.Namespace) -> None:
    background = background_for(args.reference)
    store = RenderStore(args.ours)
    geometry = store.record.geometry
    width, rows = geometry.width, geometry.plane_rows()
    reference = Reference(args.reference, store)
    print("film_tick actor_px dx dy hit world_dx world_dy world_agree")
    shifts: list[tuple[int, int, int, int]] = []
    for matched in reference.from_report(read_report(args.report)):
        page = matched.page
        pixels = page.actor_pixels()
        if len(pixels) < args.min_pixels:
            continue
        capture_index = matched.capture_indices()
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
                        and is_object(capture_index[y * width + x], background)
                    ):
                        hit += 1
                if hit > best[0]:
                    best = (hit, dx, dy)
        capture_actor = capture_actor_pixels(
            capture_index,
            shifted_pixels(pixels, best[1], best[2], width, rows),
            width,
            rows,
            background,
        )
        world = world_shift(
            page.indices, capture_index, pixels, width, rows, args.world_reach, capture_actor
        )
        shifts.append((best[1], best[2], world[0], world[1]))
        print(
            matched.frame.film_tick,
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
    root: Path | None = None,
) -> tuple[float, int]:
    """Mean actor-window IoU over every `every`-th scored frame, and the frames used.

    Backdrop is the capture film's ``background`` bands (:func:`background_for`, read under *root*).
    """
    background = background_for(reference, root)
    store = RenderStore(ours)
    geometry = store.record.geometry
    width, rows = geometry.width, geometry.plane_rows()
    total = 0.0
    count = 0
    scored = list(Reference(reference, store).from_report(read_report(report)))
    for matched in scored[::every]:
        pixels = set(matched.page.actor_pixels())
        if len(pixels) < min_pixels:
            continue
        xs = [i % width for i in pixels]
        ys = [i // width for i in pixels]
        capture_index = matched.capture_indices()
        seen = {
            y * width + x
            for y in range(max(0, min(ys) - pad), min(rows, max(ys) + pad))
            for x in range(max(0, min(xs) - pad), min(width, max(xs) + pad))
            if is_object(capture_index[y * width + x], background)
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
    """Summarise one ``report.json``: headline, class loss, worst frames and the journal scores."""
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
        f"[summary] journal entry: ssim {ssim:.4f}  iou {iou:.4f}  scored {matched} at `<commit>`"
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
    index = sub.add_parser("index", help=cmd_index.__doc__)
    index.set_defaults(func=cmd_index)
    index.add_argument("--film", required=True, choices=references.reference_films(REPO_ROOT))
    index.add_argument("--ticks", required=True, help="comma list of 0-based film ticks")
    index.add_argument("--index", required=True, help="a palette index, or a range such as 236-239")
    index.add_argument(
        "--ours",
        type=Path,
        default=None,
        help="an existing render directory to read, instead of rendering --ticks now",
    )
    index.add_argument("--no-build", action="store_true", help="reuse the release binary")
    index.add_argument(
        "--software-only",
        action="store_true",
        help="render on the software adapter (lavapipe), even when a GPU is available",
    )
    reg = sub.add_parser("register", help=cmd_register.__doc__)
    reg.set_defaults(func=cmd_register)
    reg.add_argument(
        "--reference",
        type=dataroot.data_path_arg,
        default=None,
        help="a capture directory (default: ctry's reference from references.toml)",
    )
    reg.add_argument("--ours", type=Path, required=True, help="render directory")
    reg.add_argument("--ticks", required=True, help="comma list of captured film ticks")
    reg.add_argument("--time-reach", type=int, default=4, help="render ticks tried either side")
    reg.add_argument("--shift-reach", type=int, default=6, help="page shift tried either way, px")
    reg.add_argument("--pad", type=int, default=8, help="px left out around props and actors")
    reg.add_argument("--with-props", action="store_true", help="compare prop pixels too")
    for name, fn in commands:
        p = sub.add_parser(name)
        p.set_defaults(func=fn)
        p.add_argument(
            "--reference",
            type=dataroot.data_path_arg,
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
        if args.func is not cmd_summary and args.func is not cmd_index and args.reference is None:
            try:
                args.reference = stack.enter_context(
                    references.open_reference(dataroot.data_root(), "ctry")
                )
            except references.ReferenceCaptureError as err:
                print(f"parity_probe: {err}", file=sys.stderr)
                return 1
        try:
            result = args.func(args)
        except references.ReferenceCaptureError as err:
            print(f"parity_probe: {err}", file=sys.stderr)
            return 1
    return 0 if result is None else int(result)


if __name__ == "__main__":
    sys.exit(main())
