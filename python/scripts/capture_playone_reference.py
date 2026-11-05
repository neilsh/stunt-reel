"""Capture PLAYONE.EXE Mode 13h reference frames for visual parity.

Stages the film and its .ALL under the data root, launches dosbox-automation on its own web-server
port, and runs a plan: a Lua trace of the whole film, a choice of frames made here, and dump passes
that read the A000 page and the working palette at exactly those emulated frames (see
research/playone-exe/capture-dosbox-automation.md). Most films replay bit for bit; where one
lands a tick apart, each page keeps the tick its own pass read. No debugger is involved.

Rasters, palettes, and meta.json become the film's one frame capture, ``captures/<film>/frames/``
(gitignored, shared through the data root): a successful capture is written beside the old one
and swapped in (ADR 0028). Making it the reference parity scores against is a reviewed edit of
research/parity/references.toml, not something this script does; until then a replaced
reference fails its pinned hash. ``--out`` writes anywhere else and replaces nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from stunt_reel import capture_store, dataroot, parity_layout
from stunt_reel.all_archive import ArchiveError, resolve_all
from stunt_reel.dataroot import data_path_arg
from stunt_reel.parity_artifacts import CAPTURE_FRAMES_DIR, FilmId
from stunt_reel.tac import automation, playone, staging
from stunt_reel.tac.emulator import EmulatorUnavailable
from stunt_reel.tac.framebuffer import FILM_STRIDE_TICKS, capture
from stunt_reel.tac.plan import PlanError

#: The frame cap of a capture that may fill the store; another needs --out (ADR 0028).
DEFAULT_MAX_FRAMES = 2000


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--film",
        type=data_path_arg,
        default="corpus/stisldem/VAULT/CTRY.FLM",
        help=(
            "the film's .FLM file; its .ALL is the sibling or one stored by make-all (a film "
            "with neither is refused); it is staged alone into "
            f"<data root>/{parity_layout.stage_root().as_posix()}/<name>-<session>/ so the dialog "
            f"needs one prefix key (default %(default)s)"
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
            "new directory receiving tick_*.idx, palettes_*.json, and meta.json; one holding a "
            "capture or other files is refused, but rasters and palettes left by a run that died "
            "before meta.json are cleared first; no stored capture is replaced (default: replace the "
            f"film's capture, <data root>/{parity_layout.capture_root().as_posix()}/<film>/frames, by swap)"
        ),
    )
    parser.add_argument(
        "--game-root",
        type=Path,
        default=None,
        help=(
            "game tree whose PLAYONE.EXE and engine files to run, such as "
            "<data root>/builds/patched from mise run game-builds (default: the film's own tree, "
            "else the demo); the build is recognised by its hash"
        ),
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=DEFAULT_MAX_FRAMES,
        help="cap on captured film frames; the film's end stops the trace by itself",
    )
    parser.add_argument(
        "--stride",
        type=int,
        default=FILM_STRIDE_TICKS,
        help=f"film ticks between kept frames (default {FILM_STRIDE_TICKS})",
    )
    args = parser.parse_args()
    if args.max_frames < 1:
        parser.error("--max-frames must be at least 1")
    if args.out is None and (
        args.max_frames != DEFAULT_MAX_FRAMES or args.stride != FILM_STRIDE_TICKS
    ):
        parser.error(
            "a non-default --max-frames or --stride needs --out: only default parameters fill the store (ADR 0028)"
        )
    return args


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
    if args.out is not None:
        out = resolve(args.out)
        try:
            capture_store.check_outside(out, dataroot.data_root() / parity_layout.capture_root())
        except ValueError as exc:
            print(f"[capture] {exc}", file=sys.stderr)
            return 2
        return _capture_into(args, out, film, archive, film_id)
    # The film's one capture of this kind is replaced only by a complete, successful one.
    target = dataroot.data_root() / parity_layout.frames_path(slug)
    try:
        capture_store.check_replaceable(target)
    except ValueError as exc:
        print(f"[capture] {exc}", file=sys.stderr)
        return 2
    out = capture_store.stage(target)
    try:
        code = _capture_into(args, out, film, archive, film_id)
        if code == 0:
            capture_store.publish(out, target)
            report(f"replaced the capture in {target}")
        return code
    finally:
        capture_store.discard(out)


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
    engine_root = resolve(args.game_root) if args.game_root is not None else None
    try:
        staged = staging.stage_play(film, archive, engine_root)
    except OSError as exc:
        print(f"[capture] {exc}", file=sys.stderr)
        return 1
    try:
        layout = playone.layout_for(staged.mount / "PLAYONE.EXE")
    except (playone.UnknownBuild, OSError) as exc:
        staging.unstage(staged)
        print(f"[capture] {exc}", file=sys.stderr)
        return 2
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
            layout=layout,
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
    args = parse_args()
    if dataroot.require_corpus_or_report("mise run capture-ref") is None:
        return 2
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
