"""The render store: the plane files beside ``render.json`` (ADR 0027), read and written in
per-second zstd chunks.
"""

from __future__ import annotations

import shutil
import struct
import zlib
from collections import OrderedDict
from compression import zstd
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from stunt_reel.parity_artifacts._fields import _error
from stunt_reel.parity_artifacts.render import (
    RENDER_CHUNK_TICKS,
    RENDER_DOCUMENT,
    RENDER_SCHEMA_VERSION,
    FilmId,
    Geometry,
    Page,
    RenderChunk,
    RenderRecord,
    RenderTick,
    StoreSpan,
    _read_render_v2,
    write_render,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path


#: A render's index planes, one byte per pixel, a zstd frame per film second.
RENDER_INDEX_FILE = "frames.zst"
#: A render's layer planes, one little-endian u16 per pixel, chunked like the index planes.
RENDER_LAYER_FILE = "layers.zst"
#: A render's distinct palettes, :data:`PALETTE_BYTES` each, as one zstd frame.
RENDER_PALETTE_FILE = "palettes.zst"
#: One indexed PNG per film second of a render, for people.
RENDER_PREVIEW_DIR = "preview"
#: Bytes of one stored render palette: 256 RGB triples.
PALETTE_BYTES = 768
#: zstd level of every render chunk (mirrors the Rust ``render_store``).
_ZSTD_LEVEL = 3
#: Decoded chunks a :class:`RenderStore` keeps, so a reader reaching back one second does
#: not decode twice.
_CACHED_CHUNKS = 2


def _indexed_png(width: int, height: int, palette: bytes, indices: bytes) -> bytes:
    """An 8-bit indexed PNG of *indices* in *palette*, standard library only."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body)
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    rows = b"".join(b"\x00" + indices[y * width : (y + 1) * width] for y in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 3, 0, 0, 0))
        + chunk(b"PLTE", palette)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


@dataclass(frozen=True)
class StoredFrame:
    """One stored render tick: its planes and the palette its picture is drawn in.

    ``indices`` holds one byte per pixel over the full raster, ``layers`` one
    little-endian u16 per pixel, and ``palette`` 256 RGB triples; the picture is
    ``palette[index]`` at every pixel.
    """

    indices: bytes
    layers: bytes
    palette: bytes


class RenderStore:
    """Reads a render directory's store (ADR 0027), keeping the last two decoded chunks.

    Opening reads and validates ``render.json``, checks the two plane files against its
    chunk table and reads the palettes, so a later :meth:`frame` only decodes.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.record = _read_render_v2(directory)
        ends = (0, 0)
        if self.record.chunks:
            last = self.record.chunks[-1]
            ends = (last.index.offset + last.index.length, last.layer.offset + last.layer.length)
        if self.record.ticks:
            for name, end in zip((RENDER_INDEX_FILE, RENDER_LAYER_FILE), ends, strict=True):
                path = directory / name
                try:
                    size = path.stat().st_size
                except OSError as err:
                    raise _error("missing", f"the file must be readable ({err})", path) from err
                if size != end:
                    raise _error(
                        "store", f"holds {size} bytes but render.json's chunks end at {end}", path
                    )
        self._palettes = _read_palettes(directory / RENDER_PALETTE_FILE, self.record.palette_count)
        self._rows = {entry.tick: row for row, entry in enumerate(self.record.ticks)}
        self._cache: OrderedDict[int, tuple[bytes, bytes]] = OrderedDict()

    def ticks(self) -> list[int]:
        """The film ticks the render holds, ascending."""
        return [entry.tick for entry in self.record.ticks]

    def holds(self, tick: int) -> bool:
        """Whether the render holds film tick *tick*."""
        return tick in self._rows

    def credits(self, tick: int) -> bool:
        """Whether the film shows credits at *tick*; ``False`` for a tick the store lacks."""
        row = self._rows.get(tick)
        return row is not None and self.record.ticks[row].credits

    def frame(self, tick: int) -> StoredFrame:
        """The planes and palette of film tick *tick*, decoding its chunk unless cached."""
        slot = self.record.locate(tick)
        if slot is None:
            raise _error("missing", f"holds no render of tick {tick}", self.directory)
        chunk, position = slot
        indices, layers = self._decoded(chunk)
        pixels = self.record.geometry.width * self.record.geometry.height
        entry = self.record.ticks[self._rows[tick]]
        return StoredFrame(
            indices=indices[position * pixels : (position + 1) * pixels],
            layers=layers[position * pixels * 2 : (position + 1) * pixels * 2],
            palette=self._palettes[entry.palette_index],
        )

    def _decoded(self, chunk: int) -> tuple[bytes, bytes]:
        cached = self._cache.get(chunk)
        if cached is not None:
            self._cache.move_to_end(chunk)
            return cached
        entry = self.record.chunks[chunk]
        pixels = self.record.geometry.width * self.record.geometry.height * entry.ticks
        decoded = (
            self._read_chunk(RENDER_INDEX_FILE, entry.index, entry.second, pixels),
            self._read_chunk(RENDER_LAYER_FILE, entry.layer, entry.second, pixels * 2),
        )
        self._cache[chunk] = decoded
        while len(self._cache) > _CACHED_CHUNKS:
            self._cache.popitem(last=False)
        return decoded

    def _read_chunk(self, name: str, span: StoreSpan, second: int, expected: int) -> bytes:
        path = self.directory / name
        try:
            with path.open("rb") as handle:
                handle.seek(span.offset)
                packed = handle.read(span.length)
        except OSError as err:
            raise _error("missing", f"the file must be readable ({err})", path) from err
        try:
            raw = zstd.decompress(packed)
        except zstd.ZstdError as err:
            raise _error("store", f"second {second} does not decompress: {err}", path) from err
        if len(raw) != expected:
            raise _error(
                "store",
                f"second {second} decompresses to {len(raw)} bytes, expected {expected}",
                path,
            )
        return raw


def _read_palettes(path: Path, count: int) -> tuple[bytes, ...]:
    """``palettes.zst``, which must hold exactly *count* palettes."""
    if count == 0 and not path.exists():
        return ()
    try:
        packed = path.read_bytes()
    except OSError as err:
        raise _error("missing", f"the file must be readable ({err})", path) from err
    try:
        raw = zstd.decompress(packed)
    except zstd.ZstdError as err:
        raise _error("store", f"does not decompress: {err}", path) from err
    expected = count * PALETTE_BYTES
    if len(raw) != expected:
        raise _error(
            "store", f"holds {len(raw)} bytes, expected {expected} for {count} palettes", path
        )
    return tuple(raw[at : at + PALETTE_BYTES] for at in range(0, expected, PALETTE_BYTES))


class RenderStoreWriter:
    """Writes a render's planes in tick order, a zstd chunk per film second (ADR 0027).

    Nothing is created until the first tick. The writer replaces its own files and
    ``preview/`` and leaves anything else in the directory.
    """

    def __init__(self, directory: Path, geometry: Geometry) -> None:
        self.directory = directory
        self.geometry = geometry
        self._pixels = geometry.width * geometry.height
        self._started = False
        self._ends = [0, 0]
        self._last_tick: int | None = None
        self._palettes: dict[bytes, int] = {}
        self._open: tuple[int, list[bytes], list[bytes]] | None = None
        self._chunks: list[RenderChunk] = []

    def push(self, tick: int, palette: bytes, indices: bytes, layers: bytes) -> int:
        """Append one tick and return the index of its palette in the store.

        *layers* is one little-endian u16 per pixel; *palette* 768 bytes.
        """
        if len(indices) != self._pixels or len(layers) != 2 * self._pixels:
            raise _error(
                "geometry",
                f"tick {tick} has {len(indices)} index and {len(layers)} layer bytes, expected "
                f"{self._pixels} and {2 * self._pixels} for "
                f"{self.geometry.width}x{self.geometry.height}",
                self.directory,
            )
        if len(palette) != PALETTE_BYTES:
            raise _error("store", f"tick {tick} palette holds {len(palette)} bytes", self.directory)
        if self._last_tick is not None and tick <= self._last_tick:
            raise _error(
                "ordering", f"tick {tick} does not follow tick {self._last_tick}", self.directory
            )
        if not self._started:
            self._start()
        second = tick // RENDER_CHUNK_TICKS
        if self._open is not None and self._open[0] != second:
            self._close_chunk()
        if self._open is None:
            preview = self.directory / RENDER_PREVIEW_DIR / f"sec_{second:04d}.png"
            preview.write_bytes(
                _indexed_png(self.geometry.width, self.geometry.height, palette, indices)
            )
            self._open = (second, [], [])
        self._open[1].append(bytes(indices))
        self._open[2].append(bytes(layers))
        self._last_tick = tick
        return self._palettes.setdefault(bytes(palette), len(self._palettes))

    def finish(self) -> tuple[int, tuple[RenderChunk, ...]] | None:
        """Write the last chunk and ``palettes.zst``: the palette count and chunk table.

        ``None`` when no tick was pushed.
        """
        if not self._started:
            return None
        self._close_chunk()
        packed = zstd.compress(b"".join(self._palettes), level=_ZSTD_LEVEL)
        (self.directory / RENDER_PALETTE_FILE).write_bytes(packed)
        return len(self._palettes), tuple(self._chunks)

    def _start(self) -> None:
        preview = self.directory / RENDER_PREVIEW_DIR
        if preview.is_dir():
            shutil.rmtree(preview)
        preview.mkdir(parents=True)
        for name in (RENDER_INDEX_FILE, RENDER_LAYER_FILE):
            (self.directory / name).write_bytes(b"")
        self._started = True

    def _close_chunk(self) -> None:
        if self._open is None:
            return
        second, indices, layers = self._open
        spans: list[StoreSpan] = []
        planes = (b"".join(indices), b"".join(layers))
        for slot, (name, raw) in enumerate(
            zip((RENDER_INDEX_FILE, RENDER_LAYER_FILE), planes, strict=True)
        ):
            packed = zstd.compress(raw, level=_ZSTD_LEVEL)
            with (self.directory / name).open("ab") as handle:
                handle.write(packed)
            spans.append(StoreSpan(offset=self._ends[slot], length=len(packed)))
            self._ends[slot] += len(packed)
        self._chunks.append(
            RenderChunk(second=second, ticks=len(indices), index=spans[0], layer=spans[1])
        )
        self._open = None


def write_render_store(
    directory: Path,
    film: FilmId,
    geometry: Geometry,
    frames: Iterable[tuple[RenderTick, StoredFrame]],
) -> RenderRecord:
    """Write a whole render store from *frames* in tick order, ``render.json`` last.

    Each tick's ``palette_index`` is assigned by the store; the one it carries is ignored. Any
    ``render.json`` already in *directory* is removed first, so a write that fails or holds no
    tick never leaves the previous render readable as this one.
    """
    (directory / RENDER_DOCUMENT).unlink(missing_ok=True)
    writer = RenderStoreWriter(directory, geometry)
    ticks: list[RenderTick] = []
    for tick, frame in frames:
        index = writer.push(tick.tick, frame.palette, frame.indices, frame.layers)
        ticks.append(replace(tick, palette_index=index))
    table = writer.finish()
    if table is None:
        raise _error("missing", "a render store needs at least one tick", directory)
    palette_count, chunks = table
    record = RenderRecord(
        schema_version=RENDER_SCHEMA_VERSION,
        film=film,
        geometry=geometry,
        ticks=tuple(ticks),
        palette_count=palette_count,
        chunks=chunks,
    )
    write_render(directory / RENDER_DOCUMENT, record)
    return record


def read_page(store: RenderStore, tick: int) -> Page:
    """One stored tick's planes as a :class:`Page`, over the record's full raster.

    The planes span width * height pixels even when viewport_rows narrows the drawn
    scene; only Page.actor_pixels narrows its scan to the viewport.
    """
    frame = store.frame(tick)
    count = len(frame.layers) // 2
    return Page(
        indices=frame.indices,
        layers=struct.unpack(f"<{count}H", frame.layers),
        geometry=store.record.geometry,
    )
