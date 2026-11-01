"""Strip the audio stream from an AVI so a capture keeps only its picture.

dosbox-automation records video and audio together; parity reads only the picture, and the
sound doubles the file. :func:`video_only` copies stream 0's video chunks into a fresh AVI
(header, one ``strl``, ``movi``, rebuilt ``idx1``) and refuses what it cannot copy faithfully:
an OpenDML continuation (a second ``RIFF AVIX``, files over 1 GB), a missing index, or a chunk
that runs past its list.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["AviError", "video_only"]

_VIDEO_IDS = (b"00dc", b"00db")
_AVIH_STREAMS = 24
_AVIH_TOTAL_FRAMES = 16
_AVIH_BYTES = 56


class AviError(ValueError):
    """The file is not an AVI this module can strip."""


def _chunks(data: bytes, start: int, end: int, what: str) -> list[tuple[bytes, int, int]]:
    """``(id, payload start, payload size)`` for each chunk in ``data[start:end]``."""
    found: list[tuple[bytes, int, int]] = []
    pos = start
    while pos < end:
        if pos + 8 > end:
            raise AviError(f"{what}: a chunk header runs past the end at byte {pos}")
        ckid = data[pos : pos + 4]
        (size,) = struct.unpack_from("<I", data, pos + 4)
        if pos + 8 + size > end:
            raise AviError(f"{what}: chunk {ckid!r} at byte {pos} runs past its list")
        found.append((ckid, pos + 8, size))
        pos += 8 + size + (size & 1)
    return found


def _chunk(ckid: bytes, payload: bytes) -> bytes:
    return ckid + struct.pack("<I", len(payload)) + payload + (b"\0" if len(payload) & 1 else b"")


def _list(kind: bytes, payload: bytes) -> bytes:
    return _chunk(b"LIST", kind + payload)


def _check_container(data: bytes) -> int:
    """The end of the first RIFF, after refusing a non-AVI or an OpenDML continuation."""
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"AVI ":
        raise AviError("not a RIFF AVI file")
    (size,) = struct.unpack_from("<I", data, 4)
    end: int = 8 + size + (size & 1)
    if end > len(data):
        raise AviError("the RIFF chunk runs past the end of the file")
    if data[end : end + 4] == b"RIFF" and data[end + 8 : end + 12] == b"AVIX":
        raise AviError("an OpenDML continuation (RIFF AVIX) is not supported")
    return end


def _video_strl(data: bytes, hdrl_start: int, hdrl_end: int) -> bytes:
    """The first ``strl`` of ``hdrl``, as a list chunk, after checking it is the video."""
    for ckid, start, size in _chunks(data, hdrl_start, hdrl_end, "hdrl"):
        if ckid == b"LIST" and data[start : start + 4] == b"strl":
            inner = _chunks(data, start + 4, start + size, "strl")
            strh = next((c for c in inner if c[0] == b"strh"), None)
            if strh is None or data[strh[1] : strh[1] + 4] != b"vids":
                raise AviError("stream 0 is not a video stream")
            return _list(b"strl", data[start + 4 : start + size])
    raise AviError("the AVI has no stream list")


def video_only(src: Path, dst: Path) -> int:
    """Write *dst* holding only *src*'s stream 0 video chunks; return how many there are."""
    data = src.read_bytes()
    riff_end = _check_container(data)

    hdrl: tuple[int, int] | None = None
    movi: tuple[int, int] | None = None
    index: tuple[int, int] | None = None
    for ckid, start, size in _chunks(data, 12, riff_end, "RIFF"):
        form = data[start : start + 4]
        if ckid == b"LIST" and form == b"hdrl":
            hdrl = (start + 4, start + size)
        elif ckid == b"LIST" and form == b"movi":
            movi = (start, start + size)
        elif ckid == b"idx1":
            index = (start, start + size)
    if hdrl is None:
        raise AviError("the AVI has no hdrl list")
    if movi is None:
        raise AviError("the AVI has no movi list")
    if index is None:
        raise AviError("the AVI has no idx1 index")

    avih = next((c for c in _chunks(data, *hdrl, "hdrl") if c[0] == b"avih"), None)
    if avih is None or avih[2] < _AVIH_BYTES:
        raise AviError("the AVI has no usable avih header")
    strl = _video_strl(data, *hdrl)

    flags = {offset: flag for _ckid, flag, offset, _size in _chunks_idx(data, *index)}

    movi_fourcc = movi[0]
    chunks = _chunks(data, movi[0] + 4, movi[1], "movi")
    # idx1 offsets are relative to the movi fourcc by the spec; some writers use the file.
    first_relative = (chunks[0][1] - 8 - movi_fourcc) if chunks else 0
    base = movi_fourcc if first_relative in flags or not flags else 0

    kept: list[bytes] = []
    table: list[bytes] = []
    cursor = 4
    for ckid, start, size in chunks:
        if ckid not in _VIDEO_IDS:
            continue
        payload = data[start : start + size]
        kept.append(_chunk(ckid, payload))
        table.append(struct.pack("<4sIII", ckid, flags.get(start - 8 - base, 0), cursor, size))
        cursor += 8 + size + (size & 1)

    avih_payload = bytearray(data[avih[1] : avih[1] + avih[2]])
    struct.pack_into("<I", avih_payload, _AVIH_STREAMS, 1)
    struct.pack_into("<I", avih_payload, _AVIH_TOTAL_FRAMES, len(kept))
    hdrl_out = _list(b"hdrl", _chunk(b"avih", bytes(avih_payload)) + strl)
    movi_out = _list(b"movi", b"".join(kept))
    idx_out = _chunk(b"idx1", b"".join(table))
    body = b"AVI " + hdrl_out + movi_out + idx_out
    dst.write_bytes(b"RIFF" + struct.pack("<I", len(body)) + body)
    return len(kept)


def _chunks_idx(data: bytes, start: int, end: int) -> list[tuple[bytes, int, int, int]]:
    """The ``(id, flags, offset, size)`` entries of an ``idx1`` payload."""
    if (end - start) % 16:
        raise AviError("idx1 is not a whole number of 16-byte entries")
    return [struct.unpack_from("<4sIII", data, pos) for pos in range(start, end, 16)]
