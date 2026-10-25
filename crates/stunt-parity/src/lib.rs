//! The parity artifact port: the typed documents exchanged by the renderer,
//! the comparator and the Python tooling.
//!
//! This crate is the schema and nothing else: no filesystem, no image decoding,
//! no GPU. The Rust adapter lives in `stunt-cli` (`parity_artifacts`)
//! and the Python adapter in `python/stunt_reel/parity_artifacts.py`; both
//! speak the types defined here.
//!
//! `render.json` and a capture's `meta.json` carry [`SCHEMA_VERSION`].
//! Reports stay readable across versions through `serde(default)` optional
//! fields; making a field required is a schema bump.

pub mod capture;
pub mod error;
pub mod film;
pub mod render;
pub mod report;

pub use capture::{CaptureSet, CapturedFrame};
pub use error::ArtifactError;
pub use film::FilmId;
pub use render::{CameraPose, Geometry, RenderPalette, RenderRecord, RenderTick};
pub use report::{FrameReport, I6Gate, Report};

/// Version carried by `render.json` and a capture's `meta.json`.
pub const SCHEMA_VERSION: u32 = 1;
