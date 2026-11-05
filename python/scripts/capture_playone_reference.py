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
import logging
import sys
from pathlib import Path
from typing import Any

from stunt_reel import capture_run, dataroot, parity_layout
from stunt_reel.dataroot import data_path_arg
from stunt_reel.tac import automation
from stunt_reel.tac.framebuffer import FILM_STRIDE_TICKS, capture

#: The frame cap of a capture that may fill the store; another needs --out (ADR 0028).
DEFAULT_MAX_FRAMES = 2000


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


def report(line: str) -> None:
    """Print the plan's progress the way capture-ref always has."""
    print(f"[capture] {line}", flush=True)


def plan_frames(args: argparse.Namespace) -> capture_run.Plan:
    """The frame capture's plan: trace the film, pick frames, dump them into the attempt's ``out``."""

    def plan(attempt: capture_run.Attempt) -> str:
        meta: dict[str, Any] = capture(
            attempt.runner(),
            attempt.out,
            keys=attempt.keys,
            max_frames=args.max_frames,
            stride=args.stride,
            film=attempt.film_id,
            provenance=attempt.provenance,
            progress=report,
            layout=attempt.engine,
        )
        if not meta["frames"]:
            raise capture_run.Failed("no frames captured")
        return f"captured {len(meta['frames'])} frames into {attempt.out}"

    return plan


def run(args: argparse.Namespace, launch: capture_run.Launch = automation.launched) -> int:
    """Capture one film's frames through the shared lifecycle; 0, 1 failed, 2 refused."""
    job = capture_run.Job(
        tag="capture",
        task="capture-ref",
        kind="frames",
        film=args.film,
        name=args.name,
        out=args.out,
        game_root=args.game_root,
    )
    return capture_run.execute(job, plan_frames(args), launch=launch)


def main() -> int:
    """Run the capture and terminate the emulator."""
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    args = parse_args()
    if dataroot.require_corpus_or_report("mise run capture-ref") is None:
        return 2
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
