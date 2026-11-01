"""Record a film as one dosbox-automation AVI with its tick and palette log.

Stages the film and its .ALL under the data root, launches dosbox-automation on its own
web-server port with the stage's recording directory as its capture directory, and runs one Lua
script: boot, ``dosbox.capture_start()``, then a per-frame log of the film clock, the global tick
and palette writes until the film holds its last picture. The audio is stripped from the AVI.

The result lands in a new directory per capture under ``captures/<film>/video/`` (gitignored,
shared through the data root). A capture is written once and never changed (ADR 0022); making
it the reference parity scores against is a reviewed edit of ``research/parity/references.toml``,
not something this script does.
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

from stunt_reel import dataroot, parity_layout, runs
from stunt_reel.all_archive import ArchiveError, resolve_all
from stunt_reel.dataroot import ensure_links_or_report
from stunt_reel.parity_artifacts import CAPTURE_META, FilmId
from stunt_reel.tac import automation, playone, staging, video
from stunt_reel.tac.emulator import EmulatorUnavailable

DEFAULT_FILM: Path = Path("corpus/stisldem/VAULT/CTRY.FLM")
#: Beside the stage's mount, so ``unstage`` deletes the raw (audio-carrying) recording.
RECORDING_DIR = "recording"


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
            f"<data root>/{parity_layout.stage_root().as_posix()}/<name>-<session>/ "
            f"(default {DEFAULT_FILM})"
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
            "new directory receiving capture.avi and meta.json; an existing non-empty one is "
            f"refused (default {parity_layout.capture_root().as_posix()}/<film>/video/"
            "<next run number>)"
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
        default=video.VIDEO_MAX_FRAMES,
        help=(
            "cap on recorded emulated frames; the film's end stops the recording by itself "
            f"(default {video.VIDEO_MAX_FRAMES})"
        ),
    )
    args = parser.parse_args()
    if args.max_frames < 1:
        parser.error("--max-frames must be at least 1")
    return args


def resolve(path: Path) -> Path:
    """Resolve a path against the repository root."""
    return path if path.is_absolute() else dataroot.REPO_ROOT / path


def report(line: str) -> None:
    """Print progress the way capture-ref does."""
    print(f"[capture-video] {line}", flush=True)


def run(args: argparse.Namespace) -> int:
    """Record one film and report where the capture landed."""
    film = resolve(args.film)
    if not film.is_file():
        print(f"[capture-video] {film} not found", file=sys.stderr)
        return 2
    try:
        slug = parity_layout.slug_for(film, args.name)
    except ValueError as exc:
        print(f"[capture-video] {exc}", file=sys.stderr)
        return 2
    if not ensure_links_or_report("mise run capture-video"):
        return 2
    try:
        archive = resolve_all(film, dataroot.REPO_ROOT, slug)
        all_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
    except (ArchiveError, OSError) as exc:
        print(f"[capture-video] {exc}", file=sys.stderr)
        return 2
    film_id = FilmId(
        name=film.name,
        flm_bytes=film.stat().st_size,
        flm_sha256=hashlib.sha256(film.read_bytes()).hexdigest(),
        all_sha256=all_sha256,
    )
    claimed: Path | None = None
    if args.out is None:
        parent = dataroot.REPO_ROOT / parity_layout.video_root(slug)
        out = parent / runs.claim_run(parent)
        claimed = out
    else:
        out = resolve(args.out)
    try:
        return _record_into(args, out, film, archive, film_id)
    finally:
        # A run that died before meta.json (written last) is no capture; free its number.
        if claimed is not None and not (claimed / CAPTURE_META).exists():
            shutil.rmtree(claimed, ignore_errors=True)


def _record_into(
    args: argparse.Namespace, out: Path, film: Path, archive: Path, film_id: FilmId
) -> int:
    """Stage the film, record it and write the capture into *out*; 0 on success."""
    if out.is_dir() and any(out.iterdir()):
        print(
            f"[capture-video] {out} already exists; a capture is never written over",
            file=sys.stderr,
        )
        return 2
    provenance = {
        "captured_on": datetime.now(UTC).date().isoformat(),
        "checkout": re.sub(r"[^A-Za-z0-9._-]", "-", dataroot.REPO_ROOT.name),
    }
    engine_root = resolve(args.game_root) if args.game_root is not None else None
    try:
        staged = staging.stage_play(film, archive, engine_root)
    except OSError as exc:
        print(f"[capture-video] {exc}", file=sys.stderr)
        return 1
    try:
        layout = playone.layout_for(staged.mount / "PLAYONE.EXE")
    except (playone.UnknownBuild, OSError) as exc:
        staging.unstage(staged)
        print(f"[capture-video] {exc}", file=sys.stderr)
        return 2
    recording = staged.root / RECORDING_DIR
    try:
        recording.mkdir()
        capture = video.record_video(
            lambda: automation.launched(
                lambda port: staged.write_conf(port, capture_dir=recording)
            ),
            out,
            recording,
            keys=playone.film_selection_names(film.stem),
            layout=layout,
            film=film_id,
            provenance=provenance,
            cap=args.max_frames,
        )
    except EmulatorUnavailable as exc:
        print(f"[capture-video] {exc}; run via mise run capture-video", file=sys.stderr)
        return 1
    except (
        automation.ScriptError,
        video.VideoCaptureError,
        RuntimeError,
        TimeoutError,
        OSError,
    ) as exc:
        print(f"[capture-video] {exc}", file=sys.stderr)
        return 1
    finally:
        staging.unstage(staged)

    report(
        f"recorded {len(capture.log.frame)} frames ({capture.end}), film starts at frame "
        f"{capture.film_start_frame}, {len(capture.palettes.changes)} palette changes, into {out}"
    )
    return 0


def main() -> int:
    """Record the film and terminate the emulator."""
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    return run(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
