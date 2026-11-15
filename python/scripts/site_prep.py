"""Write the research site's Starlight content from the paths ``site/published.toml`` names.

Replaces ``site/src/content/docs``, ``site/public/media`` and ``site/src/generated/sidebar.json``
with pages carrying Starlight front matter and links pointing at site pages or GitHub.

Usage: ``mise run site-prep``; ``--root DIR`` names a repository root other than this one.
Exit status: ``0`` when the content is written, ``1`` when a published file cannot be turned
into a page (the message names it), ``2`` for bad arguments.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
lazy from collections.abc import Sequence

from stunt_reel.site_pages import prepare

REPO_ROOT = Path(__file__).resolve().parents[2]


def main(argv: Sequence[str] | None = None) -> int:
    """Write the site content under ``--root`` as *argv* asks; the exit status."""
    parser = argparse.ArgumentParser(
        prog="mise run site-prep --",
        description="Write the research site's content from site/published.toml.",
    )
    parser.add_argument(
        "--root", type=Path, default=REPO_ROOT, help="the repository root (default: this one)"
    )
    args = parser.parse_args(argv)
    root: Path = args.root
    if not (root / "site" / "published.toml").is_file():
        parser.error(f"{root / 'site' / 'published.toml'} is not a file")
    try:
        pages, images = prepare(root, root / "site")
    except ValueError as err:
        print(err, file=sys.stderr)
        return 1
    print(f"wrote {pages} pages and {images} images to site/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
