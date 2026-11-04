"""Generate a film's .ALL archive by running MAKEONE.EXE under dosbox-automation.

PLAYONE.EXE needs a film's .ALL beside its .FLM, and most films ship without one.
MAKEONE.EXE writes it: this script stages the film and the game's RES tree in a private
mount, loads the film in MAKEONE's requester, waits for the guest to return to DOS, and
stores it as the film's one archive, captures/<film>/archives/ (ADR 0028), replacing any older one.
A film then needs no extra flags for capture-ref, which checks the stored archive against the film's hash.

After storing the archive it writes the film's manifest, manifests/all/<film>.toml, for review and
commit (ADR 0032); an archive holding content the game's RES lacks gets none, and the stored
archive stays the record. --manifest-only writes the manifest from the stored archive without
running MAKEONE.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from stunt_reel import capture_store, dataroot, link, parity_layout
from stunt_reel.all_archive import (
    META_FILE,
    ArchiveError,
    ArchiveMeta,
    check_archive,
    publish_archive,
)
from stunt_reel.dataroot import ensure_links_or_report
from stunt_reel.tac import makeone, staging
from stunt_reel.tac.automation import ScriptError
from stunt_reel.tac.emulator import EmulatorUnavailable

DEFAULT_GAME_ROOT: Path = Path("corpus/stuntisl")

#: Writes an archive's manifest: ``(archive, flm, game, makeone_sha256, out)``.
Extract = Callable[[Path, Path, str, str, Path], None]


def extract_with_binary(
    archive: Path, flm: Path, game: str, makeone_sha256: str, out: Path
) -> None:
    """The default :data:`Extract`: ``stuntreel link extract``, run in the checkout."""
    link.ensure_binary()
    link.extract_manifest(archive, flm, game, makeone_sha256, out, cwd=dataroot.REPO_ROOT)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--film", type=Path, required=True, help="the film's .FLM file")
    parser.add_argument(
        "--name",
        help="the film's directory under captures/ (default: its parent folder and stem)",
    )
    parser.add_argument(
        "--game-root",
        type=Path,
        default=DEFAULT_GAME_ROOT,
        help=f"full-game tree holding MAKEONE.EXE, its engine files and RES (default {DEFAULT_GAME_ROOT})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=makeone.DEFAULT_TIMEOUT,
        help="seconds MAKEONE may take to play the film and return to DOS",
    )
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help="write the manifest from the film's stored archive; do not run MAKEONE",
    )
    return parser.parse_args()


def resolve(path: Path) -> Path:
    """Resolve a path against the repository root."""
    return path if path.is_absolute() else dataroot.REPO_ROOT / path


def report(line: str) -> None:
    """Print the run's progress."""
    print(f"[make-all] {line}", flush=True)


def game_arg(game_root: Path) -> str:
    """*game_root* as the manifest records it: relative to the checkout when inside it."""
    if game_root.is_relative_to(dataroot.REPO_ROOT):
        return game_root.relative_to(dataroot.REPO_ROOT).as_posix()
    return game_root.as_posix()


def write_manifest(
    archive: Path, film: Path, game_root: Path, makeone_sha256: str, slug: str, extract: Extract
) -> int:
    """Write the film's manifest from *archive*; 0 written, 3 not linkable, 1 an error."""
    out = dataroot.REPO_ROOT / parity_layout.manifest_path(slug)
    try:
        extract(archive, film, game_arg(game_root), makeone_sha256, out)
    except link.NotLinkable as exc:
        report(f"no manifest: {exc}; the stored archive stays the record")
        return 3
    except link.LinkError as exc:
        print(f"[make-all] warning: no manifest written: {exc}", file=sys.stderr)
        return 1
    report(f"wrote manifest {parity_layout.manifest_path(slug).as_posix()}")
    return 0


def manifest_only(film: Path, game_root: Path, slug: str, extract: Extract) -> int:
    """Write the manifest from the film's stored archive; 0, 1 when it fails, 2 when refused."""
    make = f"run: mise run make-all -- --film {film}"
    stored = capture_store.current(dataroot.REPO_ROOT / parity_layout.archive_path(slug))
    if stored is None:
        print(f"[make-all] no stored archive for {film}; {make}", file=sys.stderr)
        return 2
    try:
        meta = ArchiveMeta.from_json((stored / META_FILE).read_text(encoding="utf-8"))
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        print(f"[make-all] {stored} has an unreadable meta.json: {exc}", file=sys.stderr)
        return 1
    if meta.flm_sha256 != hashlib.sha256(film.read_bytes()).hexdigest():
        print(f"[make-all] the stored archive was made from another .FLM; {make}", file=sys.stderr)
        return 2
    archive = stored / f"{film.stem.upper()}.ALL"
    return (
        0
        if write_manifest(archive, film, game_root, meta.makeone_sha256, slug, extract) == 0
        else 1
    )


def run(
    args: argparse.Namespace,
    launch: makeone.Launch | None = None,
    extract: Extract | None = None,
) -> int:
    """Generate and store one archive; 0 on success, 1 on a failed run, 2 when refused.

    The manifest written after it does not change the exit code: the archive is stored.
    """
    film = resolve(args.film)
    game_root = resolve(args.game_root)
    extract = extract or extract_with_binary
    if not film.is_file():
        print(f"[make-all] {film} not found", file=sys.stderr)
        return 2
    try:
        slug = parity_layout.slug_for(film, args.name)
    except ValueError as exc:
        print(f"[make-all] {exc}", file=sys.stderr)
        return 2
    if not ensure_links_or_report("mise run make-all"):
        return 2
    if args.manifest_only:
        return manifest_only(film, game_root, slug, extract)
    try:
        capture_store.check_replaceable(dataroot.REPO_ROOT / parity_layout.archive_path(slug))
    except ValueError as exc:
        print(f"[make-all] {exc}", file=sys.stderr)
        return 2

    flm_bytes = film.read_bytes()
    flm_sha256 = hashlib.sha256(flm_bytes).hexdigest()
    created = datetime.now(UTC).date()

    started = time.monotonic()
    try:
        data = makeone.make_all(
            film,
            game_root=game_root,
            launch=launch,
            timeout=args.timeout,
            progress=report,
            warn=lambda message: print(f"[make-all] warning: {message}", file=sys.stderr),
        )
        check_archive(data)
    except EmulatorUnavailable as exc:
        print(f"[make-all] {exc}; run via mise run make-all", file=sys.stderr)
        return 1
    except (ArchiveError, ScriptError, RuntimeError, TimeoutError, OSError) as exc:
        print(f"[make-all] {exc}", file=sys.stderr)
        return 1

    try:
        meta = ArchiveMeta(
            film=film.name,
            flm_bytes=len(flm_bytes),
            flm_sha256=flm_sha256,
            all_bytes=len(data),
            all_sha256=hashlib.sha256(data).hexdigest(),
            makeone_sha256=hashlib.sha256((game_root / "MAKEONE.EXE").read_bytes()).hexdigest(),
            game_files=tuple(
                (name, (game_root / name).stat().st_size) for name in staging.MAKEONE_FILES
            ),
            wall_seconds=round(time.monotonic() - started, 1),
            created=created.isoformat(),
        )
        written = publish_archive(dataroot.REPO_ROOT, data, meta, slug=slug, film=film.name)
    except (OSError, ValueError) as exc:
        print(f"[make-all] could not store the archive: {exc}", file=sys.stderr)
        return 1
    print(f"[make-all] wrote {written} ({len(data)} bytes in {meta.wall_seconds} s)", flush=True)
    archive = written / f"{film.stem.upper()}.ALL"
    write_manifest(archive, film, game_root, meta.makeone_sha256, slug, extract)
    return 0


def main() -> int:
    """Run one make-all and terminate the emulator."""
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    return run(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
