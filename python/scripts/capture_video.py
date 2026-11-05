"""Record a film as one dosbox-automation AVI with its tick and palette log.

Stages the film and its .ALL under the data root, launches dosbox-automation on its own
web-server port with the stage's recording directory as its capture directory, and runs one Lua
script: boot, ``dosbox.capture_start()``, then a per-frame log of the film clock, the global tick
and palette writes until the film holds its last picture. The audio is stripped from the AVI.

The result becomes the film's one video capture, ``captures/<film>/video/`` (gitignored, shared
through the data root): a successful recording is written beside the old one and swapped in
(ADR 0028). Making it the reference parity scores against is a reviewed edit of
``research/parity/references.toml``, not something this script does. ``--out`` writes anywhere
else and replaces nothing.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from stunt_reel import capture_run, dataroot, parity_layout
from stunt_reel.dataroot import data_path_arg
from stunt_reel.tac import automation, video

#: Beside the stage's mount, so ``unstage`` deletes the raw (audio-carrying) recording.
RECORDING_DIR = "recording"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--film",
        type=data_path_arg,
        default=dataroot.DEFAULT_FILM,
        help=(
            "the film's .FLM file; its .ALL is the sibling or one stored by make-all (a film "
            "with neither is refused); it is staged alone into "
            f"<data root>/{parity_layout.stage_root().as_posix()}/<name>-<session>/ "
            f"(default %(default)s)"
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
            "refused and no stored capture is replaced (default: replace the film's capture, "
            f"<data root>/{parity_layout.capture_root().as_posix()}/<film>/video, by swap)"
        ),
    )
    parser.add_argument(
        "--game-root",
        type=data_path_arg,
        default=None,
        help=(
            "game tree whose PLAYONE.EXE and engine files to run, such as "
            "<data root>/builds/unpatched from mise run game-builds (default: the build the "
            "film's references.toml row names, else patch3, falling back to unpatched when "
            "patch3 stalls and the film has no row); the build is recognised by its hash"
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
    if args.out is None and args.max_frames != video.VIDEO_MAX_FRAMES:
        parser.error(
            "a non-default --max-frames needs --out: only default parameters fill the store (ADR 0028)"
        )
    return args


def report(line: str) -> None:
    """Print progress the way capture-ref does."""
    print(f"[capture-video] {line}", flush=True)


def plan_video(args: argparse.Namespace) -> capture_run.Plan:
    """The video capture's plan: record the film into the attempt's ``out``, audio stripped."""

    def plan(attempt: capture_run.Attempt) -> str:
        recording = attempt.stage.root / RECORDING_DIR
        recording.mkdir()
        recorded = video.record_video(
            attempt.runner(capture_dir=recording),
            attempt.out,
            recording,
            keys=attempt.keys,
            layout=attempt.engine,
            film=attempt.film_id,
            provenance=attempt.provenance,
            cap=args.max_frames,
        )
        return (
            f"recorded {len(recorded.log.frame)} frames ({recorded.end}), film starts at frame "
            f"{recorded.film_start_frame}, {len(recorded.palettes.changes)} palette changes, "
            f"into {attempt.out}"
        )

    return plan


def run(args: argparse.Namespace, launch: capture_run.Launch = automation.launched) -> int:
    """Record one film through the shared lifecycle; 0, 1 failed, 2 refused."""
    job = capture_run.Job(
        tag="capture-video",
        task="capture-video",
        kind="video",
        film=args.film,
        name=args.name,
        out=args.out,
        game_root=args.game_root,
    )
    return capture_run.execute(job, plan_video(args), launch=launch)


def main() -> int:
    """Record the film and terminate the emulator."""
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    args = parse_args()
    if dataroot.require_corpus_or_report("mise run capture-video") is None:
        return 2
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
