"""Capture PLAYONE.EXE Mode 13h reference frames for visual parity.

Launches DOSBox-X with tools/dosbox/dosbox-parity.conf (which auto-starts PLAYONE.EXE on its
LOAD FILM dialog), accepts the emulator's outbound debugger connection on a control
port the OS chooses, confirms CTRY.FLM with BIOS Data Area keystrokes, and dumps one whole
frame per post-retrace trap hit until the frame budget is met.

Rasters, palettes, and meta.json land in a new directory per capture under the captures root
(gitignored, shared through the data root). A capture is written once and never changed
(ADR 0022); making it the reference parity scores against is a reviewed edit of
research/parity/references.toml, not something this script does.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from stunt_reel import dataroot, parity_layout
from stunt_reel.dataroot import ensure_links_or_report
from stunt_reel.parity_artifacts import FilmId
from stunt_reel.tac import playone
from stunt_reel.tac.emulator import EmulatorUnavailable, Launching, PortTaken, WaitingForGuest
from stunt_reel.tac.framebuffer import capture
from stunt_reel.tac.session import DialogSettled, Session, SessionError, SessionEvent, run_session

DEFAULT_FILM: Path = Path("corpus/stisldem/VAULT/CTRY.FLM")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--film",
        type=Path,
        default=DEFAULT_FILM,
        help=(
            "the film's .FLM file (its .ALL must sit beside it); it is staged alone into "
            f"{parity_layout.stage_root().as_posix()}/<name>-<session>/ so the dialog needs one prefix "
            f"key (default {DEFAULT_FILM})"
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "new directory receiving tick_*.idx, palettes_*.json, and meta.json; an existing "
            f"non-empty one is refused (default {parity_layout.capture_root().as_posix()}/"
            "<film name, lower case>/<date>-<checkout>-<film hash>)"
        ),
    )
    parser.add_argument(
        "--dgroup-segment",
        type=lambda text: int(text, 16),
        default=playone.DGROUP_RUNTIME_SEG,
        help=(
            "hex DS segment of PLAYONE.EXE's DGROUP at runtime, used to read the film clock "
            f"(default {playone.DGROUP_RUNTIME_SEG:04X}, the DS observed in the T11 live check)"
        ),
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=2000,
        help=(
            "cap on captured film frames; capture normally stops by itself once the film "
            "clock holds still at the end of the film"
        ),
    )
    parser.add_argument(
        "--conf",
        type=Path,
        default=Path("tools/dosbox/dosbox-parity.conf"),
        help="DOSBox-X configuration used for the capture run",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help=(
            "pin the control port instead of letting the OS choose; a pre-launched "
            "DOSBox-X needs this to know where to dial, so use it with --no-launch"
        ),
    )
    parser.add_argument(
        "--no-launch",
        action="store_true",
        help="attach to an already launched DOSBox-X instead of starting one",
    )
    args = parser.parse_args()
    if args.no_launch and args.port == 0:
        parser.error(
            "--no-launch needs --port: a running DOSBox-X can only dial a port it was told"
        )
    return args


def resolve(path: Path) -> Path:
    """Resolve a path against the repository root."""
    return path if path.is_absolute() else dataroot.REPO_ROOT / path


def is_taken(out_dir: Path) -> bool:
    """True when *out_dir* already holds anything: a capture is never written over."""
    return out_dir.is_dir() and any(out_dir.iterdir())


def report(event: SessionEvent) -> None:
    """Print the session's progress the way capture-ref always has."""
    if isinstance(event, Launching):
        print(f"[capture] launching {event.exe} -conf {event.conf} (cwd {event.cwd})", flush=True)
    elif isinstance(event, WaitingForGuest):
        print(f"[capture] waiting for DOSBox-X on 127.0.0.1:{event.port}", flush=True)
    elif isinstance(event, DialogSettled):
        print(f"[capture] dialog settled: {event.distinct_indices} distinct indices", flush=True)


def run(args: argparse.Namespace) -> int:
    """Drive one capture session and report its artifacts."""
    film = resolve(args.film)
    conf = resolve(args.conf)
    if not ensure_links_or_report("mise run capture-ref"):
        return 2
    flm_sha256 = hashlib.sha256(film.read_bytes()).hexdigest()
    film_id = FilmId(name=film.name, flm_bytes=film.stat().st_size, flm_sha256=flm_sha256)
    out = resolve(
        args.out
        or parity_layout.capture_path(
            film.stem,
            parity_layout.new_capture_id(
                datetime.now(UTC).date(), dataroot.REPO_ROOT.name, flm_sha256
            ),
        )
    )
    if is_taken(out):
        print(f"[capture] {out} already exists; a capture is never written over", file=sys.stderr)
        return 2

    def sample(session: Session) -> dict[str, Any]:
        return capture(session, out, args.max_frames, film=film_id)

    try:
        meta = run_session(
            film,
            sample=sample,
            conf=conf,
            dgroup_segment=args.dgroup_segment,
            port=args.port,
            no_launch=args.no_launch,
            progress=report,
        )
    except PortTaken as exc:
        where = "" if exc.port == 0 else f" on 127.0.0.1:{exc.port}"
        print(f"[capture] cannot bind a control port{where} ({exc})", file=sys.stderr)
        return 1
    except EmulatorUnavailable as exc:
        print(f"[capture] {exc}; run via mise run capture-ref", file=sys.stderr)
        return 1
    except (SessionError, RuntimeError, TimeoutError, ConnectionError) as exc:
        status = getattr(exc, "emulator_status", None)
        suffix = f"; emulator exit status {status}" if status is not None else ""
        print(f"[capture] {exc}{suffix}", file=sys.stderr)
        return 1

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
