//! StuntReel Modern `wgpu` Presentation Engine (`crates/stunt-render/src/lib.rs`).
//!
//! Delivers hardware-accelerated presentation of Stunt Island scenes conforming
//! strictly to system architectural invariants:
//! - `[I1]` Right-handed metric coordinate basis (+X Right, +Y Up, -Z Forward).
//! - `[I2]` Flat arena allocation without self-referential pointers.
//! - `[I3]` VGA Mode 13h 256-color palette lookup texture with `@interpolate(flat)`.
//! - `[I4]` Discrete simulation ticks (20/30 Hz) with sub-tick interpolation.
//! - `[I5]` Dual-pipeline hardware depth bias pass for coplanar decals.
//! - `[I6]` 4:3 physical aspect ratio ($320 \times 240$) and SSIM parity evaluation.

pub mod camera;
pub mod headless;
pub mod mesh;
pub mod palette;
pub mod parity;
pub mod pipeline;

pub use camera::{
    ASPECT_4_3, CameraController, CameraGpuResources, CameraMode, CameraUniform, FreeCamState,
};
pub use headless::{HeadlessError, HeadlessRenderer};
pub use mesh::{GpuMeshSlice, GpuModel, GpuNode};
pub use palette::{PALETTE_LUT_HEIGHT, PALETTE_LUT_WIDTH, PaletteLut, build_palette_lut_bytes};
pub use parity::{
    ASPECT_CORRECTED_HEIGHT, MODE13H_HEIGHT, MODE13H_WIDTH, PHASE1_SSIM_THRESHOLD,
    PHASE2_SSIM_THRESHOLD, compute_frame_ssim, compute_luminance, compute_window_ssim,
    evaluate_visual_parity, rescale_mode13h_frame, rgb_to_luminance, rgba_to_luminance,
};
pub use pipeline::{ModelUniform, RenderPipelines};
