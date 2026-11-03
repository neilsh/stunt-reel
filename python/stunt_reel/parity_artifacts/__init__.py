"""Typed readers and writers for the parity artifacts, standard library only.

This is the Python mirror of the Rust port in ``crates/stunt-parity``: the same
documents, field names, schema version and validation rules, so a ``render.json``
written by either side loads in the other. The package is the one home for artifact
names, tick file naming, the capture ``--tick-range`` mapping, the capture document
writer and the retime document rewrite; callers stop hard-coding the 320x200
raster, the 185-row viewport or the actor layer id.

One module per document family, every public name re-exported here so callers import
from ``stunt_reel.parity_artifacts``:

- ``_fields``: :class:`ArtifactError`, JSON file access and the field readers every
  document shares;
- ``render``: the film identity, the geometry and the ``render.json`` record;
- ``store``: the plane files beside ``render.json``;
- ``capture``: a capture's ``meta.json`` and palette files;
- ``video``: a video capture's ``meta.json``;
- ``report``: ``report.json``.

The capture writer emits the port's document first and then merges the harness's
diagnostic keys (``palette_source``, ``global_tick`` and so on). Those keys are
capture evidence, not parity contract: the port does not read them, and a
diagnostic may not shadow a field the port owns.

``render.json`` is the typed render record (ADR 0005) and the table of contents of
the render store beside it (ADR 0027): ``frames.zst``, ``layers.zst`` and
``palettes.zst``, read by :class:`RenderStore` and written by
:class:`RenderStoreWriter` with the standard library's ``compression.zstd``. Reports
keep serde-defaulted optional fields, so a report written before a field existed
still loads.

Errors are ``ArtifactError`` (a ``ValueError`, so the parity scripts' existing
handlers keep working), naming the file and the field.
"""

from __future__ import annotations

from stunt_reel.parity_artifacts._fields import (
    CAPTURE_META,
    PALETTE_ENTRIES,
    SCHEMA_VERSION,
    ArtifactError,
)
from stunt_reel.parity_artifacts.capture import (
    CAPTURE_FRAMES_DIR as CAPTURE_FRAMES_DIR,
)
from stunt_reel.parity_artifacts.capture import (
    CAPTURE_HEIGHT,
    CAPTURE_WIDTH,
    CapturedFrame,
    CaptureSet,
    read_capture,
    read_capture_palette,
    write_capture,
)
from stunt_reel.parity_artifacts.capture import (
    _capture_document as _capture_document,
)
from stunt_reel.parity_artifacts.render import (
    LAYER_FIRST_ACTOR,
    RENDER_CHUNK_TICKS,
    RENDER_DOCUMENT,
    RENDER_SCHEMA_VERSION,
    CameraPose,
    FilmId,
    Geometry,
    Page,
    RenderChunk,
    RenderControls,
    RenderPalette,
    RenderRecord,
    RenderTick,
    StoreSpan,
    open_render,
    read_render,
    tick_range_for_captured_ticks,
    write_render,
)
from stunt_reel.parity_artifacts.render import (
    _film_fields as _film_fields,
)
from stunt_reel.parity_artifacts.report import (
    FrameReport,
    I6Gate,
    Report,
    parse_report,
    read_report,
    write_report,
)
from stunt_reel.parity_artifacts.store import (
    PALETTE_BYTES,
    RENDER_INDEX_FILE,
    RENDER_LAYER_FILE,
    RENDER_PALETTE_FILE,
    RENDER_PREVIEW_DIR,
    RenderStore,
    RenderStoreWriter,
    StoredFrame,
    read_page,
    write_render_store,
)
from stunt_reel.parity_artifacts.video import (
    VIDEO_FILE,
    PaletteChange,
    PaletteLog,
    TickLog,
    VideoCapture,
    load_video_capture,
    write_video_capture,
)
from stunt_reel.parity_artifacts.video import (
    VIDEO_KIND as VIDEO_KIND,
)

__all__ = [
    "CAPTURE_HEIGHT",
    "CAPTURE_META",
    "CAPTURE_WIDTH",
    "LAYER_FIRST_ACTOR",
    "PALETTE_BYTES",
    "PALETTE_ENTRIES",
    "RENDER_CHUNK_TICKS",
    "RENDER_DOCUMENT",
    "RENDER_INDEX_FILE",
    "RENDER_LAYER_FILE",
    "RENDER_PALETTE_FILE",
    "RENDER_PREVIEW_DIR",
    "RENDER_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "VIDEO_FILE",
    "ArtifactError",
    "CameraPose",
    "CaptureSet",
    "CapturedFrame",
    "FilmId",
    "FrameReport",
    "Geometry",
    "I6Gate",
    "Page",
    "PaletteChange",
    "PaletteLog",
    "RenderChunk",
    "RenderControls",
    "RenderPalette",
    "RenderRecord",
    "RenderStore",
    "RenderStoreWriter",
    "RenderTick",
    "Report",
    "StoreSpan",
    "StoredFrame",
    "TickLog",
    "VideoCapture",
    "load_video_capture",
    "open_render",
    "parse_report",
    "read_capture",
    "read_capture_palette",
    "read_page",
    "read_render",
    "read_report",
    "tick_range_for_captured_ticks",
    "write_capture",
    "write_render",
    "write_render_store",
    "write_report",
    "write_video_capture",
]
