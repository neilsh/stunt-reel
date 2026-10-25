"""Deprecated shim: the parity tooling now consumes ``stunt_reel.parity_artifacts``.

This module stays only during migration (landing 4 of the render artifact unit
deletes it). It re-exports the adapter under the names the old validators used, so
callers outside this checkout keep importing, and the migration has one auditable
place. New code imports the adapter directly.
"""

from __future__ import annotations

from stunt_reel.parity_artifacts import (
    PALETTE_ENTRIES,
    ArtifactError,
    read_capture,
    read_capture_palette,
    read_report,
)

#: The old boundary-error name; the adapter's ``ArtifactError`` replaced it.
ParityInputError = ArtifactError
#: The old capture-palette reader name.
load_palette = read_capture_palette

__all__ = [
    "PALETTE_ENTRIES",
    "ArtifactError",
    "ParityInputError",
    "load_palette",
    "read_capture",
    "read_capture_palette",
    "read_report",
]
