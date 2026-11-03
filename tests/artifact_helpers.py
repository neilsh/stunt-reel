"""Synthetic parity artifact documents for the Python adapter tests: one small, valid value of each family."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any
lazy from pathlib import Path

from stunt_reel.parity_artifacts import (
    RENDER_CHUNK_TICKS,
    RENDER_SCHEMA_VERSION,
    SCHEMA_VERSION,
    CameraPose,
    CapturedFrame,
    CaptureSet,
    FilmId,
    FrameReport,
    Geometry,
    I6Gate,
    PaletteChange,
    PaletteLog,
    RenderChunk,
    RenderPalette,
    RenderRecord,
    RenderTick,
    Report,
    StoreSpan,
    TickLog,
    VideoCapture,
)


def write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def sample_geometry() -> Geometry:
    return Geometry(width=320, height=200, viewport_rows=185)


def sample_tick(tick: int) -> RenderTick:
    return RenderTick(
        tick=tick,
        palette=RenderPalette(sky=0x2000, brightness=0x8000, saturation=0x8000),
        camera=CameraPose(
            eye=(0.0, 10.0, 50.0),
            target=(0.0, 0.0, 0.0),
            fov_degrees=45.0,
            roll_radians=0.0,
        ),
        palette_index=0,
    )


def sample_record(ticks: tuple[int, ...] = (10, 12)) -> RenderRecord:
    return replace(store_record(ticks), film=FilmId(name="CTRY.FLM", flm_bytes=100))


def raw_record(schema_version: int = RENDER_SCHEMA_VERSION) -> dict[str, Any]:
    """A document shaped exactly as serde writes it, to pin cross-language loading."""
    return {
        "schema_version": schema_version,
        "film": {"name": "CTRY.FLM", "flm_bytes": 100},
        "geometry": {"width": 320, "height": 200, "viewport_rows": 185},
        "ticks": [
            {
                "tick": 10,
                "palette": {"sky": 0x2000, "brightness": 0x8000, "saturation": 0x8000},
                "camera": {
                    "eye": [0.0, 10.0, 50.0],
                    "target": [0.0, 0.0, 0.0],
                    "fov_degrees": 45.0,
                    "roll_radians": 0.0,
                },
                "palette_index": 0,
                "credits": True,
            }
        ],
        "palette_count": 1,
        "chunks": [
            {
                "second": 0,
                "ticks": 1,
                "index": {"offset": 0, "length": 10},
                "layer": {"offset": 0, "length": 10},
            }
        ],
    }


def capture_meta() -> dict[str, Any]:
    return {
        "film": "CTRY.FLM",
        "flm_bytes": 100,
        "flm_sha256": "abc",
        "frames": [
            {"ordinal": 1, "film_tick": 9, "global_tick": 12, "distinct_indices": 58},
            {"film_tick": 10, "frame_file": "other.idx", "palette_file": "palettes_0002.json"},
        ],
    }


def sample_capture() -> CaptureSet:
    return CaptureSet(
        schema_version=SCHEMA_VERSION,
        film=FilmId(name="CTRY.FLM", flm_bytes=100, flm_sha256="abc"),
        geometry=Geometry(width=320, height=200),
        frames=(
            CapturedFrame(
                ordinal=1,
                film_tick=9,
                frame_file="tick_0001.idx",
                palette_file="palettes_0001.json",
            ),
            CapturedFrame(
                ordinal=2,
                film_tick=10,
                frame_file="other.idx",
                palette_file="palettes_0002.json",
            ),
        ),
    )


def sample_report() -> Report:
    return Report(
        per_frame=(
            FrameReport(
                film_tick=9,
                ssim=0.7,
                iou=0.9,
                ordinal=1,
                index_agreement=0.5,
                loss_by_class={"sky": 0.1},
                fade_level=1.0,
                authored_fade_level=1.0,
                scored=True,
            ),
            FrameReport(film_tick=10, ssim=0.6, iou=0.8, ordinal=2, scored=False),
        ),
        reference_frames=2,
        frames=2,
        unmatched=0,
        sky_indices=(227, 238),
        mean_ssim=0.65,
        min_ssim=0.6,
        mean_iou=0.85,
        min_fade_level=0.25,
        mean_ssim_scored=0.7,
        i6_gate=I6Gate(initial=False, sign_off=False),
        mean_iou_scored=0.9,
        mean_index_agreement_scored=0.5,
        mean_loss_by_class_scored={"sky": 0.1},
        scored_frames=1,
        excluded_frames=1,
    )


def store_record(ticks: tuple[int, ...]) -> RenderRecord:
    """A record whose chunk table matches *ticks*, ten bytes per chunk in each file."""
    chunks: list[RenderChunk] = []
    for tick in ticks:
        second = tick // RENDER_CHUNK_TICKS
        if chunks and chunks[-1].second == second:
            chunks[-1] = replace(chunks[-1], ticks=chunks[-1].ticks + 1)
        else:
            span = StoreSpan(offset=10 * len(chunks), length=10)
            chunks.append(RenderChunk(second=second, ticks=1, index=span, layer=span))
    return RenderRecord(
        RENDER_SCHEMA_VERSION,
        FilmId(),
        sample_geometry(),
        tuple(sample_tick(tick) for tick in ticks),
        1,
        tuple(chunks),
    )


def sample_video() -> VideoCapture:
    return VideoCapture(
        schema_version=SCHEMA_VERSION,
        kind="video",
        film=FilmId(name="SYNTH.FLM", flm_bytes=4, flm_sha256="00", all_sha256="11"),
        geometry=Geometry(width=4, height=2),
        playone_build="synthetic",
        cpu_profile="capture",
        capture_start_frame=100,
        film_start_frame=103,
        end="hold",
        log=TickLog(frame=(101, 102, 103, 104), film_tick=(7, 7, 8, 9), global_tick=(0, 1, 2, 3)),
        palettes=PaletteLog(
            initial=tuple((i, i, i) for i in range(256)),
            changes=(PaletteChange(frame=103, first=32, rgb=((255, 0, 0),) * 32),),
        ),
    )
