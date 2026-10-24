"""Capture PLAYONE.EXE Mode 13h reference frames for visual parity.

Launches DOSBox-X with ``dosbox-parity.conf`` (which auto-starts ``PLAYONE.EXE`` on
its LOAD FILM dialog), accepts the emulator's outbound debugger connection on the MCP
control port, confirms ``CTRY.FLM`` with BIOS Data Area keystrokes, and dumps one
whole frame per post-retrace trap hit until the frame budget is met.

Reference rasters, palettes, and ``meta.json`` land under ``build/`` (gitignored);
nothing here is committed evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import shutil
import subprocess
import sys
from pathlib import Path

from stunt_reel.dataroot import is_shared, require_shared_write
from stunt_reel.tac import playone
from stunt_reel.tac.client import TacClient
from stunt_reel.tac.framebuffer import capture
from stunt_reel.tac.transport import ListenTransport

CONTROL_PORT: int = 58991
LAUNCH_TIMEOUT_SECONDS: float = 30.0
EMULATOR_STOP_SECONDS: float = 10.0
REPO_ROOT: Path = Path(__file__).resolve().parents[2]
DEFAULT_FILM: Path = Path("corpus/stisldem/VAULT/CTRY.FLM")
#: Engine files the player needs beside ``PLAYONE.EXE`` (everything in the demo root but VAULT).
ENGINE_FILES: tuple[str, ...] = (
    "DRIVER1.BIN",
    "DRIVER2.BIN",
    "DRIVER3.BIN",
    "GAME.CFG",
    "INSTALL.CFG",
    "PFONT.BIN",
    "PLAYONE.EXE",
    "VDATA.BIN",
)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--film",
        type=Path,
        default=DEFAULT_FILM,
        help=(
            "the film's .FLM file (its .ALL must sit beside it); it is staged alone into "
            f"build/parity/stage/<name>/ so the dialog needs one prefix key (default {DEFAULT_FILM})"
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=(
            "directory receiving tick_*.idx, palettes_*.json, and meta.json "
            "(default build/parity/reference/<film name, lower case>)"
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
        default=Path("dosbox-parity.conf"),
        help="DOSBox-X configuration used for the capture run",
    )
    parser.add_argument(
        "--no-launch",
        action="store_true",
        help="attach to an already launched DOSBox-X instead of starting one",
    )
    return parser.parse_args()


def stage_film(film: Path, conf: Path) -> tuple[Path, Path]:
    """Stage ``film`` alone in a fresh mount and write a DOSBox-X conf that mounts it.

    ``PLAYONE.EXE`` takes no film argument and its listbox only jumps by first letter, so
    the mount holds the engine files and a ``VAULT`` with just this film's ``.FLM`` and
    ``.ALL``: the keys are then always the first letter, Down, Enter. Returns the staged
    mount and the generated conf (both under ``build/parity/stage/``).
    """
    archive = film.with_suffix(".ALL")
    for needed in (film, archive):
        if not needed.is_file():
            msg = f"{needed} not found (the film's .FLM and .ALL must sit together)"
            raise FileNotFoundError(msg)
    source_root = film.parent.parent
    stage = REPO_ROOT / "build" / "parity" / "stage" / film.stem.lower()
    shutil.rmtree(stage, ignore_errors=True)
    (stage / "VAULT").mkdir(parents=True)
    for name in ENGINE_FILES:
        shutil.copy2(source_root / name, stage / name)
    shutil.copy2(film, stage / "VAULT" / film.name)
    shutil.copy2(archive, stage / "VAULT" / archive.name)

    text = conf.read_text(encoding="utf-8")
    mount = stage.relative_to(REPO_ROOT).as_posix()
    text = text.replace('mount c "corpus/stisldem"', f'mount c "{mount}"')
    text = text.replace(r"VAULT\CTRY.FLM", rf"VAULT\{film.name}")
    staged_conf = stage.parent / f"stage-{film.stem.lower()}.conf"
    staged_conf.write_text(text, encoding="utf-8")
    return stage, staged_conf


def clear_frames(out_dir: Path) -> None:
    """Delete rasters from an earlier run so the capture cannot leave stale frames."""
    if not out_dir.is_dir():
        return
    for pattern in ("tick_*.idx", "palettes_*.json", "_scratch.idx"):
        for stale in out_dir.glob(pattern):
            stale.unlink()


def run_session(args: argparse.Namespace) -> int:
    """Launch one emulator, drive the dialog, and capture frames."""
    film: Path = args.film if args.film.is_absolute() else REPO_ROOT / args.film
    out: Path = args.out or Path("build/parity/reference") / film.stem.lower()
    out_dir: Path = out if out.is_absolute() else REPO_ROOT / out
    if is_shared(out_dir):
        require_shared_write("mise run capture-ref")
    conf: Path = args.conf if args.conf.is_absolute() else REPO_ROOT / args.conf
    _stage, conf = stage_film(film, conf)
    clear_frames(out_dir)
    film_meta = {
        "film": film.name,
        "flm_bytes": film.stat().st_size,
        "flm_sha256": hashlib.sha256(film.read_bytes()).hexdigest(),
    }

    transport = ListenTransport(port=CONTROL_PORT)
    try:
        transport.listen()
    except OSError as exc:
        print(
            f"[capture] cannot listen on 127.0.0.1:{CONTROL_PORT} ({exc}); "
            "close the running DOSBox-X instance (or use --no-launch)",
            file=sys.stderr,
        )
        return 1

    client = TacClient(transport)
    emulator: subprocess.Popen[bytes] | None = None
    try:
        if not args.no_launch:
            exe = shutil.which("dosbox-x")
            if exe is None:
                print(
                    "[capture] dosbox-x is not on PATH; run via mise run capture-ref",
                    file=sys.stderr,
                )
                return 1
            print(
                f"[capture] launching {exe} -conf {conf} (cwd {REPO_ROOT})",
                flush=True,
            )
            emulator = subprocess.Popen(  # noqa: S603
                [exe, "-conf", str(conf)], cwd=str(REPO_ROOT)
            )

        print(f"[capture] waiting for DOSBox-X on 127.0.0.1:{CONTROL_PORT}", flush=True)
        transport.accept(timeout=LAUNCH_TIMEOUT_SECONDS)
        if not client.ping():
            print("[capture] debugger did not answer PING", file=sys.stderr)
            return 1

        meta = capture(
            out_dir,
            args.max_frames,
            client,
            dgroup_segment=args.dgroup_segment,
            film_prefix=film.name[0].lower(),
            extra_meta=film_meta,
        )
    except (RuntimeError, TimeoutError, ConnectionError) as exc:
        if emulator is not None:
            print(
                f"[capture] {exc}; emulator exit status {emulator.poll()}",
                file=sys.stderr,
            )
        else:
            print(f"[capture] {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()
        if emulator is not None and emulator.poll() is None:
            emulator.terminate()
            try:
                emulator.wait(timeout=EMULATOR_STOP_SECONDS)
            except subprocess.TimeoutExpired:
                emulator.kill()

    frames = meta["frames"]
    if not frames:
        print("[capture] no frames captured", file=sys.stderr)
        return 1
    print(
        f"[capture] captured {len(frames)} frames into {out_dir}",
        flush=True,
    )
    return 0


def main() -> int:
    """Run the capture and terminate the emulator."""
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    return run_session(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
