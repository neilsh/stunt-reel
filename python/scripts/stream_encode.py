"""Encode a ``capture-video --stream`` directory's ``stream.log`` into a lossless ``stream.mkv``.

``mise run stream-encode -- <dir> [--delete-log]`` writes ``<dir>/stream.mkv`` and
``<dir>/stream.json`` (see :mod:`stunt_reel.tac.stream`). ``--delete-log`` removes the log only
after the round trip has passed. Exit 0 when encoded, 2 when the log is refused.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from stunt_reel.tac import stream

if TYPE_CHECKING:
    from collections.abc import Sequence


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dir", type=Path, help=f"directory holding {stream.LOG_NAME}")
    parser.add_argument(
        "--delete-log",
        action="store_true",
        help=f"delete {stream.LOG_NAME} once the round trip has passed",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Encode the log; 0 encoded, 2 refused."""
    args = parse_args(argv)
    try:
        info = stream.encode_stream(
            args.dir / stream.LOG_NAME, args.dir, delete_log=args.delete_log
        )
    except (stream.StreamError, OSError) as error:
        print(f"stream-encode: {error}", file=sys.stderr)
        return 2
    mkv_bytes = (args.dir / stream.MKV_NAME).stat().st_size
    raw_mb = info.frames * stream.FRAME_BYTES / 1e6
    print(
        f"[stream-encode] {info.frames} frames, {stream.MKV_NAME} {mkv_bytes} bytes, "
        f"raw {raw_mb:.1f} MB"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
