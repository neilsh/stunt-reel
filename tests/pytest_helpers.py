"""Per-run pytest temporary roots, shaped for DSH's Windows sandbox.

pytest deletes a --basetemp directory it finds on disk and resets the permissions
of a cache directory it creates.  A sandboxed run may do neither, so the checkout
keeps a cache directory it creates itself and names the temporary root after the
run: there is nothing stale to delete, and pytest never resets a directory the
sandbox already provisioned.
"""

from __future__ import annotations

import os
import secrets
import shutil
import struct
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from stunt_reel.bench.planes import RenderPlanes

CACHE_DIRNAME = ".pytest_cache"
BASETEMP_PREFIX = "basetemp-"
KEEP_BASETEMPS = 3

_SHIM_INSTALLED = False


def _needs_mkdir_shim() -> bool:
    """Return whether this process needs the shim, without narrowing a caller.

    The answer is a plain bool from a call, not a `sys.platform` comparison in
    the caller, so a mypy run analysing for another platform cannot narrow the
    guard to always true and mark the shim body unreachable.
    """
    return sys.platform == "win32"


def install_windows_mkdir_shim() -> None:
    """Ignore the POSIX mode on Windows, once per process.

    A directory created with mkdir(mode=0o700) cannot be listed or removed by the
    process that created it under DSH's Windows sandbox; pytest creates its
    basetemp and numbered temp dirs that way.  Windows ignores the mode anyway, so
    dropping it changes no behaviour outside the sandbox.
    """
    global _SHIM_INSTALLED  # noqa: PLW0603
    if _SHIM_INSTALLED or not _needs_mkdir_shim():
        return
    real_mkdir = os.mkdir

    def mkdir(
        path: str | os.PathLike[str], mode: int = 0o777, *, dir_fd: int | None = None
    ) -> None:
        del mode  # Windows ignores it; keeping the name keeps keyword callers working
        real_mkdir(path, 0o777, dir_fd=dir_fd)

    os.mkdir = mkdir  # type: ignore[assignment]
    _SHIM_INSTALLED = True


def cache_dir(rootpath: Path) -> Path:
    """Return the checkout's pytest cache directory, creating it without a chmod."""
    cache = rootpath / CACHE_DIRNAME
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def per_run_basetemp(
    rootpath: Path, *, now: datetime | None = None, suffix: str | None = None
) -> Path:
    """Return a fresh basetemp path under rootpath; it must not exist yet."""
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%S")
    suffix = suffix if suffix is not None else secrets.token_hex(2)
    return rootpath / CACHE_DIRNAME / f"{BASETEMP_PREFIX}{stamp}-{suffix}"


def prune_old_basetemps(cache: Path, *, keep: int = KEEP_BASETEMPS) -> None:
    """Remove the older per-run basetemps, best effort; the sandbox may refuse."""
    try:
        runs = sorted(
            path
            for path in cache.iterdir()
            if path.is_dir() and path.name.startswith(BASETEMP_PREFIX)
        )
    except OSError:
        return
    for path in runs[: max(0, len(runs) - keep)]:
        shutil.rmtree(path, ignore_errors=True)


def _riff_chunk(ckid: bytes, payload: bytes) -> bytes:
    pad = b"\0" if len(payload) & 1 else b""
    return ckid + struct.pack("<I", len(payload)) + payload + pad


def build_avi(video: list[bytes], audio: list[bytes]) -> bytes:
    """A minimal AVI: avih, a ``vids`` and an ``auds`` stream list, interleaved ``movi``, ``idx1``.

    The first video chunk is a keyframe (flag 0x10); every other chunk has flag 0. Chunk ``n`` of
    each kind is written video first, so the file reads 00dc, 01wb, 00dc, 01wb, ...
    """

    def lst(kind: bytes, payload: bytes) -> bytes:
        return _riff_chunk(b"LIST", kind + payload)

    count = len(video)
    avih = bytearray(56)
    struct.pack_into("<IIII", avih, 0, 14286, 0, 0, 0x10)
    struct.pack_into("<III", avih, 16, count, 0, 2)
    struct.pack_into("<II", avih, 32, 320, 200)
    strl_v = lst(
        b"strl",
        _riff_chunk(b"strh", b"vids" + b"\0" * 52) + _riff_chunk(b"strf", b"\0" * 40),
    )
    strl_a = lst(
        b"strl",
        _riff_chunk(b"strh", b"auds" + b"\0" * 52) + _riff_chunk(b"strf", b"\0" * 16),
    )
    hdrl = lst(b"hdrl", _riff_chunk(b"avih", bytes(avih)) + strl_v + strl_a)

    movi = b""
    index = b""
    pieces = [(b"00dc", payload) for payload in video]
    pieces = (
        [
            piece
            for pair in zip(pieces, [(b"01wb", payload) for payload in audio], strict=False)
            for piece in pair
        ]
        + pieces[len(audio) :]
        + [(b"01wb", payload) for payload in audio[len(video) :]]
    )
    keyframe = True
    for ckid, payload in pieces:
        flags = 0x10 if ckid == b"00dc" and keyframe else 0
        keyframe = keyframe and ckid != b"00dc"
        index += struct.pack("<4sIII", ckid, flags, 4 + len(movi), len(payload))
        movi += _riff_chunk(ckid, payload)
    body = b"AVI " + hdrl + lst(b"movi", movi) + _riff_chunk(b"idx1", index)
    return b"RIFF" + struct.pack("<I", len(body)) + body


class MemorySource:
    """A :class:`~stunt_reel.bench.planes.RenderSource` over planes held in memory."""

    def __init__(self, ticks: dict[int, RenderPlanes]) -> None:
        self._ticks = ticks

    def ticks(self) -> list[int]:
        """The held ticks, ascending."""
        return sorted(self._ticks)

    def load(self, tick: int) -> RenderPlanes:
        """The planes of one held tick."""
        return self._ticks[tick]
