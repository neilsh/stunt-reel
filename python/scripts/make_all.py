"""Generate a film's .ALL archive by running MAKEONE.EXE under DOSBox-X.

PLAYONE.EXE needs a film's .ALL beside its .FLM, and most films ship without one.
MAKEONE.EXE writes it: this script stages the film and the game's RES tree in a private
mount, loads the film in MAKEONE's requester, waits for the guest to return to DOS, and
stores the archive once under captures/all/<film>/<id>/ (ADR 0022). A film then needs no
extra flags for capture-ref, which finds the stored archive by the film's hash.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from stunt_reel import dataroot, parity_layout
from stunt_reel.all_archive import (
    ArchiveError,
    ArchiveMeta,
    ArchiveTaken,
    check_archive,
    publish_archive,
)
from stunt_reel.dataroot import ensure_links_or_report
from stunt_reel.tac import makeone, staging
from stunt_reel.tac.emulator import (
    Emulator,
    EmulatorUnavailable,
    Launching,
    PortTaken,
    WaitingForGuest,
)
from stunt_reel.tac.session import DialogSettled, SessionEvent

DEFAULT_GAME_ROOT: Path = Path("corpus/stuntisl")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--film", type=Path, required=True, help="the film's .FLM file")
    parser.add_argument(
        "--game-root",
        type=Path,
        default=DEFAULT_GAME_ROOT,
        help=f"full-game tree holding MAKEONE.EXE, its engine files and RES (default {DEFAULT_GAME_ROOT})",
    )
    parser.add_argument(
        "--conf",
        type=Path,
        default=Path("tools/dosbox/dosbox-parity.conf"),
        help="DOSBox-X configuration the MAKEONE conf is derived from",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=makeone.DEFAULT_TIMEOUT,
        help="seconds MAKEONE may take to play the film and return to DOS",
    )
    return parser.parse_args()


def resolve(path: Path) -> Path:
    """Resolve a path against the repository root."""
    return path if path.is_absolute() else dataroot.REPO_ROOT / path


def report(event: SessionEvent) -> None:
    """Print the session's progress."""
    if isinstance(event, Launching):
        print(f"[make-all] launching {event.exe} -conf {event.conf} (cwd {event.cwd})", flush=True)
    elif isinstance(event, WaitingForGuest):
        print(f"[make-all] waiting for DOSBox-X on 127.0.0.1:{event.port}", flush=True)
    elif isinstance(event, DialogSettled):
        print(
            f"[make-all] requester settled: {event.distinct_indices} distinct indices", flush=True
        )


def run(args: argparse.Namespace, emulator: Emulator | None = None) -> int:
    """Generate and store one archive; 0 on success, 1 on a failed run, 2 when refused."""
    film = resolve(args.film)
    game_root = resolve(args.game_root)
    try:
        parity_layout.require_film_stem(film.stem)
    except ValueError as exc:
        print(f"[make-all] {exc}", file=sys.stderr)
        return 2
    if not film.is_file():
        print(f"[make-all] {film} not found", file=sys.stderr)
        return 2
    if not ensure_links_or_report("mise run make-all"):
        return 2

    flm_bytes = film.read_bytes()
    flm_sha256 = hashlib.sha256(flm_bytes).hexdigest()
    created = datetime.now(UTC).date()
    capture_id = parity_layout.new_capture_id(
        created, re.sub(r"[^A-Za-z0-9._-]", "-", dataroot.REPO_ROOT.name), flm_sha256
    )
    target = dataroot.REPO_ROOT / parity_layout.all_path(film.stem, capture_id)
    if (target / "meta.json").exists():
        print(
            f"[make-all] {target} already exists; an archive is never written over", file=sys.stderr
        )
        return 2

    started = time.monotonic()
    try:
        data = makeone.make_all(
            film,
            game_root=game_root,
            conf=resolve(args.conf),
            timeout=args.timeout,
            emulator=emulator,
            progress=report,
            warn=lambda message: print(f"[make-all] warning: {message}", file=sys.stderr),
        )
        check_archive(data)
    except PortTaken as exc:
        print(f"[make-all] cannot bind a control port ({exc})", file=sys.stderr)
        return 1
    except EmulatorUnavailable as exc:
        print(f"[make-all] {exc}; run via mise run make-all", file=sys.stderr)
        return 1
    except (ArchiveError, RuntimeError, TimeoutError, ConnectionError, OSError) as exc:
        status = getattr(exc, "emulator_status", None)
        suffix = f"; emulator exit status {status}" if status is not None else ""
        print(f"[make-all] {exc}{suffix}", file=sys.stderr)
        return 1

    makeone_exe = game_root / "MAKEONE.EXE"
    meta = ArchiveMeta(
        film=film.name,
        flm_bytes=len(flm_bytes),
        flm_sha256=flm_sha256,
        all_bytes=len(data),
        all_sha256=hashlib.sha256(data).hexdigest(),
        makeone_sha256=hashlib.sha256(makeone_exe.read_bytes()).hexdigest(),
        game_files=tuple(
            (name, (game_root / name).stat().st_size) for name in staging.MAKEONE_FILES
        ),
        wall_seconds=round(time.monotonic() - started, 1),
        created=created.isoformat(),
    )
    try:
        written = publish_archive(dataroot.REPO_ROOT, film.name, capture_id, data, meta)
    except ArchiveTaken as exc:
        print(f"[make-all] {exc}", file=sys.stderr)
        return 2
    print(f"[make-all] wrote {written} ({len(data)} bytes in {meta.wall_seconds} s)", flush=True)
    return 0


def main() -> int:
    """Run one make-all and terminate the emulator."""
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    return run(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
