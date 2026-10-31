"""Capture PLAYONE.EXE Mode 13h reference frames for visual parity.

Stages the film and its .ALL under the data root, launches dosbox-automation on its own web-server
port, and runs a plan: a Lua trace of the whole film, a choice of frames made here, and dump passes
that read the A000 page and the working palette at exactly those emulated frames (see
research/playone-exe/capture-dosbox-automation.md). Most films replay bit for bit; where one
lands a tick apart, each page keeps the tick its own pass read. No debugger is involved.

Rasters, palettes, and meta.json land in a new directory per capture under the captures root
(gitignored, shared through the data root). A capture is written once and never changed
(ADR 0022); making it the reference parity scores against is a reviewed edit of
research/parity/references.toml, not something this script does.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from stunt_reel import dataroot, parity_layout, runs
from stunt_reel.all_archive import ArchiveError, resolve_all
from stunt_reel.dataroot import ensure_links_or_report
from stunt_reel.parity_artifacts import CAPTURE_FRAMES_DIR, FilmId
from stunt_reel.tac import automation, playone, staging
from stunt_reel.tac.emulator import EmulatorUnavailable
from stunt_reel.tac.framebuffer import FILM_STRIDE_TICKS, capture
from stunt_reel.tac.plan import PlanError

DEFAULT_FILM: Path = Path("corpus/stisldem/VAULT/CTRY.FLM")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--film",
        type=Path,
        default=DEFAULT_FILM,
        help=(
            "the film's .FLM file; its .ALL is the sibling or one stored by make-all (a film "
            "with neither is refused); it is staged alone into "
            f"<data root>/{parity_layout.stage_root().as_posix()}/<name>-<session>/ so the dialog "
            f"needs one prefix key (default {DEFAULT_FILM})"
        ),
    )
    parser.add_argument(
        "--name",
        help="the film's directory under captures/ (default: its parent folder and stem)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "new directory receiving tick_*.idx, palettes_*.json, and meta.json; an existing "
            f"non-empty one is refused (default {parity_layout.capture_root().as_posix()}/"
            "<film>/frames/<next run number>)"
        ),
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=2000,
        help="cap on captured film frames; the film's end stops the trace by itself",
    )
    parser.add_argument(
        "--stride",
        type=int,
        default=FILM_STRIDE_TICKS,
        help=f"film ticks between kept frames (default {FILM_STRIDE_TICKS})",
    )
    return parser.parse_args()


def resolve(path: Path) -> Path:
    """Resolve a path against the repository root."""
    return path if path.is_absolute() else dataroot.REPO_ROOT / path


def is_taken(out_dir: Path) -> bool:
    """True when *out_dir* holds a capture, or anything else: a capture is never written over.

    A run that died before ``meta.json`` (which is written last) left only rasters and
    palettes; that is no capture, so those files are cleared and the same id can be retried.
    """
    if not out_dir.is_dir():
        return False
    if not (out_dir / "meta.json").exists():
        frames = out_dir / CAPTURE_FRAMES_DIR
        for directory in (frames, out_dir):
            for pattern in ("tick_*.idx", "palettes_*.json"):
                for partial in directory.glob(pattern):
                    partial.unlink()
        if frames.is_dir() and not any(frames.iterdir()):
            frames.rmdir()
    return any(out_dir.iterdir())


def report(line: str) -> None:
    """Print the plan's progress the way capture-ref always has."""
    print(f"[capture] {line}", flush=True)


def run(args: argparse.Namespace) -> int:
    """Run one capture plan and report its artifacts."""
    film = resolve(args.film)
    if not film.is_file():
        print(f"[capture] {film} not found", file=sys.stderr)
        return 2
    try:
        slug = parity_layout.slug_for(film, args.name)
    except ValueError as exc:
        print(f"[capture] {exc}", file=sys.stderr)
        return 2
    if not ensure_links_or_report("mise run capture-ref"):
        return 2
    try:
        archive = resolve_all(film, dataroot.REPO_ROOT, slug)
        all_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
    except (ArchiveError, OSError) as exc:
        print(f"[capture] {exc}", file=sys.stderr)
        return 2
    film_id = FilmId(
        name=film.name,
        flm_bytes=film.stat().st_size,
        flm_sha256=hashlib.sha256(film.read_bytes()).hexdigest(),
        all_sha256=all_sha256,
    )
    claimed: Path | None = None
    if args.out is None:
        parent = dataroot.REPO_ROOT / parity_layout.frames_root(slug)
        out = parent / runs.claim_run(parent)
        claimed = out
    else:
        out = resolve(args.out)
    try:
        return _capture_into(args, out, film, archive, film_id)
    finally:
        # A run that died before meta.json (written last) is no capture; free its number.
        if claimed is not None and not (claimed / "meta.json").exists():
            shutil.rmtree(claimed, ignore_errors=True)


def _capture_into(
    args: argparse.Namespace,
    out: Path,
    film: Path,
    archive: Path,
    film_id: FilmId,
) -> int:
    """Stage the film, run the plan and write its capture into *out*; 0 on success."""
    if is_taken(out):
        print(f"[capture] {out} already exists; a capture is never written over", file=sys.stderr)
        return 2
    provenance = {
        "captured_on": datetime.now(UTC).date().isoformat(),
        "checkout": re.sub(r"[^A-Za-z0-9._-]", "-", dataroot.REPO_ROOT.name),
    }
    try:
        staged = staging.stage_play(film, archive)
    except OSError as exc:
        print(f"[capture] {exc}", file=sys.stderr)
        return 1
    try:
        meta: dict[str, Any] = capture(
            lambda: automation.launched(staged.write_conf),
            out,
            keys=playone.film_selection_names(film.stem),
            max_frames=args.max_frames,
            stride=args.stride,
            film=film_id,
            provenance=provenance,
            progress=report,
        )
    except EmulatorUnavailable as exc:
        print(f"[capture] {exc}; run via mise run capture-ref", file=sys.stderr)
        return 1
    except (automation.ScriptError, PlanError, RuntimeError, TimeoutError, OSError) as exc:
        print(f"[capture] {exc}", file=sys.stderr)
        return 1
    finally:
        staging.unstage(staged)

    frames = meta["frames"]
    if not frames:
        print("[capture] no frames captured", file=sys.stderr)
        return 1
    print(f"[capture] captured {len(frames)} frames into {out}", flush=True)
    return 0


def main() -> int:
    """Run the capture and terminate the emulator."""
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    return run(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
