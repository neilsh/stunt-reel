"""Look for every route by which ``PLAYONE`` could draw the ``MAP.BIN`` patches its tree lacks.

For each active ``MAP.BIN`` record with no Ground polygon in the image's scene tree, it reports:
the record's anchors and their heights in the image's own anchor table; whether each given
``SCENERY.scn`` is the image's tree (word for word, links aside) and has a polygon for it; every
byte match of its polygon, in tree or ``MAP.BIN`` form and any vertex order, in the image and in
the ``--scan`` files; any ``OP_TAP`` operand in those files naming one of its anchors; the
tree polygons under its centroid; the shapes the tree places inside its outline; and whether
the records' ``pos`` word or ``a`` chain sets them apart from the drawn ones. A control line
counts the matched records whose polygon the same byte search finds in the image. Reads proprietary files from the gitignored ``build/`` and
``corpus/``; it prints counts, offsets, indices and colour numbers only (see ``NOTICE.md``).
Evidence: ``research/playone-exe/world-scene.md`` section 2.1.

Usage: mise run scene-patches -- build/re/playone.img corpus/siarchive/Developer/FreeFlight/SIDATA/MAP.BIN
    --scn corpus/siarchive/Developer/FreeFlight/SIDATA/SCENERY.scn --scan corpus/stuntisl
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from itertools import chain
from pathlib import Path

from stunt_reel import scene_tree
from stunt_reel.dataroot import data_path_arg, read_data_file_or_report

#: Shape ids listed per patch before the list is cut short.
PLACED_SHOWN = 16


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", type=Path, help="unpacked PLAYONE.EXE load image")
    parser.add_argument("map_bin", type=Path, help="MAP.BIN to compare against")
    parser.add_argument(
        "--scn", type=Path, action="append", default=[], help="a SCENERY.scn to compare (repeat)"
    )
    parser.add_argument(
        "--scan",
        type=data_path_arg,
        action="append",
        default=[],
        help="file or directory (searched recursively) to byte-scan (repeat)",
    )
    return parser.parse_args(argv)


def scan_files(paths: list[Path]) -> list[tuple[str, Path]]:
    """The files named, and every file under each directory named, labelled from that name."""
    files: list[tuple[str, Path]] = []
    for path in paths:
        if not path.is_dir():
            files.append((path.name, path))
            continue
        for found in sorted(p for p in path.rglob("*") if p.is_file()):
            files.append((found.relative_to(path.parent).as_posix(), found))
    return files


def control(image: bytes, matched: list[scene_tree.MapPatch]) -> str:
    """How many matched records' polygons the byte search finds in the image."""
    found = sum(
        1
        for patch in matched
        if any(
            image.find(body) >= 0 for body in scene_tree.polygon_bodies(patch.anchors)["pointer"]
        )
    )
    return f"control: polygon bytes of {found} of {len(matched)} matched records found in the image"


def record_fields(map_bin: bytes, lost: set[int]) -> list[str]:
    """Whether a record's ``pos`` word or its ``a`` chain sets the lost records apart."""
    links = scene_tree.map_links(map_bin)
    drawn = {p.index for p in scene_tree.parse_map_bin(map_bin)} - lost
    lines = []
    for pos in sorted({links[i][0] for i in lost}):
        same = [i for i in sorted(drawn) if links[i][0] == pos]
        lines.append(f"pos 0x{pos:04X}: on {len(same)} drawn records {same}")
    chains = [
        "->".join(map(str, c)) + (" (no polygon)" if lost & set(c) else "")
        for c in scene_tree.link_chains(links)
        if len(c) < 10
    ]
    lines.append("a chains no record links into (under 10 long): " + ", ".join(chains))
    return lines


def polygon_hits(name: str, data: bytes, patch: scene_tree.MapPatch) -> list[str]:
    """Where ``patch``'s polygon occurs in ``data``, in either byte form."""
    return [
        f"{name}@0x{at:X} ({form})"
        for form, needles in scene_tree.polygon_bodies(patch.anchors).items()
        for needle in sorted(needles)
        for at in scene_tree.find_all(data, needle)
    ]


def describe(
    patch: scene_tree.MapPatch,
    image: bytes,
    polygons: list[scene_tree.GroundPolygon],
    hits: list[str],
    tapped: Counter[int],
    placed: set[scene_tree.Placement],
) -> list[str]:
    """The report lines for one patch."""
    heights = []
    for a in patch.anchors:
        xyz = scene_tree.image_anchor(image, a)
        heights.append("absent" if xyz is None else f"{a}:{xyz}")
    lines = [f"patch {patch.index} colour {patch.colour}: image anchors " + ", ".join(heights)]
    lines.append("  polygon bytes: " + (", ".join(hits) if hits else "none"))
    taps = {a: tapped[a] for a in patch.anchors if tapped[a]}
    lines.append(f"  OP_TAP operands naming its anchors: {taps or 'none'}")
    points = [scene_tree.image_anchor(image, a) for a in patch.anchors]
    if all(p is not None for p in points):
        xs = [p[0] for p in points if p is not None]
        zs = [p[2] for p in points if p is not None]
        centroid = (sum(xs) / len(xs), sum(zs) / len(zs))
        under = []
        for poly in polygons:
            outline = [scene_tree.image_anchor(image, a) for a in poly.anchors]
            if all(o is not None for o in outline) and scene_tree.covers(
                centroid, [(o[0], o[2]) for o in outline if o is not None]
            ):
                under.append(f"{poly.kind} 0x{poly.offset:04X} colour {poly.colour}")
        where = f"({centroid[0]:.0f}, {centroid[1]:.0f})"
        lines.append(f"  tree polygons under centroid {where}: {', '.join(under) or 'none'}")
        plan = [(p[0], p[2]) for p in points if p is not None]
        inside = Counter(s.obj for s in placed if scene_tree.covers((s.x, s.z), plan))
        shown = ", ".join(f"0x{obj:04X}x{n}" for obj, n in sorted(inside.items())[:PLACED_SHOWN])
        more = f", ... ({len(inside)} shapes)" if len(inside) > PLACED_SHOWN else ""
        lines.append(f"  shapes placed inside it: {shown or 'none'}{more}")
    return lines


def run(args: argparse.Namespace) -> int:
    """Print the report; 0 on success."""
    image = read_data_file_or_report("scene_patches", args.image)
    map_bin = read_data_file_or_report("scene_patches", args.map_bin)
    scns = {path: read_data_file_or_report("scene_patches", path) for path in args.scn}
    if image is None or map_bin is None or any(v is None for v in scns.values()):
        return 2
    try:
        scene_tree.check_map_bin(map_bin)
        segment = scene_tree.tree_segment(image)
        walked = scene_tree.walk(segment)
        placed = scene_tree.placements(segment)
        patches = scene_tree.parse_map_bin(map_bin)
        result = scene_tree.compare(walked.polygons, patches)
        lines = [
            (
                f"image tree: {len(walked.polygons)} ground polygons, {len(walked.unknown)} "
                f"unknown nodes, {len(result.map_only)} active MAP.BIN records without one"
            )
        ]
        for path, scn in scns.items():
            if scn is None:
                continue
            converted = scene_tree.scn_segment(scn)
            diff = scene_tree.diff_segments(converted, segment, walked.link_fields)
            own = scene_tree.walk(converted, link_bias=scene_tree.SCN_LINK_BIAS)
            same = [(p.offset, p.colour, p.anchors) for p in own.polygons] == [
                (p.offset, p.colour, p.anchors) for p in walked.polygons
            ]
            missing = scene_tree.compare(own.polygons, patches).map_only
            lines.append(
                f"{path.as_posix()}: {diff.words} words, {diff.link_words} of "
                f"{len(walked.link_fields)} link fields {scene_tree.SCN_LINK_BIAS} higher, "
                f"{len(diff.other)} other differences {[hex(o) for o in diff.other[:8]]}; {len(own.polygons)} ground "
                f"polygons, {'the same' if same else 'NOT the same'} as the image's; "
                f"records without one: {[m.index for m in missing]}"
            )
    except ValueError as exc:
        print(f"[scene-patches] {exc}", file=sys.stderr)
        return 1
    files = scan_files(args.scan)
    hits: dict[int, list[str]] = {m.index: [] for m in result.map_only}
    tapped: Counter[int] = Counter()
    for name, data in chain([("image", image)], ((n, f.read_bytes()) for n, f in files)):
        tapped.update(scene_tree.tap_anchors(data))
        for patch in result.map_only:
            hits[patch.index] += polygon_hits(name, data, patch)
    lines.append(
        f"scanned the image and {len(files)} files: {sum(tapped.values())} OP_TAP anchor operands, "
        f"anchors {min(tapped, default=0)}..{max(tapped, default=0)}"
    )
    lost = {m.index for m in result.map_only}
    lines.append(control(image, [p for p in patches if p.index not in lost]))
    lines += record_fields(map_bin, lost)
    for patch in result.map_only:
        lines += describe(patch, image, walked.polygons, hits[patch.index], tapped, placed)
    print("\n".join(lines))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    return run(parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
