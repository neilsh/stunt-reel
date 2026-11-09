"""Pack, upload or fetch the game archives Claude Code cloud sessions use (ADR 0039).

``pack`` builds each archive from the data root into ``target/cloud-assets/`` and rewrites its
pin in ``manifests/cloud-assets.toml``; commit that file. ``upload`` puts the packed archives
in the bucket with the owner's ``wrangler login``. ``fetch`` downloads and unpacks each archive
its folder does not hold yet (ADR 0042), with the R2 key pair from ``R2_ACCOUNT_ID``, ``R2_ACCESS_KEY_ID`` and
``R2_SECRET_ACCESS_KEY``. ``status`` shows each pin, folder and packed file. ``verify`` downloads each pinned archive
into a temporary directory, checks its sha256 and unpacks it, never touching the data root, and
exits 1 if any fails. Each takes archive
names, all by default.

Exit status: 0 done, 1 an archive could not be handled or verified, 2 the R2 variables are unset.

Usage: ``mise run cloud-assets -- [--data-root DIR] pack|upload|fetch|status|verify [ARCHIVE...]
[--replace-unmarked]``
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from stunt_reel import cloud_assets
from stunt_reel.dataroot import REPO_ROOT, data_root_flag
from stunt_reel.references import ReferenceCaptureError

#: Where ``pack`` writes and ``upload`` and ``status`` read the archives.
OUT_DIR = REPO_ROOT / "target" / "cloud-assets"


def _pack(manifest: cloud_assets.Manifest, names: list[str], root: Path) -> list[str]:
    """Packs *names* (all when empty) into OUT_DIR, rewriting the manifest after each; one line each."""
    lines = []
    for name in names or list(manifest.archives):
        before = cloud_assets.archive_named(manifest, name).bytes
        archive = cloud_assets.pack(manifest, name, root, OUT_DIR)
        manifest = cloud_assets.with_archive(manifest, archive)
        # Written after each archive, so a later failure keeps the pins already made.
        cloud_assets.MANIFEST_PATH.write_text(
            cloud_assets.manifest_text(manifest), encoding="utf-8", newline="\n"
        )
        size = archive.bytes or 0
        change = "new" if before is None else f"{size - before:+,} bytes"
        lines.append(f"packed {name}: {size:,} bytes ({change}) -> {archive.key}")
    return lines


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point; returns the exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", type=Path, help="data root [STUNT_DATA_ROOT]")
    parser.add_argument("command", choices=("pack", "upload", "fetch", "status", "verify"))
    parser.add_argument("archives", nargs="*", help="archive names [all]")
    parser.add_argument(
        "--replace-unmarked",
        action="store_true",
        help="fetch: also replace folders fetch did not write; a cloud session's data root only",
    )
    args = parser.parse_args(argv)
    try:
        failed = False
        root = data_root_flag(args.data_root)
        manifest = cloud_assets.read_manifest()
        for name in args.archives:
            cloud_assets.archive_named(manifest, name)  # refuses a typo before any work
        match args.command:
            case "pack":
                lines = _pack(manifest, args.archives, root)
            case "upload":
                lines = cloud_assets.upload(manifest, args.archives, OUT_DIR)
            case "fetch":
                lines = cloud_assets.fetch(
                    manifest,
                    args.archives,
                    root,
                    os.environ,
                    replace_unmarked=args.replace_unmarked,
                )
            case "verify":
                lines, verified = cloud_assets.verify(manifest, args.archives, os.environ)
                failed = not verified
            case _:
                lines = cloud_assets.status(manifest, root, OUT_DIR)
    except cloud_assets.MissingCredentials as exc:
        print(f"cloud-assets: {exc}", file=sys.stderr)
        return 2
    except (cloud_assets.CloudAssetsError, ReferenceCaptureError, OSError) as exc:
        print(f"cloud-assets: {exc}", file=sys.stderr)
        return 1
    for line in lines:
        print(f"cloud-assets: {line}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
