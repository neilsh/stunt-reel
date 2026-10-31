"""Build the unpatched and the Patch #3 game trees under the data root, with a manifest.

Copies ``corpus/stuntisl`` twice into ``<data root>/builds/``: ``unpatched`` as shipped and
``patched`` with ``corpus/patches`` applied as ``PATSI.BAT`` applies it, then writes
``builds/patch3-manifest.json`` listing every file added, replaced, deleted or restored, with
sizes and SHA-256. The corpus is only read (ADR 0022); a second run rebuilds both trees.
Reads proprietary files from the local, gitignored corpus; nothing it writes is committed.

Usage: mise run game-builds [-- --out DIR]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from stunt_reel import dataroot, game_builds
from stunt_reel.dataroot import ensure_links_or_report

GAME: Path = Path("corpus/stuntisl")
PATCHES: Path = Path("corpus/patches")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=f"directory receiving the two trees and the manifest (default <data root>/{game_builds.BUILDS_DIR})",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    """Build both trees and print the manifest's changes; 0 on success."""
    out = args.out if args.out is not None else dataroot.data_root() / game_builds.BUILDS_DIR
    try:
        manifest = game_builds.build_trees(
            dataroot.REPO_ROOT / GAME, dataroot.REPO_ROOT / PATCHES, out
        )
    except (game_builds.BuildError, OSError) as exc:
        print(f"[game-builds] {exc}", file=sys.stderr)
        return 1
    for change in manifest["changes"]:
        old = change["old_bytes"] if change["old_bytes"] is not None else "-"
        new = change["new_bytes"] if change["new_bytes"] is not None else "-"
        print(f"[game-builds] {change['action']:8} {change['path']:18} {old:>8} -> {new:>8}")
    for name in game_builds.BUILD_NAMES:
        print(f"[game-builds] {name}: {out / name}")
    print(f"[game-builds] manifest: {out / game_builds.MANIFEST_NAME}")
    return 0


def main() -> int:
    """Link the corpus if needed, then build."""
    if not ensure_links_or_report("mise run game-builds"):
        return 2
    return run(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
