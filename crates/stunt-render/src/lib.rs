//! `StuntReel` Modern GPU Presentation Engine (crates/stunt-render/src/lib.rs).
//!
//! Delivers hardware-accelerated presentation of Stunt Island scenes conforming
//! strictly to system architectural invariants:
//! - `[I1]` Right-handed metric coordinate basis (+X Right, +Y Up, -Z Forward).
//! - `[I2]` Flat arena allocation without self-referential pointers.
//! - `[I3]` VGA Mode 13h 256-color palette lookup texture with `@interpolate(flat)`.
//! - `[I4]` Discrete simulation ticks (50 Hz) with sub-tick interpolation.
//! - `[I5]` Dual-pipeline hardware depth bias pass for coplanar decals.
//! - `[I6]` 4:3 physical aspect ratio (320x240) and SSIM parity evaluation.
//!
//! Renderer is the entry point for both destinations: offscreen readback into a `PageSink` and a
//! presented window surface. Everything behind it - the pipelines, palette LUT, camera resources,
//! scene renderer and GPU mesh arena - is crate-private; the plane is the test seam.
#![deny(unsafe_code)]
#![warn(missing_docs)]

pub mod camera;
pub mod parity;
pub mod renderer;
pub mod video;

// Renderer plumbing: crate-private, so no GPU handle type is reachable from outside the crate.
// The decoded-shape landing still owns mesh.rs, whose items stay pub and unused outside the
// renderer; the two allows keep that module untouched while the seam is closed.
#[allow(
    unreachable_pub,
    dead_code,
    reason = "the renderer does not use mesh.rs yet, so its pub items are unreachable and unused"
)]
mod mesh;
mod palette;
mod pipeline;
mod scene_renderer;

pub use camera::{ASPECT_4_3, CameraController, CameraMode, CameraUniform, FreeCamState};
pub use palette::{
    PALETTE_LUT_HEIGHT, PALETTE_LUT_WIDTH, build_palette_lut_bytes, build_palette_lut_bytes_from,
};
pub use parity::{
    ASPECT_CORRECTED_HEIGHT, MODE13H_HEIGHT, MODE13H_WIDTH, WindowScore, compute_frame_ssim,
    compute_frame_ssim_masked, compute_luminance, compute_window_scores, compute_window_ssim,
    rescale_mode13h_frame, rgb_to_luminance, rgba_to_luminance,
};
pub use pipeline::{LAYER_FIRST_ACTOR, LAYER_NONE, LAYER_OCEAN, LAYER_PROP, LAYER_TERRAIN};
pub use renderer::{
    DEFAULT_CLEAR_PALETTE_INDEX, DEFAULT_PAGE_HEIGHT, DEFAULT_PAGE_WIDTH, Offscreen, PageSink,
    PageSize, RenderError, RenderOptions, RenderedPage, Renderer, SinkError,
};
pub use video::{FfmpegVideoWriter, VideoExportError};
