"""Stripping the audio stream from an AVI (no emulator, no corpus)."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import pytest

from pytest_helpers import build_avi
from stunt_reel.avi import AviError, video_only

if TYPE_CHECKING:
    from pathlib import Path

VIDEO = [b"\x01\x02\x03", b"\x04\x05", b"\x06\x07\x08\x09"]
AUDIO = [b"a" * 10, b"b" * 7, b"c" * 4]


def _strip(tmp_path: Path, blob: bytes) -> tuple[int, bytes]:
    src, dst = tmp_path / "in.avi", tmp_path / "out.avi"
    src.write_bytes(blob)
    count = video_only(src, dst)
    return count, dst.read_bytes()


def _movi(avi: bytes) -> list[tuple[bytes, bytes]]:
    """``(id, payload)`` of every chunk in the ``movi`` list."""
    at = avi.index(b"movi") + 4
    (outer,) = struct.unpack_from("<I", avi, avi.index(b"movi") - 4)
    end = at + outer - 4
    found = []
    while at < end:
        ckid = avi[at : at + 4]
        (size,) = struct.unpack_from("<I", avi, at + 4)
        found.append((ckid, avi[at + 8 : at + 8 + size]))
        at += 8 + size + (size & 1)
    return found


def _idx(avi: bytes) -> list[tuple[bytes, int, int, int]]:
    at = avi.index(b"idx1")
    (size,) = struct.unpack_from("<I", avi, at + 4)
    return [struct.unpack_from("<4sIII", avi, p) for p in range(at + 8, at + 8 + size, 16)]


def test_video_only_keeps_video_chunks_in_order(tmp_path: Path) -> None:
    count, out = _strip(tmp_path, build_avi(VIDEO, AUDIO))

    assert count == 3
    assert _movi(out) == [(b"00dc", payload) for payload in VIDEO]
    assert b"01wb" not in out


def test_video_only_keeps_keyframe_flags(tmp_path: Path) -> None:
    _, out = _strip(tmp_path, build_avi(VIDEO, AUDIO))

    entries = _idx(out)
    assert [flags for _, flags, _, _ in entries] == [0x10, 0, 0]
    assert [size for _, _, _, size in entries] == [len(v) for v in VIDEO]
    # Offsets are relative to the movi fourcc: the first chunk sits right after it.
    assert entries[0][2] == 4
    assert entries[1][2] == 4 + 8 + 4  # header + 3 bytes padded to 4


def test_video_only_sets_one_stream(tmp_path: Path) -> None:
    _, out = _strip(tmp_path, build_avi(VIDEO, AUDIO))

    at = out.index(b"avih") + 8
    streams, total = (
        struct.unpack_from("<I", out, at + 24)[0],
        struct.unpack_from("<I", out, at + 16)[0],
    )
    assert streams == 1
    assert total == 3
    assert out.count(b"strl") == 1
    assert b"auds" not in out


def test_zero_length_video_chunks_are_kept(tmp_path: Path) -> None:
    count, out = _strip(tmp_path, build_avi([b"\x01", b"", b"\x02"], [b"x", b"y", b"z"]))

    assert count == 3
    assert [payload for _, payload in _movi(out)] == [b"\x01", b"", b"\x02"]


def test_a_truncated_movi_is_refused(tmp_path: Path) -> None:
    blob = build_avi(VIDEO, AUDIO)
    at = blob.index(b"movi") - 4
    (size,) = struct.unpack_from("<I", blob, at)
    broken = bytearray(blob)
    struct.pack_into("<I", broken, at, size - 6)  # the list now ends inside the last chunk

    with pytest.raises(AviError, match="past its list"):
        _strip(tmp_path, bytes(broken))


def test_a_missing_idx1_is_refused(tmp_path: Path) -> None:
    blob = build_avi(VIDEO, AUDIO)
    cut = blob[: blob.index(b"idx1")]
    cut = cut[:4] + struct.pack("<I", len(cut) - 8) + cut[8:]

    with pytest.raises(AviError, match="idx1"):
        _strip(tmp_path, cut)


def test_an_opendml_continuation_is_refused(tmp_path: Path) -> None:
    blob = build_avi(VIDEO, AUDIO) + b"RIFF" + struct.pack("<I", 4) + b"AVIX"

    with pytest.raises(AviError, match="OpenDML"):
        _strip(tmp_path, blob)


def test_a_file_that_is_not_an_avi_is_refused(tmp_path: Path) -> None:
    with pytest.raises(AviError, match="RIFF AVI"):
        _strip(tmp_path, b"not an avi at all")
