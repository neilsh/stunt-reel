//! The parity artifact port: the typed documents exchanged by the renderer,
//! the comparator and the Python tooling.
//!
//! This crate is the schema and nothing else: no filesystem, no image decoding,
//! no GPU. The Rust adapter lives in `stunt-cli` (`parity_artifacts`)
//! and the Python adapter in `python/stunt_reel/parity_artifacts.py`; both
//! speak the types defined here.
//!
//! `render.json` carries [`RENDER_SCHEMA_VERSION`] and a capture's `meta.json`
//! [`SCHEMA_VERSION`]; the render moved to version 2 alone when its planes moved
//! into per-second zstd chunks (ADR 0027). A capture
//! written before the field existed reads as the current version, and a legacy
//! capture's ordinals, file names and 320x200 geometry are defaulted here rather
//! than in either adapter. Reports stay readable across versions through
//! `serde(default)` optional fields; making a field required is a schema bump.

pub mod capture;
pub mod error;
pub mod film;
pub mod render;
pub mod report;
pub mod video;

pub use capture::{CaptureSet, CapturedFrame};
pub use error::ArtifactError;
pub use film::FilmId;
pub use render::{
    CameraPose, Geometry, PALETTE_BYTES, RENDER_CHUNK_TICKS, RenderChunk, RenderPalette,
    RenderRecord, RenderTick, StoreSpan, TickSlot,
};
pub use report::{FrameReport, I6Gate, Report};
pub use video::{CaptureEnd, PaletteChange, PaletteLog, TickLog, VIDEO_FILE, VideoCapture};

/// Version carried by a capture's `meta.json`, frame or video.
pub const SCHEMA_VERSION: u32 = 1;

/// Version carried by `render.json`.
pub const RENDER_SCHEMA_VERSION: u32 = 2;
