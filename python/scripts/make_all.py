"""Generate a film's .ALL archive by running MAKEONE.EXE under dosbox-automation.

PLAYONE.EXE needs a film's .ALL beside its .FLM, and most films ship without one.
MAKEONE.EXE writes it: this script stages the film and the game's RES tree in a private
mount, loads the film in MAKEONE's requester, waits for the guest to return to DOS, and
stores it as the film's one archive, captures/<film>/archives/ (ADR 0028), replacing any older one.
The run goes through the shared capture lifecycle (stunt_reel.capture_run), which chooses the
build from the film's references.toml row, else patch3 with an unpatched fallback.
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
import os
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from stunt_reel import capture_run, capture_store, dataroot, link, parity_layout, references
from stunt_reel.all_archive import (
    META_FILE,
    ArchiveError,
    ArchiveMeta,
    check_archive,
    write_archive,
)
from stunt_reel.dataroot import data_path_arg
from stunt_reel.hashing import file_sha256
from stunt_reel.tac import makeone, staging

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
    parser.add_argument("--film", type=data_path_arg, required=True, help="the film's .FLM file")
    parser.add_argument(
        "--name",
        help="the film's directory under captures/ (default: its parent folder and stem)",
    )
    parser.add_argument(
        "--game-root",
        type=data_path_arg,
        default=None,
        help=(
            "full-game tree holding MAKEONE.EXE, its engine files and RES, such as "
            "<data root>/builds/unpatched from mise run game-builds (default: the build the "
            "film's references.toml row names, else patch3, falling back to unpatched when "
            "patch3 stalls and the film has no row)"
        ),
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
    """*game_root* as the manifest records it: ``corpus/...`` or ``builds/...`` in the data root.

    A tree elsewhere in the checkout is recorded relative to it, and any other tree as it is.
    """
    # normpath, not resolve: a primary checkout's corpus folders may be links.
    tree = Path(os.path.normpath(game_root.absolute()))
    corpus = Path(os.path.normpath(dataroot.corpus_root().absolute()))
    if tree.is_relative_to(corpus):
        # Named as resolve_data_path reads it back: corpus/<tree>.
        return (Path(corpus.name) / tree.relative_to(corpus)).as_posix()
    builds = Path(os.path.normpath((dataroot.data_root() / dataroot.BUILDS_DIRNAME).absolute()))
    if tree.is_relative_to(builds):
        return (Path(builds.name) / tree.relative_to(builds)).as_posix()
    repo = Path(os.path.normpath(dataroot.REPO_ROOT.absolute()))
    return tree.relative_to(repo).as_posix() if tree.is_relative_to(repo) else tree.as_posix()


def write_manifest(
    archive: Path,
    film: Path,
    game_root: Path,
    makeone_sha256: str,
    slug: str,
    extract: Extract,
    *,
    replaced: bool = True,
) -> int:
    """Write the film's manifest from *archive*; 0 written, 3 not linkable, 1 an error.

    When none is written after a run that *replaced* the archive, an earlier manifest is
    removed: it describes the replaced archive, and would still win over it. A backfill
    replaced nothing, so a failed one leaves the committed manifest alone.
    """
    manifest = parity_layout.manifest_path(slug)
    out = dataroot.REPO_ROOT / manifest
    try:
        extract(archive, film, game_arg(game_root), makeone_sha256, out)
    except link.NotLinkable as exc:
        report(f"no manifest: {exc}; the stored archive stays the record")
        code = 3
    except link.LinkError as exc:
        print(f"[make-all] warning: no manifest written: {exc}", file=sys.stderr)
        code = 1
    else:
        report(f"wrote manifest {manifest.as_posix()}")
        return 0
    if out.is_file():
        if replaced:
            out.unlink()
            report(f"removed the earlier {manifest.as_posix()}")
        else:
            report(f"kept {manifest.as_posix()}; it still takes precedence over the stored archive")
    return code


def manifest_only(film: Path, game_root: Path | None, slug: str, extract: Extract) -> int:
    """Write the manifest from the film's stored archive; 0, 1 when it fails, 2 when refused."""
    make = f"run: mise run make-all -- --film {film}"
    stored = capture_store.current(dataroot.data_root() / parity_layout.archive_path(slug))
    if stored is None:
        print(f"[make-all] no stored archive for {film}; {make}", file=sys.stderr)
        return 2
    try:
        meta = ArchiveMeta.from_json((stored / META_FILE).read_text(encoding="utf-8"))
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        print(f"[make-all] {stored} has an unreadable meta.json: {exc}", file=sys.stderr)
        return 1
    if meta.flm_sha256 != file_sha256(film):
        print(f"[make-all] the stored archive was made from another .FLM; {make}", file=sys.stderr)
        return 2
    archive = stored / parity_layout.all_name(film.name)
    if game_root is None:
        # The tree of the build whose MAKEONE wrote the archive.
        build = references.MAKEONE_BUILDS.get(meta.makeone_sha256)
        if build is None:
            print(
                "[make-all] the stored archive's MAKEONE build is unknown; pass --game-root "
                "with the tree that wrote it",
                file=sys.stderr,
            )
            return 2
        game_root = capture_run.build_root(build)
    return (
        0
        if write_manifest(
            archive, film, game_root, meta.makeone_sha256, slug, extract, replaced=False
        )
        == 0
        else 1
    )


def plan_archive(
    args: argparse.Namespace,
    film: Path,
    launch: makeone.Launch | None,
    kept: dict[str, Any],
) -> capture_run.Plan:
    """The archive plan: run MAKEONE on the film and write ``.ALL`` and ``meta.json`` into ``out``.

    What the manifest step needs afterwards (the metadata and the game tree) goes into *kept*.
    """

    def plan(attempt: capture_run.Attempt) -> str:
        game_root = attempt.tree
        flm_bytes = film.read_bytes()
        started = time.monotonic()
        hung: list[bool] = []
        data = makeone.make_all(
            film,
            game_root=game_root,
            launch=launch,
            timeout=args.timeout,
            progress=report,
            on_hang=lambda: hung.append(True),
            warn=lambda message: print(f"[make-all] warning: {message}", file=sys.stderr),
        )
        try:
            check_archive(data)
        except ArchiveError as exc:
            raise capture_run.Failed(str(exc)) from exc
        meta = ArchiveMeta(
            film=film.name,
            flm_bytes=len(flm_bytes),
            flm_sha256=hashlib.sha256(flm_bytes).hexdigest(),
            all_bytes=len(data),
            all_sha256=hashlib.sha256(data).hexdigest(),
            makeone_sha256=file_sha256(game_root / "MAKEONE.EXE"),
            game_files=tuple(
                (name, (game_root / name).stat().st_size) for name in staging.MAKEONE_FILES
            ),
            wall_seconds=round(time.monotonic() - started, 1),
            created=datetime.now(UTC).date().isoformat(),
            returned_to_dos=not hung,
        )
        write_archive(attempt.out, data, meta, film=film.name)
        kept.update(meta=meta, game_root=game_root)
        return f"wrote {attempt.target} ({len(data)} bytes in {meta.wall_seconds} s)"

    return plan


def run(
    args: argparse.Namespace,
    launch: makeone.Launch | None = None,
    extract: Extract | None = None,
) -> int:
    """Generate and store one archive; 0 on success, 1 on a failed run, 2 when refused.

    The manifest written after it does not change the exit code: the archive is stored.
    """
    film = resolve(args.film)
    extract = extract or extract_with_binary
    if args.manifest_only:
        if not film.is_file():
            print(f"[make-all] {film} not found", file=sys.stderr)
            return 2
        try:
            slug = parity_layout.slug_for(film, args.name)
        except ValueError as exc:
            print(f"[make-all] {exc}", file=sys.stderr)
            return 2
        return manifest_only(
            film, resolve(args.game_root) if args.game_root else None, slug, extract
        )
    kept: dict[str, Any] = {}
    job = capture_run.Job(
        tag="make-all",
        task="make-all",
        kind="archive",
        film=film,
        name=args.name,
        game_root=args.game_root,
    )
    code = capture_run.execute(job, plan_archive(args, film, launch, kept))
    if code != 0:
        return code
    slug = parity_layout.slug_for(film, args.name)
    meta: ArchiveMeta = kept["meta"]
    stored = dataroot.data_root() / parity_layout.archive_path(slug)
    archive = stored / parity_layout.all_name(film.name)
    write_manifest(archive, film, kept["game_root"], meta.makeone_sha256, slug, extract)
    return 0


def main() -> int:
    """Run one make-all and terminate the emulator."""
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    args = parse_args()
    if dataroot.require_corpus_or_report("mise run make-all") is None:
        return 2
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
