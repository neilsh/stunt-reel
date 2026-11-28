"""Encode a ``capture-video --stream`` debug log into a lossless FFV1 video and check the round trip.

The emulator's log holds one composed picture per frame as hex (``p<frame>:<flags>:<hex>``), between
an ``h<token>:<layout>:1`` header and an ``e`` trailer (see :mod:`stunt_reel.tac.luagen`).
:func:`encode_stream` pipes the pictures into ``stream.mkv`` beside the log, decodes that file
back and compares frame count and SHA-256 with what was piped. Only a passing round trip writes
``stream.json``, and only then may the log be deleted.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from collections import Counter
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from stunt_reel.tac.video import FRAME_RATE

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

WIDTH: int = 320
HEIGHT: int = 192
#: Bytes of one picture: one palette index per pixel.
FRAME_BYTES: int = WIDTH * HEIGHT
#: Hex characters of one picture's payload.
HEX_CHARS: int = 2 * FRAME_BYTES
#: The flags a picture may carry.
FLAG_VALUES: range = range(4)
SCHEMA_VERSION: int = 1
LOG_NAME: str = "stream.log"
MKV_NAME: str = "stream.mkv"
JSON_NAME: str = "stream.json"

_PREFIX = re.compile(rb"\[F:\d+ T:[^\]]*\] debugmsg: ")
_HEADER = re.compile(rb"h([0-9A-Za-z]+):([^:\s]+):1")
_FRAME = re.compile(rb"p(\d+):(\d+):([^:]*)")
_HEX = re.compile(rb"[0-9a-f]*")
_TRAILER = re.compile(rb"e(?:x)?(hold|capped)")  # luagen prefixes its strings with x


class StreamError(RuntimeError):
    """A stream log is refused, ffmpeg is missing, or the encoded file does not round-trip."""


@dataclass(frozen=True)
class StreamFrame:
    """One composed picture: its emulated frame number, flags and ``(192 * 320)`` palette indices."""

    frame: int
    flags: int
    indices: bytes


@dataclass(frozen=True)
class StreamInfo:
    """What ``stream.json`` records about an encoded stream."""

    frames: int
    first_frame: int
    flags: dict[int, int]
    layout: str
    end: str
    sha256_raw: str
    sha256_file: str


@dataclass
class _Found:
    """The header and trailer values, filled in while :func:`_frames` reads the log."""

    layout: str = ""
    end: str = ""


def _frames(path: Path, found: _Found) -> Iterator[StreamFrame]:
    """Yield the log's pictures, filling *found*; raise StreamError at the first violation."""
    try:
        handle = path.open("rb")
    except OSError as error:
        raise StreamError(f"cannot read {path}: {error}") from error
    last: int | None = None
    with handle:
        for number, line in enumerate(handle, 1):
            match = _PREFIX.match(line)
            if match is None:
                continue
            payload = line[match.end() :].rstrip(b"\r\n")
            where = f"{path}:{number}"
            kind = payload[:1]
            if kind == b"h":
                head = _HEADER.fullmatch(payload)
                if head is None:
                    raise StreamError(f"{where}: header is not h<token>:<layout>:1")
                if found.layout:
                    raise StreamError(f"{where}: a second header line")
                found.layout = head.group(2).decode("ascii")
            elif kind == b"p":
                if not found.layout:
                    raise StreamError(f"{where}: a frame line comes before the header")
                if found.end:
                    raise StreamError(f"{where}: a frame line comes after the trailer")
                picture = _FRAME.fullmatch(payload)
                if picture is None:
                    raise StreamError(f"{where}: frame line is not p<frame>:<flags>:<hex>")
                frame = int(picture.group(1))
                flags = int(picture.group(2))
                hexpart = picture.group(3)
                if flags not in FLAG_VALUES:
                    raise StreamError(f"{where}: flags {flags} are outside 0..3")
                if last is not None and frame != last + 1:
                    raise StreamError(
                        f"{where}: frame {frame} follows frame {last}, not {last + 1}"
                    )
                if len(hexpart) != HEX_CHARS:
                    raise StreamError(
                        f"{where}: frame {frame} has {len(hexpart)} hex characters, not {HEX_CHARS}"
                    )
                if _HEX.fullmatch(hexpart) is None:
                    raise StreamError(f"{where}: frame {frame} has characters outside [0-9a-f]")
                last = frame
                yield StreamFrame(frame, flags, bytes.fromhex(hexpart.decode("ascii")))
            elif kind == b"e":
                if not found.layout:
                    raise StreamError(f"{where}: the trailer comes before the header")
                if found.end:
                    raise StreamError(f"{where}: a second trailer line")
                trailer = _TRAILER.fullmatch(payload)
                if trailer is None:
                    raise StreamError(f"{where}: trailer is not e<hold|capped>")
                found.end = trailer.group(1).decode("ascii")
            # any other emulator line is noise and is ignored
    if not found.layout:
        raise StreamError(f"{path}: no header line h<token>:<layout>:1")
    if last is None:
        raise StreamError(f"{path}: no frame lines")
    if not found.end:
        raise StreamError(f"{path}: no e<hold|capped> trailer after the last frame")


def read_stream(path: Path) -> Iterator[StreamFrame]:
    """Every picture of the log at *path*, in order.

    Raises StreamError on any violation. A missing header, trailer or frame is found only at end
    of file, so the caller must consume the generator fully before trusting its pictures.
    """
    return _frames(path, _Found())


def _ffmpeg() -> str:
    """The ffmpeg executable on PATH; StreamError if there is none."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise StreamError("ffmpeg is not on PATH; the stream is encoded with it")
    return ffmpeg


def decode_stream(mkv: Path) -> Iterator[np.ndarray]:
    """Every picture of the encoded file *mkv*, in order, as ``(192, 320)`` ``uint8`` indices.

    Raises StreamError if ffmpeg cannot decode it or ends inside a picture.
    """
    ffmpeg = _ffmpeg()
    command = [ffmpeg, "-v", "error", "-i", str(mkv), "-fps_mode", "passthrough"]
    command += ["-f", "rawvideo", "-pix_fmt", "gray", "-"]
    with subprocess.Popen(command, stdout=subprocess.PIPE) as process:  # noqa: S603
        stdout = process.stdout
        if stdout is None:
            raise StreamError(f"{mkv}: ffmpeg gave no output stream")
        try:
            while chunk := stdout.read(FRAME_BYTES):
                if len(chunk) != FRAME_BYTES:
                    raise StreamError(f"{mkv}: ffmpeg ended inside a picture")
                yield np.frombuffer(chunk, dtype=np.uint8).reshape(HEIGHT, WIDTH)
            if process.wait() != 0:
                raise StreamError(f"{mkv}: ffmpeg failed to decode it")
        finally:
            process.kill()  # a reader that stops early must not leave ffmpeg on a broken pipe


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _document(info: StreamInfo) -> dict[str, object]:
    """The ``stream.json`` document for *info*."""
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "stream",
        "file": MKV_NAME,
        "sha256_raw": info.sha256_raw,
        "sha256_file": info.sha256_file,
        "frames": info.frames,
        "first_frame": info.first_frame,
        "width": WIDTH,
        "height": HEIGHT,
        "flags": {str(flag): count for flag, count in info.flags.items()},
        "layout": info.layout,
        "end": info.end,
    }


def encode_stream(log: Path, out_dir: Path, *, delete_log: bool = False) -> StreamInfo:
    """Encode the pictures of *log* into *out_dir*/stream.mkv and write stream.json beside it.

    The round trip must match (frame count and raw SHA-256) before stream.json is written. On any
    refusal the log is kept and a partial or mismatched stream.mkv is removed. With *delete_log*
    the log is deleted only after the round trip passed. Raises StreamError on every failure.
    """
    ffmpeg = _ffmpeg()
    out_dir.mkdir(parents=True, exist_ok=True)
    mkv = out_dir / MKV_NAME
    rate = f"{FRAME_RATE[0]}/{FRAME_RATE[1]}"
    command = [ffmpeg, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray"]
    command += ["-s", f"{WIDTH}x{HEIGHT}", "-framerate", rate, "-i", "-"]
    command += ["-c:v", "ffv1", "-level", "3", "-pix_fmt", "gray", "-fps_mode", "passthrough"]
    command += [str(mkv)]

    found = _Found()
    raw = hashlib.sha256()
    flags: Counter[int] = Counter()
    frames = 0
    first = 0
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)  # noqa: S603
    stdin, stderr = process.stdin, process.stderr
    if stdin is None or stderr is None:
        process.kill()
        process.wait()
        raise StreamError("ffmpeg gave no input pipe")
    try:
        for picture in _frames(log, found):
            if frames == 0:
                first = picture.frame
            try:
                stdin.write(picture.indices)
            except BrokenPipeError as error:
                raise StreamError("ffmpeg stopped accepting pictures") from error
            raw.update(picture.indices)
            flags[picture.flags] += 1
            frames += 1
        with suppress(BrokenPipeError):
            stdin.close()
        message = stderr.read().decode("utf-8", errors="replace").strip()
        status = process.wait()
    except BaseException:
        # ffmpeg may still hold the pipe: kill it, drop the unflushed input quietly, then reap it.
        process.kill()
        with suppress(OSError):
            stdin.close()
        process.wait()
        mkv.unlink(missing_ok=True)
        raise
    finally:
        stderr.close()
    if status != 0:
        mkv.unlink(missing_ok=True)
        raise StreamError(f"ffmpeg could not encode {log}: {message}")

    decoded = hashlib.sha256()
    count = 0
    try:
        for pixels in decode_stream(mkv):
            decoded.update(pixels.tobytes())
            count += 1
    except StreamError:
        mkv.unlink(missing_ok=True)
        raise
    if count != frames or decoded.hexdigest() != raw.hexdigest():
        mkv.unlink(missing_ok=True)
        hashes = "match" if decoded.hexdigest() == raw.hexdigest() else "differ"
        raise StreamError(
            f"round trip of {mkv} differs: {count} of {frames} pictures decoded, hashes {hashes}"
        )

    info = StreamInfo(
        frames=frames,
        first_frame=first,
        flags={flag: flags[flag] for flag in FLAG_VALUES},
        layout=found.layout,
        end=found.end,
        sha256_raw=raw.hexdigest(),
        sha256_file=_sha256_file(mkv),
    )
    (out_dir / JSON_NAME).write_text(json.dumps(_document(info), indent=2) + "\n", encoding="utf-8")
    if delete_log:
        log.unlink()
    return info
