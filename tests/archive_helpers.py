"""Builds synthetic ``.ALL`` archives for tests, following ``research/formats/all.ksy``."""

from __future__ import annotations

import struct

__all__ = ["build_all"]


def build_all(chunks: list[bytes]) -> bytes:
    """A valid archive: count, ids ``1..n``, ``n + 1`` offsets (the last the file size), payloads."""
    count = len(chunks)
    header = 6 * count + 6
    offsets = [header]
    for chunk in chunks:
        offsets.append(offsets[-1] + len(chunk))
    out = struct.pack("<H", count)
    out += b"".join(struct.pack("<H", chunk_id) for chunk_id in range(1, count + 1))
    out += b"".join(struct.pack("<I", offset) for offset in offsets)
    return out + b"".join(chunks)
