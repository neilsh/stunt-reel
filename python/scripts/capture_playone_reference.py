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
import logging
import shutil
import subprocess
import sys
from pathlib import Path

from stunt_reel.tac.client import TacClient
from stunt_reel.tac.framebuffer import capture
from stunt_reel.tac.transport import ListenTransport

CONTROL_PORT: int = 58991
LAUNCH_TIMEOUT_SECONDS: float = 30.0
EMULATOR_STOP_SECONDS: float = 10.0
REPO_ROOT: Path = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("build/parity/reference/ctry"),
        help="directory receiving tick_*.idx, palettes_*.json, and meta.json",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=140,
        help="maximum number of film frames to capture",
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


def clear_frames(out_dir: Path) -> None:
    """Delete rasters from an earlier run so the capture cannot leave stale frames."""
    if not out_dir.is_dir():
        return
    for pattern in ("tick_*.idx", "palettes_*.json", "_scratch.idx"):
        for stale in out_dir.glob(pattern):
            stale.unlink()


def run_session(args: argparse.Namespace) -> int:
    """Launch one emulator, drive the dialog, and capture frames."""
    out_dir: Path = args.out if args.out.is_absolute() else REPO_ROOT / args.out
    conf: Path = args.conf if args.conf.is_absolute() else REPO_ROOT / args.conf
    clear_frames(out_dir)

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

        meta = capture(out_dir, args.max_frames, client)
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
