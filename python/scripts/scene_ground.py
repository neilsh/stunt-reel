"""Walk the scene tree in ``PLAYONE.EXE``'s load image and compare its Ground with ``MAP.BIN``.

Takes the load image written by ``mise run unlzexe`` and a ``MAP.BIN`` copy, and prints the
node census, the Ground polygons by colour, and the polygons and patches that do not match.
Reads proprietary files from the gitignored ``build/`` and ``corpus/``; it prints counts,
indices and colour numbers only (see ``NOTICE.md``). Evidence:
``research/playone-exe/world-scene.md`` section 2.1.

Usage: mise run scene-ground -- build/re/playone.img corpus/siarchive/Developer/FreeFlight/SIDATA/MAP.BIN
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

from stunt_reel import scene_tree
from stunt_reel.dataroot import REPO_ROOT, ensure_links_or_report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", type=Path, help="unpacked PLAYONE.EXE load image")
    parser.add_argument("map_bin", type=Path, help="MAP.BIN to compare against")
    return parser.parse_args(argv)


def report(walked: scene_tree.TreeWalk, result: scene_tree.Comparison) -> str:
    """The printed summary."""
    nodes = sum(walked.node_types.values())
    colours = Counter(p.colour & 0xFF for p in walked.polygons)
    lines = [
        f"nodes {nodes}, unknown types {len(walked.unknown)}, leaf placements {sum(walked.leaves.values())}",
        f"ground polygons {len(walked.polygons)}: "
        + ", ".join(f"{c}x{n}" for c, n in sorted(colours.items())),
        f"same anchors and colour as MAP.BIN: {result.same}",
    ]
    lines += [
        f"recoloured: tree {p.colour} vs patch {m.index} colour {m.colour}"
        for p, m in result.recoloured
    ]
    lines += [
        f"tree only: {p.kind} at 0x{p.offset:04X} colour {p.colour} anchors {list(p.anchors)}"
        for p in result.tree_only
    ]
    lines += [
        f"MAP.BIN only: patch {m.index} colour {m.colour} anchors {list(m.anchors)}"
        for m in result.map_only
    ]
    return "\n".join(lines)


def _needs_corpus(*paths: Path) -> bool:
    """True when any path lies under the repository's ``corpus/`` link.

    The link points into the data root, outside the checkout, so a path spelled through it is
    compared before resolving, and a resolved path is compared with the link's target.
    """
    link = (REPO_ROOT / "corpus").absolute()
    target = link.resolve()

    def under(path: Path) -> bool:
        spelled = Path(os.path.normpath(path.absolute()))
        resolved = path.resolve()
        return link in (spelled, *spelled.parents) or target in (resolved, *resolved.parents)

    return any(under(p) for p in paths)


def run(args: argparse.Namespace) -> int:
    """Print the report; 0 on success."""
    if _needs_corpus(args.image, args.map_bin) and not ensure_links_or_report("scene_ground"):
        return 2
    try:
        image = args.image.read_bytes()
        map_bin = args.map_bin.read_bytes()
        scene_tree.check_map_bin(map_bin)
        walked = scene_tree.walk(scene_tree.tree_segment(image))
    except (OSError, ValueError) as exc:
        print(f"[scene-ground] {exc}", file=sys.stderr)
        return 1
    if walked.unknown:
        for offset, kind in walked.unknown:
            print(f"[scene-ground] unknown node type {kind} at 0x{offset:04X}", file=sys.stderr)
        return 1
    print(report(walked, scene_tree.compare(walked.polygons, scene_tree.parse_map_bin(map_bin))))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    return run(parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
